from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable


EXTENSIONES_ADMITIDAS = {
    ".pdf": "Tratado o artículo",
    ".docx": "Apuntes",
    ".txt": "Texto",
    ".md": "Apuntes Markdown",
}


class BibliotecaMedica:
    """Repositorio local de tratados, apuntes, exámenes y otros materiales.

    La biblioteca vive en Documentos/Asistente de Clases/Biblioteca médica.
    Los originales se conservan sin modificarse. El índice JSON sirve como base
    para el futuro buscador semántico y el chat con fuentes.
    """

    def __init__(self, raiz: str | None = None):
        documentos = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
        self.raiz = Path(raiz) if raiz else documentos / "Asistente de Clases" / "Biblioteca médica"
        self.carpetas = {
            "Tratados": self.raiz / "Tratados",
            "Apuntes": self.raiz / "Apuntes",
            "Exámenes": self.raiz / "Exámenes",
            "Artículos": self.raiz / "Artículos",
            "Otros": self.raiz / "Otros",
        }
        for carpeta in self.carpetas.values():
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
            return json.loads(self.indice_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def _guardar_indice(self, datos: Iterable[dict]) -> None:
        self.indice_path.write_text(
            json.dumps(list(datos), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def importar_archivo(self, origen: str, categoria: str = "Tratados") -> dict:
        origen_path = Path(origen)
        if not origen_path.is_file():
            raise FileNotFoundError(origen)
        if origen_path.suffix.lower() not in EXTENSIONES_ADMITIDAS:
            raise ValueError("Formato no admitido. Usa PDF, DOCX, TXT o Markdown.")
        if categoria not in self.carpetas:
            categoria = "Otros"

        hash_archivo = self._hash_archivo(origen_path)
        indice = self._leer_indice()
        existente = next((x for x in indice if x.get("sha256") == hash_archivo), None)
        if existente:
            return existente

        destino = self.carpetas[categoria] / origen_path.name
        contador = 2
        while destino.exists():
            destino = self.carpetas[categoria] / f"{origen_path.stem} ({contador}){origen_path.suffix}"
            contador += 1
        shutil.copy2(origen_path, destino)

        registro = {
            "id": hash_archivo[:16],
            "nombre": destino.name,
            "categoria": categoria,
            "extension": destino.suffix.lower(),
            "ruta": str(destino),
            "tamano_bytes": destino.stat().st_size,
            "fecha_importacion": datetime.now().isoformat(timespec="seconds"),
            "sha256": hash_archivo,
            "estado_indice_ia": "pendiente",
        }
        indice.append(registro)
        self._guardar_indice(indice)
        return registro

    def reindexar_archivos(self) -> list[dict]:
        """Reconstruye el inventario leyendo las carpetas locales.

        No crea aún embeddings ni resúmenes; deja cada documento marcado como
        pendiente para que el futuro motor IA lo procese por capítulos o bloques.
        """
        anterior = {x.get("sha256"): x for x in self._leer_indice()}
        nuevos = []
        for categoria, carpeta in self.carpetas.items():
            for ruta in sorted(carpeta.rglob("*")):
                if not ruta.is_file() or ruta.suffix.lower() not in EXTENSIONES_ADMITIDAS:
                    continue
                sha = self._hash_archivo(ruta)
                previo = anterior.get(sha, {})
                nuevos.append({
                    "id": sha[:16],
                    "nombre": ruta.name,
                    "categoria": categoria,
                    "extension": ruta.suffix.lower(),
                    "ruta": str(ruta),
                    "tamano_bytes": ruta.stat().st_size,
                    "fecha_importacion": previo.get("fecha_importacion", datetime.now().isoformat(timespec="seconds")),
                    "sha256": sha,
                    "estado_indice_ia": previo.get("estado_indice_ia", "pendiente"),
                })
        self._guardar_indice(nuevos)
        return nuevos

    def listar(self, filtro: str = "", categoria: str | None = None) -> list[dict]:
        filtro = filtro.casefold().strip()
        resultados = []
        for item in self._leer_indice():
            if categoria and item.get("categoria") != categoria:
                continue
            texto = f"{item.get('nombre', '')} {item.get('categoria', '')}".casefold()
            if not filtro or filtro in texto:
                resultados.append(item)
        return sorted(resultados, key=lambda x: x.get("fecha_importacion", ""), reverse=True)

    def abrir_raiz(self) -> None:
        os.startfile(self.raiz)

    @staticmethod
    def abrir_archivo(ruta: str) -> None:
        os.startfile(ruta)
