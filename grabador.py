"""Grabación de audio eficiente para clases largas."""
from __future__ import annotations

import os
import queue
import struct
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np


def _sounddevice():
    """Carga PortAudio solo cuando se consulta o utiliza el micrófono."""
    import sounddevice

    return sounddevice


@dataclass(frozen=True)
class FragmentoAudio:
    indice: int
    ruta: str
    inicio: float
    fin: float


@dataclass(frozen=True)
class DispositivoEntrada:
    indice: int
    nombre: str
    sample_rate: int
    canales: int = 1
    hostapi: str = ""


def recuperar_audio_interrumpido(
    archivo_audio: str | Path,
    directorio_fragmentos: str | Path,
    sample_rate: int = 16000,
    duracion_fragmento: float = 10.0,
    solapamiento_fragmento: float = 1.0,
) -> int:
    """Repara el WAV propio de ARGOS y materializa fragmentos ausentes.

    ``wave`` actualiza el tamaño de la cabecera al cerrar. Ante una caída, los
    PCM escritos siguen detrás de la cabecera aunque esta declare menos datos.
    Esta función solo se aplica a WAV mono/int16 creados por ``GrabadorAudio``.
    """
    archivo_audio = Path(archivo_audio)
    directorio = Path(directorio_fragmentos)
    if not archivo_audio.exists() or archivo_audio.stat().st_size <= 44:
        return 0
    tamano = archivo_audio.stat().st_size
    with archivo_audio.open("r+b") as archivo:
        cabecera = archivo.read(12)
        if cabecera[:4] != b"RIFF" or cabecera[8:12] != b"WAVE":
            raise RuntimeError(
                f"El audio interrumpido no es un WAV de ARGOS: {archivo_audio}"
            )
        bytes_pcm = (tamano - 44) - ((tamano - 44) % 2)
        if bytes_pcm <= 0:
            return 0
        # El grabador propio siempre produce una cabecera PCM estándar de 44
        # bytes. Corregir solo sus contadores evita cargar una clase larga
        # completa en memoria durante la recuperación.
        archivo.seek(4)
        archivo.write(struct.pack("<I", 36 + bytes_pcm))
        archivo.seek(40)
        archivo.write(struct.pack("<I", bytes_pcm))
        archivo.truncate(44 + bytes_pcm)
        archivo.flush()
        os.fsync(archivo.fileno())

    if bytes_pcm <= 0:
        return 0

    directorio.mkdir(parents=True, exist_ok=True)
    bytes_por_fragmento = max(
        sample_rate * 2, int(sample_rate * duracion_fragmento) * 2
    )
    bytes_solapamiento = max(0, int(sample_rate * solapamiento_fragmento) * 2)
    avance = max(sample_rate * 2, bytes_por_fragmento - bytes_solapamiento)
    total = 0
    desplazamiento = 0
    with archivo_audio.open("rb") as origen:
        while desplazamiento < bytes_pcm:
            if total and bytes_pcm - desplazamiento <= bytes_solapamiento:
                break
            total += 1
            ruta = directorio / f"fragmento_{total:06d}.wav"
            if ruta.exists():
                desplazamiento += avance
                continue
            origen.seek(44 + desplazamiento)
            datos = origen.read(min(bytes_por_fragmento, bytes_pcm - desplazamiento))
            temporal = ruta.with_suffix(".wav.tmp")
            with temporal.open("wb") as archivo:
                with wave.open(archivo, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(datos)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(temporal, ruta)
            desplazamiento += avance
    return total


class GrabadorAudio:
    """Graba directamente a WAV para mantener estable el uso de memoria."""

    def __init__(self, sample_rate: int = 16000, dispositivo: Optional[int] = None):
        self.sample_rate = sample_rate
        self.dispositivo = dispositivo
        self.is_recording = False
        self.nivel_actual = 0.0
        self._tiempo_inicio = 0.0
        self._stream = None
        self._stream_lock = threading.Lock()
        self._generacion_stream = 0
        self._hilo_supervision = None
        self._candidatos_entrada: list[DispositivoEntrada] = []
        self._indice_candidato = 0
        self._dispositivo_activo: DispositivoEntrada | None = None
        self._callback_dispositivo = None
        self._nivel_maximo_dispositivo = 0.0
        self._inicio_dispositivo = 0.0
        self._canal_activo = 0
        self._wav = None
        self._archivo_salida: Optional[str] = None
        self._lock = threading.Lock()
        self._cola_fragmentos = None
        self._hilo_fragmentos = None
        self._directorio_fragmentos: Optional[Path] = None
        self._callback_fragmento = None
        self._frames_por_fragmento = self.sample_rate * 10
        self._frames_solapamiento = self.sample_rate
        self._buffer_fragmento = bytearray()
        self._frames_fragmento = 0
        self._frames_nuevos_fragmento = 0
        self._frames_totales = 0
        self._indice_fragmento = 0
        self.nivel_maximo = 0.0
        self.ultimo_error: Optional[str] = None

    @staticmethod
    def listar_dispositivos():
        dispositivos: list[tuple[int, str]] = []
        try:
            sd = _sounddevice()
            entrada_predeterminada = int(sd.default.device[0])
            entradas = [
                (i, dev["name"])
                for i, dev in enumerate(sd.query_devices())
                if dev["max_input_channels"] > 0
            ]
            # El asignador genérico de Windows no siempre apunta al micrófono
            # esperado. Priorizamos el dispositivo de entrada real configurado
            # en el sistema y conservamos su índice explícito.
            entradas.sort(key=lambda item: item[0] != entrada_predeterminada)
            for i, nombre in entradas:
                dispositivos.append((i, nombre))
        except Exception as exc:
            print(f"Error al listar dispositivos: {exc}")
        return dispositivos

    @staticmethod
    def detectar_dispositivo_entrada(
        sample_rate_preferido: int = 16000,
        dispositivo_previo: int | str | None = None,
    ) -> DispositivoEntrada:
        """Elige automáticamente una entrada real y compatible.

        Se prioriza la entrada predeterminada de Windows. Los asignadores
        virtuales genéricos quedan por detrás de un micrófono físico válido.
        """
        candidatos = GrabadorAudio.detectar_dispositivos_entrada(
            sample_rate_preferido, dispositivo_previo
        )
        return candidatos[0]

    @staticmethod
    def detectar_dispositivos_entrada(
        sample_rate_preferido: int = 16000,
        dispositivo_previo: int | str | None = None,
    ) -> list[DispositivoEntrada]:
        """Devuelve entradas compatibles ordenadas para permitir failover real.

        PortAudio expone a menudo el mismo micrófono de Windows mediante MME,
        DirectSound y WASAPI. Que una ruta acepte abrirse no garantiza que
        entregue muestras. Conservamos rutas alternativas para poder cambiar
        automáticamente si la primera permanece digitalmente muda.
        """
        sd = _sounddevice()
        dispositivos = list(sd.query_devices())
        try:
            predeterminado = int(sd.default.device[0])
        except (TypeError, ValueError, IndexError):
            predeterminado = -1
        try:
            previo = int(dispositivo_previo) if dispositivo_previo != "" else -1
        except (TypeError, ValueError):
            previo = -1

        predeterminados_host = set()
        nombres_host: dict[int, str] = {}
        try:
            for indice_host, host in enumerate(sd.query_hostapis()):
                indice = int(host.get("default_input_device", -1))
                if indice >= 0:
                    predeterminados_host.add(indice)
                nombres_host[indice_host] = str(host.get("name", ""))
        except Exception:
            pass

        genericos = (
            "sound mapper",
            "asignador de sonido",
            "primary sound capture",
            "controlador primario de captura",
        )
        candidatos = []
        for indice, datos in enumerate(dispositivos):
            if int(datos.get("max_input_channels", 0)) <= 0:
                continue
            nombre = str(datos.get("name", f"Entrada {indice}"))
            puntuacion = 0
            if indice == predeterminado:
                puntuacion += 1000
            if indice in predeterminados_host:
                puntuacion += 500
            if indice == previo:
                puntuacion += 250
            nombre_normalizado = nombre.casefold()
            if any(texto in nombre_normalizado for texto in genericos):
                puntuacion -= 700
            if "mic" in nombre_normalizado:
                puntuacion += 50

            try:
                indice_host = int(datos.get("hostapi", -1))
            except (TypeError, ValueError):
                indice_host = -1
            hostapi = nombres_host.get(indice_host, "")
            host_normalizado = hostapi.casefold()
            if "wasapi" in host_normalizado:
                puntuacion += 180
            elif "wdm" in host_normalizado:
                puntuacion += 120
            elif "directsound" in host_normalizado:
                puntuacion += 60

            rates = [sample_rate_preferido]
            rate_nativo = int(float(datos.get("default_samplerate", 0) or 0))
            if rate_nativo > 0 and rate_nativo not in rates:
                rates.append(rate_nativo)
            for rate in rates:
                max_canales = max(1, int(datos.get("max_input_channels", 1)))
                canales_a_probar = []
                for canales in (min(max_canales, 4), min(max_canales, 2), 1):
                    if canales not in canales_a_probar:
                        canales_a_probar.append(canales)
                compatible = None
                for canales in canales_a_probar:
                    try:
                        sd.check_input_settings(
                            device=indice,
                            channels=canales,
                            dtype="int16",
                            samplerate=rate,
                        )
                        compatible = canales
                        break
                    except Exception:
                        continue
                if compatible is not None:
                    candidatos.append(
                        (
                            puntuacion,
                            DispositivoEntrada(
                                indice, nombre, rate, compatible, hostapi
                            ),
                        )
                    )
                    break

        if not candidatos:
            raise RuntimeError(
                "Windows no ofrece ningún micrófono de entrada utilizable. "
                "Conecta o habilita uno y revisa el permiso de micrófono para ARGOS."
            )
        candidatos.sort(key=lambda item: item[0], reverse=True)
        ordenados = [item[1] for item in candidatos]
        frecuencia_principal = ordenados[0].sample_rate
        # El WAV debe mantener una sola frecuencia. Las rutas incompatibles
        # siguen siendo detectables, pero no pueden sustituirse a mitad de WAV.
        return [
            candidato
            for candidato in ordenados
            if candidato.sample_rate == frecuencia_principal
        ][:6]

    def iniciar(
        self,
        callback_nivel: Optional[Callable[[float], None]] = None,
        archivo_salida: str = "clase_temp.wav",
        directorio_fragmentos: str | None = None,
        callback_fragmento: Optional[Callable[[FragmentoAudio], None]] = None,
        candidatos_entrada: list[DispositivoEntrada] | None = None,
        callback_dispositivo: Optional[
            Callable[[DispositivoEntrada, str], None]
        ] = None,
        duracion_fragmento: float = 10.0,
        solapamiento_fragmento: float = 1.0,
        segundos_sin_senal: float = 4.0,
    ) -> bool:
        if self.is_recording:
            return False

        self.ultimo_error = None
        self._archivo_salida = os.path.abspath(archivo_salida)
        os.makedirs(os.path.dirname(self._archivo_salida), exist_ok=True)
        self._directorio_fragmentos = (
            Path(directorio_fragmentos).resolve()
            if directorio_fragmentos
            else Path(self._archivo_salida).with_name("fragmentos_audio")
        )
        self._directorio_fragmentos.mkdir(parents=True, exist_ok=True)
        self._callback_fragmento = callback_fragmento
        self._frames_por_fragmento = max(
            self.sample_rate, int(self.sample_rate * duracion_fragmento)
        )
        self._frames_solapamiento = min(
            self._frames_por_fragmento - 1,
            max(0, int(self.sample_rate * solapamiento_fragmento)),
        )
        self._buffer_fragmento = bytearray()
        self._frames_fragmento = 0
        self._frames_nuevos_fragmento = 0
        self._frames_totales = 0
        self._indice_fragmento = 0
        self.nivel_maximo = 0.0
        self._nivel_maximo_dispositivo = 0.0
        self._callback_dispositivo = callback_dispositivo
        self._candidatos_entrada = list(candidatos_entrada or [])
        if not self._candidatos_entrada:
            self._candidatos_entrada = [
                DispositivoEntrada(
                    int(self.dispositivo if self.dispositivo is not None else -1),
                    f"Entrada {self.dispositivo}",
                    self.sample_rate,
                )
            ]
        compatibles = [
            entrada
            for entrada in self._candidatos_entrada
            if entrada.sample_rate == self.sample_rate
        ]
        if compatibles:
            self._candidatos_entrada = compatibles
        indice_inicial = next(
            (
                i
                for i, entrada in enumerate(self._candidatos_entrada)
                if entrada.indice == self.dispositivo
            ),
            0,
        )
        if indice_inicial:
            self._candidatos_entrada.insert(
                0, self._candidatos_entrada.pop(indice_inicial)
            )
        self._indice_candidato = 0
        self._cola_fragmentos = queue.Queue()
        self._hilo_fragmentos = threading.Thread(
            target=self._consumir_fragmentos,
            daemon=True,
            name="argos-audio-fragmentos",
        )
        self._hilo_fragmentos.start()

        try:
            sd = _sounddevice()
            self._wav = wave.open(self._archivo_salida, "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(self.sample_rate)

            self.is_recording = True
            self._tiempo_inicio = time.time()
            self._abrir_stream(
                sd,
                self._candidatos_entrada[0],
                callback_nivel,
            )
            self._hilo_supervision = threading.Thread(
                target=self._supervisar_entrada,
                args=(sd, callback_nivel, max(0.25, segundos_sin_senal)),
                daemon=True,
                name="argos-supervision-microfono",
            )
            self._hilo_supervision.start()
            return True
        except Exception as exc:
            self.ultimo_error = str(exc)
            self.is_recording = False
            self._cerrar_recursos()
            self._finalizar_fragmentos()
            print(f"No se pudo iniciar la grabación: {exc}")
            return False

    def detener(self, archivo_salida: Optional[str] = None):
        if not self.is_recording:
            return None
        self.is_recording = False
        self._generacion_stream += 1
        self._cerrar_recursos()
        hilo = self._hilo_supervision
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(timeout=2)
        self._hilo_supervision = None
        self._finalizar_fragmentos()
        ruta = self._archivo_salida
        if not ruta or not os.path.exists(ruta) or os.path.getsize(ruta) <= 44:
            return None
        return ruta

    def _acumular_fragmento(self, datos: bytes, frames: int) -> None:
        """Se ejecuta bajo ``_lock`` y nunca realiza E/S de disco."""
        self._buffer_fragmento.extend(datos)
        self._frames_fragmento += frames
        self._frames_nuevos_fragmento += frames
        self._frames_totales += frames
        if self._frames_fragmento >= self._frames_por_fragmento:
            self._encolar_buffer_fragmento()

    @staticmethod
    def _canal_con_mas_senal(datos: np.ndarray) -> tuple[np.ndarray, int, float]:
        """Convierte cualquier entrada a mono conservando el canal con voz."""
        matriz = np.asarray(datos, dtype=np.int16)
        if matriz.ndim == 1:
            matriz = matriz.reshape(-1, 1)
        energias = np.sqrt(
            np.mean(matriz.astype(np.float64) ** 2, axis=0)
        )
        canal = int(np.argmax(energias)) if energias.size else 0
        mono = np.ascontiguousarray(matriz[:, canal], dtype=np.int16)
        nivel = float(energias[canal]) if energias.size else 0.0
        return mono, canal, nivel

    def _abrir_stream(self, sd, entrada, callback_nivel) -> None:
        with self._stream_lock:
            self._generacion_stream += 1
            generacion = self._generacion_stream
            self._dispositivo_activo = entrada
            self.dispositivo = entrada.indice
            self._nivel_maximo_dispositivo = 0.0
            self._inicio_dispositivo = time.monotonic()

            def callback(indata, frames, time_info, status):
                if status:
                    print(f"Aviso de audio: {status}")
                if not self.is_recording or generacion != self._generacion_stream:
                    return
                mono, canal, rms = self._canal_con_mas_senal(indata)
                self._canal_activo = canal
                datos = mono.tobytes()
                with self._lock:
                    if self._wav is not None:
                        self._wav.writeframesraw(datos)
                    self._acumular_fragmento(datos, len(mono))
                nivel = min(rms / 32768.0 * 5.0, 1.0)
                self.nivel_actual = nivel
                self.nivel_maximo = max(self.nivel_maximo, nivel)
                self._nivel_maximo_dispositivo = max(
                    self._nivel_maximo_dispositivo, nivel
                )
                if callback_nivel:
                    try:
                        callback_nivel(nivel)
                    except Exception:
                        pass

            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=entrada.canales,
                dtype="int16",
                device=entrada.indice,
                blocksize=max(256, int(self.sample_rate * 0.1)),
                callback=callback,
            )
            try:
                stream.start()
            except Exception:
                try:
                    stream.close()
                except Exception:
                    pass
                raise
            self._stream = stream
        self._avisar_dispositivo(entrada, "seleccionado")

    def _supervisar_entrada(self, sd, callback_nivel, espera: float) -> None:
        """Cambia de ruta PortAudio si Windows entrega silencio digital."""
        while self.is_recording:
            time.sleep(min(0.2, espera))
            if not self.is_recording:
                return
            transcurrido = time.monotonic() - self._inicio_dispositivo
            if self._nivel_maximo_dispositivo >= 0.002:
                return
            if transcurrido < espera:
                continue
            siguiente = self._indice_candidato + 1
            if siguiente >= len(self._candidatos_entrada):
                activo = self._dispositivo_activo
                if activo is not None:
                    self._avisar_dispositivo(activo, "sin_senal")
                return
            self._indice_candidato = siguiente
            entrada = self._candidatos_entrada[siguiente]
            self._cerrar_stream()
            if not self.is_recording:
                return
            try:
                self._abrir_stream(sd, entrada, callback_nivel)
                self._avisar_dispositivo(entrada, "cambio_automatico")
            except Exception as exc:
                self.ultimo_error = f"{entrada.nombre}: {exc}"
                self._inicio_dispositivo = 0.0

    def _avisar_dispositivo(self, entrada: DispositivoEntrada, motivo: str) -> None:
        if self._callback_dispositivo:
            try:
                self._callback_dispositivo(entrada, motivo)
            except Exception:
                pass

    def _cerrar_stream(self) -> None:
        with self._stream_lock:
            self._generacion_stream += 1
            stream, self._stream = self._stream, None
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _encolar_buffer_fragmento(self) -> None:
        if (
            not self._buffer_fragmento
            or not self._frames_nuevos_fragmento
            or self._cola_fragmentos is None
        ):
            return
        self._indice_fragmento += 1
        frames = self._frames_fragmento
        fin = self._frames_totales / self.sample_rate
        inicio = max(0.0, fin - frames / self.sample_rate)
        self._cola_fragmentos.put(
            (self._indice_fragmento, bytes(self._buffer_fragmento), inicio, fin)
        )
        bytes_solapamiento = self._frames_solapamiento * 2
        if bytes_solapamiento:
            self._buffer_fragmento = bytearray(
                self._buffer_fragmento[-bytes_solapamiento:]
            )
            self._frames_fragmento = self._frames_solapamiento
        else:
            self._buffer_fragmento.clear()
            self._frames_fragmento = 0
        self._frames_nuevos_fragmento = 0

    def _consumir_fragmentos(self) -> None:
        while self._cola_fragmentos is not None:
            trabajo = self._cola_fragmentos.get()
            if trabajo is None:
                self._cola_fragmentos.task_done()
                return
            indice, datos, inicio, fin = trabajo
            try:
                fragmento = self._guardar_fragmento(indice, datos, inicio, fin)
                if self._callback_fragmento:
                    self._callback_fragmento(fragmento)
            except Exception as exc:
                self.ultimo_error = f"No se pudo guardar un fragmento de audio: {exc}"
            finally:
                self._cola_fragmentos.task_done()

    def _guardar_fragmento(
        self, indice: int, datos: bytes, inicio: float, fin: float
    ) -> FragmentoAudio:
        assert self._directorio_fragmentos is not None
        ruta = self._directorio_fragmentos / f"fragmento_{indice:06d}.wav"
        temporal = ruta.with_suffix(".wav.tmp")
        with temporal.open("wb") as bruto:
            with wave.open(bruto, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(datos)
            bruto.flush()
            os.fsync(bruto.fileno())
        os.replace(temporal, ruta)
        return FragmentoAudio(indice, str(ruta), inicio, fin)

    def _finalizar_fragmentos(self) -> None:
        with self._lock:
            self._encolar_buffer_fragmento()
        cola, hilo = self._cola_fragmentos, self._hilo_fragmentos
        if cola is not None:
            cola.put(None)
        if hilo is not None and hilo is not threading.current_thread():
            hilo.join(timeout=30)
        self._hilo_fragmentos = None

    def _cerrar_recursos(self):
        # Detener el stream fuera del lock evita bloquearse si el callback está escribiendo.
        self._cerrar_stream()
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
