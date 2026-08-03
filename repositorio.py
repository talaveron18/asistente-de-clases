from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable


def _nombre_seguro(texto: str, fallback: str = "Sin titulo") -> str:
    texto = re.sub(r'[<>:"/\\|?*]+', " ", (texto or "").strip())
    texto = re.sub(r"\s+", " ", texto).strip(" .")
    return (texto[:90] or fallback)


class RepositorioClases:
    """Organiza las clases por materia, orden, fecha y título."""

    def __init__(self, raiz: str | None = None):
        documentos = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
        self.raiz = Path(raiz) if raiz else documentos / "Asistente de Clases"
        self.raiz.mkdir(parents=True, exist_ok=True)

    def materias(self) -> list[str]:
        return sorted(p.name for p in self.raiz.iterdir() if p.is_dir())

    def siguiente_numero(self, materia: str) -> int:
        carpeta = self.raiz / _nombre_seguro(materia, "Sin materia")
        if not carpeta.exists():
            return 1
        numeros = []
        for p in carpeta.iterdir():
            m = re.match(r"^(\d{3})", p.name)
            if m:
                numeros.append(int(m.group(1)))
        return max(numeros, default=0) + 1

    def guardar_clase(self, materia: str, titulo: str, segmentos: Iterable, audio_origen: str | None = None) -> Path:
        materia_segura = _nombre_seguro(materia, "Sin materia")
        titulo_seguro = _nombre_seguro(titulo, "Clase")
        numero = self.siguiente_numero(materia_segura)
        fecha = datetime.now()
        carpeta_clase = self.raiz / materia_segura / f"{numero:03d} · {fecha:%Y-%m-%d} · {titulo_seguro}"
        carpeta_clase.mkdir(parents=True, exist_ok=False)

        segmentos = list(segmentos)
        txt = "\n".join(s.a_linea_txt() for s in segmentos)
        md = "# " + titulo_seguro + "\n\n" + f"**Materia:** {materia_segura}  \n**Fecha:** {fecha:%d/%m/%Y %H:%M}  \n**Clase:** {numero:03d}\n\n" + "\n".join(s.a_linea_markdown() for s in segmentos)
        (carpeta_clase / "transcripcion.txt").write_text(txt, encoding="utf-8")
        (carpeta_clase / "transcripcion.md").write_text(md, encoding="utf-8")

        def fmt(v: float) -> str:
            h, resto = divmod(v, 3600)
            m, s = divmod(resto, 60)
            return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s-int(s))*1000):03d}"

        with (carpeta_clase / "subtitulos.srt").open("w", encoding="utf-8") as f:
            for i, seg in enumerate(segmentos, 1):
                f.write(f"{i}\n{fmt(seg.inicio)} --> {fmt(seg.fin)}\n[{seg.rol}] {seg.texto.strip()}\n\n")

        audio_destino = None
        if audio_origen and os.path.isfile(audio_origen):
            extension = Path(audio_origen).suffix.lower() or ".wav"
            audio_destino = carpeta_clase / f"audio{extension}"
            shutil.copy2(audio_origen, audio_destino)

        ficha = {
            "materia": materia_segura,
            "titulo": titulo_seguro,
            "numero": numero,
            "fecha_iso": fecha.isoformat(timespec="seconds"),
            "segmentos": len(segmentos),
            "audio": audio_destino.name if audio_destino else None,
        }
        (carpeta_clase / "ficha.json").write_text(json.dumps(ficha, indent=2, ensure_ascii=False), encoding="utf-8")
        return carpeta_clase

    def listar_clases(self, filtro: str = "") -> list[dict]:
        filtro = filtro.casefold().strip()
        clases = []
        for materia in self.materias():
            for carpeta in sorted((self.raiz / materia).iterdir(), reverse=True):
                ficha_path = carpeta / "ficha.json"
                if not carpeta.is_dir() or not ficha_path.exists():
                    continue
                try:
                    ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                ficha["ruta"] = str(carpeta)
                texto = f"{ficha.get('materia', '')} {ficha.get('titulo', '')} {ficha.get('fecha_iso', '')}".casefold()
                if not filtro or filtro in texto:
                    clases.append(ficha)
        clases.sort(key=lambda x: x.get("fecha_iso", ""), reverse=True)
        return clases

    def abrir_raiz(self) -> None:
        os.startfile(self.raiz)

    @staticmethod
    def abrir_carpeta(ruta: str) -> None:
        os.startfile(ruta)
