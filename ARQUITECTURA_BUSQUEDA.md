# Búsqueda y trazabilidad en ARGOS

## Alcance actual

El buscador literal recorre dos fuentes locales:

1. Clases transcritas: `transcripcion.txt` + `ficha.json`.
2. Biblioteca médica: índice documental + extracción JSON por páginas.

## Referencias devueltas

- Clase: materia, título y marca temporal.
- Documento: categoría, nombre y página.
- Todos los resultados conservan la ruta de la fuente original.

## Reglas

- No se buscan PDFs marcados como `requiere_ocr`.
- No se inventan coincidencias semánticas.
- La frase exacta tiene más peso que palabras aisladas.
- El buscador semántico futuro deberá mantener estas referencias.
- El chat ARGOS no podrá responder desde una fuente sin adjuntar página o minuto cuando exista.

## Próxima capa

1. Índice SQLite FTS5 para grandes bibliotecas.
2. Fragmentación por secciones y párrafos.
3. Embeddings locales opcionales.
4. Respuestas ARGOS con citas y separación entre clase, tratado, apuntes e inferencia.
