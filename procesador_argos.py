from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

STOPWORDS = {
    "para", "como", "pero", "porque", "esto", "esta", "este", "estos", "estas",
    "desde", "hasta", "sobre", "entre", "cuando", "donde", "tambien", "entonces",
    "vamos", "ahora", "bueno", "vale", "pues", "digamos", "realmente", "basicamente",
    "tiene", "tienen", "puede", "pueden", "ser", "son", "una", "uno", "unos", "unas",
    "del", "las", "los", "que", "con", "por", "sin", "más", "muy", "hay", "al",
}

TRANSICIONES = (
    "ahora vamos a", "pasamos a", "el siguiente tema", "continuamos con",
    "por otro lado", "vamos a hablar de", "a continuación", "en cuanto a",
)

MARCAS_EXAMEN = (
    "esto entra", "entra en el examen", "muy importante", "puede caer", "suele caer",
    "lo preguntan", "de cara al examen", "ojo con esto", "no os olvidéis",
    "no se olviden", "pregunta de examen", "esto es clave",
)

MULETILLAS = (
    r"\b(?:eh+|em+|mmm+)\b", r"\b(?:bueno|vale|digamos|básicamente|realmente)\b",
    r"\b(?:o sea)\b", r"\b(?:¿no\??)\b",
)

@dataclass
class BloqueTematico:
    numero: int
    inicio: str
    fin: str
    titulo: str
    texto: str
    resumen: str
    conceptos: list[str]
    avisos_examen: list[str]
    preguntas: list[str]


def _parse_linea(linea: str) -> tuple[str, str]:
    m = re.match(r"^\[([^\]]+)\]\s*(?:[^:]+:\s*)?(.*)$", linea.strip())
    return (m.group(1), m.group(2).strip()) if m else ("00:00", linea.strip())


def _segundos(marca: str) -> int:
    partes = [int(x) for x in marca.split(":")]
    if len(partes) == 2:
        return partes[0] * 60 + partes[1]
    if len(partes) == 3:
        return partes[0] * 3600 + partes[1] * 60 + partes[2]
    return 0


def limpiar_texto(texto: str) -> str:
    salida = texto
    for patron in MULETILLAS:
        salida = re.sub(patron, " ", salida, flags=re.IGNORECASE)
    salida = re.sub(r"\b(\w+)(?:\s+\1){1,}\b", r"\1", salida, flags=re.IGNORECASE)
    salida = re.sub(r"\s+([,.;:!?])", r"\1", salida)
    salida = re.sub(r"\s+", " ", salida).strip(" ,")
    if salida:
        salida = salida[0].upper() + salida[1:]
    return salida


def _conceptos(texto: str, limite: int = 10) -> list[str]:
    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][\wáéíóúüñ-]{3,}", texto.casefold())
    contador = Counter(p for p in palabras if p not in STOPWORDS)
    return [p for p, _ in contador.most_common(limite)]


def _titulo(textos: list[str], numero: int) -> str:
    unido = " ".join(textos[:4])
    bajo = unido.casefold()
    for marca in TRANSICIONES:
        pos = bajo.find(marca)
        if pos >= 0:
            candidato = unido[pos + len(marca):].strip(" :.-")
            candidato = re.split(r"[.!?]", candidato)[0].strip()
            if 3 <= len(candidato) <= 90:
                return candidato[0].upper() + candidato[1:]
    conceptos = _conceptos(" ".join(textos), 4)
    return " · ".join(x.capitalize() for x in conceptos) or f"Bloque {numero}"


def _resumen_extractivo(textos: list[str], max_frases: int = 5) -> str:
    frases = []
    for texto in textos:
        frases.extend(x.strip() for x in re.split(r"(?<=[.!?])\s+", texto) if len(x.strip()) > 35)
    if not frases:
        return " ".join(textos[:3])[:900]
    conceptos = set(_conceptos(" ".join(textos), 12))
    puntuadas = []
    for i, frase in enumerate(frases):
        score = sum(1 for c in conceptos if c in frase.casefold()) + min(len(frase) / 180, 1)
        puntuadas.append((score, -i, frase))
    elegidas = sorted(sorted(puntuadas, reverse=True)[:max_frases], key=lambda x: -x[1])
    return " ".join(x[2] for x in elegidas)


