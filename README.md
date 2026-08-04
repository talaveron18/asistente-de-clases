# ARGOS

Aplicación local para grabar o importar clases de Medicina, transcribirlas, organizarlas y generar material de estudio con trazabilidad temporal y documental.

## Aplicación única

El punto de entrada distribuible es:

```text
argos_app.py
```

`main.py` conserva únicamente el núcleo reutilizable de grabación, transcripción, biblioteca y configuración. Ya no existen aplicaciones `main_v2.py`–`main_v7.py` ni una cadena de herencias sucesivas.

## Pipeline único

Toda clase nueva o reprocesada pasa por `OrquestadorArgos` y una sola cola:

```text
Audio o vídeo
→ Transcripción original
→ Corrección médica conservadora
→ Selección de transcripción vigente
→ Limpieza y división temática
→ Apuntes, Word, flashcards y preguntas
→ Actualización del índice SQLite FTS5
→ Referencias de la biblioteca local
```

Reglas:

- La corrección siempre parte de `transcripcion.txt`.
- `transcripcion_limpia.txt` es una salida y nunca vuelve a utilizarse como entrada.
- El pipeline, los apuntes, el índice y el chat utilizan `transcripcion_medica_revisada.txt` cuando está actualizada.
- Cada clase genera `estado_argos.json` con el resultado de cada etapa.
- Una cola dentro de la aplicación y un bloqueo en la carpeta impiden reprocesamientos simultáneos.

## Búsqueda única

El único motor de recuperación es:

```text
indice_sqlite.py · SQLite FTS5
```

`chat_argos.py` y `enriquecedor_argos.py` son consumidores de ese índice. No mantienen buscadores ni bases paralelas.

## Instalación para Windows

El usuario final solo necesita:

```text
ARGOS-Setup.exe
```

La cadena oficial de construcción es:

```text
argos_app.py
→ ARGOS.spec
→ installer.iss
→ release/ARGOS-Setup.exe
```

El instalador incluye ARGOS y FFmpeg. No requiere Python ni una instalación manual de FFmpeg.

El único workflow es:

```text
.github/workflows/windows-installer.yml
```

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

La diarización no forma parte del instalador básico: Pyannote, PyTorch y sus
dependencias solo se instalan en el entorno de desarrollo. El instalador
transcribe con Faster-Whisper y asigna una única voz docente.

## Privacidad

El contenido se procesa y almacena localmente. Los modelos de transcripción pueden descargarse la primera vez que se utilizan.

## Estado

ARGOS continúa en fase alfa. El instalador solo debe considerarse validado después de que el workflow finalice correctamente y `ARGOS-Setup.exe` se pruebe en un equipo Windows limpio.
