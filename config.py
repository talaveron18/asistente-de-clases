"""
Configuracion del Asistente de Clases.
Gestiona la configuracion persistente en un archivo JSON.
La GUI lee y escribe esta configuracion automaticamente.
"""

import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "hf_token": "",
    "whisper_model": "medium",
    "idioma": "es",
    "sample_rate": 16000,
    "temp_file": "clase_temp.wav",
    "min_hablantes": 2,
    "max_hablantes": 10,
    "dispositivo_audio": "",
    "usar_gpu": True,
}


class Config:
    """Gestiona la configuracion del programa."""

    def __init__(self):
        self.hf_token = ""
        self.whisper_model = "medium"
        self.idioma = "es"
        self.sample_rate = 16000
        self.temp_file = "clase_temp.wav"
        self.min_hablantes = 2
        self.max_hablantes = 10
        self.dispositivo_audio = ""
        self.usar_gpu = True
        self._cargar()

    def _cargar(self):
        """Carga la configuracion desde el archivo JSON si existe."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for clave, valor in data.items():
                    if hasattr(self, clave):
                        setattr(self, clave, valor)
                print("Configuracion cargada desde config.json")
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error al cargar configuracion: {e}. Usando valores por defecto.")
        else:
            print("No se encontro config.json. Usando valores por defecto.")

    def guardar(self):
        """Guarda la configuracion actual en el archivo JSON."""
        data = {
            "hf_token": self.hf_token,
            "whisper_model": self.whisper_model,
            "idioma": self.idioma,
            "sample_rate": self.sample_rate,
            "temp_file": self.temp_file,
            "min_hablantes": self.min_hablantes,
            "max_hablantes": self.max_hablantes,
            "dispositivo_audio": self.dispositivo_audio,
            "usar_gpu": self.usar_gpu,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print("Configuracion guardada en config.json")
            return True
        except IOError as e:
            print(f"Error al guardar configuracion: {e}")
            return False

    def validar(self):
        """Valida que la configuracion es correcta. Devuelve (es_valida, mensaje)."""
        if self.hf_token and len(self.hf_token) < 10:
            return False, "El token de HuggingFace parece incompleto. Déjalo vacío para transcribir sin diarización."
        modelos_validos = ["tiny", "base", "small", "medium", "large-v3", "large-v2"]
        if self.whisper_model not in modelos_validos:
            return False, f"Modelo Whisper no valido. Opciones: {', '.join(modelos_validos)}"
        return True, "Configuracion valida."

    def obtener_ruta_temp(self):
        """Devuelve la ruta completa al archivo temporal de audio."""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), self.temp_file)

    def __repr__(self):
        estado_gpu = "GPU (Nvidia)" if self.usar_gpu else "CPU"
        modelo_masked = self.hf_token[:8] + "..." if self.hf_token else "(no configurado)"
        return (
            f"Config(modelo={self.whisper_model}, idioma={self.idioma}, "
            f"gpu={estado_gpu}, hf_token={modelo_masked})"
        )
