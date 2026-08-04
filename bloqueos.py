"""Bloqueos de archivo recuperables entre procesos de ARGOS."""
from __future__ import annotations

import json
import os
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path


class BloqueoOcupadoError(RuntimeError):
    """La operación ya está protegida por otro proceso vivo."""


def _identidad_proceso(pid: int) -> str | None:
    """Devuelve una identidad estable que detecta la reutilización de un PID."""
    if pid <= 0:
        return None

    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        acceso_consulta = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(acceso_consulta, False, pid)
        if not handle:
            return None
        try:
            creado = wintypes.FILETIME()
            salida = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            usuario = wintypes.FILETIME()
            correcto = kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creado),
                ctypes.byref(salida),
                ctypes.byref(kernel),
                ctypes.byref(usuario),
            )
            if not correcto:
                return None
            valor = (creado.dwHighDateTime << 32) | creado.dwLowDateTime
            return f"windows:{valor}"
        finally:
            kernel32.CloseHandle(handle)

    stat = Path(f"/proc/{pid}/stat")
    try:
        contenido = stat.read_text(encoding="utf-8")
        # El nombre del proceso puede contener espacios y paréntesis. Los
        # campos posteriores empiezan justo después del último paréntesis.
        campos = contenido[contenido.rfind(")") + 2 :].split()
        return f"proc:{campos[19]}"  # Campo 22 de proc(5): starttime.
    except (OSError, IndexError):
        return None


def _pid_activo(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        acceso_consulta = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(acceso_consulta, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        # ERROR_INVALID_PARAMETER identifica un PID inexistente. Un acceso
        # denegado significa que el proceso sí existe.
        return ctypes.get_last_error() != 87
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class BloqueoArchivo:
    """Exclusión mutua atómica con recuperación tras cierres inesperados."""

    def __init__(
        self,
        ruta: str | Path,
        *,
        caducidad_horas: int = 6,
        esperar_segundos: float = 0,
        mensaje_ocupado: str = "La operación ya se está ejecutando.",
    ):
        self.ruta = Path(ruta)
        self.caducidad = caducidad_horas * 3600
        self.esperar_segundos = max(0.0, esperar_segundos)
        self.mensaje_ocupado = mensaje_ocupado
        self._descriptor: int | None = None
        self._token: str | None = None

    def _es_obsoleto(self) -> bool:
        try:
            antiguedad = max(0.0, time.time() - self.ruta.stat().st_mtime)
        except OSError:
            return False
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return antiguedad > 60

        host = str(datos.get("host") or "")
        try:
            pid = int(datos.get("pid"))
        except (TypeError, ValueError):
            pid = 0

        if host and host != socket.gethostname():
            return antiguedad > self.caducidad
        if not _pid_activo(pid):
            return True

        identidad_guardada = str(datos.get("pid_inicio") or "")
        identidad_actual = _identidad_proceso(pid)
        if identidad_guardada and identidad_actual:
            return identidad_guardada != identidad_actual

        # Compatibilidad con locks creados por versiones anteriores. Solo en
        # ellos se usa la edad como último recurso frente a un PID reutilizado.
        return not identidad_guardada and antiguedad > self.caducidad

    def esta_activo(self) -> bool:
        return self.ruta.exists() and not self._es_obsoleto()

    def __enter__(self):
        limite = time.monotonic() + self.esperar_segundos
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self._descriptor = os.open(
                    self.ruta,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                self._token = uuid.uuid4().hex
                contenido = json.dumps(
                    {
                        "pid": os.getpid(),
                        "pid_inicio": _identidad_proceso(os.getpid()),
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
                if self._es_obsoleto():
                    try:
                        self.ruta.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() < limite:
                    time.sleep(0.05)
                    continue
                raise BloqueoOcupadoError(self.mensaje_ocupado) from exc
            except Exception:
                self._limpiar_descriptor()
                try:
                    self.ruta.unlink()
                except OSError:
                    pass
                raise

    def _limpiar_descriptor(self) -> None:
        if self._descriptor is not None:
            try:
                os.close(self._descriptor)
            except OSError:
                pass
            self._descriptor = None

    def __exit__(self, exc_type, exc_value, traceback):
        self._limpiar_descriptor()
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            if datos.get("token") == self._token:
                self.ruta.unlink()
        except (OSError, json.JSONDecodeError):
            pass
