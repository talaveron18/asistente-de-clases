from __future__ import annotations

import csv
import json
import re
from pathlib import Path


def generar_material_estudio(carpeta: str | Path) -> dict:
    carpeta = Path(carpeta)
    fuente = carpeta / "argos_enriquecido.json"
    if not fuente.exists():
        fuente = carpeta / "pipeline_clase.json"
    datos = json.loads(fuente.read_text(encoding="utf-8"))
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
                preguntas.append(
                    (
                        limpia,
                        _respuesta_desde_bloque(limpia, bloque),
                        bloque.get("inicio", ""),
                        titulo,
                    )
                )
        if not bloque.get("preguntas"):
            preguntas.append(
                (
                    f"Explica los puntos esenciales de {titulo}.",
                    bloque.get("resumen", "").strip()
                    or _primera_frase(bloque.get("texto", "")),
                    bloque.get("inicio", ""),
                    titulo,
                )
            )

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
    for i, (pregunta, respuesta, minuto, bloque) in enumerate(preguntas, 1):
        lineas += [
            f"{i}. **{pregunta}**",
            f"   - Respuesta basada en la clase: {respuesta or 'No consta una respuesta explícita.'}",
            f"   - Bloque: {bloque}",
            f"   - Referencia: {minuto}",
            "",
        ]
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

    (carpeta / "apuntes_estudio_argos.md").write_text(
        _generar_apuntes_metodo_argos(datos, preguntas), encoding="utf-8"
    )

    docx_generado = _generar_docx(carpeta, datos, preguntas, flashcards_unicas)
    archivos = [
        "apuntes_estudio_argos.md",
        "flashcards_argos.tsv",
        "preguntas_repaso.md",
        "repaso_rapido.md",
    ]
    if docx_generado:
        archivos.append("apuntes_argos.docx")

    return {
        "flashcards": len(flashcards_unicas),
        "preguntas": len(preguntas),
        "archivos": archivos,
        "fuente": fuente.name,
    }


def _frases(texto: str) -> list[str]:
    return [
        frase.strip()
        for frase in re.split(r"(?<=[.!?])\s+|\n+", texto or "")
        if frase.strip()
    ]


def _primera_frase(texto: str) -> str:
    frases = _frases(texto)
    return frases[0] if frases else ""


def _respuesta_desde_bloque(pregunta: str, bloque: dict) -> str:
    """Extrae una respuesta próxima; nunca completa datos que no estén escritos."""
    frases = _frases(bloque.get("texto", ""))
    pregunta_normalizada = re.sub(r"\W+", " ", pregunta.casefold()).strip()
    palabras = {
        palabra
        for palabra in pregunta_normalizada.split()
        if len(palabra) > 3
        and palabra not in {"como", "cual", "cuales", "donde", "cuando", "porque"}
    }
    candidatas = [
        frase
        for frase in frases
        if "?" not in frase
        and sum(palabra in frase.casefold() for palabra in palabras) >= 1
    ]
    if candidatas:
        return max(candidatas, key=lambda frase: min(len(frase), 600))[:700]
    return (bloque.get("resumen", "") or _primera_frase(bloque.get("texto", "")))[:700]


def _relaciones_fisiopatologicas(texto: str) -> list[str]:
    marcadores = (
        "produce", "provoca", "causa", "conduce", "genera", "desencadena",
        "debido a", "porque", "por tanto", "como consecuencia", "se debe a",
    )
    return [
        frase for frase in _frases(texto)
        if any(marcador in frase.casefold() for marcador in marcadores)
    ][:8]


def _comparaciones(texto: str) -> list[str]:
    marcadores = (
        "a diferencia", "mientras que", "en cambio", "comparado con",
        "más que", "menos que", "frente a", "versus",
    )
    return [
        frase for frase in _frases(texto)
        if any(marcador in frase.casefold() for marcador in marcadores)
    ][:8]


def _errores_frecuentes(texto: str, avisos: list[str]) -> list[str]:
    marcadores = (
        "no confundir", "ojo", "atención", "excepto", "nunca", "error",
        "no es", "a diferencia",
    )
    encontrados = [
        frase for frase in _frases(texto)
        if any(marcador in frase.casefold() for marcador in marcadores)
    ]
    encontrados.extend(avisos)
    return list(dict.fromkeys(encontrados))[:8]


