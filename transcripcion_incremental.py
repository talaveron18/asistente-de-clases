"""Cola durable de transcripción mientras el micrófono sigue grabando."""
from __future__ import annotations

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
    ):
        self.transcriptor = transcriptor
        self.repositorio = repositorio
        self.carpeta = Path(carpeta)
        self.callback_segmentos = callback_segmentos
        self.callback_estado = callback_estado
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
        error = "\n".join(dict.fromkeys(self._errores)) or None
        segmentos = self.repositorio.finalizar_grabacion(self.carpeta, error)
        return ResultadoGrabacion(
            self.carpeta, segmentos, tuple(dict.fromkeys(self._errores))
        )

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
                locales = self.transcriptor.transcribir_fragmento(fragmento.ruta)
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
