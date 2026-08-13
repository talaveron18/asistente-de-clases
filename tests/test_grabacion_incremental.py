import json
import struct
import threading
import time
import wave
from pathlib import Path

import numpy as np

import grabador as modulo_grabador
from audio_asr import preparar_archivo_asr
from grabador import (
    UMBRAL_SENAL_UTIL,
    DispositivoEntrada,
    FragmentoAudio,
    GrabadorAudio,
    recuperar_audio_interrumpido,
)
from repositorio import RepositorioClases
from transcripcion_incremental import (
    TranscripcionIncremental,
    evaluar_versiones_transcripcion,
)
from transcriptor import SegmentoTranscrito


def _wav(ruta: Path, frames: int = 160, sample_rate: int = 16000) -> None:
    with wave.open(str(ruta), "wb") as archivo:
        archivo.setnchannels(1)
        archivo.setsampwidth(2)
        archivo.setframerate(sample_rate)
        archivo.writeframes(struct.pack("<h", 1000) * frames)


def test_audio_completo_se_acondiciona_por_bloques_y_borra_el_temporal(tmp_path):
    original = tmp_path / "clase.wav"
    _wav(original, frames=48000, sample_rate=48000)
    contenido_original = original.read_bytes()

    with preparar_archivo_asr(original, segundos_bloque=0.2) as (
        procesado,
        diagnostico,
    ):
        procesado = Path(procesado)
        assert procesado != original
        assert procesado.is_file()
        with wave.open(str(procesado), "rb") as archivo:
            assert archivo.getnchannels() == 1
            assert archivo.getframerate() == 16000
            assert archivo.getnframes() > 0
        assert diagnostico["bloques"] > 1

    assert not procesado.exists()
    assert original.read_bytes() == contenido_original


def test_puerta_de_calidad_rechaza_una_perdida_clara_de_cobertura():
    directo = [
        SegmentoTranscrito(
            0,
            60,
            "La prostaciclina mantiene la vasodilatación renal y el flujo sanguíneo",
            "SPEAKER_00",
            "Docente",
        )
    ]
    definitiva = [
        SegmentoTranscrito(0, 8, "La prostaciclina", "SPEAKER_00", "Docente")
    ]

    decision = evaluar_versiones_transcripcion(directo, definitiva)

    assert decision["version_elegida"] == "directo"
    assert decision["ratio_palabras"] < 0.45


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
    assert dispositivo.sample_rate == 48000


def test_hardware_conserva_rutas_con_frecuencias_nativas_distintas(monkeypatch):
    class Predeterminado:
        device = (0, 9)

    class SoundDeviceFalso:
        default = Predeterminado()

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "Micrófono Realtek WASAPI",
                    "max_input_channels": 2,
                    "default_samplerate": 48000,
                    "hostapi": 0,
                },
                {
                    "name": "Micrófono Realtek MME",
                    "max_input_channels": 2,
                    "default_samplerate": 44100,
                    "hostapi": 1,
                },
            ]

        @staticmethod
        def query_hostapis():
            return [
                {"name": "Windows WASAPI", "default_input_device": 0},
                {"name": "MME", "default_input_device": 1},
            ]

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)

    dispositivos = GrabadorAudio.detectar_dispositivos_entrada(16000)

    assert [entrada.sample_rate for entrada in dispositivos] == [48000, 44100]


def test_hardware_pide_mono_antes_que_canales_crudos_del_array(monkeypatch):
    canales_probados = []

    class Predeterminado:
        device = (0, 9)

    class SoundDeviceFalso:
        default = Predeterminado()

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "Microphone Array (Realtek Audio)",
                    "max_input_channels": 4,
                    "default_samplerate": 48000,
                    "hostapi": 0,
                }
            ]

        @staticmethod
        def query_hostapis():
            return [{"name": "Windows WASAPI", "default_input_device": 0}]

        @staticmethod
        def check_input_settings(channels, **_kwargs):
            canales_probados.append(channels)

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)

    dispositivo = GrabadorAudio.detectar_dispositivo_entrada(16000)

    assert canales_probados == [1]
    assert dispositivo.canales == 1