def _generar_apuntes_metodo_argos(datos: dict, preguntas: list[tuple]) -> str:
    lineas = [
        f"# {datos.get('titulo', 'Clase')} · Método ARGOS",
        "",
        f"**Materia:** {datos.get('materia', '')}",
        f"**Transcripción utilizada:** {datos.get('archivo_fuente', '')}",
        "",
        "> Material extractivo: organiza lo dicho en clase y las fuentes vinculadas; no completa información ausente.",
        "",
        "## Mapa de la clase",
        "",
    ]
    lineas += [
        f"- **{bloque.get('inicio')}–{bloque.get('fin')}** · {bloque.get('titulo')}"
        for bloque in datos.get("bloques", [])
    ] or ["- No se detectaron bloques temáticos."]

    for bloque in datos.get("bloques", []):
        lineas += [
            "",
            f"## {bloque.get('numero')}. {bloque.get('titulo')}",
            "",
            f"**Minuto:** {bloque.get('inicio')}–{bloque.get('fin')}",
            "",
            "### Idea central",
            "",
            bloque.get("resumen", "") or "No se obtuvo un resumen fiable.",
            "",
            "### Historia fisiopatológica",
            "",
        ]
        relaciones = _relaciones_fisiopatologicas(bloque.get("texto", ""))
        lineas += [f"{i}. {frase}" for i, frase in enumerate(relaciones, 1)] or [
            "No se detectó una secuencia causal explícita en este bloque."
        ]
        lineas += ["", "### Comparaciones expresadas", ""]
        comparaciones = _comparaciones(bloque.get("texto", ""))
        if comparaciones:
            lineas += [
                "| Referencia | Comparación literal de la clase |",
                "|---|---|",
                *[
                    f"| {bloque.get('inicio')} | {frase.replace('|', '/')} |"
                    for frase in comparaciones
                ],
            ]
        else:
            lineas.append("No se detectaron comparaciones explícitas.")
        lineas += ["", "### Errores frecuentes y avisos", ""]
        errores = _errores_frecuentes(
            bloque.get("texto", ""), bloque.get("avisos_examen", [])
        )
        lineas += [f"- {frase}" for frase in errores] or [
            "- No se detectaron advertencias explícitas."
        ]
        lineas += ["", "### Desarrollo limpio", "", bloque.get("texto", ""), ""]
        referencias = bloque.get("referencias_locales", [])
        lineas += ["### Contraste con PDF o bibliografía", ""]
        if referencias:
            for referencia in referencias:
                ubicacion = referencia.get("ubicacion") or (
                    f"Página {referencia.get('pagina')}"
                    if referencia.get("pagina")
                    else "sin página"
                )
                prioridad = (
                    "vinculada a la clase"
                    if referencia.get("vinculada_a_clase")
                    else "biblioteca general"
                )
                lineas += [
                    f"- **{referencia.get('titulo')} · {ubicacion}** ({prioridad})",
                    f"  - {referencia.get('fragmento', '')}",
                ]
        else:
            lineas.append("- No se localizaron referencias documentales próximas.")

    lineas += ["", "## Preguntas de parcial con respuesta", ""]
    for numero, (pregunta, respuesta, minuto, bloque) in enumerate(preguntas, 1):
        lineas += [
            f"{numero}. **{pregunta}**",
            f"   - **Respuesta según la clase:** {respuesta or 'No consta una respuesta explícita.'}",
            f"   - **Referencia:** {bloque}, {minuto}",
            "",
        ]
    return "\n".join(lineas)


