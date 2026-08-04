from __future__ import annotations

import json
import os
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from correccion_medica import corregir_archivo_transcripcion
from enriquecedor_argos import enriquecer_clase_con_fuentes
from indice_sqlite import IndiceConocimientoSQLite
from material_estudio import generar_material_estudio
from pipeline_clase import analizar_clase_completa

CallbackProgreso = Callable[[str, float], None]


class ClaseEnProcesoError(RuntimeError):
    pass


class _BloqueoClase:
    """Bloqueo por archivo para impedir procesos simultáneos entre ventanas."""

    def __init__(self, carpeta: Path, caducidad_horas: int = 6):
        self.ruta = carpeta / ".argos_procesando.lock"
        self.caducidad = caducidad_horas * 3600
        self._descriptor: int | None = None
        self._token: str | None = None

    @staticmethod
    def _pid_activo(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        if os.name != "nt":
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            except PermissionError:
                return True
            except OSError:
                return False
            return True

        # En Windows OpenProcess permite comprobar existencia sin terminar ni
        # señalizar el proceso. Acceso denegado significa que el PID existe.
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return ctypes.windll.kernel32.GetLastError() != 87  # PID inexistente

    def _es_obsoleto(self) -> bool:
        try:
            antiguedad = max(0.0, time.time() - self.ruta.stat().st_mtime)
        except OSError:
            return False
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Un proceso puede caer entre O_EXCL y la escritura. El margen
            # evita retirar un fichero que todavía se está inicializando.
            return antiguedad > 60

        host = str(datos.get("host") or "")
        try:
            pid = int(datos.get("pid"))
        except (TypeError, ValueError):
            pid = 0
        if not host or host == socket.gethostname():
            return not self._pid_activo(pid)
        return antiguedad > self.caducidad

    def __enter__(self):
        for intento in range(2):
            try:
                self._descriptor = os.open(
                    self.ruta,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                self._token = uuid.uuid4().hex
                contenido = json.dumps(
                    {
                        "pid": os.getpid(),
                        "host": socket.gethostname(),
                        "inicio": datetime.now().isoformat(timespec="seconds"),
                        "token": self._token,
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                os.write(self._descriptor, contenido)
                os.fsync(self._descriptor)
                return self
            except FileExistsError as exc:
                if intento == 0 and self._es_obsoleto():
                    try:
                        self.ruta.unlink()
                    except OSError:
                        pass
                    continue
                raise ClaseEnProcesoError(
                    "Esta clase ya está siendo procesada por otra ventana de ARGOS."
                ) from exc
            except Exception:
                if self._descriptor is not None:
                    try:
                        os.close(self._descriptor)
                    except OSError:
                        pass
                    self._descriptor = None
                try:
                    self.ruta.unlink()
                except OSError:
                    pass
                raise
        raise ClaseEnProcesoError("No se pudo bloquear la clase.")

    def __exit__(self, exc_type, exc_value, traceback):
        if self._descriptor is not None:
            try:
                os.close(self._descriptor)
            except OSError:
                pass
            self._descriptor = None
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            if datos.get("token") == self._token:
                self.ruta.unlink()
        except (OSError, json.JSONDecodeError):
            pass


class OrquestadorArgos:
    """Única cadena autorizada para procesar o reprocesar una clase."""

    PASOS = (
        "correccion_medica",
        "analisis_clase",
        "material_estudio",
        "indice_fts5",
        "referencias_locales",
    )

    def __init__(self, indice: IndiceConocimientoSQLite):
        self.indice = indice

    def procesar_clase(
        self,
        carpeta: str | Path,
        callback: CallbackProgreso | None = None,
    ) -> dict:
        carpeta = Path(carpeta)
        if not carpeta.is_dir():
            raise FileNotFoundError(carpeta)

        estado = {
            "version": 1,
            "estado": "procesando",
            "inicio": datetime.now().isoformat(timespec="seconds"),
            "fin": None,
            "pasos": [],
            "error": None,
            "resultado": None,
        }

        with _BloqueoClase(carpeta):
            self._guardar_estado(carpeta, estado)
            try:
                correcciones = self._paso(
                    carpeta,
                    estado,
                    "correccion_medica",
                    "Revisando terminología médica...",
                    0.08,
                    corregir_archivo_transcripcion,
                    callback,
                )
                datos = self._paso(
                    carpeta,
                    estado,
                    "analisis_clase",
                    "Limpiando y segmentando la clase...",
                    0.30,
                    analizar_clase_completa,
                    callback,
                )
                material = self._paso(
                    carpeta,
                    estado,
                    "material_estudio",
                    "Generando apuntes, Word y flashcards...",
                    0.55,
                    generar_material_estudio,
                    callback,
                )
                indice = self._paso(
                    carpeta,
                    estado,
                    "indice_fts5",
                    "Actualizando el índice único...",
                    0.75,
                    lambda _carpeta: self.indice.reconstruir(),
                    callback,
                )
                enriquecido = self._paso(
                    carpeta,
                    estado,
                    "referencias_locales",
                    "Buscando referencias en la biblioteca...",
                    0.90,
                    lambda ruta: enriquecer_clase_con_fuentes(
                        ruta, indice=self.indice
                    ),
                    callback,
                )

                resultado = {
                    "bloques": len(datos.get("bloques", [])),
                    "avisos": len(datos.get("avisos_examen", [])),
                    "preguntas": len(datos.get("preguntas_profesor", [])),
                    "correcciones": correcciones.get("total_cambios", 0),
                    "flashcards": material.get("flashcards", 0),
                    "referencias": sum(
                        len(b.get("referencias_locales", []))
                        for b in enriquecido.get("bloques", [])
                    ),
                    "indice": indice,
                    "archivo_fuente": datos.get("archivo_fuente"),
                }
                estado["estado"] = "completado"
                estado["fin"] = datetime.now().isoformat(timespec="seconds")
                estado["resultado"] = resultado
                self._guardar_estado(carpeta, estado)
                if callback:
                    callback("Procesamiento completado.", 1.0)
                return resultado
            except Exception as exc:
                estado["estado"] = "error"
                estado["fin"] = datetime.now().isoformat(timespec="seconds")
                estado["error"] = {
                    "tipo": type(exc).__name__,
                    "mensaje": str(exc),
                }
                self._guardar_estado(carpeta, estado)
                raise

    def _paso(
        self,
        carpeta: Path,
        estado: dict,
        nombre: str,
        mensaje: str,
        progreso: float,
        funcion,
        callback: CallbackProgreso | None,
    ):
        if callback:
            callback(mensaje, progreso)
        registro = {
            "nombre": nombre,
            "estado": "procesando",
            "inicio": datetime.now().isoformat(timespec="seconds"),
            "fin": None,
            "error": None,
        }
        estado["pasos"].append(registro)
        self._guardar_estado(carpeta, estado)
        try:
            resultado = funcion(carpeta)
            registro["estado"] = "completado"
            registro["fin"] = datetime.now().isoformat(timespec="seconds")
            self._guardar_estado(carpeta, estado)
            return resultado
        except Exception as exc:
            registro["estado"] = "error"
            registro["fin"] = datetime.now().isoformat(timespec="seconds")
            registro["error"] = {
                "tipo": type(exc).__name__,
                "mensaje": str(exc),
            }
            self._guardar_estado(carpeta, estado)
            raise

    @staticmethod
    def _guardar_estado(carpeta: Path, estado: dict) -> None:
        destino = carpeta / "estado_argos.json"
        temporal = destino.with_suffix(".json.tmp")
        temporal.write_text(
            json.dumps(estado, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporal.replace(destino)
