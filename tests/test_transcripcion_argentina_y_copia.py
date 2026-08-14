import math
import struct
import wave
from pathlib import Path

import numpy as np

from texto_en_directo import actualizar_texto, copiar_texto
from transcriptor import TranscriptorClases


class SegmentoWhisperFalso:
    def __init__(
        self,
        texto="La interleucina seis produce fiebre",
        **metricas,
    ):
        self.start = 0.0
        self.end = 2.0
        self.text = texto
        for nombre, valor in metricas.items():
            setattr(self, nombre, valor)


class ModeloWhisperFalso:
    def __init__(self):
        self.llamadas = []
        self.audios = []

    def transcribe(self, audio, **opciones):
        self.audios.append(audio)
        self.llamadas.append(opciones)
        return iter([SegmentoWhisperFalso()]), object()


class CajaFalsa:
    def __init__(self, texto=""):
        self.texto = texto
        self.estado = "normal"
        self.seleccion = ()
        self.vista = (0.0, 1.0)
        self.see_llamadas = 0
        self.seleccion_restaurada = None

    def configure(self, **opciones):
        self.estado = opciones.get("state", self.estado)

    def insert(self, _indice, texto):
        self.texto += texto

    def delete(self, _inicio, _fin):
        self.texto = ""

    def get(self, inicio, _fin):
        if inicio == "sel.first" and self.seleccion:
            a, b = self.seleccion
            return self.texto[a:b]
        return self.texto

    def tag_ranges(self, _etiqueta):
        return self.seleccion

    def index(self, indice):
        if indice == "sel.first" and self.seleccion:
            return f"1.{self.seleccion[0]}"
        if indice == "sel.last" and self.seleccion:
            return f"1.{self.seleccion[1]}"
        raise RuntimeError("sin selección")

    def tag_add(self, _etiqueta, inicio, fin):
        self.seleccion_restaurada = (inicio, fin)

    def yview(self):
        return self.vista

    def see(self, _indice):
        self.see_llamadas += 1


class VentanaFalsa:
    def __init__(self):
        self.portapapeles = ""

    def clipboard_clear(self):
        self.portapapeles = ""

    def clipboard_append(self, texto):
        self.portapapeles += texto


def _transcriptor_falso(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"RIFF-audio-falso")
    motor = TranscriptorClases(model_size="small", idioma="es")
    modelo = ModeloWhisperFalso()
    motor.whisper_model = modelo
    motor.modelos_cargados = True
    return motor, modelo, audio


def test_fragmentos_no_realimentan_texto_ni_prompt(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)

    primero = motor.transcribir_fragmento(str(audio))
    motor.transcribir_fragmento(str(audio))

    assert primero[0].texto == "La interleucina seis produce fiebre"
    assert modelo.llamadas[0]["language"] == "es"
    assert modelo.llamadas[0]["condition_on_previous_text"] is False
    assert modelo.llamadas[1]["condition_on_previous_text"] is False
    assert "initial_prompt" not in modelo.llamadas[0]
    assert "initial_prompt" not in modelo.llamadas[1]


def test_pasada_final_no_arrastra_texto_previo_ni_prompt(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)

    resultado = motor.transcribir_archivo(
        str(audio),
        min_hablantes=1,
        max_hablantes=1,
    )

    assert resultado[0].rol == "Docente"
    assert modelo.llamadas[0]["beam_size"] == 5
    assert modelo.llamadas[0]["condition_on_previous_text"] is False
    assert modelo.llamadas[0]["language"] == "es"
    assert modelo.llamadas[0]["word_timestamps"] is True
    assert modelo.llamadas[0]["hallucination_silence_threshold"] == 2.0
    assert modelo.llamadas[0]["vad_parameters"] == {
        "threshold": 0.25,
        "min_speech_duration_ms": 180,
        "max_speech_duration_s": 28,
        "min_silence_duration_ms": 700,
        "speech_pad_ms": 600,
    }
    assert "initial_prompt" not in modelo.llamadas[0]


