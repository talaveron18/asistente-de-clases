from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from transcripciones import fuente_vigente, procedencia

STOPWORDS = {
    "para", "como", "pero", "porque", "desde", "hasta", "sobre", "entre",
    "cuando", "donde", "este", "esta", "estos", "estas", "esto", "eso",
    "esa", "ese", "unos", "unas", "tambien", "entonces", "vamos", "ahora",
    "bueno", "bien", "muy", "mas", "menos", "cada", "todo", "toda", "todos",
    "todas", "del", "las", "los", "una", "uno", "que", "con", "sin", "por",
    "se", "es", "son", "ser", "ha", "hay", "al", "lo", "la", "el", "en",
    "y", "o", "a", "de", "un", "ya", "si", "no", "tiene", "tienen",
    "puede", "pueden",
}

# Conservador: no se eliminan «este», «vale» ni palabras con posible valor semántico.
MULETILLAS = (
    r"\b(?:eh+|em+|mmm+)\b[,. ]*",
    r"\b(?:o sea|digamos)\b[,. ]*",
)

MARCADORES_TEMA = (
    "ahora vamos a", "pasamos a", "vamos a ver", "continuamos con",
    "el siguiente tema", "por otro lado", "a continuación", "para terminar",
    "en cuanto a", "respecto a", "vamos a hablar de", "entramos en", "vamos con",
)

MARCADORES_EXAMEN = (
    "esto entra", "entra en el examen", "de cara al examen", "puede caer",
    "suele caer", "lo preguntan", "esto es importante", "muy importante",
    "ojo con", "atención a", "no os olvidéis", "no se olviden",
    "pregunta de examen", "esto es clave", "tened cuidado", "recordad que",
)

PREGUNTA_SIN_SIGNO = re.compile(
    r"^(?:y|entonces|pero|ahora)?\s*(?:¿\s*)?"
    r"(?:qué|cuál|cuáles|cómo|por qué|quién|quiénes|dónde|cuándo)\b",
    re.IGNORECASE,
)


@dataclass
class Hallazgo:
    tipo: str
    tiempo: str
    texto: str
    confianza: str


@dataclass
class BloqueTematico:
    numero: int
    inicio: str
    fin: str
    titulo: str
    texto: str
    resumen: str
    palabras_clave: list[str]
    avisos_examen: list[str]
    preguntas: list[str]
    cambios_tema: list[str]


def _parse_linea(linea: str) -> dict | None:
    linea = linea.strip()
    if not linea:
        return None
    con_rol = re.match(r"^\[([^\]]+)\]\s*([^:]+):\s*(.*)$", linea)
    if con_rol:
        return {
            "tiempo": con_rol.group(1),
            "rol": con_rol.group(2).strip(),
            "texto": con_rol.group(3).strip(),
        }
    sin_rol = re.match(r"^\[([^\]]+)\]\s*(.*)$", linea)
    if sin_rol:
        return {
            "tiempo": sin_rol.group(1),
            "rol": "Desconocido",
            "texto": sin_rol.group(2).strip(),
        }
    return {"tiempo": "00:00", "rol": "Desconocido", "texto": linea}


def _segundos(marca: str) -> int:
    try:
        partes = [int(x) for x in marca.split(":")]
    except ValueError:
        return 0
    if len(partes) == 2:
        return partes[0] * 60 + partes[1]
    if len(partes) == 3:
        return partes[0] * 3600 + partes[1] * 60 + partes[2]
    return 0


def limpiar_texto(texto: str) -> str:
    resultado = texto or ""
    for patron in MULETILLAS:
        resultado = re.sub(patron, " ", resultado, flags=re.IGNORECASE)
    resultado = re.sub(
        r"\b([\wáéíóúüñ-]+)(?:\s+\1){1,}\b",
        r"\1",
        resultado,
        flags=re.IGNORECASE,
    )
    resultado = re.sub(r"\s+([,.;:!?])", r"\1", resultado)
    resultado = re.sub(r"\s+", " ", resultado).strip(" ,.-")
    if resultado:
        resultado = resultado[0].upper() + resultado[1:]
    return resultado


