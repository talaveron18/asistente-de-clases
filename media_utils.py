from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".wma", ".aac", ".opus"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv", ".mpeg", ".mpg", ".ts"}


def localizar_ffmpeg() -> str:
    candidatos: list[Path] = []
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidatos.extend(
            [
                base / "ffmpeg.exe",
                base / "bin" / "ffmpeg.exe",
                Path(sys.executable).parent / "ffmpeg.exe",
                Path(sys.executable).parent / "bin" / "ffmpeg.exe",
            ]
        )
    for ruta in candidatos:
        if ruta.is_file():
            return str(ruta)
    return "ffmpeg"


def tipo_archivo(ruta: str) -> str:
    extension = Path(ruta).suffix.lower()
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return "desconocido"


def preparar_para_transcripcion(
    ruta: str,
    callback: Callable[[str, float], None] | None = None,
) -> tuple[str, bool, str]:
    """Devuelve (ruta_procesable, es_temporal, tipo_original).

    Los audios se procesan directamente. Los vídeos se convierten a un WAV
    mono de 16 kHz en la carpeta temporal de Windows. El llamador debe borrar
    el temporal al finalizar.
    """
    origen = Path(ruta)
    if not origen.is_file():
        raise FileNotFoundError(f"No se encontró el archivo: {ruta}")

    tipo = tipo_archivo(ruta)
    if tipo == "audio":
        return str(origen), False, tipo
    if tipo != "video":
        raise ValueError(
            "Formato no compatible. Usa audio (WAV, MP3, M4A, FLAC, OGG...) "
            "o vídeo (MP4, MKV, MOV, AVI, WEBM...)."
        )

    if callback:
        callback("Extrayendo el audio del vídeo…", 0.03)

    descriptor, temporal = tempfile.mkstemp(prefix="asistente_clases_", suffix=".wav")
    os.close(descriptor)
    comando = [
        localizar_ffmpeg(),
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(origen),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        temporal,
    ]
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            timeout=None,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if resultado.returncode != 0:
            detalle = (resultado.stderr or "Error desconocido de FFmpeg").strip()
            raise RuntimeError(f"No se pudo extraer el audio del vídeo: {detalle}")
        if not Path(temporal).is_file() or Path(temporal).stat().st_size == 0:
            raise RuntimeError("El vídeo no contiene una pista de audio utilizable.")
        if callback:
            callback("Audio del vídeo preparado. Iniciando transcripción…", 0.08)
        return temporal, True, tipo
    except Exception:
        try:
            os.remove(temporal)
        except OSError:
            pass
        raise


def eliminar_temporal(ruta: str) -> None:
    try:
        os.remove(ruta)
    except OSError:
        pass
