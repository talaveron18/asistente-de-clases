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
    preguntas: list[dict] = []

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
            marca_pregunta = re.match(r"^\[([^\]]+)\]", pregunta)
            minuto_pregunta = (
                marca_pregunta.group(1)
                if marca_pregunta
                else bloque.get("inicio", "")
            )
            limpia = re.sub(r"^\[[^\]]+\]\s*", "", pregunta).strip()
            if limpia:
                respuesta, soporte, minuto_respuesta = _respuesta_desde_bloque(
                    limpia, bloque
                )
                preguntas.append({
                    "pregunta": limpia,
                    "respuesta": respuesta,
                    "minuto": minuto_pregunta,
                    "minuto_respuesta": minuto_respuesta,
                    "bloque": titulo,
                    "soporte": soporte,
                })
        if not bloque.get("preguntas"):
            respuesta = (
                bloque.get("resumen", "").strip()
                or _primera_frase(bloque.get("texto", ""))
            )
            preguntas.append({
                "pregunta": f"Explica los puntos esenciales de {titulo}.",
                "respuesta": respuesta,
                "minuto": bloque.get("inicio", ""),
                "minuto_respuesta": bloque.get("inicio", "") if respuesta else "",
                "bloque": titulo,
                "soporte": "resumen_extractivo" if respuesta else "sin_respuesta",
            })

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
    for i, pregunta in enumerate(preguntas, 1):
        etiqueta_soporte = _etiqueta_soporte(pregunta["soporte"])
        lineas += [
            f"{i}. **{pregunta['pregunta']}**",
            f"   - Respuesta basada en la clase: {pregunta['respuesta'] or 'No consta una respuesta explícita.'}",
            f"   - Tipo de soporte: {etiqueta_soporte}",
            f"   - Bloque: {pregunta['bloque']}",
            f"   - Pregunta formulada: {pregunta['minuto']}",
            f"   - Evidencia de respuesta: {pregunta['minuto_respuesta'] or 'no localizada'}",
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

    trazabilidad = _generar_trazabilidad(datos, preguntas)
    (carpeta / "trazabilidad_argos.json").write_text(
        json.dumps(trazabilidad, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (carpeta / "trazabilidad_argos.md").write_text(
        _generar_markdown_trazabilidad(trazabilidad), encoding="utf-8"
    )

    docx_generado = _generar_docx(carpeta, datos, preguntas, flashcards_unicas)
    archivos = [
        "apuntes_estudio_argos.md",
        "flashcards_argos.tsv",
        "preguntas_repaso.md",
        "repaso_rapido.md",
        "trazabilidad_argos.json",
        "trazabilidad_argos.md",
    ]
    if docx_generado:
        archivos.append("apuntes_argos.docx")

    return {
        "flashcards": len(flashcards_unicas),
        "preguntas": len(preguntas),
        "calidad": trazabilidad["metricas"],
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


def _es_pregunta(texto: str) -> bool:
    normal = texto.strip().casefold().lstrip("¿")
    return "?" in texto or bool(
        re.match(
            r"^(?:qué|cuál|cuáles|cómo|por qué|quién|quiénes|dónde|cuándo)\b",
            normal,
        )
    )


def _frases_del_bloque(bloque: dict) -> list[tuple[str, str]]:
    segmentos = bloque.get("segmentos") or []
    frases_temporales = []
    for segmento in segmentos:
        minuto = str(segmento.get("tiempo") or bloque.get("inicio", ""))
        frases_temporales.extend(
            (minuto, frase)
            for frase in _frases(segmento.get("texto", ""))
        )
    if frases_temporales:
        return frases_temporales
    return [
        (str(bloque.get("inicio", "")), frase)
        for frase in _frases(bloque.get("texto", ""))
    ]


def _respuesta_desde_bloque(pregunta: str, bloque: dict) -> tuple[str, str, str]:
    """Extrae una respuesta próxima; nunca completa datos que no estén escritos."""
    frases = _frases_del_bloque(bloque)
    pregunta_normalizada = re.sub(r"\W+", " ", pregunta.casefold()).strip()
    palabras = {
        palabra
        for palabra in pregunta_normalizada.split()
        if len(palabra) > 3
        and palabra not in {"como", "cual", "cuales", "donde", "cuando", "porque"}
    }
    minimo_coincidencias = 1 if len(palabras) <= 1 else 2
    candidatas = [
        (minuto, frase)
        for minuto, frase in frases
        if not _es_pregunta(frase)
        and sum(palabra in frase.casefold() for palabra in palabras)
        >= minimo_coincidencias
    ]
    if candidatas:
        minuto, respuesta = max(
            candidatas,
            key=lambda item: (
                sum(palabra in item[1].casefold() for palabra in palabras),
                min(len(item[1]), 600),
            ),
        )
        return (
            respuesta[:700],
            "respuesta_explicitada",
            minuto,
        )
    return "", "sin_respuesta", ""


def _etiqueta_soporte(soporte: str) -> str:
    return {
        "respuesta_explicitada": "respuesta localizada en la transcripción",
        "resumen_extractivo": "respuesta construida con el resumen extractivo del bloque",
        "sin_respuesta": "la clase formula la pregunta, pero no conserva una respuesta explícita",
    }.get(soporte, soporte.replace("_", " "))


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


def _generar_apuntes_metodo_argos(datos: dict, preguntas: list[dict]) -> str:
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
    for numero, pregunta in enumerate(preguntas, 1):
        lineas += [
            f"{numero}. **{pregunta['pregunta']}**",
            f"   - **Respuesta según la clase:** {pregunta['respuesta'] or 'No consta una respuesta explícita.'}",
            f"   - **Soporte:** {_etiqueta_soporte(pregunta['soporte'])}",
            f"   - **Pregunta formulada:** {pregunta['bloque']}, {pregunta['minuto']}",
            f"   - **Evidencia de respuesta:** {pregunta['minuto_respuesta'] or 'no localizada'}",
            "",
        ]
    return "\n".join(lineas)


def _generar_trazabilidad(datos: dict, preguntas: list[dict]) -> dict:
    bloques_salida = []
    total_referencias = 0
    bloques_con_referencias = 0
    relaciones_total = 0
    comparaciones_total = 0

    for bloque in datos.get("bloques", []):
        referencias = []
        for referencia in bloque.get("referencias_locales", []):
            referencias.append({
                "titulo": referencia.get("titulo", "Documento"),
                "ubicacion": referencia.get("ubicacion") or (
                    f"Página {referencia.get('pagina')}"
                    if referencia.get("pagina")
                    else "Sin página"
                ),
                "pagina": referencia.get("pagina"),
                "ruta": referencia.get("ruta", ""),
                "fragmento": referencia.get("fragmento", ""),
                "vinculada_a_clase": bool(referencia.get("vinculada_a_clase")),
            })
        relaciones = _relaciones_fisiopatologicas(bloque.get("texto", ""))
        comparaciones = _comparaciones(bloque.get("texto", ""))
        total_referencias += len(referencias)
        bloques_con_referencias += bool(referencias)
        relaciones_total += len(relaciones)
        comparaciones_total += len(comparaciones)
        bloques_salida.append({
            "numero": bloque.get("numero"),
            "titulo": bloque.get("titulo", "Bloque"),
            "inicio": bloque.get("inicio", ""),
            "fin": bloque.get("fin", ""),
            "idea_central": bloque.get("resumen", ""),
            "relaciones_causales": relaciones,
            "comparaciones": comparaciones,
            "avisos_examen": bloque.get("avisos_examen", []),
            "referencias_documentales": referencias,
        })

    total_bloques = len(bloques_salida)
    preguntas_explicitas = sum(
        pregunta.get("soporte") == "respuesta_explicitada"
        for pregunta in preguntas
    )
    preguntas_resumen = sum(
        pregunta.get("soporte") == "resumen_extractivo"
        for pregunta in preguntas
    )
    preguntas_sin_respuesta = sum(
        pregunta.get("soporte") == "sin_respuesta"
        for pregunta in preguntas
    )
    cobertura = round(
        (bloques_con_referencias / total_bloques) * 100, 1
    ) if total_bloques else 0.0
    metricas = {
        "bloques": total_bloques,
        "bloques_con_referencia_documental": bloques_con_referencias,
        "cobertura_documental_porcentaje": cobertura,
        "referencias_documentales": total_referencias,
        "relaciones_causales_explicitas": relaciones_total,
        "comparaciones_explicitas": comparaciones_total,
        "preguntas": len(preguntas),
        "preguntas_con_respuesta_explicitada": preguntas_explicitas,
        "preguntas_desde_resumen": preguntas_resumen,
        "preguntas_sin_respuesta": preguntas_sin_respuesta,
    }
    return {
        "version": 1,
        "titulo": datos.get("titulo", "Clase"),
        "materia": datos.get("materia", ""),
        "archivo_fuente": datos.get("archivo_fuente", ""),
        "criterio": (
            "Solo se atribuyen respuestas explícitas cuando ARGOS localiza una "
            "frase afirmativa relacionada en la transcripción. La cobertura "
            "documental mide presencia de referencias, no exactitud clínica."
        ),
        "metricas": metricas,
        "preguntas": preguntas,
        "bloques": bloques_salida,
    }


def _generar_markdown_trazabilidad(trazabilidad: dict) -> str:
    metricas = trazabilidad["metricas"]
    lineas = [
        f"# Fuentes y control · {trazabilidad.get('titulo', 'Clase')}",
        "",
        f"**Transcripción fuente:** {trazabilidad.get('archivo_fuente', '')}",
        "",
        f"> {trazabilidad.get('criterio', '')}",
        "",
        "## Control de cobertura",
        "",
        "| Indicador | Resultado |",
        "|---|---|",
        f"| Bloques temáticos | {metricas['bloques']} |",
        f"| Bloques con referencia documental | {metricas['bloques_con_referencia_documental']} de {metricas['bloques']} ({metricas['cobertura_documental_porcentaje']} %) |",
        f"| Referencias documentales localizadas | {metricas['referencias_documentales']} |",
        f"| Relaciones causales explícitas | {metricas['relaciones_causales_explicitas']} |",
        f"| Comparaciones explícitas | {metricas['comparaciones_explicitas']} |",
        f"| Preguntas con respuesta localizada | {metricas['preguntas_con_respuesta_explicitada']} de {metricas['preguntas']} |",
        f"| Preguntas sin respuesta explícita | {metricas['preguntas_sin_respuesta']} |",
        "",
    ]
    for bloque in trazabilidad.get("bloques", []):
        lineas += [
            f"## {bloque.get('numero')}. {bloque.get('titulo')}",
            "",
            f"**Audio/transcripción:** {bloque.get('inicio')}–{bloque.get('fin')}",
            "",
            "### Idea central extraída",
            "",
            bloque.get("idea_central") or "No se obtuvo una idea central fiable.",
            "",
            "### Referencias documentales",
            "",
        ]
        referencias = bloque.get("referencias_documentales", [])
        if referencias:
            for referencia in referencias:
                prioridad = (
                    "fuente vinculada por el usuario"
                    if referencia.get("vinculada_a_clase")
                    else "biblioteca general"
                )
                lineas += [
                    f"- **{referencia.get('titulo')} · {referencia.get('ubicacion')}** ({prioridad})",
                    f"  - {referencia.get('fragmento') or 'Sin fragmento disponible.'}",
                ]
        else:
            lineas.append("- Este bloque no tiene contraste documental localizado.")
        lineas.append("")

    lineas += ["## Auditoría de preguntas", ""]
    for numero, pregunta in enumerate(trazabilidad.get("preguntas", []), 1):
        lineas += [
            f"{numero}. **{pregunta.get('pregunta')}**",
            f"   - Respuesta: {pregunta.get('respuesta') or 'No consta una respuesta explícita.'}",
            f"   - Soporte: {_etiqueta_soporte(pregunta.get('soporte', ''))}",
            f"   - Pregunta formulada: {pregunta.get('bloque')}, {pregunta.get('minuto')}",
            f"   - Evidencia de respuesta: {pregunta.get('minuto_respuesta') or 'no localizada'}",
            "",
        ]
    return "\n".join(lineas)


def _generar_docx(carpeta: Path, datos: dict, preguntas: list[dict], flashcards: list) -> bool:
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
    for pregunta in preguntas:
        doc.add_paragraph(
            f"{pregunta['pregunta']} ({pregunta['bloque']}, {pregunta['minuto']})",
            style="List Number",
        )
        doc.add_paragraph(
            "Respuesta basada en la clase: "
            f"{pregunta['respuesta'] or 'No consta una respuesta explícita.'}"
        )
        doc.add_paragraph(f"Soporte: {_etiqueta_soporte(pregunta['soporte'])}")
        doc.add_paragraph(
            "Evidencia de respuesta: "
            f"{pregunta['minuto_respuesta'] or 'no localizada'}"
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
