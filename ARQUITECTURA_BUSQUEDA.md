# Búsqueda y trazabilidad en ARGOS

## Motor único

ARGOS utiliza exclusivamente `indice_sqlite.py` y SQLite FTS5 para recuperar conocimiento local.

Se ha retirado el buscador literal paralelo. El chat y el enriquecedor de apuntes no mantienen índices propios: ambos son consumidores del mismo FTS5.

## Fuentes indexadas

1. Clases transcritas: se seleccionan mediante `transcripciones.fuente_vigente()`.
   - Se usa `transcripcion_medica_revisada.txt` cuando está actualizada.
   - En caso contrario se usa `transcripcion.txt`.
   - `transcripcion_limpia.txt` nunca se utiliza como entrada.
2. Biblioteca médica: índice documental y extracción JSON por páginas.

## Referencias devueltas

- Clase: materia, título, marca temporal y procedencia original/revisión médica.
- Documento: categoría, nombre y página.
- Todos los resultados conservan la ruta de la fuente original.

## Reglas

- No se indexan PDFs marcados como `requiere_ocr`.
- No se inventan coincidencias semánticas.
- La consulta FTS5 incluye la frase completa y sus términos para priorizar coincidencias próximas sin perder recuperación.
- El chat extractivo no responde sin adjuntar sus fuentes.
- El enriquecedor solo busca en `Biblioteca médica` y conserva documento y página.
- Una futura búsqueda semántica deberá ser una capa sobre FTS5, no un índice paralelo con otro contrato de resultados.

## Flujo

```text
transcripción vigente / documentos extraídos
                ↓
       indice_sqlite.py (FTS5)
          ↙             ↘
  chat_argos.py   enriquecedor_argos.py
```