def _palabras_clave(texto: str, limite: int = 8) -> list[str]:
    tokens = re.findall(
        r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\wáéíóúüñ-]{3,}", texto.casefold()
    )
    conteo = Counter(t for t in tokens if t not in STOPWORDS)
    return [p for p, _ in conteo.most_common(limite)]


def _titulo_bloque(textos: list[str], numero: int) -> str:
    unido = " ".join(textos[:5])
    bajo = unido.casefold()
    for marcador in MARCADORES_TEMA:
        pos = bajo.find(marcador)
        if pos >= 0:
            candidato = unido[pos + len(marcador):].strip(" :,.—-")
            candidato = re.split(r"[.!?]", candidato)[0].strip()
            if 3 <= len(candidato) <= 90:
                return candidato[0].upper() + candidato[1:]
    claves = _palabras_clave(" ".join(textos), 4)
    return " · ".join(p.title() for p in claves) if claves else f"Bloque {numero}"


def _resumen_extractivo(textos: list[str], max_frases: int = 5) -> str:
    frases: list[str] = []
    for texto in textos:
        frases.extend(
            f.strip()
            for f in re.split(r"(?<=[.!?])\s+", texto)
            if len(f.strip()) > 35
        )
    if not frases:
        return " ".join(textos[:3])[:900]
    claves = set(_palabras_clave(" ".join(frases), 12))
    puntuadas = []
    for i, frase in enumerate(frases):
        score = (
            sum(1 for p in claves if p in frase.casefold())
            + min(len(frase) / 180, 1)
            + (1 if i < 3 else 0)
        )
        puntuadas.append((score, -i, frase))
    elegidas = sorted(puntuadas, reverse=True)[:max_frases]
    elegidas.sort(key=lambda x: -x[1])
    return " ".join(x[2] for x in elegidas)


def _detectar_hallazgos(entradas: list[dict]) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    vistos: set[tuple[str, str, str]] = set()
    for entrada in entradas:
        texto = entrada["texto"].strip()
        normal = texto.casefold()
        candidatos: list[Hallazgo] = []

        if "?" in texto or texto.startswith("¿"):
            candidatos.append(Hallazgo("pregunta", entrada["tiempo"], texto, "alta"))
        elif PREGUNTA_SIN_SIGNO.search(texto):
            candidatos.append(Hallazgo("pregunta", entrada["tiempo"], texto, "media"))

        if any(m in normal for m in MARCADORES_EXAMEN):
            candidatos.append(Hallazgo("examen", entrada["tiempo"], texto, "alta"))

        if any(m in normal for m in MARCADORES_TEMA):
            candidatos.append(Hallazgo("tema", entrada["tiempo"], texto, "media"))

        for candidato in candidatos:
            clave = (candidato.tipo, candidato.tiempo, candidato.texto)
            if clave not in vistos:
                vistos.add(clave)
                hallazgos.append(candidato)
    return hallazgos


def _escribir_atomico(ruta: Path, contenido: str) -> None:
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(contenido, encoding="utf-8")
    temporal.replace(ruta)


