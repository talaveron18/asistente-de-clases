from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable

from extractor_documentos import extraer_documento, guardar_extraccion


EXTENSIONES_ADMITIDAS = {".pdf", ".docx", ".txt", ".md"}
CATEGORIAS = ("Tratados", "Apuntes", "Exámenes", "Artículos", "Otros")


class BibliotecaMedica:
    """Repositorio local de tratados, apuntes, exámenes y materiales médicos."""

    def __init__(self, raiz: str | None = None):
        documentos = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
        self.raiz = Path(raiz) if raiz else documentos / "Asistente de Clases" / "Biblioteca médica"
        self.carpetas = {nombre: self.raiz / nombre for nombre in CATEGORIAS}
        self.indice_texto = self.raiz / "_indice_texto"
        for carpeta in (*self.carpetas.values(), self.indice_texto):
            carpeta.mkdir(parents=True, exist_ok=True)
        self.indice_path = self.raiz / "indice_biblioteca.json"
        if not self.indice_path.exists():
            self._guardar_indice([])

    @staticmethod
    def _hash_archivo(ruta: Path) -> str:
        digest = hashlib.sha256()
        with ruta.open("rb") as f:
            for bloque in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(bloque)
        return digest.hexdigest()

    def _leer_indice(self) -> list[dict]:
        try:
            datos = json.loads(self.indice_path.read_text(encoding="utf-8"))
            return datos if isinstance(datos, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _guardar_indice(self, datos: Iterable[dict]) -> None:
        temporal = self.indice_path.with_suffix(".tmp")
        temporal.write_text(json.dumps(list(datos), indent=2, ensure_ascii=False), encoding="utf-8")
        temporal.replace(self.indice_path)

    def importar_archivo(self, origen: str, categoria: str = "Tratados") -> tuple[dict, bool]:
        origen_path = Path(origen)
        if not origen_path.is_file():
            raise FileNotFoundError(origen)
        if origen_path.suffix.lower() not in EXTENSIONES_ADMITIDAS:
            raise ValueError("Formato no admitido. Usa PDF, DOCX, TXT o Markdown.")
        categoria = categoria if categoria in self.carpetas else "Otros"

        sha = self._hash_archivo(origen_path)
        indice = self._leer_indice()
        existente = next((x for x in indice if x.get("sha256") == sha), None)
        if existente:
            return existente, False

        destino = self.carpetas[categoria] / origen_path.name
        contador = 2
        while destino.exists():
            destino = self.carpetas[categoria] / f"{origen_path.stem} ({contador}){origen_path.suffix}"
            contador += 1
        shutil.copy2(origen_path, destino)

        registro = {
            "id": sha[:16],
            "nombre": destino.name,
            "categoria": categoria,
            "extension": destino.suffix.lower(),
            "ruta": str(destino),
            "tamano_bytes": destino.stat().st_size,
            "fecha_importacion": datetime.now().isoformat(timespec="seconds"),
            "sha256": sha,
            "estado_indice_ia": "pendiente",
            "total_paginas": None,
            "caracteres_extraidos": 0,
            "requiere_ocr": False,
            "ruta_extraccion": None,
        }
        indice.append(registro)
        self._guardar_indice(indice)
        return registro, True

    def procesar_documento(self, item_id: str, callback=None) -> dict:
        indice = self._leer_indice()
        item = next((x for x in indice if x.get("id") == item_id), None)
        if not item:
            raise KeyError(f"Documento no encontrado: {item_id}")

        item["estado_indice_ia"] = "procesando"
        self._guardar_indice(indice)
        try:
            resultado = extraer_documento(item["ruta"], callback)
            destino = self.indice_texto / f"{item_id}.json"
            guardar_extraccion(resultado, str(destino))
            item["ruta_extraccion"] = str(destino)
            item["total_paginas"] = resultado.get("total_paginas") or len(resultado.get("paginas", []))
            item["caracteres_extraidos"] = resultado.get("caracteres", 0)
            item["requiere_ocr"] = bool(resultado.get("requiere_ocr"))
            item["estado_indice_ia"] = "requiere_ocr" if item["requiere_ocr"] else "texto_extraido"
            item["fecha_procesado"] = datetime.now().isoformat(timespec="seconds")
            return item
        except Exception as exc:
            item["estado_indice_ia"] = "error"
            item["ultimo_error"] = str(exc)
            raise
        finally:
            self._guardar_indice(indice)

    def procesar_pendientes(self, callback=None) -> list[dict]:
        resultados = []
        pendientes = [x for x in self._leer_indice() if x.get("estado_indice_ia") in {"pendiente", "error"}]
        total = max(1, len(pendientes))
        for i, item in enumerate(pendientes, 1):
            if callback:
                callback(f"Procesando {item['nombre']} ({i}/{total})", (i - 1) / total)
            resultados.append(self.procesar_documento(item["id"], callback=None))
        if callback:
            callback("Biblioteca procesada.", 1.0)
        return resultados

    def listar(self, filtro: str = "", categoria: str | None = None) -> list[dict]:
        filtro = filtro.casefold().strip()
        resultados = []
        for item in self._leer_indice():
            if categoria and categoria != "Todas" and item.get("categoria") != categoria:
                continue
            texto = f"{item.get('nombre', '')} {item.get('categoria', '')} {item.get('estado_indice_ia', '')}".casefold()
            if not filtro or filtro in texto:
                resultados.append(item)
        return sorted(resultados, key=lambda x: x.get("fecha_importacion", ""), reverse=True)

    def reindexar_archivos(self) -> list[dict]:
        anterior = {x.get("sha256"): x for x in self._leer_indice()}
        nuevos = []
        for categoria, carpeta in self.carpetas.items():
            for ruta in sorted(carpeta.rglob("*")):
                if not ruta.is_file() or ruta.suffix.lower() not in EXTENSIONES_ADMITIDAS:
                    continue
                sha = self._hash_archivo(ruta)
                previo = anterior.get(sha, {})
                registro = {
                    "id": sha[:16],
                    "nombre": ruta.name,
                    "categoria": categoria,
                    "extension": ruta.suffix.lower(),
                    "ruta": str(ruta),
                    "tamano_bytes": ruta.stat().st_size,
                    "fecha_importacion": previo.get("fecha_importacion", datetime.now().isoformat(timespec="seconds")),
                    "sha256": sha,
                    "estado_indice_ia": previo.get("estado_indice_ia", "pendiente"),
                    "total_paginas": previo.get("total_paginas"),
                    "caracteres_extraidos": previo.get("caracteres_extraidos", 0),
                    "requiere_ocr": previo.get("requiere_ocr", False),
                    "ruta_extraccion": previo.get("ruta_extraccion"),
                }
                nuevos.append(registro)
        self._guardar_indice(nuevos)
        return nuevos

    def abrir_raiz(self) -> None:
        os.startfile(self.raiz)

    @staticmethod
    def abrir_archivo(ruta: str) -> None:
        os.startfile(ruta)
