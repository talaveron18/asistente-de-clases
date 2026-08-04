from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from transcripciones import fuente_vigente, procedencia


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
        self._crear_esquema()

    def _conectar(self):
        conexion = sqlite3.connect(self.db_path, timeout=30)
        conexion.row_factory = sqlite3.Row
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
        terminos = re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", consulta)
        terminos = [t for t in terminos if len(t) > 1]
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
        registros = [*self._leer_clases(), *self._leer_documentos()]
        total = max(1, len(registros))
        with self._conectar() as con:
            con.execute("DELETE FROM conocimiento")
            for i, registro in enumerate(registros, 1):
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
                if callback and (i == total or i % 25 == 0):
                    callback(
                        f"Indexando {i} de {total} bloques...", i / total
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

    def _leer_clases(self):
        registros = []
        for ficha_path in self.raiz.rglob("ficha.json"):
            if "Biblioteca médica" in ficha_path.parts:
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
            es_revisada = procedencia(carpeta) == "clase/revisada"
            etiqueta_fuente = "revisión médica" if es_revisada else "original"
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
                            f"{materia} · {minuto or 'sin minuto'} · "
                            f"{etiqueta_fuente}"
                        ),
                        "contenido": linea,
                        "ruta": str(carpeta),
                        "minuto": minuto,
                    }
                )
        return registros

    def _leer_documentos(self):
        indice_path = (
            self.raiz / "Biblioteca médica" / "indice_biblioteca.json"
        )
        if not indice_path.exists():
            return []
        try:
            indice = json.loads(indice_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

        registros = []
        for item in indice:
            if item.get("estado_indice_ia") != "texto_extraido":
                continue
            ruta_indice = (
                item.get("ruta_extraccion")
                or item.get("ruta_indice_texto")
                or item.get("indice_texto")
            )
            if not ruta_indice or not Path(ruta_indice).exists():
                continue
            try:
                extraccion = json.loads(
                    Path(ruta_indice).read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                continue
            for pagina in extraccion.get("paginas", []):
                texto = (pagina.get("texto") or "").strip()
                if not texto:
                    continue
                numero = int(pagina.get("pagina", 1))
                registros.append(
                    {
                        "id": f"doc:{item.get('id')}:{numero}",
                        "tipo_fuente": "Documento",
                        "categoria": item.get("categoria", "Documento"),
                        "titulo": item.get("nombre", "Documento"),
                        "materia": "",
                        "ubicacion": f"Página {numero}",
                        "contenido": texto,
                        "ruta": item.get("ruta", ""),
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
        filtros = []
        params: list[object] = [self._consulta_fts(consulta)]
        if alcance == "Clases":
            filtros.append("tipo_fuente = 'Clase'")
        elif alcance == "Biblioteca médica":
            filtros.append("tipo_fuente = 'Documento'")
        elif alcance not in {"Todo", ""}:
            filtros.append("categoria = ?")
            params.append(alcance)
        where_extra = (
            " AND " + " AND ".join(filtros) if filtros else ""
        )
        sql = f"""
            SELECT tipo_fuente, categoria, titulo, materia, ubicacion,
                   snippet(conocimiento, 6, '⟦', '⟧', ' … ', 38) AS fragmento,
                   ruta, pagina, minuto, bm25(conocimiento) AS rango
            FROM conocimiento
            WHERE conocimiento MATCH ? {where_extra}
            ORDER BY rango
            LIMIT ?
        """
        params.append(max(1, limite))
        try:
            with self._conectar() as con:
                filas = con.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []
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
