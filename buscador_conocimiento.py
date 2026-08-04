from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


@dataclass
class ResultadoBusqueda:
    tipo_fuente: str
    titulo: str
    ubicacion: str
    fragmento: str
    ruta: str
    puntuacion: int
    materia: str = ""
    pagina: int | None = None
    minuto: str | None = None

    def a_dict(self) -> dict:
        return asdict(self)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto.casefold()).strip()


def _terminos(consulta: str) -> list[str]:
    return [x for x in re.findall(r"[\wáéíóúüñ]+", _normalizar(consulta)) if len(x) > 1]


def _fragmento(texto: str, consulta: str, margen: int = 170) -> str:
    limpio = re.sub(r"\s+", " ", texto or "").strip()
    if not limpio:
        return ""
    normalizado = _normalizar(limpio)
    candidatos = [_normalizar(consulta), *_terminos(consulta)]
    posiciones = [normalizado.find(x) for x in candidatos if x and normalizado.find(x) >= 0]
    centro = min(posiciones) if posiciones else 0
    inicio = max(0, centro - margen)
    fin = min(len(limpio), centro + margen)
    prefijo = "…" if inicio else ""
    sufijo = "…" if fin < len(limpio) else ""
    return prefijo + limpio[inicio:fin].strip() + sufijo


def _puntuacion(texto: str, consulta: str) -> int:
    base = _normalizar(texto)
    frase = _normalizar(consulta)
    score = 0
    if frase and frase in base:
        score += 100 + base.count(frase) * 10
    for termino in _terminos(consulta):
        score += min(base.count(termino), 8) * 8
    return score


class BuscadorConocimiento:
    """Busca literalmente en clases y documentos médicos procesados.

    No usa IA ni inventa relaciones: devuelve coincidencias verificables con
    minuto, página y ruta de origen. Es la capa de trazabilidad previa al
    futuro buscador semántico y al chat ARGOS.
    """

    def __init__(self, raiz_general: str | None = None):
        documentos = Path.home() / "Documents"
        self.raiz_general = Path(raiz_general) if raiz_general else documentos / "Asistente de Clases"
        self.raiz_clases = self.raiz_general
        self.raiz_medica = self.raiz_general / "Biblioteca médica"
        self.indice_medico = self.raiz_medica / "indice_biblioteca.json"

    def buscar(
        self,
        consulta: str,
        alcance: str = "Todo",
        limite: int = 100,
    ) -> list[ResultadoBusqueda]:
        consulta = consulta.strip()
        if len(consulta) < 2:
            return []
        resultados: list[ResultadoBusqueda] = []
        if alcance in {"Todo", "Clases"}:
            resultados.extend(self._buscar_clases(consulta))
        if alcance in {"Todo", "Biblioteca médica", "Tratados", "Apuntes", "Exámenes", "Artículos", "Otros"}:
            categoria = None if alcance in {"Todo", "Biblioteca médica"} else alcance
            resultados.extend(self._buscar_documentos(consulta, categoria))
        resultados.sort(key=lambda x: (x.puntuacion, x.tipo_fuente == "Clase"), reverse=True)
        return resultados[: max(1, limite)]

    def _buscar_clases(self, consulta: str) -> Iterable[ResultadoBusqueda]:
        if not self.raiz_clases.exists():
            return []
        resultados = []
        for ficha_path in self.raiz_clases.rglob("ficha.json"):
            if "Biblioteca médica" in ficha_path.parts:
                continue
            carpeta = ficha_path.parent
            transcripcion = carpeta / "transcripcion.txt"
            if not transcripcion.exists():
                continue
            try:
                ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
                lineas = transcripcion.read_text(encoding="utf-8", errors="replace").splitlines()
            except (OSError, json.JSONDecodeError):
                continue
            materia = ficha.get("materia", carpeta.parent.name)
            titulo = ficha.get("titulo", carpeta.name)
            for linea in lineas:
                score = _puntuacion(linea, consulta)
                if not score:
                    continue
                marca = re.match(r"^\[([^\]]+)\]", linea)
                minuto = marca.group(1) if marca else None
                resultados.append(ResultadoBusqueda(
                    tipo_fuente="Clase",
                    titulo=titulo,
                    ubicacion=f"{materia} · {minuto or 'sin marca temporal'}",
                    fragmento=_fragmento(linea, consulta),
                    ruta=str(carpeta),
                    puntuacion=score,
                    materia=materia,
                    minuto=minuto,
                ))
        return resultados

    def _buscar_documentos(self, consulta: str, categoria: str | None) -> Iterable[ResultadoBusqueda]:
        if not self.indice_medico.exists():
            return []
        try:
            indice = json.loads(self.indice_medico.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        resultados = []
        for item in indice:
            if categoria and item.get("categoria") != categoria:
                continue
            if item.get("estado_indice_ia") != "texto_extraido":
                continue
            ruta_indice = item.get("ruta_indice_texto") or item.get("indice_texto")
            if not ruta_indice:
                continue
            path = Path(ruta_indice)
            if not path.exists():
                continue
            try:
                extraccion = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for pagina in extraccion.get("paginas", []):
                texto = pagina.get("texto", "")
                score = _puntuacion(texto, consulta)
                if not score:
                    continue
                numero = int(pagina.get("pagina", 1))
                resultados.append(ResultadoBusqueda(
                    tipo_fuente=item.get("categoria", "Documento"),
                    titulo=item.get("nombre", "Documento"),
                    ubicacion=f"Página {numero}",
                    fragmento=_fragmento(texto, consulta),
                    ruta=item.get("ruta", ""),
                    puntuacion=score,
                    pagina=numero,
                ))
        return resultados
