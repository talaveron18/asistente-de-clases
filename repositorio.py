from __future__ import annotations

import json
import os
import re
import shutil
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Iterable

from transcriptor import SegmentoTranscrito


_FICHA_LOCK = threading.RLock()


def _nombre_seguro(texto: str, fallback: str = "Sin titulo") -> str:
    texto = re.sub(r'[<>:"/\\|?*]+', " ", (texto or "").strip())
    texto = re.sub(r"\s+", " ", texto).strip(" .")
    return (texto[:90] or fallback)


def _escribir_texto_atomico(ruta: Path, contenido: str) -> None:
    temporal = ruta.with_name(
        f"{ruta.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    with temporal.open("w", encoding="utf-8", newline="\n") as archivo:
        archivo.write(contenido)
        archivo.flush()
        os.fsync(archivo.fileno())
    os.replace(temporal, ruta)


def _escribir_json_atomico(ruta: Path, datos: dict | list) -> None:
    _escribir_texto_atomico(
        ruta, json.dumps(datos, indent=2, ensure_ascii=False)
    )


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

    def iniciar_grabacion(
        self,
        materia: str,
        titulo: str,
        sample_rate: int = 16000,
        dispositivo_audio: str = "",
    ) -> Path:
        """Reserva y persiste la clase antes de abrir el micrófono."""
        materia_segura = _nombre_seguro(materia, "Sin materia")
        titulo_seguro = _nombre_seguro(titulo, "Clase")
        numero = self.siguiente_numero(materia_segura)
        fecha = datetime.now()
        carpeta = (
            self.raiz
            / materia_segura
            / f"{numero:03d} · {fecha:%Y-%m-%d} · {titulo_seguro}"
        )
        carpeta.mkdir(parents=True, exist_ok=False)
        (carpeta / "fragmentos_audio").mkdir()
        _escribir_texto_atomico(carpeta / "transcripcion.txt", "")
        _escribir_json_atomico(
            carpeta / "ficha.json",
            {
                "materia": materia_segura,
                "titulo": titulo_seguro,
                "numero": numero,
                "fecha_iso": fecha.isoformat(timespec="seconds"),
                "segmentos": 0,
                "audio": "audio.wav",
                "origen": "microfono",
                "sample_rate": sample_rate,
                "dispositivo_audio": dispositivo_audio,
                "estado_grabacion": "grabando",
                "ultima_actualizacion": fecha.isoformat(timespec="seconds"),
                "error_grabacion": None,
            },
        )
        return carpeta

    @staticmethod
    def marcar_estado_grabacion(
        carpeta: str | Path, estado: str, error: str | None = None
    ) -> None:
        carpeta = Path(carpeta)
        ficha_path = carpeta / "ficha.json"
        with _FICHA_LOCK:
            try:
                ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                ficha = {}
            ficha["estado_grabacion"] = estado
            ficha["error_grabacion"] = error
            ficha["ultima_actualizacion"] = datetime.now().isoformat(
                timespec="seconds"
            )
            _escribir_json_atomico(ficha_path, ficha)

    @staticmethod
    def guardar_transcripcion_fragmento(
        carpeta: str | Path,
        indice: int,
        inicio: float,
        fin: float,
        segmentos: Iterable[SegmentoTranscrito],
    ) -> list[SegmentoTranscrito]:
        carpeta = Path(carpeta)
        datos = {
            "indice": indice,
            "inicio": inicio,
            "fin": fin,
            "segmentos": [
                {
                    "inicio": segmento.inicio,
                    "fin": segmento.fin,
                    "texto": segmento.texto,
                    "hablante_original": segmento.hablante_original,
                    "rol": segmento.rol,
                }
                for segmento in segmentos
            ],
        }
        destino = carpeta / "fragmentos_audio" / f"fragmento_{indice:06d}.json"
        _escribir_json_atomico(destino, datos)
        todos = RepositorioClases.segmentos_grabacion(carpeta)
        RepositorioClases._escribir_transcripciones(carpeta, todos)
        RepositorioClases.marcar_estado_grabacion(carpeta, "transcribiendo")
        return todos

    @staticmethod
    def segmentos_grabacion(carpeta: str | Path) -> list[SegmentoTranscrito]:
        carpeta = Path(carpeta)
        segmentos = []
        for ruta in sorted((carpeta / "fragmentos_audio").glob("fragmento_*.json")):
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
                for segmento in datos.get("segmentos", []):
                    segmentos.append(SegmentoTranscrito(**segmento))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        segmentos.sort(key=lambda item: (item.inicio, item.fin))
        unicos = []
        for segmento in segmentos:
            texto = re.sub(r"\W+", " ", segmento.texto.casefold()).strip()
            duplicado = any(
                texto
                and texto
                == re.sub(r"\W+", " ", previo.texto.casefold()).strip()
                and abs(segmento.inicio - previo.inicio) <= 2.0
                for previo in unicos[-3:]
            )
            if not duplicado:
                unicos.append(segmento)
        return unicos

    @staticmethod
    def fragmentos_pendientes(
        carpeta: str | Path, solapamiento_fragmento: float = 1.0
    ):
        from grabador import FragmentoAudio

        carpeta = Path(carpeta)
        pendientes = []
        inicio = 0.0
        for ruta in sorted(
            (carpeta / "fragmentos_audio").glob("fragmento_*.wav")
        ):
            try:
                indice = int(ruta.stem.rsplit("_", 1)[1])
            except (IndexError, ValueError):
                continue
            try:
                with wave.open(str(ruta), "rb") as wav_file:
                    duracion = wav_file.getnframes() / wav_file.getframerate()
            except (OSError, wave.Error, ZeroDivisionError):
                continue
            fin = inicio + duracion
            if not ruta.with_suffix(".json").exists():
                pendientes.append(
                    FragmentoAudio(indice, str(ruta), inicio, fin)
                )
            inicio = max(inicio, fin - solapamiento_fragmento)
        return pendientes

    def grabaciones_interrumpidas(self) -> list[Path]:
        estados = {
            "grabando",
            "deteniendo",
            "transcribiendo",
            "interrumpida",
            "transcripcion_incompleta",
        }
        pendientes = []
        for materia in self.materias():
            for carpeta in (self.raiz / materia).iterdir():
                ficha_path = carpeta / "ficha.json"
                if not carpeta.is_dir() or not ficha_path.exists():
                    continue
                try:
                    ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if ficha.get("estado_grabacion") in estados:
                    pendientes.append(carpeta)
        return sorted(pendientes)

    @staticmethod
    def finalizar_grabacion(
        carpeta: str | Path, error: str | None = None
    ) -> list[SegmentoTranscrito]:
        carpeta = Path(carpeta)
        segmentos = RepositorioClases.segmentos_grabacion(carpeta)
        RepositorioClases._escribir_transcripciones(carpeta, segmentos)
        estado = "transcripcion_incompleta" if error else (
            "guardada" if segmentos else "sin_voz"
        )
        with _FICHA_LOCK:
            RepositorioClases.marcar_estado_grabacion(carpeta, estado, error)
            ficha_path = carpeta / "ficha.json"
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            ficha["segmentos"] = len(segmentos)
            _escribir_json_atomico(ficha_path, ficha)
        return segmentos

    @staticmethod
    def _escribir_transcripciones(
        carpeta: Path, segmentos: Iterable[SegmentoTranscrito]
    ) -> None:
        segmentos = list(segmentos)
        titulo = carpeta.name.split(" · ", 2)[-1]
        txt = "\n".join(s.a_linea_txt() for s in segmentos)
        md = "# " + titulo + "\n\n" + "\n".join(
            s.a_linea_markdown() for s in segmentos
        )
        _escribir_texto_atomico(carpeta / "transcripcion.txt", txt)
        _escribir_texto_atomico(carpeta / "transcripcion.md", md)

        lineas_srt = []
        for i, seg in enumerate(segmentos, 1):
            def fmt(v: float) -> str:
                h, resto = divmod(v, 3600)
                m, s = divmod(resto, 60)
                return (
                    f"{int(h):02d}:{int(m):02d}:{int(s):02d},"
                    f"{int((s-int(s))*1000):03d}"
                )
            lineas_srt.append(
                f"{i}\n{fmt(seg.inicio)} --> {fmt(seg.fin)}\n"
                f"[{seg.rol}] {seg.texto.strip()}\n"
            )
        _escribir_texto_atomico(
            carpeta / "subtitulos.srt", "\n".join(lineas_srt)
        )

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
        _escribir_texto_atomico(carpeta_clase / "transcripcion.txt", txt)
        _escribir_texto_atomico(carpeta_clase / "transcripcion.md", md)

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
        _escribir_json_atomico(carpeta_clase / "ficha.json", ficha)
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
