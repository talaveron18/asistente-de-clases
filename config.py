"""Configuración persistente y rutas seguras para la aplicación instalada."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AsistenteDeClases"
CONFIG_FILE = APP_DIR / "config.json"


class Config:
    def __init__(self):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.hf_token = ""
        self.whisper_model = "small"
        self.idioma = "es"
        self.sample_rate = 16000
        self.min_hablantes = 2
        self.max_hablantes = 10
        self.dispositivo_audio = ""
        self.usar_gpu = True
        self.ultima_materia = ""
        self._cargar()

    def _cargar(self):
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                for clave, valor in data.items():
                    if hasattr(self, clave):
                        setattr(self, clave, valor)
            except (json.JSONDecodeError, OSError):
                pass

    def guardar(self):
        data = {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
        try:
            CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except OSError:
            return False

    def validar(self):
        if self.hf_token and len(self.hf_token) < 10:
            return False, "El token de Hugging Face parece incompleto. Déjalo vacío para transcribir sin diarización."
        if self.whisper_model not in ["tiny", "base", "small", "medium", "large-v3", "large-v2"]:
            return False, "Modelo Whisper no válido."
        return True, "Configuración válida."

    def obtener_ruta_temp(self):
        return str(Path(tempfile.gettempdir()) / "asistente_clase_actual.wav")
