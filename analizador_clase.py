from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


PATRONES_EXAMEN = [
    r"\besto entra\b", r"\bentra en (?:el )?examen\b", r"\besto es importante\b",
    r"\bmuy importante\b", r"\besto lo preguntan\b", r"\bpuede caer\b",
    r"\bde cara al examen\b", r"\btened cuidado\b", r"\bojo con\b",
    r"\bno os olvidéis\b", r"\brecordad que\b",
]

PATRONES_CAMBIO_TEMA = [
    r"\bahora vamos a (?:ver|hablar de|pasar a)\b",
    r"\bpasamos a\b", r"\bel siguiente tema\b", r"\bpor otro lado\b",
    r"\bentramos en\b", r"\bcontinuamos con\b", r"\bvamos con\b",
]


@dataclass
class HallazgoClase:
    tipo: str
    tiempo: str
    texto: str
    confianza: str = "alta"


class AnalizadorClase:
    """Analiza una transcripción sin IA externa y conserva trazabilidad temporal."""

    def analizar_carpeta(self, carpeta: str | Path) -> dict:
        carpeta = Path(carpeta)
        transcripcion = carpeta / "transcripcion.txt"
        ficha = carpeta / "ficha.json"
        if not transcripcion.exists():
            raise FileNotFoundError(f"No existe {transcripcion}")

        metadatos = {}
        if ficha.exists():
            try:
                metadatos = json.loads(ficha.read_text(encoding="utf-8"))
            except Exception:
                metadatos = {}

        lineas = transcripcion.read_text(encoding="utf-8", errors="replace").splitlines()
        hallazgos = self.analizar_lineas(lineas)
        resultado = {
            "materia": metadatos.get("materia", carpeta.parent.name),
            "titulo": metadatos.get("titulo", carpeta.name),
            "preguntas": [asdict(x) for x in hallazgos if x.tipo == "pregunta"],
            "avisos_examen": [asdict(x) for x in hallazgos if x.tipo == "examen"],
            "cambios_tema": [asdict(x) for x in hallazgos if x.tipo == "tema"],
            "indice_temporal": self._crear_indice_temporal(hallazgos),
        }
        (carpeta / "analisis_clase.json").write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (carpeta / "analisis_clase.md").write_text(
            self._a_markdown(resultado), encoding="utf-8"
        )
        return resultado

    def analizar_lineas(self, lineas: Iterable[str]) -> list[HallazgoClase]:
        hallazgos: list[HallazgoClase] = []
        vistos = set()
        for linea in lineas:
            tiempo, texto = self._separar_linea(linea)
            if not texto:
                continue
            normal = texto.casefold()
            candidatos: list[HallazgoClase] = []

            if "?" in texto or re.search(r"\b(?:qué|cuál|cuáles|cómo|por qué|quién|dónde|cuándo)\b", normal):
                candidatos.append(HallazgoClase("pregunta", tiempo, texto, "media" if "?" not in texto else "alta"))

            if any(re.search(p, normal) for p in PATRONES_EXAMEN):
                candidatos.append(HallazgoClase("examen", tiempo, texto, "alta"))

            if any(re.search(p, normal) for p in PATRONES_CAMBIO_TEMA):
                candidatos.append(HallazgoClase("tema", tiempo, texto, "media"))

            for item in candidatos:
                clave = (item.tipo, item.tiempo, item.texto)
                if clave not in vistos:
                    hallazgos.append(item)
                    vistos.add(clave)
        return hallazgos

    @staticmethod
    def _separar_linea(linea: str) -> tuple[str, str]:
        m = re.match(r"^\[([^\]]+)\]\s*(?:[^:]+:\s*)?(.*)$", linea.strip())
        if m:
            return m.group(1), m.group(2).strip()
        return "sin marca", linea.strip()

    @staticmethod
    def _crear_indice_temporal(hallazgos: list[HallazgoClase]) -> list[dict]:
        temas = [x for x in hallazgos if x.tipo == "tema"]
        return [
            {"tiempo": x.tiempo, "descripcion": x.texto, "origen": "cambio de tema detectado"}
            for x in temas
        ]

    @staticmethod
    def _a_markdown(resultado: dict) -> str:
        def bloque(titulo: str, items: list[dict]) -> str:
            if not items:
                return f"## {titulo}\n\nNo se detectaron elementos.\n"
            lineas = [f"## {titulo}", ""]
            for x in items:
                lineas.append(f"- **{x.get('tiempo', 'sin marca')}** — {x.get('texto') or x.get('descripcion', '')}")
            return "\n".join(lineas) + "\n"

        return (
            f"# Análisis de clase\n\n"
            f"**Materia:** {resultado.get('materia', '')}  \n"
            f"**Título:** {resultado.get('titulo', '')}\n\n"
            + bloque("Índice temporal", resultado.get("indice_temporal", []))
            + "\n"
            + bloque("Avisos de examen", resultado.get("avisos_examen", []))
            + "\n"
            + bloque("Preguntas detectadas", resultado.get("preguntas", []))
        )
