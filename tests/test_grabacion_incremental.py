import json
import struct
import threading
import time
import wave
from pathlib import Path

import numpy as np

import grabador as modulo_grabador
from grabador import (
    DispositivoEntrada,
    FragmentoAudio,
    GrabadorAudio,
    recuperar_audio_interrumpido,
)
from repositorio import RepositorioClases
from transcripcion_incremental import TranscripcionIncremental
from transcriptor import SegmentoTranscrito


def _wav(ruta: Path, frames: int = 160, sample_rate: int = 16000) -> None:
    with wave.open(str(ruta), "wb") as archivo:
        archivo.setnchannels(1)
        archivo.setsampwidth(2)
        archivo.setframerate(sample_rate)
        archivo.writeframes(struct.pack("<h", 1000) * frames)


def test_hardware_automatico_prefiere_microfono_real(monkeypatch):
    class Predeterminado:
        device = (0, 9)

    class SoundDeviceFalso:
        default = Predeterminado()

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "Asignador de sonido Microsoft - Input",
                    "max_input_channels": 2,
                    "default_samplerate": 44100,
                },
                {
                    "name": "Micrófono USB",
                    "max_input_channels": 1,
                    "default_samplerate": 48000,
                },
            ]

        @staticmethod
        def query_hostapis():
            return [{"default_input_device": 1}]

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)

    dispositivo = GrabadorAudio.detectar_dispositivo_entrada()

    assert dispositivo.indice == 1
    assert dispositivo.nombre == "Micrófono USB"
    assert dispositivo.sample_rate == 16000


def test_hardware_automatico_adapta_frecuencia_nativa(monkeypatch):
    class Predeterminado:
        device = (0, 2)

    class SoundDeviceFalso:
        default = Predeterminado()

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "Micrófono integrado",
                    "max_input_channels": 1,
                    "default_samplerate": 48000,
                }
            ]

        @staticmethod
        def query_hostapis():
            return []

        @staticmethod
        def check_input_settings(samplerate, **_kwargs):
            if samplerate != 48000:
                raise ValueError("frecuencia no admitida")

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)

    dispositivo = GrabadorAudio.detectar_dispositivo_entrada(16000)

    assert dispositivo.sample_rate == 48000


def test_grabador_persiste_fragmentos_sin_bloquear_callback(
    tmp_path, monkeypatch
):
    callbacks = []

    class StreamFalso:
        def __init__(self, callback, **_kwargs):
            self.callback = callback

        def start(self):
            self.callback(
                np.full((10, 1), 1200, dtype=np.int16), 10, None, None
            )

        def stop(self):
            return None

        def close(self):
            return None

    class SoundDeviceFalso:
        InputStream = StreamFalso

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)
    grabador = GrabadorAudio(sample_rate=10, dispositivo=3)

    assert grabador.iniciar(
        archivo_salida=str(tmp_path / "audio.wav"),
        directorio_fragmentos=str(tmp_path / "fragmentos_audio"),
        callback_fragmento=callbacks.append,
        duracion_fragmento=1,
    )
    assert grabador.detener() == str(tmp_path / "audio.wav")

    assert len(callbacks) == 1
    assert Path(callbacks[0].ruta).exists()
    with wave.open(callbacks[0].ruta, "rb") as archivo:
        assert archivo.getnframes() == 10
    with wave.open(str(tmp_path / "audio.wav"), "rb") as archivo:
        assert archivo.getnframes() == 10


def test_grabador_usa_el_canal_multicanal_que_contiene_voz(tmp_path, monkeypatch):
    class StreamFalso:
        def __init__(self, callback, channels, **_kwargs):
            assert channels == 2
            self.callback = callback

        def start(self):
            entrada = np.column_stack(
                (
                    np.zeros(10, dtype=np.int16),
                    np.full(10, 2400, dtype=np.int16),
                )
            )
            self.callback(entrada, 10, None, None)

        def stop(self):
            return None

        def close(self):
            return None

    class SoundDeviceFalso:
        InputStream = StreamFalso

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)
    entrada = DispositivoEntrada(7, "Microphone Array", 10, 2, "WASAPI")
    grabador = GrabadorAudio(sample_rate=10, dispositivo=7)

    assert grabador.iniciar(
        archivo_salida=str(tmp_path / "audio.wav"),
        candidatos_entrada=[entrada],
        duracion_fragmento=1,
    )
    grabador.detener()

    with wave.open(str(tmp_path / "audio.wav"), "rb") as archivo:
        muestras = np.frombuffer(archivo.readframes(10), dtype=np.int16)
    assert muestras.tolist() == [2400] * 10
    assert grabador.nivel_maximo > 0.002


