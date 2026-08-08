import numpy as np

from grabador import GrabadorAudio


def _tono(frecuencia: float, sample_rate: int, duracion: float = 0.1) -> np.ndarray:
    tiempos = np.arange(round(sample_rate * duracion), dtype=np.float64) / sample_rate
    return np.rint(12000 * np.sin(2 * np.pi * frecuencia * tiempos)).astype(np.int16)


def _rms(muestras: np.ndarray) -> float:
    return float(np.sqrt(np.mean(muestras.astype(np.float64) ** 2)))


def test_remuestreo_conserva_tono_de_voz():
    original = _tono(440, 48000)

    resultado = GrabadorAudio._remuestrear_mono(original, 48000, 16000)

    assert _rms(resultado) >= _rms(original) * 0.95


def test_remuestreo_atenua_frecuencia_que_produciria_aliasing():
    original = _tono(14000, 48000)

    resultado = GrabadorAudio._remuestrear_mono(original, 48000, 16000)

    assert _rms(resultado) < _rms(original) / 3


def test_remuestreo_no_toca_audio_que_ya_esta_a_16_khz():
    original = _tono(440, 16000)

    resultado = GrabadorAudio._remuestrear_mono(original, 16000, 16000)

    np.testing.assert_array_equal(resultado, original)


def test_remuestreo_conserva_la_duracion():
    original = _tono(440, 48000, duracion=0.137)

    resultado = GrabadorAudio._remuestrear_mono(original, 48000, 16000)

    assert len(resultado) == round(len(original) * 16000 / 48000)