def analizar_clase_completa(
    carpeta: str | Path,
    minutos_bloque: int = 12,
) -> dict:
    """Único motor de limpieza, análisis y segmentación de clases."""
    carpeta = Path(carpeta)
    transcripcion = fuente_vigente(carpeta)
    entradas = [
        _parse_linea(x)
        for x in transcripcion.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    ]
    entradas = [x for x in entradas if x and x["texto"]]
    if not entradas:
        raise ValueError("La transcripción no contiene segmentos analizables.")

    for entrada in entradas:
        entrada["texto_limpio"] = limpiar_texto(entrada["texto"])
        entrada["segundos"] = _segundos(entrada["tiempo"])

    hallazgos = _detectar_hallazgos(entradas)
    bloques_raw: list[list[dict]] = [[]]
    inicio_actual = entradas[0]["segundos"]
    for entrada in entradas:
        cambio_explicito = any(
            m in entrada["texto"].casefold() for m in MARCADORES_TEMA
        )
        supera_intervalo = (
            entrada["segundos"] - inicio_actual >= max(5, minutos_bloque) * 60
        )
        if bloques_raw[-1] and (cambio_explicito or supera_intervalo):
            bloques_raw.append([])
            inicio_actual = entrada["segundos"]
        bloques_raw[-1].append(entrada)

    bloques: list[BloqueTematico] = []
    for i, grupo in enumerate(bloques_raw, 1):
        textos_limpios = [x["texto_limpio"] for x in grupo if x["texto_limpio"]]
        avisos = [
            f"[{h.tiempo}] {h.texto}"
            for h in hallazgos
            if h.tipo == "examen"
            and grupo[0]["segundos"] <= _segundos(h.tiempo) <= grupo[-1]["segundos"]
        ]
        preguntas = [
            f"[{h.tiempo}] {h.texto}"
            for h in hallazgos
            if h.tipo == "pregunta"
            and grupo[0]["segundos"] <= _segundos(h.tiempo) <= grupo[-1]["segundos"]
        ]
        cambios = [
            f"[{h.tiempo}] {h.texto}"
            for h in hallazgos
            if h.tipo == "tema"
            and grupo[0]["segundos"] <= _segundos(h.tiempo) <= grupo[-1]["segundos"]
        ]
        bloques.append(
            BloqueTematico(
                numero=i,
                inicio=grupo[0]["tiempo"],
                fin=grupo[-1]["tiempo"],
                titulo=_titulo_bloque(textos_limpios, i),
                texto="\n".join(textos_limpios),
                resumen=_resumen_extractivo(textos_limpios),
                palabras_clave=_palabras_clave(" ".join(textos_limpios)),
                avisos_examen=avisos,
                preguntas=preguntas,
                cambios_tema=cambios,
            )
        )

    ficha_path = carpeta / "ficha.json"
    try:
        ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        ficha = {}

    preguntas_detalladas = [asdict(h) for h in hallazgos if h.tipo == "pregunta"]
    avisos_detallados = [asdict(h) for h in hallazgos if h.tipo == "examen"]
    cambios_detallados = [asdict(h) for h in hallazgos if h.tipo == "tema"]
    indice_temporal = [
        {
            "tiempo": bloque.inicio,
            "titulo": bloque.titulo,
            "fin": bloque.fin,
            "origen": "bloque temático consolidado",
        }
        for bloque in bloques
    ]

    resultado = {
        "materia": ficha.get("materia", carpeta.parent.name),
        "titulo": ficha.get("titulo", carpeta.name),
        "numero": ficha.get("numero"),
        "archivo_fuente": transcripcion.name,
        "fuente_transcripcion": transcripcion.name,
        "procedencia": procedencia(carpeta),
        "bloques": [asdict(b) for b in bloques],
        "indice_temporal": indice_temporal,
        "avisos_examen": [f"[{h.tiempo}] {h.texto}" for h in hallazgos if h.tipo == "examen"],
        "avisos_examen_detallados": avisos_detallados,
        "preguntas_profesor": [f"[{h.tiempo}] {h.texto}" for h in hallazgos if h.tipo == "pregunta"],
        "preguntas_detalladas": preguntas_detalladas,
        "cambios_tema": cambios_detallados,
        "palabras_clave_globales": _palabras_clave(
            " ".join(x["texto_limpio"] for x in entradas), 20
        ),
    }

    _escribir_atomico(
        carpeta / "pipeline_clase.json",
        json.dumps(resultado, ensure_ascii=False, indent=2),
    )
    _escribir_atomico(
        carpeta / "apuntes_argos.md",
        _generar_markdown_argos(resultado),
    )
    _escribir_atomico(
        carpeta / "transcripcion_limpia.txt",
        "\n".join(
            f"[{x['tiempo']}] {x['rol']}: {x['texto_limpio']}" for x in entradas
        ),
    )

    analisis = {
        "materia": resultado["materia"],
        "titulo": resultado["titulo"],
        "archivo_fuente": resultado["archivo_fuente"],
        "preguntas": preguntas_detalladas,
        "avisos_examen": avisos_detallados,
        "cambios_tema": cambios_detallados,
        "indice_temporal": indice_temporal,
    }
    _escribir_atomico(
        carpeta / "analisis_clase.json",
        json.dumps(analisis, ensure_ascii=False, indent=2),
    )
    _escribir_atomico(
        carpeta / "analisis_clase.md",
        _generar_markdown_analisis(analisis),
    )
    return resultado


