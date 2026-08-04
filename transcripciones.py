from __future__ import annotations

from pathlib import Path


NOMBRE_ORIGINAL = "transcripcion.txt"
NOMBRE_REVISADA = "transcripcion_medica_revisada.txt"


def fuente_original(carpeta: str | Path) -> Path:
    """Devuelve la transcripción original e inmutable de una clase."""
    ruta = Path(carpeta) / NOMBRE_ORIGINAL
    if not ruta.exists():
        raise FileNotFoundError(ruta)
    return ruta


def fuente_vigente(carpeta: str | Path) -> Path:
    """Selecciona la mejor transcripción disponible.

    La revisión médica solo se usa cuando existe y no es más antigua que el
    original. ``transcripcion_limpia.txt`` nunca se considera una entrada: es
    una salida derivada y no debe encadenar pérdidas de información.
    """
    carpeta = Path(carpeta)
    original = fuente_original(carpeta)
    revisada = carpeta / NOMBRE_REVISADA
    if revisada.exists() and revisada.stat().st_mtime >= original.stat().st_mtime:
        return revisada
    return original


def procedencia(carpeta: str | Path) -> str:
    return "clase/revisada" if fuente_vigente(carpeta).name == NOMBRE_REVISADA else "clase/original"
