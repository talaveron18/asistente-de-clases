"""Cola durable de transcripción mientras el micrófono sigue grabando."""
from __future__ import annotations

import inspect
import queue
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from grabador import FragmentoAudio
from repositorio import RepositorioClases
from transcriptor import SegmentoTranscrito, TranscriptorClases


@dataclass(frozen=True)
class ResultadoGrabacion:
    carpeta: Path
    segmentos: list[SegmentoTranscrito]
    errores: tuple[str, ...]
    transcripcion_final: bool = False

    @property
    def completa(self) -> bool:
        return not self.errores


class TranscripcionIncremental:
    """Procesa fragmentos en orden y confirma cada uno en disco.

    Un JSON junto a cada WAV actúa como confirmación durable. Si el proceso se
    interrumpe, al reiniciar solo se vuelven a procesar WAV sin ese JSON.
    """

    def __init__(
        self,
        transcriptor: TranscriptorClases,
        repositorio: RepositorioClases,
        carpeta: str | Path,
        callback_segmentos: Callable[[list[SegmentoTranscrito]], None] | None = None,
        callback_estado: Callable[[str], None] | None = None,
        consolidar_audio_completo: bool = False,
        min_hablantes: int = 2,
        max_hablantes: int = 10,
        materia: str = "",
        titulo: str = "",
    ):
        self.transcriptor = transcriptor
        self.repositorio = repositorio
        self.carpeta = Path(carpeta)
        self.callback_segmentos = callback_segmentos
        self.callback_estado = callback_estado
        self.consolidar_audio_completo = consolidar_audio_completo
        self.min_hablantes = min_hablantes
        self.max_hablantes = max_hablantes
        self._contexto_clase = " · ".join(
            parte.strip() for parte in (materia, titulo) if parte and parte.strip()
        )
        self._contexto_directo = ""
        self._cola: queue.Queue[FragmentoAudio | None] = queue.Queue()
        self._errores: list[str] = []
        self._cerrada = False
        self._hilo = threading.Thread(
            target=self._consumir,
            daemon=True,
            name="argos-transcripcion-incremental",
        )
        self._hilo.start()

    def encolar(self, fragmento: FragmentoAudio) -> None:
        if self._cerrada:
            raise RuntimeError("La transcripción incremental ya está cerrada.")
        self._cola.put(fragmento)
        self._estado(
            f"Audio {fragmento.inicio:.0f}–{fragmento.fin:.0f} s guardado; "
            "transcribiendo automáticamente…"
        )

    def encolar_varios(self, fragmentos: Iterable[FragmentoAudio]) -> None:
        for fragmento in fragmentos:
            self.encolar(fragmento)

    def finalizar(self, timeout: float | None = None) -> ResultadoGrabacion:
        if not self._cerrada:
            self._cerrada = True
            self._cola.put(None)
        self._hilo.join(timeout=timeout)
        if self._hilo.is_alive():
            self._errores.append(
                "La cola de transcripción no terminó dentro del tiempo previsto."
            )
        segmentos_directo = self.repositorio.segmentos_grabacion(self.carpeta)
        segmentos_finales = None
        if self.consolidar_audio_completo and not self._hilo.is_alive():
            segmentos_finales = self._consolidar_audio_completo(segmentos_directo)
            if segmentos_finales is not None:
                # La pasada completa cubre también cualquier fragmento que haya
                # fallado durante el directo. Los diagnósticos permanecen en
                # disco, pero la clase ya no está incompleta.
                self._errores.clear()
        error = "\n".join(dict.fromkeys(self._errores)) or None
        segmentos = self.repositorio.finalizar_grabacion(
            self.carpeta,
            error,
            segmentos_finales=segmentos_finales,
        )
        return ResultadoGrabacion(
            self.carpeta,
            segmentos,
            tuple(dict.fromkeys(self._errores)),
            transcripcion_final=segmentos_finales is not None,
        )

    def _consolidar_audio_completo(
        self, segmentos_directo: list[SegmentoTranscrito]
    ) -> list[SegmentoTranscrito] | None:
        audio = self.carpeta / "audio.wav"
        if not audio.is_file() or audio.stat().st_size <= 44:
            self._errores.append(
                "No se pudo crear la transcripción final: falta el audio completo."
            )
            return None
        self._estado(
            "Audio completo guardado. Preparando la transcripción definitiva…"
        )

        def progreso(mensaje: str, _valor: float) -> None:
            self._estado(f"Transcripción definitiva: {mensaje}")

        try:
            opciones = {
                "callback_progreso": progreso,
                "min_hablantes": self.min_hablantes,
                "max_hablantes": self.max_hablantes,
            }
            if self._acepta_parametro(
                self.transcriptor.transcribir_archivo, "contexto_clase"
            ):
                opciones["contexto_clase"] = self._contexto_clase
            finales = self.transcriptor.transcribir_archivo(str(audio), **opciones)
        except Exception as exc:
            self._errores.append(f"Transcripción definitiva: {exc}")
            self._estado(
                "No terminó la pasada definitiva; se conserva el texto en directo."
            )
            return None
        if segmentos_directo and not finales:
            self._errores.append(
                "La pasada definitiva no detectó texto aunque sí existe "
                "transcripción en directo."
            )
            self._estado(
                "La pasada definitiva no detectó voz; se conserva el texto en directo."
            )
            return None
        self._estado(
            "Transcripción definitiva completada sobre el audio íntegro."
        )
        return list(finales)

    def cerrar_sin_esperar(self) -> None:
        """Permite cerrar la ventana; la recuperación continuará al reiniciar."""
        if not self._cerrada:
            self._cerrada = True
            self._cola.put(None)

    def _consumir(self) -> None:
        while True:
            fragmento = self._cola.get()
            if fragmento is None:
                self._cola.task_done()
                return
            try:
                self._transcribir(fragmento)
            finally:
                self._cola.task_done()

    def _transcribir(self, fragmento: FragmentoAudio) -> None:
        ultimo_error = None
        for _intento in range(2):
            try:
                opciones = {}
                metodo = self.transcriptor.transcribir_fragmento
                if self._acepta_parametro(metodo, "contexto_clase"):
                    opciones["contexto_clase"] = self._contexto_clase
                if self._acepta_parametro(metodo, "contexto_previo"):
                    opciones["contexto_previo"] = self._contexto_directo
                locales = metodo(fragmento.ruta, **opciones)
                segmentos = [
                    SegmentoTranscrito(
                        inicio=segmento.inicio + fragmento.inicio,
                        fin=segmento.fin + fragmento.inicio,
                        texto=segmento.texto,
                        hablante_original=segmento.hablante_original,
                        rol=segmento.rol,
                    )
                    for segmento in locales
                ]
                todos = self.repositorio.guardar_transcripcion_fragmento(
                    self.carpeta,
                    fragmento.indice,
                    fragmento.inicio,
                    fragmento.fin,
                    segmentos,
                )
                if self.callback_segmentos:
                    self.callback_segmentos(todos)
                texto_nuevo = " ".join(
                    segmento.texto.strip()
                    for segmento in segmentos
                    if segmento.texto.strip()
                )
                if texto_nuevo:
                    acumulado = " ".join(
                        f"{self._contexto_directo} {texto_nuevo}".split()
                    )
                    self._contexto_directo = acumulado[-260:]
                self._estado(
                    f"Transcripción guardada hasta {fragmento.fin:.0f} s. "
                    "La grabación continúa."
                )
                return
            except Exception as exc:  # se reintenta una vez con el WAV intacto
                ultimo_error = exc
        mensaje = f"Fragmento {fragmento.indice}: {ultimo_error}"
        self._errores.append(mensaje)
        self._registrar_error(fragmento, ultimo_error)
        self._estado(
            "No se pudo transcribir este fragmento; el audio está protegido. "
            f"Detalle: {ultimo_error}"
        )

    @staticmethod
    def _acepta_parametro(metodo, nombre: str) -> bool:
        """Mantiene compatibles los transcriptores antiguos y los dobles de prueba."""
        try:
            parametros = inspect.signature(metodo).parameters
        except (TypeError, ValueError):
            return False
        return nombre in parametros or any(
            parametro.kind is inspect.Parameter.VAR_KEYWORD
            for parametro in parametros.values()
        )

    def _registrar_error(self, fragmento: FragmentoAudio, error: Exception) -> None:
        registro = {
            "timestamp": time.time(),
            "fragmento": fragmento.indice,
            "ruta": fragmento.ruta,
            "inicio": fragmento.inicio,
            "fin": fragmento.fin,
            "modelo": getattr(self.transcriptor, "model_size", "desconocido"),
            "dispositivo": getattr(
                self.transcriptor, "dispositivo_real", "desconocido"
            ),
            "error_tipo": type(error).__name__,
            "error": str(error),
        }
        try:
            with (self.carpeta / "diagnostico_transcripcion.jsonl").open(
                "a", encoding="utf-8"
            ) as archivo:
                archivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _estado(self, mensaje: str) -> None:
        if self.callback_estado:
            self.callback_estado(mensaje)
