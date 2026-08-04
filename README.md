# ARGOS

Aplicación local para grabar o importar clases de Medicina, transcribirlas, organizarlas y generar material de estudio con trazabilidad temporal y documental.

## Aplicación única

El único punto de entrada es:

```text
argos_app.py
```

`main.py` contiene el núcleo reutilizable de grabación, transcripción, biblioteca y configuración. Ya no existen `main_v2.py`, `main_v3.py` ni versiones heredadas sucesivas.

## Flujo de una clase

```text
Audio o vídeo
→ Transcripción
→ Organización por materia
→ Limpieza y división temática
→ Corrección médica auditable
→ Apuntes y Word
→ Flashcards y preguntas
→ Referencias de la biblioteca local
→ Índice SQLite FTS5
```

## Instalación para Windows

El usuario final solo necesita un archivo:

```text
ARGOS-Setup.exe
```

El instalador incluye ARGOS y FFmpeg. No requiere Python ni una instalación manual de FFmpeg.

La cadena oficial de construcción es única:

```text
argos_app.py
→ ARGOS.spec
→ installer.iss
→ release/ARGOS-Setup.exe
```

El único workflow es:

```text
.github/workflows/windows-installer.yml
```

Cuando se ejecute correctamente en la rama `main`, publicará el instalador como artefacto y como Release `latest`.

## Ejecución desde el código fuente

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python argos_app.py
```

También puede utilizarse `EJECUTAR.bat`.

## Funciones actuales

- Grabación directa a WAV sin acumular la clase completa en memoria.
- Faster-Whisper con GPU opcional y retorno a CPU.
- Diarización opcional mediante Pyannote cuando se instala y configura.
- Importación de audio y vídeo largo.
- Archivo local por materia, fecha y número.
- Biblioteca médica para PDF, DOCX, TXT y Markdown.
- Extracción de PDF por página y detección de documentos que requieren OCR.
- Índice SQLite FTS5 para clases y documentos.
- Chat documental con referencias a página o minuto.
- Apuntes Markdown y Word.
- Flashcards TSV y preguntas de repaso.
- Corrección médica mediante glosario explícito y registro de cambios.

## Privacidad

El contenido se procesa y almacena localmente. Los modelos de transcripción pueden descargarse la primera vez que se utilizan.

## Estado

ARGOS continúa en fase alfa. El instalador debe considerarse validado únicamente después de que el workflow finalice correctamente y el `ARGOS-Setup.exe` se pruebe en un equipo Windows limpio.