def _generar_docx(carpeta: Path, datos: dict, preguntas: list, flashcards: list) -> bool:
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError:
        return False

    doc = Document()
    estilos = doc.styles
    estilos["Normal"].font.name = "Aptos"
    estilos["Normal"].font.size = Pt(10.5)

    doc.add_heading(datos.get("titulo", "Clase"), 0)
    doc.add_paragraph(f"Materia: {datos.get('materia', '')}")
    doc.add_paragraph("Documento generado automáticamente a partir de la transcripción. Requiere revisión.")

    doc.add_heading("Conceptos dominantes", level=1)
    doc.add_paragraph(", ".join(datos.get("palabras_clave_globales", [])) or "No detectados.")

    doc.add_heading("Índice temporal", level=1)
    for bloque in datos.get("bloques", []):
        doc.add_paragraph(
            f"{bloque.get('inicio')}–{bloque.get('fin')} · {bloque.get('titulo')}",
            style="List Bullet",
        )

    doc.add_heading("Apuntes por bloques", level=1)
    for bloque in datos.get("bloques", []):
        doc.add_heading(f"{bloque.get('numero')}. {bloque.get('titulo')}", level=2)
        doc.add_paragraph(f"Referencia: {bloque.get('inicio')}–{bloque.get('fin')}")
        doc.add_heading("Resumen", level=3)
        doc.add_paragraph(bloque.get("resumen", "") or "Sin resumen automático.")
        doc.add_heading("Conceptos clave", level=3)
        doc.add_paragraph(", ".join(bloque.get("palabras_clave", [])) or "—")
        doc.add_heading("Historia fisiopatológica", level=3)
        relaciones = _relaciones_fisiopatologicas(bloque.get("texto", ""))
        if relaciones:
            for relacion in relaciones:
                doc.add_paragraph(relacion, style="List Number")
        else:
            doc.add_paragraph(
                "No se detectó una secuencia causal explícita en este bloque."
            )
        comparaciones = _comparaciones(bloque.get("texto", ""))
        if comparaciones:
            doc.add_heading("Comparaciones expresadas", level=3)
            tabla_comparaciones = doc.add_table(rows=1, cols=2)
            tabla_comparaciones.style = "Table Grid"
            tabla_comparaciones.rows[0].cells[0].text = "Minuto"
            tabla_comparaciones.rows[0].cells[1].text = "Comparación literal"
            for comparacion in comparaciones:
                celdas = tabla_comparaciones.add_row().cells
                celdas[0].text = bloque.get("inicio", "")
                celdas[1].text = comparacion
        errores = _errores_frecuentes(
            bloque.get("texto", ""), bloque.get("avisos_examen", [])
        )
        if errores:
            doc.add_heading("Errores frecuentes y avisos", level=3)
            for error in errores:
                doc.add_paragraph(error, style="List Bullet")
        if bloque.get("avisos_examen"):
            doc.add_heading("Avisos de examen", level=3)
            for aviso in bloque["avisos_examen"]:
                doc.add_paragraph(aviso, style="List Bullet")
        if bloque.get("preguntas"):
            doc.add_heading("Preguntas formuladas", level=3)
            for pregunta in bloque["preguntas"]:
                doc.add_paragraph(pregunta, style="List Bullet")
        doc.add_heading("Desarrollo limpio", level=3)
        doc.add_paragraph(bloque.get("texto", ""))
        referencias = bloque.get("referencias_locales", [])
        if referencias:
            doc.add_heading("Contraste documental", level=3)
            for referencia in referencias:
                doc.add_paragraph(
                    f"{referencia.get('titulo')} · {referencia.get('ubicacion')}: "
                    f"{referencia.get('fragmento', '')}",
                    style="List Bullet",
                )

    doc.add_heading("Preguntas de repaso", level=1)
    for pregunta, respuesta, minuto, bloque in preguntas:
        doc.add_paragraph(
            f"{pregunta} ({bloque}, {minuto})", style="List Number"
        )
        doc.add_paragraph(
            f"Respuesta basada en la clase: {respuesta or 'No consta una respuesta explícita.'}"
        )

    doc.add_heading("Flashcards", level=1)
    tabla = doc.add_table(rows=1, cols=3)
    tabla.style = "Table Grid"
    tabla.rows[0].cells[0].text = "Frente"
    tabla.rows[0].cells[1].text = "Dorso"
    tabla.rows[0].cells[2].text = "Minuto"
    for frente, dorso, minuto in flashcards:
        celdas = tabla.add_row().cells
        celdas[0].text = frente
        celdas[1].text = dorso
        celdas[2].text = minuto

    doc.save(carpeta / "apuntes_argos.docx")
    return True


def _frase_relevante(texto: str, palabra: str) -> str:
    frases = [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", texto) if x.strip()]
    candidatas = [x for x in frases if palabra.casefold() in x.casefold()]
    if not candidatas:
        return ""
    mejor = max(candidatas, key=lambda x: min(len(x), 500))
    return mejor[:600]
