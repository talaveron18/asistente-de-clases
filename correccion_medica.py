from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from transcripciones import fuente_original

# Correcciones de errores frecuentes de ASR. Solo se aplican coincidencias completas.
# La lista debe crecer con datos reales del usuario, no con sustituciones especulativas.
CORRECCIONES_BASE = {
    "interleucina uno": "interleucina 1",
    "interleucina dos": "interleucina 2",
    "interleucina seis": "interleucina 6",
    "factor de necrosis tumoral alfa": "TNF-alfa",
    "inmunoglobulina ge": "inmunoglobulina G",
    "inmunoglobulina eme": "inmunoglobulina M",
    "linfocito te": "linfocito T",
    "linfocitos te": "linfocitos T",
    "linfocito be": "linfocito B",
    "linfocitos be": "linfocitos B",
    "gram positiva": "Gram positiva",
    "gram positivas": "Gram positivas",
    "gram negativa": "Gram negativa",
    "gram negativas": "Gram negativas",
    "pese erre": "PCR",
    "reacción en cadena de polimerasa": "reacción en cadena de la polimerasa",
    "se de cuatro": "CD4",
    "se de ocho": "CD8",
    "c tres": "C3",
    "c cinco": "C5",
}


@dataclass
class CambioMedico:
    original: str
    corregido: str
    motivo: str
    confianza: float


def corregir_texto_medico(
    texto: str,
    correcciones: dict[str, str] | None = None,
) -> tuple[str, list[CambioMedico]]:
    """Corrige solo patrones explícitos de alta confianza."""
    resultado = texto or ""
    cambios: list[CambioMedico] = []
    reglas = dict(CORRECCIONES_BASE)
    if correcciones:
        reglas.update(correcciones)

    for original, corregido in sorted(
        reglas.items(), key=lambda x: len(x[0]), reverse=True
    ):
        patron = re.compile(
            rf"(?<!\w){re.escape(original)}(?!\w)", re.IGNORECASE
        )
        coincidencias = list(patron.finditer(resultado))
        if not coincidencias:
            continue
        resultado = patron.sub(corregido, resultado)
        cambios.extend(
            CambioMedico(
                original,
                corregido,
                "glosario médico validado",
                1.0,
            )
            for _ in coincidencias
        )
    return resultado, cambios


def cargar_glosario_usuario(ruta: str | Path) -> dict[str, str]:
    path = Path(ruta)
    if not path.exists():
        return {}
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(datos, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in datos.items()
        if str(k).strip() and str(v).strip()
    }


def _escribir_atomico(ruta: Path, contenido: str) -> None:
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(contenido, encoding="utf-8")
    temporal.replace(ruta)


def corregir_archivo_transcripcion(carpeta: str | Path) -> dict:
    """Genera la revisión siempre desde el original, nunca desde una derivada.

    Esto hace que reprocesar sea idempotente y evita encadenar limpieza o
    correcciones sobre ``transcripcion_limpia.txt``.
    """
    carpeta = Path(carpeta)
    origen = fuente_original(carpeta)
    glosario = cargar_glosario_usuario(
        carpeta.parent.parent / "glosario_medico.json"
    )

    lineas_salida: list[str] = []
    cambios_totales: list[dict] = []
    for numero, linea in enumerate(
        origen.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        corregida, cambios = corregir_texto_medico(linea, glosario)
        lineas_salida.append(corregida)
        for cambio in cambios:
            item = asdict(cambio)
            item["linea"] = numero
            cambios_totales.append(item)

    destino = carpeta / "transcripcion_medica_revisada.txt"
    _escribir_atomico(destino, "\n".join(lineas_salida))
    informe = {
        "archivo_origen": origen.name,
        "archivo_corregido": destino.name,
        "cambios": cambios_totales,
        "total_cambios": len(cambios_totales),
        "regla": (
            "Solo correcciones explícitas de alta confianza; requiere revisión humana."
        ),
    }
    _escribir_atomico(
        carpeta / "correcciones_medicas.json",
        json.dumps(informe, ensure_ascii=False, indent=2),
    )
    return informe
