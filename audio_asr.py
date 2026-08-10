"""Acondicionamiento ligero de voz antes de enviarla al motor ASR.

El WAV original de la clase nunca se modifica.  Los fragmentos de directo se
leen, se convierten a mono/16 kHz y se les aplica una ganancia limitada basada
en los tramos con actividad.  El objetivo es acercar la señal cruda de
PortAudio a la entrada que ofrecen los capturadores de voz profesionales sin
amplificar silencio digital ni ocultar el audio fuente.
"""
from __future__ import annotations

import math
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


FRECUENCIA_ASR = 16000
OBJETIVO_VOZ_DBFS = -22.0
GANANCIA_MAXIMA_DB = 22.0
UMBRAL_ACTIVIDAD_DBFS = -55.0


@dataclass(frozen=True)
class DiagnosticoAudioASR:
    procesado: bool
    rms_dbfs: float
    pico_dbfs: float
    rms_activo_dbfs: float
    ganancia_db: float
    sample_rate_origen: int
    sample_rate_asr: int

    def como_dict(self) -> dict[str, float | int | bool]:
        return {
            "procesado": self.procesado,
            "rms_dbfs": round(self.rms_dbfs, 2),
            "pico_dbfs": round(self.pico_dbfs, 2),
            "rms_activo_dbfs": round(self.rms_activo_dbfs, 2),
            "ganancia_db": round(self.ganancia_db, 2),
            "sample_rate_origen": self.sample_rate_origen,
            "sample_rate_asr": self.sample_rate_asr,
        }


def _dbfs(valor: float) -> float:
    return 20.0 * math.log10(max(float(valor), 1e-10))


def _rms(muestras: np.ndarray) -> float:
    if muestras.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(muestras, dtype=np.float64))))


def _rms_activo(muestras: np.ndarray, sample_rate: int) -> float:
    """Estima la energía de voz sin dejar que muchos silencios hundan el RMS."""
    tamano = max(1, int(sample_rate * 0.03))
    cantidad = muestras.size // tamano
    if cantidad <= 0:
        return _rms(muestras)
    bloques = muestras[: cantidad * tamano].reshape(cantidad, tamano)
    energias = np.sqrt(np.mean(np.square(bloques, dtype=np.float64), axis=1))
    umbral = 10.0 ** (UMBRAL_ACTIVIDAD_DBFS / 20.0)
    activos = energias[energias >= umbral]
    if activos.size == 0:
        return float(np.percentile(energias, 95)) if energias.size else 0.0
    # El percentil 75 sigue la voz y evita que un golpe aislado determine toda
    # la ganancia de un fragmento de diez segundos.
    return float(np.percentile(activos, 75))


def _remuestrear(muestras: np.ndarray, origen: int, destino: int) -> np.ndarray:
    if muestras.size == 0 or origen == destino:
        return np.ascontiguousarray(muestras, dtype=np.float32)
    datos = muestras.astype(np.float64, copy=False)
    if origen > destino:
        factor = max(2, int(round(origen / destino)))
        nucleo = np.full(factor, 1.0 / factor, dtype=np.float64)
        izquierda = (factor - 1) // 2
        derecha = factor - 1 - izquierda
        datos = np.convolve(
            np.pad(datos, (izquierda, derecha), mode="edge"),
            nucleo,
            mode="valid",
        )
    cantidad = max(1, int(round(datos.size * destino / origen)))
    salida = np.interp(
        np.linspace(0, datos.size - 1, cantidad, dtype=np.float64),
        np.arange(datos.size, dtype=np.float64),
        datos,
    )
    return np.ascontiguousarray(salida, dtype=np.float32)


def preparar_fragmento_asr(
    ruta: str | Path,
) -> tuple[str | np.ndarray, DiagnosticoAudioASR | None]:
    """Devuelve audio mono/16 kHz acondicionado o la ruta si no es PCM WAV."""
    ruta = str(ruta)
    try:
        with wave.open(ruta, "rb") as archivo:
            canales = archivo.getnchannels()
            ancho = archivo.getsampwidth()
            sample_rate = archivo.getframerate()
            frames = archivo.readframes(archivo.getnframes())
    except (OSError, EOFError, wave.Error):
        return ruta, None
    if ancho != 2 or canales < 1 or sample_rate <= 0 or not frames:
        return ruta, None

    enteras = np.frombuffer(frames, dtype="<i2")
    if enteras.size < canales:
        return ruta, None
    enteras = enteras[: enteras.size - (enteras.size % canales)]
    matriz = enteras.reshape(-1, canales).astype(np.float32)
    # La petición mono permite que Windows/driver entregue su mezcla procesada;
    # este promedio es la red de seguridad para WAV multicanal antiguos.
    muestras = matriz.mean(axis=1) / 32768.0
    muestras -= float(np.mean(muestras, dtype=np.float64))

    rms = _rms(muestras)
    pico = float(np.max(np.abs(muestras))) if muestras.size else 0.0
    activo = _rms_activo(muestras, sample_rate)
    umbral = 10.0 ** (UMBRAL_ACTIVIDAD_DBFS / 20.0)
    ganancia = 1.0
    if activo >= umbral:
        objetivo = 10.0 ** (OBJETIVO_VOZ_DBFS / 20.0)
        ganancia = min(
            objetivo / max(activo, 1e-10),
            10.0 ** (GANANCIA_MAXIMA_DB / 20.0),
        )
        ganancia = max(1.0, ganancia)

    acondicionadas = np.clip(muestras * ganancia, -0.98, 0.98)
    acondicionadas = _remuestrear(
        acondicionadas, sample_rate, FRECUENCIA_ASR
    )
    diagnostico = DiagnosticoAudioASR(
        procesado=True,
        rms_dbfs=_dbfs(rms),
        pico_dbfs=_dbfs(pico),
        rms_activo_dbfs=_dbfs(activo),
        ganancia_db=20.0 * math.log10(max(ganancia, 1e-10)),
        sample_rate_origen=sample_rate,
        sample_rate_asr=FRECUENCIA_ASR,
    )
    return acondicionadas, diagnostico