def test_directo_acondiciona_voz_lejana_y_mantiene_vad(tmp_path):
    audio = tmp_path / "voz_lejana.wav"
    sample_rate = 48000
    segundos = 2
    amplitud = 275  # RMS aproximado 0,6 %; nivel mostrado por ARGOS ~3 %.
    tiempo = np.arange(sample_rate * segundos, dtype=np.float64) / sample_rate
    muestras = np.rint(
        amplitud * np.sin(2 * math.pi * 220 * tiempo)
    ).astype(np.int16)
    with wave.open(str(audio), "wb") as archivo:
        archivo.setnchannels(1)
        archivo.setsampwidth(2)
        archivo.setframerate(sample_rate)
        archivo.writeframes(struct.pack(f"<{muestras.size}h", *muestras))

    motor = TranscriptorClases(model_size="small", idioma="es")
    modelo = ModeloWhisperFalso()
    motor.whisper_model = modelo
    motor.modelos_cargados = True

    motor.transcribir_fragmento(str(audio))

    procesado = modelo.audios[0]
    assert isinstance(procesado, np.ndarray)
    assert procesado.dtype == np.float32
    assert procesado.size == 16000 * segundos
    assert float(np.sqrt(np.mean(procesado.astype(np.float64) ** 2))) > 0.04
    assert modelo.llamadas[0]["vad_filter"] is True
    assert modelo.llamadas[0]["beam_size"] == 3
    assert modelo.llamadas[0]["word_timestamps"] is True
    assert modelo.llamadas[0]["hallucination_silence_threshold"] == 2.0
    assert modelo.llamadas[0]["vad_parameters"] == {
        "threshold": 0.35,
        "min_speech_duration_ms": 180,
        "max_speech_duration_s": 28,
        "min_silence_duration_ms": 350,
        "speech_pad_ms": 500,
    }
    assert modelo.llamadas[0]["repetition_penalty"] > 1
    assert modelo.llamadas[0]["no_repeat_ngram_size"] == 4
    assert motor.ultimo_diagnostico_audio["ganancia_db"] > 10


def test_directo_corta_la_tercera_alucinacion_igual_con_audio_debil(tmp_path):
    audio = tmp_path / "voz_debil.wav"
    sample_rate = 16000
    tiempo = np.arange(sample_rate, dtype=np.float64) / sample_rate
    muestras = np.rint(180 * np.sin(2 * math.pi * 220 * tiempo)).astype(
        np.int16
    )
    with wave.open(str(audio), "wb") as archivo:
        archivo.setnchannels(1)
        archivo.setsampwidth(2)
        archivo.setframerate(sample_rate)
        archivo.writeframes(muestras.tobytes())

    motor = TranscriptorClases(model_size="small", idioma="es")
    modelo = ModeloWhisperFalso()
    motor.whisper_model = modelo
    motor.modelos_cargados = True

    resultados = [motor.transcribir_fragmento(str(audio)) for _ in range(3)]

    assert [len(resultado) for resultado in resultados] == [1, 1, 0]
    assert "tres fragmentos" in motor.consumir_descartes()[0]["razon"]


def test_directo_no_fuerza_segundo_intento_sin_vad(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)
    modelo.transcribe = lambda _audio, **opciones: (
        modelo.llamadas.append(opciones) or iter([]),
        object(),
    )

    resultado = motor.transcribir_fragmento(str(audio))

    assert resultado == []
    assert len(modelo.llamadas) == 1
    assert modelo.llamadas[0]["vad_filter"] is True


