from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

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


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.casefold()


def corregir_texto_medico(texto: str, correcciones: dict[str, str] | None = None) -> tuple[str, list[CambioMedico]]:
    """Corrige solo patrones explícitos de alta confianza.

    No intenta adivinar diagnósticos ni sustituye palabras por similitud fonética.
    Devuelve el texto y un registro de cambios para revisión humana.
    """
    resultado = texto or ""
    cambios: list[CambioMedico] = []
    reglas = dict(CORRECCIONES_BASE)
    if correcciones:
        reglas.update(correcciones)

    for original, corregido in sorted(reglas.items(), key=lambda x: len(x[0]), reverse=True):
        patron = re.compile(rf"(?<!\w){re.escape(original)}(?!\w)", re.IGNORECASE)
        coincidencias = list(patron.finditer(resultado))
        if not coincidencias:
            continue
        resultado = patron.sub(corregido, resultado)
        for _ in coincidencias:
            cambios.append(CambioMedico(original, corregido, "glosario médico validado", 1.0))
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
    return {str(k): str(v) for k, v in datos.items() if str(k).strip() and str(v).strip()}


def corregir_archivo_transcripcion(carpeta: str | Path) -> dict:
    carpeta = Path(carpeta)
    origen = carpeta / "transcripcion_limpia.txt"
    if not origen.exists():
        origen = carpeta / "transcripcion.txt"
    if not origen.exists():
        raise FileNotFoundError(origen)

    glosario = cargar_glosario_usuario(carpeta.parent.parent / "glosario_medico.json")
    lineas_salida: list[str] = []
    cambios_totales: list[dict] = []
    for numero, linea in enumerate(origen.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        corregida, cambios = corregir_texto_medico(linea, glosario)
        lineas_salida.append(corregida)
        for cambio in cambios:
            item = asdict(cambio)
            item["linea"] = numero
            cambios_totales.append(item)

    destino = carpeta / "transcripcion_medica_revisada.txt"
    destino.write_text("\n".join(lineas_salida), encoding="utf-8")
    informe = {
        "archivo_origen": origen.name,
        "archivo_corregido": destino.name,
        "cambios": cambios_totales,
        "total_cambios": len(cambios_totales),
        "regla": "Solo correcciones explícitas de alta confianza; requiere revisión humana.",
    }
    (carpeta / "correcciones_medicas.json").write_text(
        json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return informe
