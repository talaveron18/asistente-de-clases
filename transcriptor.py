"""Motor local de transcripción y diarización opcional."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Dict, Optional


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

    def cargar_modelos(self, callback_status: Optional[Callable] = None):
        def status(msg, p=0.0):
            print(f"[Carga] {msg}")
            if callback_status:
                callback_status(msg, p)

        if not _verificar_ffmpeg():
            raise RuntimeError("FFmpeg no está disponible.")

        status(f"Cargando Whisper {self.model_size}...", 0.1)
        from faster_whisper import WhisperModel

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

    def transcribir_archivo(self, archivo_audio: str, callback_progreso=None, min_hablantes: int = 2, max_hablantes: int = 10):
        if not self.modelos_cargados or self.whisper_model is None:
            raise RuntimeError("Los modelos no están cargados.")
        if not os.path.isfile(archivo_audio):
            raise FileNotFoundError(archivo_audio)

        def prog(msg, p):
            if callback_progreso:
                callback_progreso(msg, p)

        prog("Transcribiendo con Whisper...", 0.05)
        language = None if self.idioma == "auto" else self.idioma
        segmentos_iter, _info = self.whisper_model.transcribe(
            archivo_audio,
            language=language,
            beam_size=3,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=True,
        )
        segmentos_whisper = list(segmentos_iter)
        if not segmentos_whisper:
            return []
        prog(f"Texto detectado: {len(segmentos_whisper)} segmentos.", 0.55)

        if not self.diarizacion_disponible:
            prog("Finalizando sin diarización.", 1.0)
            return [SegmentoTranscrito(s.start, s.end, s.text, "SPEAKER_00", "Docente") for s in segmentos_whisper]

        prog("Separando voces...", 0.6)
        kwargs = {"num_speakers": min_hablantes} if min_hablantes == max_hablantes else {"min_speakers": min_hablantes, "max_speakers": max_hablantes}
        salida = self.diarization_pipeline(archivo_audio, **kwargs)
        anotacion = getattr(salida, "exclusive_speaker_diarization", None) or getattr(salida, "speaker_diarization", None) or salida
        turnos = []
        if hasattr(anotacion, "itertracks"):
            for turno, _, hablante in anotacion.itertracks(yield_label=True):
                turnos.append({"inicio": turno.start, "fin": turno.end, "hablante": hablante})
        else:
            for turno, hablante in anotacion:
                turnos.append({"inicio": turno.start, "fin": turno.end, "hablante": hablante})

        prog("Transcripción completada.", 1.0)
        return self._asignar_roles(self._fusionar(segmentos_whisper, turnos))

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
