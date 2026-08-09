"""Autoprueba no interactiva del ejecutable empaquetado.

Solo se activa mediante variables de entorno del workflow. No forma parte del
recorrido normal del usuario y evita declarar válido un instalador que carga el
modelo pero no consigue ejecutar una inferencia real.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from biblioteca_medica import BibliotecaMedica
from indice_sqlite import IndiceConocimientoSQLite
from media_utils import eliminar_temporal, preparar_para_transcripcion
from orquestador import OrquestadorArgos
from repositorio import RepositorioClases
from transcriptor import SegmentoTranscrito, TranscriptorClases


ARCHIVOS_PIPELINE_OBLIGATORIOS = (
    "transcripcion_medica_revisada.txt",
    "pipeline_clase.json",
    "argos_enriquecido.json",
    "apuntes_estudio_argos.md",
    "preguntas_repaso.md",
    "flashcards_argos.tsv",
    "repaso_rapido.md",
    "apuntes_argos.docx",
    "estado_argos.json",
)


def probar_pipeline_completo(raiz: str | Path, documento: str | Path) -> dict:
    """Ejecuta el recorrido médico completo usado por el binario distribuido."""
    raiz = Path(raiz)
    repositorio = RepositorioClases(str(raiz))
    biblioteca = BibliotecaMedica(str(raiz / "Biblioteca médica"))
    item, _creado = biblioteca.importar_archivo(str(documento), "Apuntes")
    item = biblioteca.procesar_documento(item["id"])

    segmentos = [
        SegmentoTranscrito(
            0,
            18,
            (
                "El shock provoca hipoperfusión tisular porque el sistema "
                "circulatorio no aporta suficiente oxígeno."
            ),
            "SPEAKER_00",
            "Docente",
        ),
        SegmentoTranscrito(
            18,
            36,
            (
                "A diferencia del shock distributivo, el hipovolémico se "
                "asocia a una reducción del volumen circulante."
            ),
            "SPEAKER_00",
            "Docente",
        ),
        SegmentoTranscrito(
            36,
            52,
            "Pregunta de examen: ¿por qué aumenta el lactato en el shock?",
            "SPEAKER_00",
            "Docente",
        ),
    ]
    carpeta = repositorio.guardar_clase(
        "Patología",
        "Validación integral del shock",
        segmentos,
    )
    repositorio.vincular_documentos(carpeta, [item])

    indice = IndiceConocimientoSQLite(str(raiz))
    resultado = OrquestadorArgos(indice).procesar_clase(carpeta)
    faltantes = [
        nombre
        for nombre in ARCHIVOS_PIPELINE_OBLIGATORIOS
        if not (carpeta / nombre).is_file()
        or (carpeta / nombre).stat().st_size == 0
    ]
    estado = json.loads((carpeta / "estado_argos.json").read_text(encoding="utf-8"))
    if estado.get("estado") != "completado":
        raise RuntimeError("El pipeline empaquetado no terminó como completado.")
    if faltantes:
        raise RuntimeError(
            "El pipeline empaquetado no generó: " + ", ".join(faltantes)
        )
    if resultado.get("bloques", 0) < 1 or resultado.get("flashcards", 0) < 1:
        raise RuntimeError(
            "El pipeline empaquetado no produjo bloques y tarjetas utilizables."
        )
    if resultado.get("referencias", 0) < 1:
        raise RuntimeError(
            "El pipeline empaquetado no vinculó la fuente médica de prueba."
        )
    return {
        "ok": True,
        "carpeta": str(carpeta),
        "archivos": len(ARCHIVOS_PIPELINE_OBLIGATORIOS),
        "bloques": resultado.get("bloques", 0),
        "flashcards": resultado.get("flashcards", 0),
        "referencias": resultado.get("referencias", 0),
    }


def ejecutar_autoprueba_desde_entorno() -> int:
    salida = Path(os.environ["ARGOS_SELFTEST_RESULT"])
    audio = os.environ.get("ARGOS_SELFTEST_AUDIO", "")
    video = os.environ.get("ARGOS_SELFTEST_VIDEO", "")
    documento = os.environ.get("ARGOS_SELFTEST_DOCUMENT", "")
    resultado = {
        "ok": False,
        "audio_segmentos": 0,
        "video_segmentos": 0,
        "documento_caracteres": 0,
        "pipeline_ok": False,
        "pipeline_archivos": 0,
        "pipeline_bloques": 0,
        "pipeline_flashcards": 0,
        "pipeline_referencias": 0,
    }
    try:
        motor = TranscriptorClases(
            model_size="tiny", usar_gpu=False, idioma="auto"
        )
        motor.cargar_modelos()
        segmentos_audio = motor.transcribir_archivo(audio)
        resultado["audio_segmentos"] = len(segmentos_audio)
        resultado["audio_texto"] = " ".join(
            segmento.texto.strip() for segmento in segmentos_audio
        )

        ruta_video, temporal, _tipo = preparar_para_transcripcion(video)
        try:
            segmentos_video = motor.transcribir_archivo(ruta_video)
        finally:
            if temporal:
                eliminar_temporal(ruta_video)
        resultado["video_segmentos"] = len(segmentos_video)
        resultado["video_texto"] = " ".join(
            segmento.texto.strip() for segmento in segmentos_video
        )

        with tempfile.TemporaryDirectory(prefix="argos_pipeline_prueba_") as raiz:
            biblioteca = BibliotecaMedica(str(Path(raiz) / "biblioteca_aislada"))
            item, creado = biblioteca.importar_archivo(documento, "Apuntes")
            procesado = biblioteca.procesar_documento(item["id"])
            resultado["documento_creado"] = creado
            resultado["documento_caracteres"] = procesado["caracteres_extraidos"]

            pipeline = probar_pipeline_completo(Path(raiz) / "integral", documento)
            resultado["pipeline_ok"] = pipeline["ok"]
            resultado["pipeline_archivos"] = pipeline["archivos"]
            resultado["pipeline_bloques"] = pipeline["bloques"]
            resultado["pipeline_flashcards"] = pipeline["flashcards"]
            resultado["pipeline_referencias"] = pipeline["referencias"]

        resultado["ok"] = bool(
            resultado["audio_segmentos"]
            and resultado["video_segmentos"]
            and resultado["documento_caracteres"]
            and resultado["pipeline_ok"]
        )
        if not resultado["ok"]:
            resultado["error"] = (
                "La autoprueba no completó audio, vídeo, documento y pipeline médico."
            )
    except Exception as exc:
        resultado["error_tipo"] = type(exc).__name__
        resultado["error"] = str(exc)
    finally:
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_text(
            json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return 0 if resultado["ok"] else 1