def test_grabador_cambia_automaticamente_si_la_primera_ruta_esta_muda(
    tmp_path, monkeypatch
):
    cambios = []
    hay_senal = threading.Event()

    class StreamFalso:
        def __init__(self, callback, device, **_kwargs):
            self.callback = callback
            self.device = device

        def start(self):
            amplitud = 0 if self.device == 1 else 2200
            self.callback(
                np.full((10, 1), amplitud, dtype=np.int16), 10, None, None
            )
            if amplitud:
                hay_senal.set()

        def stop(self):
            return None

        def close(self):
            return None

    class SoundDeviceFalso:
        InputStream = StreamFalso

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)
    entradas = [
        DispositivoEntrada(1, "Micrófono MME", 10, 1, "MME"),
        DispositivoEntrada(2, "Micrófono WASAPI", 10, 1, "WASAPI"),
    ]
    grabador = GrabadorAudio(sample_rate=10, dispositivo=1)

    assert grabador.iniciar(
        archivo_salida=str(tmp_path / "audio.wav"),
        candidatos_entrada=entradas,
        callback_dispositivo=lambda entrada, motivo: cambios.append(
            (entrada.indice, motivo)
        ),
        segundos_sin_senal=0.25,
    )
    assert hay_senal.wait(timeout=2)
    grabador.detener()

    assert grabador.dispositivo == 2
    assert (2, "cambio_automatico") in cambios
    assert grabador.nivel_maximo > 0.002


def test_transcripcion_se_guarda_antes_de_detener(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Patología", "Shock")
    fragmento_wav = carpeta / "fragmentos_audio" / "fragmento_000001.wav"
    _wav(fragmento_wav)
    guardado = threading.Event()

    class TranscriptorFalso:
        @staticmethod
        def transcribir_fragmento(_ruta):
            return [
                SegmentoTranscrito(0, 1, "Shock distributivo", "SPEAKER_00", "Docente")
            ]

    incremental = TranscripcionIncremental(
        TranscriptorFalso(),
        repositorio,
        carpeta,
        callback_segmentos=lambda _segmentos: guardado.set(),
    )
    incremental.encolar(FragmentoAudio(1, str(fragmento_wav), 0, 10))

    assert guardado.wait(timeout=3)
    assert "Shock distributivo" in (carpeta / "transcripcion.txt").read_text(
        encoding="utf-8"
    )
    assert (carpeta / "fragmentos_audio" / "fragmento_000001.json").exists()

    resultado = incremental.finalizar()
    assert resultado.completa
    assert json.loads((carpeta / "ficha.json").read_text(encoding="utf-8"))[
        "estado_grabacion"
    ] == "guardada"


def test_fallo_conserva_audio_y_se_recupera_sin_duplicar(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Patología", "Sepsis")
    fragmento_wav = carpeta / "fragmentos_audio" / "fragmento_000001.wav"
    _wav(fragmento_wav)

    class TranscriptorRoto:
        @staticmethod
        def transcribir_fragmento(_ruta):
            raise RuntimeError("modelo ocupado")

    primera = TranscripcionIncremental(TranscriptorRoto(), repositorio, carpeta)
    primera.encolar(FragmentoAudio(1, str(fragmento_wav), 0, 10))
    resultado_fallido = primera.finalizar()

    assert not resultado_fallido.completa
    assert fragmento_wav.exists()
    assert repositorio.fragmentos_pendientes(carpeta)

    class TranscriptorRecuperado:
        @staticmethod
        def transcribir_fragmento(_ruta):
            return [
                SegmentoTranscrito(0, 1, "Sepsis", "SPEAKER_00", "Docente")
            ]

    segunda = TranscripcionIncremental(
        TranscriptorRecuperado(), repositorio, carpeta
    )
    segunda.encolar_varios(repositorio.fragmentos_pendientes(carpeta))
    resultado = segunda.finalizar()

    assert resultado.completa
    assert len(resultado.segmentos) == 1
    assert (carpeta / "transcripcion.txt").read_text(encoding="utf-8").count(
        "Sepsis"
    ) == 1


def test_solapamiento_no_duplica_la_misma_frase(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Microbiología", "Virus")

    repositorio.guardar_transcripcion_fragmento(
        carpeta,
        1,
        0,
        10,
        [SegmentoTranscrito(9.0, 10.0, "Virus ARN", "SPEAKER_00", "Docente")],
    )
    segmentos = repositorio.guardar_transcripcion_fragmento(
        carpeta,
        2,
        9,
        19,
        [SegmentoTranscrito(9.2, 10.2, "Virus ARN", "SPEAKER_00", "Docente")],
    )

    assert len(segmentos) == 1
    assert (carpeta / "transcripcion.txt").read_text(encoding="utf-8").count(
        "Virus ARN"
    ) == 1


def test_repara_wav_tras_cierre_inesperado_y_crea_tramo_pendiente(tmp_path):
    audio = tmp_path / "audio.wav"
    _wav(audio, frames=25, sample_rate=10)
    datos = bytearray(audio.read_bytes())
    datos[4:8] = struct.pack("<I", 38)
    datos[40:44] = struct.pack("<I", 2)
    audio.write_bytes(datos)

    total = recuperar_audio_interrumpido(
        audio,
        tmp_path / "fragmentos_audio",
        sample_rate=10,
        duracion_fragmento=1,
        solapamiento_fragmento=0,
    )

    assert total == 3
    with wave.open(str(audio), "rb") as archivo:
        assert archivo.getnframes() == 25
    assert len(list((tmp_path / "fragmentos_audio").glob("*.wav"))) == 3