def test_hardware_prefiere_wasapi_al_clon_mme_predeterminado(monkeypatch):
    class Predeterminado:
        device = (0, 9)

    class SoundDeviceFalso:
        default = Predeterminado()

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "Micrófono Realtek",
                    "max_input_channels": 2,
                    "default_samplerate": 48000,
                    "hostapi": 0,
                },
                {
                    "name": "Micrófono Realtek",
                    "max_input_channels": 2,
                    "default_samplerate": 48000,
                    "hostapi": 1,
                },
            ]

        @staticmethod
        def query_hostapis():
            return [
                {"name": "MME", "default_input_device": 0},
                {"name": "Windows WASAPI", "default_input_device": 1},
            ]

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)

    dispositivos = GrabadorAudio.detectar_dispositivos_entrada(
        16000, dispositivo_previo=0
    )

    assert [(entrada.indice, entrada.hostapi) for entrada in dispositivos] == [
        (1, "Windows WASAPI"),
        (0, "MME"),
    ]


def test_hardware_deja_asus_ai_noise_detras_del_microfono_fisico(monkeypatch):
    class Predeterminado:
        device = (0, 9)

    class SoundDeviceFalso:
        default = Predeterminado()

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "AI Noise-cancelling Input (ASUS)",
                    "max_input_channels": 2,
                    "default_samplerate": 44100,
                    "hostapi": 0,
                },
                {
                    "name": "Micrófono (Realtek(R) Audio)",
                    "max_input_channels": 2,
                    "default_samplerate": 48000,
                    "hostapi": 1,
                },
            ]

        @staticmethod
        def query_hostapis():
            return [
                {"name": "Windows WASAPI", "default_input_device": 0},
                {"name": "MME", "default_input_device": 1},
            ]

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)

    dispositivos = GrabadorAudio.detectar_dispositivos_entrada(16000, 0)

    assert [entrada.nombre for entrada in dispositivos] == [
        "Micrófono (Realtek(R) Audio)",
        "AI Noise-cancelling Input (ASUS)",
    ]


def test_hardware_no_recorta_el_microfono_real_despues_de_doce_rutas(monkeypatch):
    class Predeterminado:
        device = (0, 9)

    virtuales = [
        {
            "name": f"AI Noise-cancelling Input (ASUS) {indice}",
            "max_input_channels": 2,
            "default_samplerate": 44100,
            "hostapi": 0,
        }
        for indice in range(13)
    ]

    class SoundDeviceFalso:
        default = Predeterminado()

        @staticmethod
        def query_devices():
            return virtuales + [
                {
                    "name": "Micrófono (Realtek(R) Audio)",
                    "max_input_channels": 2,
                    "default_samplerate": 48000,
                    "hostapi": 1,
                }
            ]

        @staticmethod
        def query_hostapis():
            return [
                {"name": "Windows WASAPI", "default_input_device": 0},
                {"name": "MME", "default_input_device": 13},
            ]

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)

    dispositivos = GrabadorAudio.detectar_dispositivos_entrada(16000)

    assert len(dispositivos) == 14
    assert dispositivos[0].nombre == "Micrófono (Realtek(R) Audio)"


def test_hardware_excluye_mezcla_estereo_aunque_tenga_senal_y_host_preferido(
    monkeypatch,
):
    class Predeterminado:
        device = (0, 9)

    class SoundDeviceFalso:
        default = Predeterminado()

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "Mezcla estéreo (Realtek HD Audio Stereo input)",
                    "max_input_channels": 2,
                    "default_samplerate": 48000,
                    "hostapi": 0,
                },
                {
                    "name": "Micrófono (Realtek(R) Audio)",
                    "max_input_channels": 2,
                    "default_samplerate": 48000,
                    "hostapi": 1,
                },
            ]

        @staticmethod
        def query_hostapis():
            return [
                {"name": "Windows WDM-KS", "default_input_device": 0},
                {"name": "MME", "default_input_device": 1},
            ]

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)

    dispositivos = GrabadorAudio.detectar_dispositivos_entrada(16000, 0)

    assert [(entrada.indice, entrada.nombre) for entrada in dispositivos] == [
        (1, "Micrófono (Realtek(R) Audio)")
    ]


