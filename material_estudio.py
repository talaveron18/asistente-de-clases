from __future__ import annotations

import csv
import json
import re
from pathlib import Path


def generar_material_estudio(carpeta: str | Path) -> dict:
    carpeta = Path(carpeta)
    datos = json.loads((carpeta / "pipeline_clase.json").read_text(encoding="utf-8"))
    flashcards = []
    preguntas = []

    for bloque in datos.get("bloques", []):
        titulo = bloque.get("titulo", "Bloque")
        resumen = bloque.get("resumen", "").strip()
        claves = bloque.get("palabras_clave", [])
        if resumen:
            flashcards.append((f"Resume {titulo}", resumen, bloque.get("inicio", "")))
        for clave in claves[:5]:
            respuesta = _frase_relevante(bloque.get("texto", ""), clave)
            if respuesta:
                flashcards.append((f"¿Qué se explicó sobre {clave}?", respuesta, bloque.get("inicio", "")))
        for pregunta in bloque.get("preguntas", []):
            limpia = re.sub(r"^\[[^\]]+\]\s*", "", pregunta).strip()
            if limpia:
                preguntas.append((limpia, bloque.get("inicio", ""), titulo))
        if not bloque.get("preguntas"):
            preguntas.append((f"Explica los puntos esenciales de {titulo}.", bloque.get("inicio", ""), titulo))

    # Eliminar duplicados conservando orden.
    vistos = set()
    flashcards_unicas = []
    for frente, dorso, minuto in flashcards:
        clave = (frente.casefold(), dorso.casefold())
        if clave not in vistos:
            vistos.add(clave)
            flashcards_unicas.append((frente, dorso, minuto))

    with (carpeta / "flashcards_argos.tsv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["Frente", "Dorso", "Minuto"])
        writer.writerows(flashcards_unicas)

    lineas = [f"# Preguntas de repaso · {datos.get('titulo', '')}", ""]
    for i, (pregunta, minuto, bloque) in enumerate(preguntas, 1):
        lineas += [f"{i}. **{pregunta}**", f"   - Bloque: {bloque}", f"   - Referencia: {minuto}", ""]
    (carpeta / "preguntas_repaso.md").write_text("\n".join(lineas), encoding="utf-8")

    hoja = [
        f"# Hoja de repaso rápido · {datos.get('titulo', '')}", "",
        f"**Materia:** {datos.get('materia', '')}", "",
        "## Conceptos dominantes", "",
        ", ".join(datos.get("palabras_clave_globales", [])) or "—", "",
        "## Avisos de examen", "",
    ]
    hoja += [f"- {x}" for x in datos.get("avisos_examen", [])] or ["- No se detectaron avisos explícitos."]
    hoja += ["", "## Bloques esenciales", ""]
    for bloque in datos.get("bloques", []):
        hoja += [
            f"### {bloque.get('numero')}. {bloque.get('titulo')}",
            f"**Minuto:** {bloque.get('inicio')}–{bloque.get('fin')}", "",
            bloque.get("resumen", ""), "",
        ]
    (carpeta / "repaso_rapido.md").write_text("\n".join(hoja), encoding="utf-8")

    return {
        "flashcards": len(flashcards_unicas),
        "preguntas": len(preguntas),
        "archivos": ["flashcards_argos.tsv", "preguntas_repaso.md", "repaso_rapido.md"],
    }


def _frase_relevante(texto: str, palabra: str) -> str:
    frases = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", texto) if x.strip()]
    candidatas = [x for x in frases if palabra.casefold() in x.casefold()]
    if not candidatas:
        return ""
    mejor = max(candidatas, key=lambda x: min(len(x), 500))
    return mejor[:600]
