from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

STOPWORDS = {
    "para", "como", "pero", "porque", "desde", "hasta", "sobre", "entre", "cuando", "donde",
    "este", "esta", "estos", "estas", "esto", "eso", "esa", "ese", "unos", "unas", "tambien",
    "entonces", "vamos", "ahora", "bueno", "bien", "muy", "mas", "menos", "cada", "todo",
    "toda", "todos", "todas", "del", "las", "los", "una", "uno", "que", "con", "sin", "por",
    "se", "es", "son", "ser", "ha", "hay", "al", "lo", "la", "el", "en", "y", "o", "a",
    "de", "un", "ya", "si", "no",
}
MULETILLAS = [r"\b(?:eh+|em+|mmm+|este+|bueno|vale|o sea|digamos|básicamente|literalmente)\b[,. ]*"]
MARCADORES_TEMA = [
    "ahora vamos a", "pasamos a", "vamos a ver", "continuamos con", "el siguiente tema",
    "por otro lado", "a continuación", "para terminar", "en cuanto a", "respecto a",
]
MARCADORES_EXAMEN = [
    "esto entra", "entra en el examen", "de cara al examen", "puede caer", "suele caer",
    "lo preguntan", "esto es importante", "muy importante", "ojo con", "atención a",
    "no os olvidéis", "no se olviden",
]


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


def _parse_linea(linea: str):
    m = re.match(r"^\[([^\]]+)\]\s*([^:]+):\s*(.*)$", linea.strip())
    if not m:
        return None
    return {"tiempo": m.group(1), "rol": m.group(2).strip(), "texto": m.group(3).strip()}


def _segundos(marca: str) -> int:
    partes = [int(x) for x in marca.split(":")]
    if len(partes) == 2:
        return partes[0] * 60 + partes[1]
    if len(partes) == 3:
        return partes[0] * 3600 + partes[1] * 60 + partes[2]
    return 0


def limpiar_texto(texto: str) -> str:
    resultado = texto
    for patron in MULETILLAS:
        resultado = re.sub(patron, " ", resultado, flags=re.I)
    resultado = re.sub(r"\s+", " ", resultado).strip(" ,.-")
    if resultado:
        resultado = resultado[0].upper() + resultado[1:]
    return resultado


def _palabras_clave(texto: str, limite=8) -> list[str]:
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{4,}", texto.casefold())
    conteo = Counter(t for t in tokens if t not in STOPWORDS)
    return [p for p, _ in conteo.most_common(limite)]


def _titulo_bloque(textos: list[str], numero: int) -> str:
    unido = " ".join(textos[:5])
    for marcador in MARCADORES_TEMA:
        pos = unido.casefold().find(marcador)
        if pos >= 0:
            candidato = unido[pos + len(marcador):].strip(" :,.—-")
            candidato = re.split(r"[.!?]", candidato)[0].strip()
            if 4 <= len(candidato) <= 90:
                return candidato[0].upper() + candidato[1:]
    claves = _palabras_clave(" ".join(textos), 4)
    return " · ".join(p.title() for p in claves) if claves else f"Bloque {numero}"


def _resumen_extractivo(textos: list[str], max_frases=5) -> str:
    frases = []
    for texto in textos:
        frases.extend([f.strip() for f in re.split(r"(?<=[.!?])\s+", texto) if len(f.strip()) > 35])
    if not frases:
        return " ".join(textos[:3])[:900]
    claves = set(_palabras_clave(" ".join(frases), 12))
    puntuadas = []
    for i, frase in enumerate(frases):
        score = sum(1 for p in claves if p in frase.casefold()) + (1 if i < 3 else 0)
        puntuadas.append((score, -i, frase))
    elegidas = sorted(puntuadas, reverse=True)[:max_frases]
    elegidas = sorted(elegidas, key=lambda x: -x[1])
    return " ".join(x[2] for x in elegidas)


