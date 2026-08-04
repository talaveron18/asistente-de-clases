"""Grabación de audio eficiente para clases largas."""
from __future__ import annotations

import os
import threading
import time
import wave
from typing import Callable, Optional

import numpy as np


def _sounddevice():
    """Carga PortAudio solo cuando se consulta o utiliza el micrófono."""
    import sounddevice

    return sounddevice


class GrabadorAudio:
    """Graba directamente a WAV para mantener estable el uso de memoria."""

    def __init__(self, sample_rate: int = 16000, dispositivo: Optional[int] = None):
        self.sample_rate = sample_rate
        self.dispositivo = dispositivo
        self.is_recording = False
        self.nivel_actual = 0.0
        self._tiempo_inicio = 0.0
        self._stream = None
        self._wav = None
        self._archivo_salida: Optional[str] = None
        self._lock = threading.Lock()
        self.ultimo_error: Optional[str] = None

    @staticmethod
    def listar_dispositivos():
        dispositivos = []
        try:
            sd = _sounddevice()
            for i, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0:
                    dispositivos.append((i, dev["name"]))
        except Exception as exc:
            print(f"Error al listar dispositivos: {exc}")
        return dispositivos

    def iniciar(
        self,
        callback_nivel: Optional[Callable[[float], None]] = None,
        archivo_salida: str = "clase_temp.wav",
    ) -> bool:
        if self.is_recording:
            return False

        self.ultimo_error = None
        self._archivo_salida = os.path.abspath(archivo_salida)
        os.makedirs(os.path.dirname(self._archivo_salida), exist_ok=True)

        try:
            sd = _sounddevice()
            self._wav = wave.open(self._archivo_salida, "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(self.sample_rate)

            def callback(indata, frames, time_info, status):
                if status:
                    print(f"Aviso de audio: {status}")
                if not self.is_recording:
                    return
                datos = np.asarray(indata, dtype=np.int16)
                with self._lock:
                    if self._wav is not None:
                        self._wav.writeframesraw(datos.tobytes())
                nivel = float(np.sqrt(np.mean(datos.astype(np.float64) ** 2)))
                self.nivel_actual = min(nivel / 32768.0 * 5.0, 1.0)
                if callback_nivel:
                    try:
                        callback_nivel(self.nivel_actual)
                    except Exception:
                        pass

            self.is_recording = True
            self._tiempo_inicio = time.time()
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                device=self.dispositivo,
                blocksize=1600,
                callback=callback,
            )
            self._stream.start()
            return True
        except Exception as exc:
            self.ultimo_error = str(exc)
            self.is_recording = False
            self._cerrar_recursos()
            print(f"No se pudo iniciar la grabación: {exc}")
            return False

    def detener(self, archivo_salida: Optional[str] = None):
        if not self.is_recording:
            return None
        self.is_recording = False
        self._cerrar_recursos()
        ruta = self._archivo_salida
        if not ruta or not os.path.exists(ruta) or os.path.getsize(ruta) <= 44:
            return None
        return ruta

    def _cerrar_recursos(self):
        # Detener el stream fuera del lock evita bloquearse si el callback está escribiendo.
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            wav_file, self._wav = self._wav, None
            if wav_file is not None:
                try:
                    wav_file.close()
                except Exception:
                    pass

    def obtener_duracion(self):
        return time.time() - self._tiempo_inicio if self._tiempo_inicio else 0

    def esta_grabando(self):
        return self.is_recording

    def obtener_nivel(self):
        return self.nivel_actual
