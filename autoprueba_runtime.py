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
from media_utils import eliminar_temporal, preparar_para_transcripcion
from transcriptor import TranscriptorClases


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

        with tempfile.TemporaryDirectory(prefix="argos_biblioteca_prueba_") as raiz:
            biblioteca = BibliotecaMedica(raiz)
            item, creado = biblioteca.importar_archivo(documento, "Apuntes")
            procesado = biblioteca.procesar_documento(item["id"])
            resultado["documento_creado"] = creado
            resultado["documento_caracteres"] = procesado["caracteres_extraidos"]

        resultado["ok"] = bool(
            resultado["audio_segmentos"]
            and resultado["video_segmentos"]
            and resultado["documento_caracteres"]
        )
        if not resultado["ok"]:
            resultado["error"] = (
                "La autoprueba no obtuvo texto de audio, vídeo y documento."
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
