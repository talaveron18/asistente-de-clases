from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from extracciones import ruta_documento_de, ruta_extraccion_de
from transcripciones import fuente_vigente, procedencia


_LOCKS_GUARD = threading.Lock()
_LOCKS_RECONSTRUCCION: dict[str, threading.RLock] = {}


def _lock_reconstruccion(ruta: Path) -> threading.RLock:
    """Comparte el bloqueo entre todas las instancias del mismo proceso."""
    clave = str(ruta.resolve())
    with _LOCKS_GUARD:
        return _LOCKS_RECONSTRUCCION.setdefault(clave, threading.RLock())


@dataclass
class CoincidenciaFTS:
    tipo_fuente: str
    categoria: str
    titulo: str
    materia: str
    ubicacion: str
    contenido: str
    ruta: str
    pagina: int | None = None
    minuto: str | None = None
    relevancia: float = 0.0


class IndiceConocimientoSQLite:
    """Único motor de búsqueda local para clases y biblioteca médica."""

    def __init__(self, raiz_general: str | None = None):
        documentos = Path.home() / "Documents"
        self.raiz = (
            Path(raiz_general)
            if raiz_general
            else documentos / "Asistente de Clases"
        )
        self.raiz.mkdir(parents=True, exist_ok=True)
        self.db_path = self.raiz / "argos_conocimiento.sqlite3"
        self._lock = _lock_reconstruccion(self.db_path)
        self._crear_esquema()

    def _conectar(self):
        conexion = sqlite3.connect(self.db_path, timeout=300)
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA busy_timeout=300000")
        return conexion

    def _crear_esquema(self):
        with self._conectar() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS conocimiento USING fts5(
                    id UNINDEXED,
                    tipo_fuente,
                    categoria,
                    titulo,
                    materia,
                    ubicacion,
                    contenido,
                    ruta UNINDEXED,
                    pagina UNINDEXED,
                    minuto UNINDEXED,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS metadatos(
                    clave TEXT PRIMARY KEY,
                    valor TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _consulta_fts(consulta: str) -> str:
        terminos = [
            t
            for t in re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", consulta)
            if len(t) > 1
        ]
        if not terminos:
            return '"' + consulta.replace('"', '""') + '"'

        partes: list[str] = []
        if len(terminos) > 1:
            frase = " ".join(terminos).replace('"', '""')
            partes.append(f'"{frase}"')
        partes.extend(
            f'"{termino.replace(chr(34), chr(34) * 2)}"'
            for termino in terminos
        )
        return " OR ".join(dict.fromkeys(partes))

    def reconstruir(self, callback=None) -> dict:
        """Reconstruye el índice en una sección crítica local e interproceso.

        ``BEGIN IMMEDIATE`` se toma antes de leer las fuentes. De esta forma
        otra ventana no puede iniciar una segunda reconstrucción mientras la
        primera aún está recorriendo clases y documentos.
        """
        with self._lock:
            with self._conectar() as con:
                con.execute("BEGIN IMMEDIATE")
                registros = [*self._leer_clases(), *self._leer_documentos()]
                total = max(1, len(registros))
                con.execute("DELETE FROM conocimiento")
                for indice, registro in enumerate(registros, 1):
                    con.execute(
                        "INSERT INTO conocimiento VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            registro["id"],
                            registro["tipo_fuente"],
                            registro["categoria"],
                            registro["titulo"],
                            registro["materia"],
                            registro["ubicacion"],
                            registro["contenido"],
                            registro["ruta"],
                            registro.get("pagina"),
                            registro.get("minuto"),
                        ),
                    )
                    if callback and (indice == total or indice % 25 == 0):
                        callback(
                            f"Indexando {indice} de {total} bloques...",
                            indice / total,
                        )
                con.execute(
                    "INSERT OR REPLACE INTO metadatos(clave, valor) "
                    "VALUES ('total_bloques', ?)",
                    (str(len(registros)),),
                )
            return {
                "bloques": len(registros),
                "clases": sum(
                    r["tipo_fuente"] == "Clase" for r in registros
                ),
                "documentos": sum(
                    r["tipo_fuente"] != "Clase" for r in registros
                ),
            }

    def _leer_clases(self) -> list[dict]:
        registros: list[dict] = []
        for ficha_path in self.raiz.rglob("ficha.json"):
            if any(
                carpeta in ficha_path.parts
                for carpeta in ("Biblioteca médica", "Papelera ARGOS")
            ):
                continue
            carpeta = ficha_path.parent
            try:
                transcripcion = fuente_vigente(carpeta)
                ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
                lineas = transcripcion.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except (OSError, json.JSONDecodeError, FileNotFoundError):
                continue

            materia = ficha.get("materia", carpeta.parent.name)
            titulo = ficha.get("titulo", carpeta.name)
            etiqueta = (
                "revisión médica"
                if procedencia(carpeta) == "clase/revisada"
                else "original"
            )
            for numero_linea, linea in enumerate(lineas):
                if not linea.strip():
                    continue
                marca = re.match(r"^\[([^\]]+)\]", linea)
                minuto = marca.group(1) if marca else None
                registros.append(
                    {
                        "id": f"clase:{ficha_path}:{numero_linea}",
                        "tipo_fuente": "Clase",
                        "categoria": "Clases",
                        "titulo": titulo,
                        "materia": materia,
                        "ubicacion": (
                            f"{materia} · {minuto or 'sin minuto'} · {etiqueta}"
                        ),
                        "contenido": linea,
                        "ruta": str(carpeta),
                        "minuto": minuto,
                    }
                )
        return registros

    def _leer_documentos(self) -> list[dict]:
        raiz_biblioteca = self.raiz / "Biblioteca médica"
        indice_path = raiz_biblioteca / "indice_biblioteca.json"
        if not indice_path.exists():
            return []
        try:
            items = json.loads(indice_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        registros: list[dict] = []
        for item in items:
            if item.get("estado_indice_ia") != "texto_extraido":
                continue
            ruta_indice = ruta_extraccion_de(item, raiz_biblioteca)
            if ruta_indice is None:
                continue
            try:
                extraccion = json.loads(ruta_indice.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for pagina in extraccion.get("paginas", []):
                texto = (pagina.get("texto") or "").strip()
                if not texto:
                    continue
                numero = int(pagina.get("pagina", 1))
                ruta_original = ruta_documento_de(item, raiz_biblioteca)
                registros.append(
                    {
                        "id": f"doc:{item.get('id')}:{numero}",
                        "tipo_fuente": "Documento",
                        "categoria": item.get("categoria", "Documento"),
                        "titulo": item.get("nombre", "Documento"),
                        "materia": "",
                        "ubicacion": f"Página {numero}",
                        "contenido": texto,
                        "ruta": str(ruta_original or item.get("ruta", "")),
                        "pagina": numero,
                    }
                )
        return registros

    def buscar(
        self,
        consulta: str,
        alcance: str = "Todo",
        limite: int = 40,
    ) -> list[CoincidenciaFTS]:
        consulta = consulta.strip()
        if len(consulta) < 2:
            return []

        filtros: list[str] = []
        parametros: list[object] = [self._consulta_fts(consulta)]
        if alcance == "Clases":
            filtros.append("tipo_fuente = 'Clase'")
        elif alcance == "Biblioteca médica":
            filtros.append("tipo_fuente = 'Documento'")
        elif alcance not in {"Todo", ""}:
            filtros.append("categoria = ?")
            parametros.append(alcance)
        extra = " AND " + " AND ".join(filtros) if filtros else ""
        sql = f"""
            SELECT tipo_fuente, categoria, titulo, materia, ubicacion,
                   snippet(conocimiento, 6, '', '', ' … ', 38) AS fragmento,
                   ruta, pagina, minuto, bm25(conocimiento) AS rango
            FROM conocimiento
            WHERE conocimiento MATCH ? {extra}
            ORDER BY rango
            LIMIT ?
        """
        parametros.append(max(1, limite))
        with self._conectar() as con:
            filas = con.execute(sql, parametros).fetchall()
        return [
            CoincidenciaFTS(
                tipo_fuente=fila["tipo_fuente"],
                categoria=fila["categoria"],
                titulo=fila["titulo"],
                materia=fila["materia"],
                ubicacion=fila["ubicacion"],
                contenido=fila["fragmento"],
                ruta=fila["ruta"],
                pagina=fila["pagina"],
                minuto=fila["minuto"],
                relevancia=float(fila["rango"] or 0),
            )
            for fila in filas
        ]

    def estadisticas(self) -> dict:
        with self._conectar() as con:
            total = con.execute(
                "SELECT count(*) FROM conocimiento"
            ).fetchone()[0]
            clases = con.execute(
                "SELECT count(*) FROM conocimiento WHERE tipo_fuente='Clase'"
            ).fetchone()[0]
        return {
            "bloques": total,
            "clases": clases,
            "documentos": total - clases,
        }