def test_detector_descarta_bucle_y_conserva_diagnostico(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)
    frase = "fuerte el hueso alta glada y valiente se tiene"
    modelo.transcribe = lambda _audio, **_opciones: (
        iter([SegmentoWhisperFalso(" ".join([frase] * 5))]),
        object(),
    )

    resultado = motor.transcribir_fragmento(str(audio))
    descartes = motor.consumir_descartes()

    assert resultado == []
    assert len(descartes) == 1
    assert "repetida 5 veces" in descartes[0]["razon"]
    assert descartes[0]["texto"].count("fuerte") == 5


def test_detector_corta_cola_repetida_y_conserva_inicio_valido(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)
    inicio = "En el daño alveolar difuso aparecen membranas hialinas"
    bucle = "esto es muy importante para el examen"
    modelo.transcribe = lambda _audio, **_opciones: (
        iter([SegmentoWhisperFalso(f"{inicio}. " + " ".join([bucle] * 4))]),
        object(),
    )

    resultado = motor.transcribir_fragmento(str(audio))

    assert len(resultado) == 1
    assert resultado[0].texto == f"{inicio}."
    assert motor.consumir_descartes()[0]["ambito"] == "directo"


def test_detector_no_confunde_una_repeticion_docente_normal(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)
    modelo.transcribe = lambda _audio, **_opciones: (
        iter(
            [
                SegmentoWhisperFalso(
                    "Esto es importante. Esto es importante. Ahora seguimos "
                    "con la fisiopatología del edema pulmonar."
                )
            ]
        ),
        object(),
    )

    resultado = motor.transcribir_fragmento(str(audio))

    assert len(resultado) == 1
    assert "Ahora seguimos" in resultado[0].texto
    assert motor.consumir_descartes() == []


def test_detector_descarta_segmento_con_dos_metricas_patologicas(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)
    modelo.transcribe = lambda _audio, **_opciones: (
        iter(
            [
                SegmentoWhisperFalso(
                    "Texto plausible pero inventado",
                    no_speech_prob=0.7,
                    avg_logprob=-1.3,
                    compression_ratio=1.2,
                )
            ]
        ),
        object(),
    )

    resultado = motor.transcribir_fragmento(str(audio))

    assert resultado == []
    assert "confianza baja" in motor.consumir_descartes()[0]["razon"]


def test_detector_no_descarta_solo_por_probabilidad_de_silencio(tmp_path):
    motor, modelo, audio = _transcriptor_falso(tmp_path)
    modelo.transcribe = lambda _audio, **_opciones: (
        iter(
            [
                SegmentoWhisperFalso(
                    "Los neumocitos tipo dos regeneran el epitelio alveolar",
                    no_speech_prob=0.85,
                    avg_logprob=-0.2,
                    compression_ratio=1.1,
                )
            ]
        ),
        object(),
    )

    resultado = motor.transcribir_fragmento(str(audio))

    assert len(resultado) == 1
    assert motor.consumir_descartes() == []


def test_actualizacion_incremental_no_reescribe_ni_mueve_una_seleccion():
    caja = CajaFalsa("Primera frase")
    caja.seleccion = (0, 7)

    renderizado = actualizar_texto(
        caja, "Primera frase\nSegunda frase", "Primera frase"
    )

    assert renderizado == "Primera frase\nSegunda frase"
    assert caja.texto == renderizado
    assert caja.estado == "disabled"
    assert caja.see_llamadas == 0


def test_copia_funciona_durante_la_transcripcion_sin_editar_el_cuadro():
    caja = CajaFalsa("Shock distributivo\nShock cardiogénico")
    ventana = VentanaFalsa()

    texto = copiar_texto(ventana, caja)

    assert texto == caja.texto
    assert ventana.portapapeles == caja.texto


def test_una_correccion_del_ultimo_fragmento_conserva_la_seleccion():
    caja = CajaFalsa("Interleucina seis")
    caja.seleccion = (0, 12)

    actualizar_texto(caja, "Interleucina 6", "Interleucina seis")

    assert caja.texto == "Interleucina 6"
    assert caja.seleccion_restaurada == ("1.0", "1.12")
    assert caja.see_llamadas == 0