def test_hardware_no_acepta_loopback_como_unico_microfono(monkeypatch):
    class Predeterminado:
        device = (0, 9)

    class SoundDeviceFalso:
        default = Predeterminado()

        @staticmethod
        def query_devices():
            return [
                {
                    "name": "Stereo Mix (Realtek Audio)",
                    "max_input_channels": 2,
                    "default_samplerate": 48000,
                    "hostapi": 0,
                }
            ]

        @staticmethod
        def query_hostapis():
            return [{"name": "Windows WASAPI", "default_input_device": 0}]

        @staticmethod
        def check_input_settings(**_kwargs):
            return None

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)

    import pytest

    with pytest.raises(RuntimeError, match="micrófono"):
        GrabadorAudio.detectar_dispositivos_entrada()


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


def test_prueba_manual_informa_el_nivel_mientras_escucha():
    niveles = []

    class StreamFalso:
        def __init__(self, callback, **_kwargs):
            self.callback = callback

        def start(self):
            self.callback(
                np.full((100, 1), 2400, dtype=np.int16), 100, None, None
            )

        def stop(self):
            return None

        def close(self):
            return None

    class SoundDeviceFalso:
        InputStream = StreamFalso

    entrada = DispositivoEntrada(4, "Micrófono Realtek", 48000, 1, "WASAPI")

    nivel = GrabadorAudio.medir_senal(
        entrada,
        duracion=0.1,
        sd=SoundDeviceFalso,
        callback_nivel=niveles.append,
    )

    assert nivel >= UMBRAL_SENAL_UTIL
    assert niveles == [nivel]


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


def test_pausa_omite_audio_y_reanuda_el_mismo_wav(tmp_path, monkeypatch):
    streams = []

    class StreamFalso:
        def __init__(self, callback, **_kwargs):
            self.callback = callback
            streams.append(self)

        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            return None

    class SoundDeviceFalso:
        InputStream = StreamFalso

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)
    entrada = DispositivoEntrada(4, "Micrófono Realtek", 10, 1, "WASAPI")
    grabador = GrabadorAudio(sample_rate=10, dispositivo=4)

    assert grabador.iniciar(
        archivo_salida=str(tmp_path / "audio.wav"),
        candidatos_entrada=[entrada],
        duracion_fragmento=10,
    )
    callback = streams[0].callback
    callback(np.full((10, 1), 1000, dtype=np.int16), 10, None, None)
    assert grabador.pausar()
    callback(np.full((10, 1), 9000, dtype=np.int16), 10, None, None)
    assert grabador.esta_pausado()
    assert grabador.reanudar()
    callback(np.full((10, 1), 2000, dtype=np.int16), 10, None, None)
    grabador.detener()

    with wave.open(str(tmp_path / "audio.wav"), "rb") as archivo:
        muestras = np.frombuffer(archivo.readframes(100), dtype=np.int16)
    assert muestras.tolist() == [1000] * 10 + [2000] * 10


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
    monkeypatch.setattr(
        GrabadorAudio,
        "medir_senal",
        staticmethod(lambda entrada, duracion=0.35, sd=None: 0.0),
    )
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


def test_cambio_manual_reinicia_la_lista_despues_de_agotarla():
    aperturas = []

    class StreamFalso:
        def __init__(self, device, **_kwargs):
            aperturas.append(device)

        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            return None

    class SoundDeviceFalso:
        InputStream = StreamFalso

    entradas = [
        DispositivoEntrada(1, "Micrófono Realtek", 48000, 2, "WASAPI"),
        DispositivoEntrada(2, "AI Noise-cancelling Input (ASUS)", 44100, 2, "MME"),
    ]
    grabador = GrabadorAudio(sample_rate=48000, dispositivo=2)
    grabador.is_recording = True
    grabador._sd = SoundDeviceFalso
    grabador._candidatos_entrada = entradas
    grabador._indice_candidato = len(entradas) - 1

    assert grabador.probar_siguiente_entrada()

    assert aperturas == [1]
    assert grabador.dispositivo == 1
    grabador.is_recording = False
    grabador._cerrar_stream()