class ProcesadorArgos:
    def __init__(self, duracion_bloque_min: int = 12):
        self.duracion_bloque = max(5, duracion_bloque_min) * 60

    def procesar_carpeta(self, ruta_clase: str) -> dict:
        carpeta = Path(ruta_clase)
        transcripcion = carpeta / "transcripcion.txt"
        ficha_path = carpeta / "ficha.json"
        if not transcripcion.exists():
            raise FileNotFoundError("No existe transcripcion.txt en la clase.")
        ficha = json.loads(ficha_path.read_text(encoding="utf-8")) if ficha_path.exists() else {}
        lineas = [x for x in transcripcion.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
        registros = []
        for linea in lineas:
            tiempo, texto = _parse_linea(linea)
            registros.append({"tiempo": tiempo, "segundos": _segundos(tiempo), "texto": limpiar_texto(texto)})
        bloques = self._segmentar(registros)
        resultado = {
            "materia": ficha.get("materia", carpeta.parent.name),
            "titulo": ficha.get("titulo", carpeta.name),
            "numero": ficha.get("numero"),
            "bloques": [asdict(x) for x in bloques],
            "conceptos_globales": _conceptos(" ".join(x["texto"] for x in registros), 20),
            "avisos_examen": [f"[{x['tiempo']}] {x['texto']}" for x in registros if any(m in x['texto'].casefold() for m in MARCAS_EXAMEN)],
            "preguntas": [f"[{x['tiempo']}] {x['texto']}" for x in registros if "?" in x["texto"]],
        }
        (carpeta / "argos_clase.json").write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
        (carpeta / "transcripcion_limpia.txt").write_text(
            "\n".join(f"[{x['tiempo']}] {x['texto']}" for x in registros), encoding="utf-8"
        )
        (carpeta / "apuntes_argos.md").write_text(self._markdown(resultado), encoding="utf-8")
        return resultado

    def _segmentar(self, registros: list[dict]) -> list[BloqueTematico]:
        if not registros:
            return []
        grupos: list[list[dict]] = [[]]
        inicio = registros[0]["segundos"]
        for reg in registros:
            explicito = any(m in reg["texto"].casefold() for m in TRANSICIONES)
            supera = reg["segundos"] - inicio >= self.duracion_bloque
            if grupos[-1] and (explicito or supera):
                grupos.append([])
                inicio = reg["segundos"]
            grupos[-1].append(reg)
        bloques = []
        for i, grupo in enumerate(grupos, 1):
            textos = [x["texto"] for x in grupo if x["texto"]]
            avisos = [f"[{x['tiempo']}] {x['texto']}" for x in grupo if any(m in x['texto'].casefold() for m in MARCAS_EXAMEN)]
            preguntas = [f"[{x['tiempo']}] {x['texto']}" for x in grupo if "?" in x["texto"]]
            bloques.append(BloqueTematico(
                numero=i,
                inicio=grupo[0]["tiempo"],
                fin=grupo[-1]["tiempo"],
                titulo=_titulo(textos, i),
                texto="\n".join(f"[{x['tiempo']}] {x['texto']}" for x in grupo),
                resumen=_resumen_extractivo(textos),
                conceptos=_conceptos(" ".join(textos), 10),
                avisos_examen=avisos,
                preguntas=preguntas,
            ))
        return bloques

    @staticmethod
    def _markdown(r: dict) -> str:
        out = [f"# {r['titulo']}", "", f"**Materia:** {r['materia']}", "", "## Vista general", ""]
        out.append("**Conceptos principales:** " + ", ".join(r.get("conceptos_globales", [])))
        out.extend(["", "## Índice temporal", ""])
        for b in r["bloques"]:
            out.append(f"- **[{b['inicio']}–{b['fin']}] {b['titulo']}**")
        out.extend(["", "## Apuntes por bloques", ""])
        for b in r["bloques"]:
            out.extend([
                f"### {b['numero']}. {b['titulo']}", "",
                f"**Tiempo:** {b['inicio']}–{b['fin']}", "",
                b['resumen'], "",
                "**Conceptos:** " + ", ".join(b['conceptos']), "",
            ])
            if b["avisos_examen"]:
                out.extend(["**Avisos de examen:**", *[f"- {x}" for x in b["avisos_examen"]], ""])
            if b["preguntas"]:
                out.extend(["**Preguntas formuladas:**", *[f"- {x}" for x in b["preguntas"]], ""])
        out.extend(["## Avisos de examen consolidados", ""])
        out.extend([f"- {x}" for x in r.get("avisos_examen", [])] or ["No se detectaron avisos explícitos."])
        out.extend(["", "## Preguntas de la clase", ""])
        out.extend([f"- {x}" for x in r.get("preguntas", [])] or ["No se detectaron preguntas explícitas."])
        out.extend(["", "> Documento generado automáticamente a partir de la transcripción. Debe revisarse antes de estudiar."])
        return "\n".join(out)
