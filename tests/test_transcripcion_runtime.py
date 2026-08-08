from __future__ import annotations

import sys
import types
import wave

import main as modulo_main
import transcriptor as modulo_transcriptor
from main import AsistenteClasesApp
from transcriptor import TranscriptorClases


class _SegmentoWhisper:
    start = 0.0
    end = 1.2
    text = " prueba de voz"


def _wav_vacio(ruta):
    with wave.open(str(ruta), "wb") as archivo:
        archivo.setnchannels(1)
        archivo.setsampwidth(2)
        archivo.setframerate(16000)
        archivo.writeframes(b"\0\0" * 1600)


def test_inferencia_cuda_perezosa_reintenta_automaticamente_en_cpu(
    tmp_path, monkeypatch
):
    creados = []

    class ModeloFalso:
        def __init__(self, _tamano, device, **_kwargs):
            self.device = device
            creados.append(device)

        def transcribe(self, _ruta, **_opciones):
            if self.device == "cuda":
                def generador_roto():
                    raise RuntimeError("cublas64_12.dll no encontrado")
                    yield

                return generador_roto(), object()
            return iter([_SegmentoWhisper()]), object()

    monkeypatch.setattr(modulo_transcriptor, "_verificar_ffmpeg", lambda: True)
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=ModeloFalso),
    )
    ruta = tmp_path / "voz.wav"
    _wav_vacio(ruta)

    avisos = []
    motor = TranscriptorClases(model_size="tiny", usar_gpu=True)
    motor.cargar_modelos(lambda mensaje, _p: avisos.append(mensaje))
    segmentos = motor.transcribir_fragmento(str(ruta))

    assert creados == ["cuda", "cpu"]
    assert motor.dispositivo_real == "cpu"
    assert [segmento.texto.strip() for segmento in segmentos] == ["prueba de voz"]
    assert any("automáticamente por CPU" in aviso for aviso in avisos)


def test_fragmento_con_voz_baja_reintenta_sin_vad(tmp_path):
    opciones = []

    class ModeloFalso:
        def transcribe(self, _ruta, **kwargs):
            opciones.append(kwargs)
            if kwargs.get("vad_filter"):
                return iter([]), object()
            return iter([_SegmentoWhisper()]), object()

    ruta = tmp_path / "voz_baja.wav"
    _wav_vacio(ruta)
    motor = TranscriptorClases(model_size="tiny", usar_gpu=False)
    motor.whisper_model = ModeloFalso()
    motor.modelos_cargados = True

    segmentos = motor.transcribir_fragmento(str(ruta))

    assert len(segmentos) == 1
    assert [opcion.get("vad_filter") for opcion in opciones] == [True, False]


def test_selector_unificado_envia_documento_a_biblioteca(tmp_path, monkeypatch):
    documento = tmp_path / "tema.txt"
    documento.write_text("Contenido médico", encoding="utf-8")
    llamados = []

    class Tabs:
        def set(self, nombre):
            llamados.append(("tab", nombre))

    app = types.SimpleNamespace(
        tabs=Tabs(),
        categoria_documentos=types.SimpleNamespace(get=lambda: "Todas"),
        _importar_y_procesar_documentos=lambda rutas, categoria: llamados.append(
            (list(rutas), categoria)
        ),
    )
    monkeypatch.setattr(
        modulo_main.filedialog, "askopenfilename", lambda **_kwargs: str(documento)
    )

    AsistenteClasesApp._seleccionar_archivo(app)

    assert llamados == [
        ("tab", "Biblioteca"),
        ([str(documento)], "Tratados"),
    ]


def test_documento_importado_se_extrae_sin_segundo_boton(monkeypatch):
    procesados = []

    class Biblioteca:
        def importar_archivo(self, ruta, categoria):
            return {"id": "doc-1"}, True

        def procesar_documento(self, item_id, callback):
            procesados.append(item_id)
            callback("Leyendo", 0.5)

    class HiloInmediato:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(modulo_main.threading, "Thread", HiloInmediato)
    monkeypatch.setattr(modulo_main.messagebox, "showinfo", lambda *_a, **_k: None)
    app = types.SimpleNamespace(
        biblioteca_medica=Biblioteca(),
        _refrescar_documentos=lambda: None,
        estado_documentos=types.SimpleNamespace(configure=lambda **_kwargs: None),
        _actualizar_progreso_documentos=lambda *_args: None,
        _fin_importacion_documentos=lambda *_args: None,
        after=lambda _ms, callback, *args: callback(*args),
    )

    AsistenteClasesApp._importar_y_procesar_documentos(
        app, ["tema.txt"], "Apuntes"
    )

    assert procesados == ["doc-1"]