def test_seleccion_manual_abre_la_ruta_exacta_durante_la_grabacion():
    aperturas = []
    cambios = []

    class StreamFalso:
        def __init__(self, device, **_kwargs):
            aperturas.append(device)

        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            return None

    class SoundDeviceFalso:
        InputStream = StreamFalso

    entradas = [
        DispositivoEntrada(3, "AI Noise-cancelling Input", 48000, 1, "MME"),
        DispositivoEntrada(11, "Micrófono Realtek", 48000, 2, "WASAPI"),
        DispositivoEntrada(18, "Micrófono USB", 44100, 1, "WASAPI"),
    ]
    grabador = GrabadorAudio(sample_rate=48000, dispositivo=3)
    grabador.is_recording = True
    grabador._sd = SoundDeviceFalso
    grabador._callback_nivel = None
    grabador._candidatos_entrada = entradas
    grabador._dispositivo_activo = entradas[0]
    grabador._callback_dispositivo = lambda entrada, motivo: cambios.append(
        (entrada.indice, motivo)
    )

    assert grabador.seleccionar_entrada(18)

    assert aperturas == [18]
    assert grabador.dispositivo == 18
    assert grabador._indice_candidato == 2
    assert (18, "seleccion_manual") in cambios
    grabador.is_recording = False
    grabador._cerrar_stream()


def test_grabacion_puede_fijar_entrada_sin_rotacion_automatica(
    tmp_path, monkeypatch
):
    streams = []

    class StreamFalso:
        def __init__(self, device, **_kwargs):
            streams.append(device)

        def start(self):
            return None

        def stop(self):
            return None

        def close(self):
            return None

    class SoundDeviceFalso:
        InputStream = StreamFalso

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)
    entradas = [
        DispositivoEntrada(7, "Micrófono elegido", 48000, 1, "WASAPI"),
        DispositivoEntrada(8, "Otra entrada", 48000, 1, "MME"),
    ]
    grabador = GrabadorAudio(sample_rate=48000, dispositivo=7)

    assert grabador.iniciar(
        archivo_salida=str(tmp_path / "audio.wav"),
        candidatos_entrada=entradas,
        priorizar_senal_inicial=False,
        supervisar_entrada=False,
    )
    time.sleep(0.3)
    grabador.detener()

    assert streams == [7]


def test_prueba_real_descarta_el_mejor_puntuado_si_esta_mudo(
    tmp_path, monkeypatch
):
    aperturas = []

    class StreamFalso:
        def __init__(self, callback, device, samplerate, **_kwargs):
            self.callback = callback
            self.device = device
            self.samplerate = samplerate
            aperturas.append(device)

        def start(self):
            amplitud = 0 if self.device == 1 else 2400
            self.callback(
                np.full((int(self.samplerate * 0.1), 1), amplitud, dtype=np.int16),
                int(self.samplerate * 0.1),
                None,
                None,
            )

        def stop(self):
            return None

        def close(self):
            return None

    class SoundDeviceFalso:
        InputStream = StreamFalso

    monkeypatch.setattr(modulo_grabador, "_sounddevice", SoundDeviceFalso)
    entradas = [
        DispositivoEntrada(1, "Realtek WASAPI", 1000, 1, "Windows WASAPI"),
        DispositivoEntrada(2, "Realtek MME", 1000, 1, "MME"),
    ]
    grabador = GrabadorAudio(sample_rate=1000, dispositivo=1)

    assert grabador.iniciar(
        archivo_salida=str(tmp_path / "audio.wav"),
        candidatos_entrada=entradas,
        duracion_fragmento=10,
    )
    grabador.detener()

    assert aperturas[:3] == [1, 2, 2]
    assert grabador.dispositivo == 2
    assert grabador.pruebas_senal[0]["nivel"] == 0
    assert grabador.pruebas_senal[1]["nivel"] >= UMBRAL_SENAL_UTIL