def _generar_markdown_argos(datos: dict) -> str:
    lineas = [
        f"# {datos['titulo']}",
        "",
        f"**Materia:** {datos['materia']}",
        f"**Fuente procesada:** {datos.get('archivo_fuente', '')}",
        "",
        "## Visión general",
        "",
        "**Conceptos dominantes:** "
        + ", ".join(datos.get("palabras_clave_globales", [])),
        "",
        "## Índice temporal",
        "",
    ]
    lineas.extend(
        f"- **[{x['tiempo']}–{x['fin']}] {x['titulo']}**"
        for x in datos.get("indice_temporal", [])
    )
    lineas.append("")

    for bloque in datos["bloques"]:
        lineas += [
            f"## {bloque['numero']}. {bloque['titulo']}",
            "",
            f"**Intervalo:** {bloque['inicio']}–{bloque['fin']}",
            "",
            "### Resumen",
            "",
            bloque["resumen"] or "Sin resumen automático.",
            "",
            "### Conceptos clave",
            "",
            " | ".join(bloque["palabras_clave"]) or "—",
            "",
        ]
        if bloque["avisos_examen"]:
            lineas += ["### Avisos de examen", ""]
            lineas += [f"- {x}" for x in bloque["avisos_examen"]]
            lineas.append("")
        if bloque["preguntas"]:
            lineas += ["### Preguntas formuladas", ""]
            lineas += [f"- {x}" for x in bloque["preguntas"]]
            lineas.append("")
        lineas += ["### Desarrollo limpio", "", bloque["texto"], ""]
    lineas.append(
        "> Documento generado automáticamente. Debe revisarse antes de estudiar."
    )
    return "\n".join(lineas)


def _generar_markdown_analisis(datos: dict) -> str:
    lineas = [
        "# Análisis de clase",
        "",
        f"**Materia:** {datos.get('materia', '')}  ",
        f"**Título:** {datos.get('titulo', '')}  ",
        f"**Fuente:** {datos.get('archivo_fuente', '')}",
        "",
        "## Índice temporal",
        "",
    ]
    indice = datos.get("indice_temporal", [])
    lineas += [
        f"- **{x['tiempo']}–{x['fin']}** — {x['titulo']}" for x in indice
    ] or ["No se detectaron bloques."]

    for titulo, clave in (
        ("Avisos de examen", "avisos_examen"),
        ("Preguntas detectadas", "preguntas"),
        ("Cambios de tema explícitos", "cambios_tema"),
    ):
        lineas += ["", f"## {titulo}", ""]
        items = datos.get(clave, [])
        lineas += [
            f"- **{x.get('tiempo', 'sin marca')}** — {x.get('texto', '')} "
            f"_(confianza {x.get('confianza', 'sin valorar')})_"
            for x in items
        ] or ["No se detectaron elementos."]
    return "\n".join(lineas)
