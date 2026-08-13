"""Motor local de transcripción y diarización opcional."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from audio_asr import preparar_archivo_asr, preparar_fragmento_asr

OPCIONES_DECODIFICACION = {
    "language": None,
    "beam_size": 3,
    "vad_filter": True,
    "condition_on_previous_text": False,
    "repetition_penalty": 1.08,
    "no_repeat_ngram_size": 4,
    "compression_ratio_threshold": 2.4,
    "log_prob_threshold": -1.0,
    "no_speech_threshold": 0.6,
    "temperature": 0.0,
}
_PATRON_PALABRA = re.compile(r"\w+", flags=re.UNICODE)


def _ffmpeg_executable() -> str:
    """Localiza FFmpeg incluido en el instalador o disponible en el PATH."""
    candidatos = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        candidatos.extend([
            os.path.join(base, "ffmpeg.exe"),
            os.path.join(base, "bin", "ffmpeg.exe"),
            os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe"),
            os.path.join(os.path.dirname(sys.executable), "bin", "ffmpeg.exe"),
        ])
    for ruta in candidatos:
        if os.path.isfile(ruta):
            return ruta
    return "ffmpeg"


def _verificar_ffmpeg() -> bool:
    try:
        return subprocess.run(
            [_ffmpeg_executable(), "-version"], capture_output=True, timeout=5
        ).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


@dataclass
class SegmentoTranscrito:
    inicio: float
    fin: float
    texto: str
    hablante_original: str
    rol: str

    @staticmethod
    def formatear_tiempo(segundos: float) -> str:
        horas = int(segundos // 3600)
        mins = int((segundos % 3600) // 60)
        segs = int(segundos % 60)
        return f"{horas:02d}:{mins:02d}:{segs:02d}" if horas else f"{mins:02d}:{segs:02d}"

    def a_linea_txt(self):
        return f"[{self.formatear_tiempo(self.inicio)}] {self.rol}: {self.texto.strip()}"

    def a_linea_markdown(self):
        linea = f"[{self.formatear_tiempo(self.inicio)}] {self.rol}: {self.texto.strip()}"
        return f"**{linea}**" if self.rol == "Docente" else f"*{linea}*"


@dataclass(frozen=True)
class _SegmentoReconocido:
    start: float
    end: float
    text: str


def _valor_metrica(segmento, nombre: str) -> float | None:
    valor = getattr(segmento, nombre, None)
    try:
        return float(valor) if valor is not None else None
    except (TypeError, ValueError):
        return None


def _normalizar_texto(texto: str) -> str:
    return " ".join(
        coincidencia.group(0).casefold()
        for coincidencia in _PATRON_PALABRA.finditer(texto)
    )


def _recortar_repeticion_degenerada(texto: str) -> tuple[str, str | None]:
    """Corta una cola repetida tres veces sin reescribir el texto válido previo."""
    coincidencias = list(_PATRON_PALABRA.finditer(texto))
    palabras = [coincidencia.group(0).casefold() for coincidencia in coincidencias]
    total = len(palabras)
    for inicio in range(total):
        maximo = min(16, (total - inicio) // 3)
        for tamano in range(3, maximo + 1):
            patron = palabras[inicio : inicio + tamano]
            repeticiones = 1
            posicion = inicio + tamano
            while palabras[posicion : posicion + tamano] == patron:
                repeticiones += 1
                posicion += tamano
            repetidas = repeticiones * tamano
            cola = total - inicio
            if (
                repeticiones >= 3
                and repetidas >= 12
                and repetidas / max(cola, 1) >= 0.7
            ):
                prefijo = texto[: coincidencias[inicio].start()].strip()
                if len(_PATRON_PALABRA.findall(prefijo)) < 5:
                    prefijo = ""
                return prefijo, (
                    f"secuencia de {tamano} palabras repetida "
                    f"{repeticiones} veces"
                )
    return texto.strip(), None


class TranscriptorClases:
    def __init__(self, hf_token: str = "", model_size: str = "medium", usar_gpu: bool = True, idioma: str = "es"):
        self.hf_token = hf_token.strip()
        self.model_size = model_size
        self.usar_gpu = usar_gpu
        self.idioma = idioma
        self.whisper_model = None
        self.diarization_pipeline = None
        self.modelos_cargados = False
        self.diarizacion_disponible = False
        self.dispositivo_real = "cpu"
        self._transcripcion_lock = threading.Lock()
        self._whisper_model_cls = None
        self._callback_status = None
        self.ultimo_aviso = ""
        self.ultimo_diagnostico_audio = None
        self._historial_fragmentos: deque[str] = deque(maxlen=3)
        self._descartes_pendientes: list[dict] = []
        self._diagnosticos_lock = threading.Lock()

    def cargar_modelos(self, callback_status: Optional[Callable] = None):
        self._callback_status = callback_status

        def status(msg, p=0.0):
            print(f"[Carga] {msg}")
            if callback_status:
                callback_status(msg, p)

        if not _verificar_ffmpeg():
            raise RuntimeError("FFmpeg no está disponible.")

        status(f"Cargando Whisper {self.model_size}...", 0.1)
        from faster_whisper import WhisperModel

        self._whisper_model_cls = WhisperModel

        # Faster-Whisper comprueba CUDA directamente. Así no necesitamos
        # empaquetar PyTorch en el instalador básico.
        if self.usar_gpu:
            try:
                self.whisper_model = WhisperModel(
                    self.model_size, device="cuda", compute_type="float16"
                )
                self.dispositivo_real = "cuda"
            except Exception as exc:
                print(f"GPU no disponible para Whisper ({exc}); usando CPU.")

        if self.whisper_model is None:
            self.whisper_model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=max(1, (os.cpu_count() or 4) - 1),
            )
            self.dispositivo_real = "cpu"
        status(f"Whisper listo en {self.dispositivo_real.upper()}.", 0.55)

        if self.hf_token:
            status("Cargando diarización opcional...", 0.65)
            try:
                import torch
                from pyannote.audio import Pipeline
                try:
                    pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-community-1", token=self.hf_token
                    )
                except TypeError:
                    pipeline = Pipeline.from_pretrained(
                        "pyannote/speaker-diarization-3.1", use_auth_token=self.hf_token
                    )
                if self.dispositivo_real == "cuda":
                    pipeline.to(torch.device("cuda"))
                self.diarization_pipeline = pipeline
                self.diarizacion_disponible = True
                status("Diarización lista.", 0.95)
            except Exception as exc:
                self.diarization_pipeline = None
                self.diarizacion_disponible = False
                print(f"Diarización desactivada: {exc}")
                status("Whisper listo; diarización no instalada.", 0.95)
        else:
            status("Whisper listo; sin token, se omite la diarización.", 0.95)

        self.modelos_cargados = True
        status("Modelos listos.", 1.0)

    def _avisar(self, mensaje: str, progreso: float = 0.0) -> None:
        self.ultimo_aviso = mensaje
        print(f"[Whisper] {mensaje}")
        if self._callback_status:
            self._callback_status(mensaje, progreso)

    def _cambiar_a_cpu(self, error_gpu: Exception) -> None:
        """Recupera una inferencia CUDA rota sin perder la clase.

        CTranslate2 puede construir el modelo CUDA y descubrir que faltan
        cuBLAS/cuDNN únicamente al ejecutar la primera transcripción. Por eso
        comprobar solo ``WhisperModel(...)`` no demuestra que la GPU funcione.
        """
        if self.dispositivo_real != "cuda":
            raise error_gpu
        if self._whisper_model_cls is None:
            from faster_whisper import WhisperModel

            self._whisper_model_cls = WhisperModel
        self._avisar(
            "La GPU no pudo transcribir; ARGOS continúa automáticamente por CPU.",
            0.04,
        )
        self.whisper_model = self._whisper_model_cls(
            self.model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=max(1, (os.cpu_count() or 4) - 1),
        )
        self.dispositivo_real = "cpu"
        if self.diarization_pipeline is not None:
            try:
                import torch

                self.diarization_pipeline.to(torch.device("cpu"))
            except Exception:
                self.diarization_pipeline = None
                self.diarizacion_disponible = False

    def _inferir(self, archivo_audio: str, **opciones):
        """Materializa el generador dentro del bloqueo y reintenta en CPU."""
        with self._transcripcion_lock:
            try:
                segmentos_iter, info = self.whisper_model.transcribe(
                    archivo_audio, **opciones
                )
                return list(segmentos_iter), info
            except Exception as error_gpu:
                if self.dispositivo_real != "cuda":
                    raise
                self._cambiar_a_cpu(error_gpu)
                try:
                    segmentos_iter, info = self.whisper_model.transcribe(
                        archivo_audio, **opciones
                    )
                    return list(segmentos_iter), info
                except Exception as error_cpu:
                    raise RuntimeError(
                        "Whisper falló primero en GPU y también al reintentarlo "
                        f"por CPU. GPU: {error_gpu}. CPU: {error_cpu}"
                    ) from error_cpu

    def _opciones_decodificacion(self, silencio_ms: int) -> dict:
        opciones = dict(OPCIONES_DECODIFICACION)
        opciones["language"] = None if self.idioma == "auto" else self.idioma
        opciones["vad_parameters"] = {
            "threshold": 0.5,
            "min_speech_duration_ms": 250,
            "min_silence_duration_ms": silencio_ms,
            "speech_pad_ms": 400,
        }
        return opciones

    def _registrar_descarte(
        self, segmento, texto: str, razon: str, ambito: str
    ) -> None:
        diagnostico = {
            "evento": "texto_descartado",
            "ambito": ambito,
            "inicio": _valor_metrica(segmento, "start"),
            "fin": _valor_metrica(segmento, "end"),
            "texto": texto.strip(),
            "razon": razon,
            "no_speech_prob": _valor_metrica(segmento, "no_speech_prob"),
            "avg_logprob": _valor_metrica(segmento, "avg_logprob"),
            "compression_ratio": _valor_metrica(segmento, "compression_ratio"),
            "audio": (
                self.ultimo_diagnostico_audio if ambito == "directo" else None
            ),
        }
        with self._diagnosticos_lock:
            self._descartes_pendientes.append(diagnostico)

    def consumir_descartes(self) -> list[dict]:
        """Entrega los diagnósticos una sola vez para persistirlos con la clase."""
        with self._diagnosticos_lock:
            descartes = self._descartes_pendientes
            self._descartes_pendientes = []
        return descartes

    def crear_motor_para_modelo(
        self,
        model_size: str,
        callback_status: Optional[Callable] = None,
    ) -> "TranscriptorClases":
        """Carga un motor independiente sin reemplazar el usado en directo."""
        if model_size == self.model_size:
            return self
        motor = TranscriptorClases(
            hf_token=self.hf_token,
            model_size=model_size,
            usar_gpu=self.usar_gpu,
            idioma=self.idioma,
        )
        motor.cargar_modelos(callback_status)
        return motor

    def _filtrar_segmentos(self, segmentos, ambito: str) -> list[_SegmentoReconocido]:
        resultado = []
        for segmento in segmentos:
            texto_original = str(getattr(segmento, "text", "")).strip()
            if not texto_original:
                continue
            texto, razon_repeticion = _recortar_repeticion_degenerada(
                texto_original
            )
            no_voz = _valor_metrica(segmento, "no_speech_prob")
            logprob = _valor_metrica(segmento, "avg_logprob")
            compresion = _valor_metrica(segmento, "compression_ratio")
            senales_malas = sum(
                (
                    no_voz is not None and no_voz >= 0.6,
                    logprob is not None and logprob <= -1.0,
                    compresion is not None and compresion >= 2.4,
                )
            )
            razon = razon_repeticion
            if senales_malas >= 2:
                razon = razon or "confianza baja y salida anómala"
                texto = ""

            if razon:
                self._registrar_descarte(
                    segmento, texto_original, razon, ambito
                )
                self._avisar(
                    "Se descartó una salida repetitiva o sin voz; "
                    "el audio original permanece guardado."
                )
            if texto:
                resultado.append(
                    _SegmentoReconocido(segmento.start, segmento.end, texto)
                )
        return resultado

    def _filtrar_bucle_entre_fragmentos(
        self, originales, filtrados: list[_SegmentoReconocido]
    ) -> list[_SegmentoReconocido]:
        texto = " ".join(segmento.text for segmento in filtrados).strip()
        normalizado = _normalizar_texto(texto)
        if not normalizado:
            return filtrados
        repetido = (
            len(self._historial_fragmentos) >= 2
            and normalizado == self._historial_fragmentos[-1]
            and normalizado == self._historial_fragmentos[-2]
        )
        audio_debil = bool(
            self.ultimo_diagnostico_audio
            and self.ultimo_diagnostico_audio.get("rms_activo_dbfs", 0.0)
            <= -38.0
        )
        self._historial_fragmentos.append(normalizado)
        if not (repetido and audio_debil):
            return filtrados
        referencia = originales[0] if originales else filtrados[0]
        razon = "mismo texto en tres fragmentos consecutivos con audio débil"
        self._registrar_descarte(referencia, texto, razon, "directo")
        self._avisar(
            "Se descartó una salida repetida entre fragmentos; "
            "el audio original permanece guardado."
        )
        return []

    def transcribir_archivo(
        self,
        archivo_audio: str,
        callback_progreso=None,
        min_hablantes: int = 2,
        max_hablantes: int = 10,
        acondicionar_audio: bool = False,
    ):
        if not self.modelos_cargados or self.whisper_model is None:
            raise RuntimeError("Los modelos no están cargados.")
        if not os.path.isfile(archivo_audio):
            raise FileNotFoundError(archivo_audio)

        def prog(msg, p):
            if callback_progreso:
                callback_progreso(msg, p)

        contexto_audio = (
            preparar_archivo_asr(archivo_audio)
            if acondicionar_audio
            else nullcontext((archivo_audio, None))
        )
        with contexto_audio as (entrada_asr, diagnostico):
            if diagnostico is not None:
                self.ultimo_diagnostico_audio = diagnostico
                prog("Audio acondicionado en mono a 16 kHz.", 0.04)
            prog("Transcribiendo con Whisper...", 0.05)
            segmentos_whisper, _info = self._inferir(
                entrada_asr,
                **self._opciones_decodificacion(silencio_ms=500),
            )
            self._historial_fragmentos.clear()
            segmentos_whisper = self._filtrar_segmentos(
                segmentos_whisper, ambito="archivo"
            )
            if not segmentos_whisper:
                return []
            prog(f"Texto detectado: {len(segmentos_whisper)} segmentos.", 0.55)

            if not self.diarizacion_disponible:
                prog("Finalizando sin diarización.", 1.0)
                return [
                    SegmentoTranscrito(
                        s.start, s.end, s.text, "SPEAKER_00", "Docente"
                    )
                    for s in segmentos_whisper
                ]

            prog("Separando voces...", 0.6)
            kwargs = (
                {"num_speakers": min_hablantes}
                if min_hablantes == max_hablantes
                else {
                    "min_speakers": min_hablantes,
                    "max_speakers": max_hablantes,
                }
            )
            with self._transcripcion_lock:
                salida = self.diarization_pipeline(entrada_asr, **kwargs)
            anotacion = (
                getattr(salida, "exclusive_speaker_diarization", None)
                or getattr(salida, "speaker_diarization", None)
                or salida
            )
            turnos = []
            if hasattr(anotacion, "itertracks"):
                for turno, _, hablante in anotacion.itertracks(yield_label=True):
                    turnos.append(
                        {
                            "inicio": turno.start,
                            "fin": turno.end,
                            "hablante": hablante,
                        }
                    )
            else:
                for turno, hablante in anotacion:
                    turnos.append(
                        {
                            "inicio": turno.start,
                            "fin": turno.end,
                            "hablante": hablante,
                        }
                    )

            prog("Transcripción completada.", 1.0)
            return self._asignar_roles(
                self._fusionar(segmentos_whisper, turnos)
            )

    def transcribir_fragmento(self, archivo_audio: str):
        """Transcribe un fragmento corto sin bloquear la captura de audio.

        La diarización se reserva al procesamiento posterior. Ejecutarla cada
        diez segundos sería lenta e introduciría roles incoherentes entre
        fragmentos.
        """
        if not self.modelos_cargados or self.whisper_model is None:
            raise RuntimeError("Los modelos no están cargados.")
        if not os.path.isfile(archivo_audio):
            raise FileNotFoundError(archivo_audio)
        audio_asr, diagnostico = preparar_fragmento_asr(archivo_audio)
        self.ultimo_diagnostico_audio = (
            diagnostico.como_dict() if diagnostico is not None else None
        )
        segmentos_originales, _info = self._inferir(
            audio_asr, **self._opciones_decodificacion(silencio_ms=350)
        )
        segmentos_iter = self._filtrar_segmentos(
            segmentos_originales, ambito="directo"
        )
        segmentos_iter = self._filtrar_bucle_entre_fragmentos(
            segmentos_originales, segmentos_iter
        )
        return [
            SegmentoTranscrito(
                segmento.start,
                segmento.end,
                segmento.text,
                "SPEAKER_00",
                "Docente",
            )
            for segmento in segmentos_iter
        ]

    @staticmethod
    def _fusionar(segmentos_whisper, turnos):
        resultado = []
        for seg in segmentos_whisper:
            centro = (seg.start + seg.end) / 2
            candidatos = [t for t in turnos if t["inicio"] <= centro <= t["fin"]]
            if candidatos:
                hablante = candidatos[0]["hablante"]
            else:
                hablante = max(turnos, key=lambda t: max(0, min(seg.end, t["fin"]) - max(seg.start, t["inicio"])), default={"hablante": "Desconocido"})["hablante"]
            resultado.append({"inicio": seg.start, "fin": seg.end, "texto": seg.text, "hablante": hablante})
        return resultado

    @staticmethod
    def _asignar_roles(segmentos):
        tiempos: Dict[str, float] = {}
        for s in segmentos:
            tiempos[s["hablante"]] = tiempos.get(s["hablante"], 0) + max(0, s["fin"] - s["inicio"])
        docente = max(tiempos, key=tiempos.get) if tiempos else "Desconocido"
        otros = [h for h, _ in sorted(tiempos.items(), key=lambda x: x[1], reverse=True) if h != docente]
        roles = {docente: "Docente", **{h: f"Alumno {i+1}" for i, h in enumerate(otros)}}
        return [SegmentoTranscrito(s["inicio"], s["fin"], s["texto"], s["hablante"], roles.get(s["hablante"], "Alumno")) for s in segmentos]

    def exportar_txt(self, segmentos, archivo):
        with open(archivo, "w", encoding="utf-8") as f:
            f.write("\n".join(s.a_linea_txt() for s in segmentos))

    def exportar_markdown(self, segmentos, archivo):
        with open(archivo, "w", encoding="utf-8") as f:
            f.write("# Transcripción de clase\n\n" + "\n".join(s.a_linea_markdown() for s in segmentos))

    def exportar_srt(self, segmentos, archivo):
        def fmt(v):
            h, r = divmod(v, 3600)
            m, s = divmod(r, 60)
            return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s-int(s))*1000):03d}"
        with open(archivo, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segmentos, 1):
                f.write(f"{i}\n{fmt(seg.inicio)} --> {fmt(seg.fin)}\n[{seg.rol}] {seg.texto.strip()}\n\n")

    @staticmethod
    def obtener_texto_para_ia(segmentos):
        return "\n".join(s.a_linea_txt() for s in segmentos)

    @staticmethod
    def obtener_resumen_hablantes(segmentos):
        stats = {}
        for seg in segmentos:
            d = stats.setdefault(seg.rol, {"tiempo_segundos": 0.0, "n_intervenciones": 0, "palabras": 0})
            d["tiempo_segundos"] += max(0, seg.fin - seg.inicio)
            d["n_intervenciones"] += 1
            d["palabras"] += len(seg.texto.split())
        return stats
