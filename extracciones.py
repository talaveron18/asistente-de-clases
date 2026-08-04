from __future__ import annotations

from pathlib import Path


def ruta_extraccion_de(
    item: dict,
    raiz_biblioteca: str | Path,
) -> Path | None:
    """Resuelve la extracción canónica y las claves históricas.

    Si la biblioteca se ha movido y la ruta absoluta guardada ya no existe,
    recupera el JSON por el identificador estable del documento.
    """
    for clave in ("ruta_extraccion", "ruta_indice_texto", "indice_texto"):
        valor = item.get(clave)
        if not valor:
            continue
        ruta = Path(valor)
        if ruta.exists():
            return ruta

    item_id = str(item.get("id") or "").strip()
    if not item_id:
        return None
    recuperada = Path(raiz_biblioteca) / "_indice_texto" / f"{item_id}.json"
    return recuperada if recuperada.exists() else None