def test_failover_admite_otra_frecuencia_y_normaliza_el_wav(tmp_path, monkeypatch):
    hay_senal = threading.Event()
    frecuencias_abiertas = []

    class StreamFalso:
        def __init__(self, callback, device, samplerate, **_kwargs):
            self.callback = callback
            self.device = device
            self.samplerate = samplerate
            frecuencias_abiertas.append((device, samplerate))

        def start(self):
            cantidad = int(self.samplerate)
            amplitud = 0 if self.device == 1 else 3000
            self.callback(
                np.full((cantidad, 1), amplitud, dtype=np.int16),
                cantidad,
                None,
                None,
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
    monkeypatch.setattr(
        GrabadorAudio,
        "medir_senal",
        staticmethod(lambda entrada, duracion=0.35, sd=None: 0.0),
    )
    entradas = [
        DispositivoEntrada(1, "Micrófono 10 Hz", 10, 1, "MME"),
        DispositivoEntrada(2, "Micrófono 20 Hz", 20, 1, "WASAPI"),
    ]
    grabador = GrabadorAudio(sample_rate=10, dispositivo=1)

    assert grabador.iniciar(
        archivo_salida=str(tmp_path / "audio.wav"),
        candidatos_entrada=entradas,
        segundos_sin_senal=0.25,
        duracion_fragmento=10,
    )
    assert hay_senal.wait(timeout=2)
    grabador.detener()

    assert frecuencias_abiertas == [(1, 10), (2, 20)]
    with wave.open(str(tmp_path / "audio.wav"), "rb") as archivo:
        assert archivo.getframerate() == 10
        muestras = np.frombuffer(archivo.readframes(100), dtype=np.int16)
    assert muestras[-10:].tolist() == [3000] * 10


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


def test_salida_descartada_se_registra_sin_borrar_el_audio(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Patología", "SDRA")
    fragmento_wav = carpeta / "fragmentos_audio" / "fragmento_000001.wav"
    _wav(fragmento_wav)

    class TranscriptorConDescarte:
        model_size = "small"
        dispositivo_real = "cpu"

        @staticmethod
        def transcribir_fragmento(_ruta):
            return []

        @staticmethod
        def consumir_descartes():
            return [
                {
                    "evento": "texto_descartado",
                    "ambito": "directo",
                    "texto": "frase inventada frase inventada",
                    "razon": "bucle de prueba",
                }
            ]

    incremental = TranscripcionIncremental(
        TranscriptorConDescarte(), repositorio, carpeta
    )
    incremental.encolar(FragmentoAudio(1, str(fragmento_wav), 0, 10))
    resultado = incremental.finalizar()

    registros = [
        json.loads(linea)
        for linea in (carpeta / "diagnostico_transcripcion.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert resultado.completa
    assert fragmento_wav.exists()
    assert registros[0]["evento"] == "texto_descartado"
    assert registros[0]["fragmento"] == 1
    assert registros[0]["razon"] == "bucle de prueba"


def test_finalizar_grabacion_registra_audio_completo(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Patología", "Shock")
    _wav(carpeta / "audio.wav", frames=25, sample_rate=10)

    repositorio.finalizar_grabacion(carpeta)

    ficha = json.loads((carpeta / "ficha.json").read_text(encoding="utf-8"))
    assert ficha["audio"] == "audio.wav"
    assert ficha["audio_guardado"] is True
    assert ficha["audio_duracion_segundos"] == 2.5
    assert ficha["audio_sample_rate"] == 10
    assert ficha["audio_bytes"] == (carpeta / "audio.wav").stat().st_size
    assert repositorio.obtener_audio_clase(carpeta) == carpeta / "audio.wav"


def test_pasada_final_usa_audio_completo_y_conserva_borrador_directo(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Patología", "Shock")
    _wav(carpeta / "audio.wav", frames=30, sample_rate=10)
    fragmento_wav = carpeta / "fragmentos_audio" / "fragmento_000001.wav"
    _wav(fragmento_wav)

    class TranscriptorFalso:
        @staticmethod
        def transcribir_fragmento(_ruta):
            return [
                SegmentoTranscrito(
                    0, 1, "El shock es una", "SPEAKER_00", "Docente"
                )
            ]

        @staticmethod
        def transcribir_archivo(
            ruta, callback_progreso=None, min_hablantes=2, max_hablantes=10
        ):
            assert ruta == str(carpeta / "audio.wav")
            assert (min_hablantes, max_hablantes) == (2, 4)
            if callback_progreso:
                callback_progreso("escuchando todo", 0.5)
            return [
                SegmentoTranscrito(
                    0,
                    3,
                    "El shock es una insuficiencia circulatoria aguda.",
                    "SPEAKER_00",
                    "Docente",
                )
            ]

    incremental = TranscripcionIncremental(
        TranscriptorFalso(),
        repositorio,
        carpeta,
        consolidar_audio_completo=True,
        min_hablantes=2,
        max_hablantes=4,
    )
    incremental.encolar(FragmentoAudio(1, str(fragmento_wav), 0, 1))
    resultado = incremental.finalizar()

    assert resultado.completa
    assert resultado.transcripcion_final
    assert "insuficiencia circulatoria aguda" in (
        carpeta / "transcripcion.txt"
    ).read_text(encoding="utf-8")
    assert "El shock es una" in (carpeta / "transcripcion_directo.txt").read_text(
        encoding="utf-8"
    )
    ficha = json.loads((carpeta / "ficha.json").read_text(encoding="utf-8"))
    assert ficha["transcripcion_final"] is True
    assert ficha["fuente_transcripcion"] == "audio_completo"


def test_fallo_pasada_final_conserva_texto_directo_y_marca_recuperacion(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Microbiología", "Virus")
    _wav(carpeta / "audio.wav", frames=20, sample_rate=10)
    fragmento_wav = carpeta / "fragmentos_audio" / "fragmento_000001.wav"
    _wav(fragmento_wav)

    class TranscriptorFalso:
        @staticmethod
        def transcribir_fragmento(_ruta):
            return [
                SegmentoTranscrito(0, 1, "Virus ARN", "SPEAKER_00", "Docente")
            ]

        @staticmethod
        def transcribir_archivo(*_args, **_kwargs):
            raise RuntimeError("modelo temporalmente ocupado")

    incremental = TranscripcionIncremental(
        TranscriptorFalso(),
        repositorio,
        carpeta,
        consolidar_audio_completo=True,
    )
    incremental.encolar(FragmentoAudio(1, str(fragmento_wav), 0, 1))
    resultado = incremental.finalizar()

    assert not resultado.completa
    assert not resultado.transcripcion_final
    assert "Virus ARN" in (carpeta / "transcripcion.txt").read_text(
        encoding="utf-8"
    )
    ficha = json.loads((carpeta / "ficha.json").read_text(encoding="utf-8"))
    assert ficha["estado_grabacion"] == "transcripcion_incompleta"
    assert ficha["transcripcion_final"] is False


def test_listar_clases_reconoce_audio_antiguo_sin_metadatos(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Microbiología", "Virus")
    _wav(carpeta / "audio.wav", frames=10, sample_rate=10)

    clase = repositorio.listar_clases()[0]

    assert clase["audio_disponible"] is True
    assert clase["audio_guardado"] is True
    assert clase["audio_duracion_segundos"] == 1.0


def test_importar_clase_copia_el_audio_y_no_depende_del_temporal(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    origen = tmp_path / "extraido_de_video.wav"
    _wav(origen, frames=30, sample_rate=10)

    carpeta = repositorio.guardar_clase(
        "Farmacología", "Antibióticos", [], str(origen)
    )
    origen.unlink()

    audio = repositorio.obtener_audio_clase(carpeta)
    assert audio == carpeta / "audio.wav"
    assert audio.exists()
    ficha = json.loads((carpeta / "ficha.json").read_text(encoding="utf-8"))
    assert ficha["audio_guardado"] is True
    assert ficha["audio_duracion_segundos"] == 3.0


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


def test_transcripcion_une_fragmentos_y_elimina_solapamiento_parcial(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Economía", "Trading")

    repositorio.guardar_transcripcion_fragmento(
        carpeta,
        1,
        0,
        10,
        [
            SegmentoTranscrito(
                1.0,
                9.8,
                "Te dicen que multiplicarás tus ahorros. Vas a vivir",
                "SPEAKER_00",
                "Docente",
            )
        ],
    )
    repositorio.guardar_transcripcion_fragmento(
        carpeta,
        2,
        9,
        19,
        [
            SegmentoTranscrito(
                9.1,
                18.0,
                "vas a vivir del trading cada mes.",
                "SPEAKER_00",
                "Docente",
            )
        ],
    )

    texto = (carpeta / "transcripcion.txt").read_text(encoding="utf-8")
    assert texto.count("Docente:") == 1
    assert texto.casefold().count("vas a vivir") == 1
    assert "Vas a vivir del trading cada mes." in texto


def test_clase_se_puede_renombrar_y_mover_a_papelera(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Microbiología", "Nombre provisional")
    (carpeta / "nota.txt").write_text("conservar", encoding="utf-8")

    renombrada = repositorio.renombrar_clase(carpeta, "Micobacterias")

    assert renombrada.name.endswith(" · Micobacterias")
    assert json.loads((renombrada / "ficha.json").read_text(encoding="utf-8"))[
        "titulo"
    ] == "Micobacterias"
    assert repositorio.listar_clases()[0]["ruta"] == str(renombrada)

    papelera = repositorio.eliminar_clase(renombrada)

    assert (papelera / "nota.txt").read_text(encoding="utf-8") == "conservar"
    assert not renombrada.exists()
    assert repositorio.listar_clases() == []
    assert "Papelera ARGOS" not in repositorio.materias()


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


def test_pasada_final_carga_turbo_sin_reemplazar_el_motor_directo(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Farmacología", "Prostaglandinas")
    _wav(carpeta / "audio.wav", frames=32000)
    fragmento = carpeta / "fragmentos_audio" / "fragmento_000001.wav"
    _wav(fragmento, frames=16000)
    cargas = []
    opciones_finales = []

    class MotorDirecto:
        model_size = "small"

        @staticmethod
        def transcribir_fragmento(_ruta):
            return [
                SegmentoTranscrito(
                    0,
                    1,
                    "La prostaciclina produce vasodilatación renal",
                    "SPEAKER_00",
                    "Docente",
                )
            ]

    class MotorFinal:
        model_size = "large-v3-turbo"

        @staticmethod
        def transcribir_archivo(_ruta, **opciones):
            opciones_finales.append(opciones)
            return [
                SegmentoTranscrito(
                    0,
                    2,
                    "La prostaciclina produce vasodilatación renal y conserva el filtrado",
                    "SPEAKER_00",
                    "Docente",
                )
            ]

    def crear(modelo, _progreso):
        cargas.append(modelo)
        return MotorFinal()

    directo = MotorDirecto()
    incremental = TranscripcionIncremental(
        directo,
        repositorio,
        carpeta,
        consolidar_audio_completo=True,
        modelo_final="large-v3-turbo",
        creador_transcriptor_final=crear,
    )
    incremental.encolar(FragmentoAudio(1, str(fragmento), 0, 1))
    resultado = incremental.finalizar()

    assert resultado.completa
    assert cargas == ["large-v3-turbo"]
    assert opciones_finales[0]["acondicionar_audio"] is True
    assert incremental.transcriptor is directo
    assert (carpeta / "transcripcion_directo.json").is_file()
    assert (carpeta / "transcripcion_definitiva.json").is_file()
    decision = json.loads(
        (carpeta / "decision_transcripcion.json").read_text(encoding="utf-8")
    )
    assert decision["modelo_usado"] == "large-v3-turbo"
    assert decision["version_elegida"] == "definitiva"


def test_version_rechazada_se_conserva_y_puede_activarse_manualmente(tmp_path):
    repositorio = RepositorioClases(str(tmp_path / "clases"))
    carpeta = repositorio.iniciar_grabacion("Fisiología", "COX")
    directo = [
        SegmentoTranscrito(
            0,
            60,
            "COX uno y COX dos originan prostanoides con efectos dependientes del tejido",
            "SPEAKER_00",
            "Docente",
        )
    ]
    definitiva = [
        SegmentoTranscrito(0, 5, "COX uno", "SPEAKER_00", "Docente")
    ]
    decision = evaluar_versiones_transcripcion(directo, definitiva)

    activa = repositorio.finalizar_grabacion(
        carpeta,
        segmentos_finales=definitiva,
        segmentos_directo=directo,
        decision_transcripcion=decision,
    )

    assert activa == directo
    assert "efectos dependientes" in (
        carpeta / "transcripcion.txt"
    ).read_text(encoding="utf-8")
    assert "COX uno" in (
        carpeta / "transcripcion_definitiva.txt"
    ).read_text(encoding="utf-8")

    restaurada = repositorio.activar_version_transcripcion(
        carpeta, "definitiva"
    )

    assert restaurada == definitiva
    ficha = json.loads((carpeta / "ficha.json").read_text(encoding="utf-8"))
    assert ficha["version_transcripcion_activa"] == "definitiva"