def analizar_clase_completa(carpeta: str | Path, minutos_bloque: int = 12) -> dict:
    carpeta = Path(carpeta)
    revisada = carpeta / "transcripcion_medica_revisada.txt"
    transcripcion = revisada if revisada.exists() else carpeta / "transcripcion.txt"
    if not transcripcion.exists():
        raise FileNotFoundError(transcripcion)

    entradas = [_parse_linea(x) for x in transcripcion.read_text(encoding="utf-8", errors="replace").splitlines()]
    entradas = [x for x in entradas if x and x["texto"]]
    if not entradas:
        raise ValueError("La transcripción no contiene segmentos analizables.")

    bloques_raw: list[list[dict]] = [[]]
    inicio_actual = _segundos(entradas[0]["tiempo"])
    for entrada in entradas:
        seg = _segundos(entrada["tiempo"])
        cambio_explicito = any(m in entrada["texto"].casefold() for m in MARCADORES_TEMA)
        if bloques_raw[-1] and (seg - inicio_actual >= minutos_bloque * 60 or cambio_explicito):
            bloques_raw.append([])
            inicio_actual = seg
        bloques_raw[-1].append(entrada)

    bloques = []
    avisos_globales, preguntas_globales = [], []
    for i, grupo in enumerate(bloques_raw, 1):
        textos_limpios = [limpiar_texto(x["texto"]) for x in grupo if limpiar_texto(x["texto"])]
        avisos = [f"[{x['tiempo']}] {x['texto']}" for x in grupo if any(m in x["texto"].casefold() for m in MARCADORES_EXAMEN)]
        preguntas = [f"[{x['tiempo']}] {x['texto']}" for x in grupo if "?" in x["texto"] or x["texto"].strip().startswith("¿")]
        avisos_globales.extend(avisos)
        preguntas_globales.extend(preguntas)
        bloques.append(BloqueTematico(
            numero=i,
            inicio=grupo[0]["tiempo"],
            fin=grupo[-1]["tiempo"],
            titulo=_titulo_bloque(textos_limpios, i),
            texto="\n".join(textos_limpios),
            resumen=_resumen_extractivo(textos_limpios),
            palabras_clave=_palabras_clave(" ".join(textos_limpios)),
            avisos_examen=avisos,
            preguntas=preguntas,
        ))

    ficha_path = carpeta / "ficha.json"
    ficha = json.loads(ficha_path.read_text(encoding="utf-8")) if ficha_path.exists() else {}
    resultado = {
        "materia": ficha.get("materia", carpeta.parent.name),
        "titulo": ficha.get("titulo", carpeta.name),
        "fuente_transcripcion": transcripcion.name,
        "bloques": [asdict(b) for b in bloques],
        "avisos_examen": avisos_globales,
        "preguntas_profesor": preguntas_globales,
        "palabras_clave_globales": _palabras_clave(" ".join(x["texto"] for x in entradas), 20),
    }
    (carpeta / "pipeline_clase.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    (carpeta / "apuntes_argos.md").write_text(_generar_markdown_argos(resultado), encoding="utf-8")
    (carpeta / "transcripcion_limpia.txt").write_text(
        "\n".join(f"[{x['tiempo']}] {x['rol']}: {limpiar_texto(x['texto'])}" for x in entradas),
        encoding="utf-8",
    )
    return resultado


def _generar_markdown_argos(datos: dict) -> str:
    lineas = [
        f"# {datos['titulo']}", "", f"**Materia:** {datos['materia']}", "",
        "## Visión general", "",
        "**Conceptos dominantes:** " + ", ".join(datos.get("palabras_clave_globales", [])), "",
    ]
    for bloque in datos["bloques"]:
        lineas += [
            f"## {bloque['numero']}. {bloque['titulo']}", "",
            f"**Intervalo:** {bloque['inicio']}–{bloque['fin']}", "",
            "### Resumen", "", bloque["resumen"] or "Sin resumen automático.", "",
            "### Conceptos clave", "", " | ".join(bloque["palabras_clave"]) or "—", "",
        ]
        if bloque["avisos_examen"]:
            lineas += ["### Avisos de examen", ""] + [f"- {x}" for x in bloque["avisos_examen"]] + [""]
        if bloque["preguntas"]:
            lineas += ["### Preguntas formuladas", ""] + [f"- {x}" for x in bloque["preguntas"]] + [""]
        lineas += ["### Desarrollo limpio", "", bloque["texto"], ""]
    return "\n".join(lineas)
