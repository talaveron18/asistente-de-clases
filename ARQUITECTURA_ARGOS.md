# Arquitectura de Asistente de Clases / ARGOS

## 1. Transcripción profesional

Pensada para reuniones, entrevistas, clases impartidas y cualquier grabación no académica.

Funciones:
- Grabar audio en directo.
- Importar audio o vídeo largo.
- Transcribir con marcas de tiempo.
- Diarización opcional.
- Exportar TXT, Markdown y SRT.
- Guardar por proyecto, cliente o evento.

Este espacio no debe mezclar automáticamente el contenido con la base médica.

## 2. Estudio médico

Pensado para construir una base de conocimiento personal por asignaturas.

Fuentes:
- Clases grabadas.
- Vídeos históricos.
- Apuntes propios.
- Exámenes y preguntas del profesor.
- Tratados y libros en PDF.
- Artículos y guías.

Estructura local:

```text
Documentos/Asistente de Clases/
├── Clases/
└── Biblioteca médica/
    ├── Tratados/
    ├── Apuntes/
    ├── Exámenes/
    ├── Artículos/
    └── Otros/
```

## Principio de trazabilidad

Toda respuesta futura del motor IA deberá distinguir claramente:
- contenido procedente de una clase;
- contenido procedente de apuntes;
- contenido procedente de un tratado o artículo;
- inferencias o explicaciones generadas por la IA.

Nunca se debe presentar una afirmación como procedente de un libro cuando no esté sustentada por ese documento.

## Fases

### Fase 1 — Repositorios locales
- Biblioteca de clases.
- Biblioteca médica.
- Importación de PDF, DOCX, TXT y Markdown.
- Índice de archivos y detección de duplicados.

### Fase 2 — Extracción documental
- Lectura de PDFs con texto.
- OCR opcional para PDFs escaneados.
- División por capítulos, páginas y bloques.
- Conservación de página y fuente.

### Fase 3 — Buscador inteligente
- Búsqueda literal.
- Búsqueda semántica.
- Resultados con fuente, página y minuto.

### Fase 4 — ARGOS IA
- Apuntes estructurados.
- Resúmenes por bloques.
- Preguntas del profesor.
- Conceptos señalados como importantes.
- Flashcards y exámenes.
- Comparación entre clase, apuntes y tratados.

### Fase 5 — Chat con conocimiento
- Respuestas fundamentadas en las fuentes seleccionadas.
- Citas a página, archivo y minuto.
- Elección de alcance: una clase, una materia o toda la biblioteca.

## Instalador

El usuario debe recibir un único `Asistente-de-Clases-Setup.exe`.
La instalación crea accesos directos y las carpetas de datos en Documentos. Los modelos se descargan en el primer uso para evitar un instalador de varios gigabytes.
