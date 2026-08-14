"""Actualización segura y desatendida de la instalación Windows de ARGOS."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen


REPOSITORIO = "talaveron18/asistente-de-clases"
MANIFIESTO_URL = (
    f"https://github.com/{REPOSITORIO}/releases/download/latest/ARGOS-version.json"
)
INSTALADOR_URL = (
    f"https://github.com/{REPOSITORIO}/releases/download/latest/ARGOS-Setup.exe"
)
LIMITE_MANIFIESTO = 64 * 1024
LIMITE_INSTALADOR = 2 * 1024 * 1024 * 1024
PATRON_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ErrorActualizacion(RuntimeError):
    """El manifiesto o el instalador no superan las comprobaciones."""


@dataclass(frozen=True)
class Actualizacion:
    version: str
    sha256: str
    tamano: int


def _partes_version(version: str) -> tuple[int, ...]:
    texto = str(version).strip()
    if not re.fullmatch(r"\d+(?:\.\d+){1,3}", texto):
        raise ErrorActualizacion(f"Versión no válida: {texto!r}")
    return tuple(int(parte) for parte in texto.split("."))


def es_mas_reciente(version_publicada: str, version_actual: str) -> bool:
    """Compara versiones numéricas rellenando con ceros los tramos ausentes."""
    publicada = _partes_version(version_publicada)
    actual = _partes_version(version_actual)
    longitud = max(len(publicada), len(actual))
    return publicada + (0,) * (longitud - len(publicada)) > actual + (0,) * (
        longitud - len(actual)
    )


def _leer_respuesta(respuesta, limite: int) -> bytes:
    longitud = respuesta.headers.get("Content-Length")
    if longitud and int(longitud) > limite:
        raise ErrorActualizacion("La descarga anunciada supera el límite permitido")
    datos = respuesta.read(limite + 1)
    if len(datos) > limite:
        raise ErrorActualizacion("La descarga supera el límite permitido")
    return datos


def buscar_actualizacion(
    version_actual: str,
    abrir: Callable = urlopen,
) -> Actualizacion | None:
    peticion = Request(
        MANIFIESTO_URL,
        headers={"User-Agent": f"ARGOS/{version_actual}", "Accept": "application/json"},
    )
    with abrir(peticion, timeout=12) as respuesta:
        datos = json.loads(_leer_respuesta(respuesta, LIMITE_MANIFIESTO))
    if not isinstance(datos, dict):
        raise ErrorActualizacion("El manifiesto de actualización no es válido")
    version = str(datos.get("version", "")).strip()
    sha256 = str(datos.get("sha256", "")).strip().lower()
    try:
        tamano = int(datos.get("tamano", 0))
    except (TypeError, ValueError) as exc:
        raise ErrorActualizacion("El tamaño del instalador no es válido") from exc
    _partes_version(version)
    if not PATRON_SHA256.fullmatch(sha256):
        raise ErrorActualizacion("La huella SHA-256 publicada no es válida")
    if tamano <= 0 or tamano > LIMITE_INSTALADOR:
        raise ErrorActualizacion("El tamaño publicado del instalador no es válido")
    if not es_mas_reciente(version, version_actual):
        return None
    return Actualizacion(version=version, sha256=sha256, tamano=tamano)


def _directorio_actualizaciones() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    return base / "ARGOS" / "actualizaciones"


def descargar_instalador(
    actualizacion: Actualizacion,
    directorio: str | Path | None = None,
    abrir: Callable = urlopen,
    progreso: Callable[[int, int], None] | None = None,
) -> Path:
    destino_dir = Path(directorio) if directorio else _directorio_actualizaciones()
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / f"ARGOS-Setup-{actualizacion.version}.exe"
    temporal = destino.with_suffix(".exe.part")
    huella = hashlib.sha256()
    descargado = 0
    peticion = Request(
        INSTALADOR_URL,
        headers={"User-Agent": f"ARGOS/{actualizacion.version}"},
    )
    try:
        with abrir(peticion, timeout=60) as respuesta, temporal.open("wb") as salida:
            while True:
                bloque = respuesta.read(1024 * 1024)
                if not bloque:
                    break
                descargado += len(bloque)
                if descargado > LIMITE_INSTALADOR:
                    raise ErrorActualizacion("El instalador supera el límite permitido")
                salida.write(bloque)
                huella.update(bloque)
                if progreso:
                    progreso(descargado, actualizacion.tamano)
        if descargado != actualizacion.tamano:
            raise ErrorActualizacion("La descarga del instalador está incompleta")
        if huella.hexdigest() != actualizacion.sha256:
            raise ErrorActualizacion("El instalador descargado no supera la comprobación SHA-256")
        temporal.replace(destino)
    except Exception:
        temporal.unlink(missing_ok=True)
        raise
    return destino


def lanzar_instalador(ruta: str | Path) -> None:
    """Inicia Inno Setup; Restart Manager cerrará y volverá a abrir ARGOS."""
    if os.name != "nt":
        raise ErrorActualizacion("La instalación automática solo está disponible en Windows")
    ejecutable = Path(ruta).resolve()
    if not ejecutable.is_file():
        raise ErrorActualizacion("No se encuentra el instalador descargado")
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [
            str(ejecutable),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/RESTARTAPPLICATIONS",
        ],
        close_fds=True,
        creationflags=flags,
    )


def actualizaciones_habilitadas() -> bool:
    return (
        os.name == "nt"
        and bool(getattr(sys, "frozen", False))
        and os.environ.get("ARGOS_DISABLE_UPDATES", "").strip() != "1"
        and not os.environ.get("ARGOS_SELFTEST_RESULT", "").strip()
    )
