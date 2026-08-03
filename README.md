# Asistente de Clases

Aplicación local para grabar o importar clases, transcribirlas con Faster-Whisper y, opcionalmente, separar docente y alumnos con Pyannote.

## Estado

Primera versión funcional. La transcripción funciona sin token de Hugging Face. La diarización requiere un token y aceptar las condiciones del modelo de Pyannote.

## Requisitos

- Windows 10/11
- Python 3.10, 3.11 o 3.12
- FFmpeg en el PATH
- GPU NVIDIA opcional

## Instalación rápida

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

## GPU NVIDIA

Instala primero una versión de PyTorch compatible con tu controlador CUDA siguiendo el selector oficial de PyTorch. Después instala el resto de dependencias.

## Uso sin diarización

Deja vacío el token de Hugging Face. Whisper transcribirá normalmente y todos los segmentos aparecerán como `Docente`.

## Privacidad

El procesamiento es local. Los modelos se descargan la primera vez desde Hugging Face.

## Archivos

- `main.py`: interfaz gráfica.
- `grabador.py`: grabación directa a disco.
- `transcriptor.py`: Whisper y Pyannote.
- `config.py`: configuración local, excluida de Git.
