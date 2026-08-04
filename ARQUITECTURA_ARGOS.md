# Arquitectura de ARGOS

## Alcance actual

1. Clases de Medicina.
2. Reuniones en una fase posterior.

La prioridad es estabilizar el flujo completo de clases antes de ampliar funciones.

## Componentes

### Núcleo de captura

- `main.py`: interfaz base, grabación, importación multimedia, biblioteca y configuración.
- `grabador.py`: grabación directa a WAV.
- `transcriptor.py`: Faster-Whisper y diarización opcional.
- `media_utils.py`: preparación de audio y vídeo.
- `repositorio.py`: archivo de clases.

### Pipeline de clase

- `argos_app.py`: punto de entrada y cola única.
- `orquestador.py`: única cadena autorizada de postprocesamiento.
- `transcripciones.py`: selección de original o revisión vigente.
- `correccion_medica.py`: revisión conservadora desde el original.
- `pipeline_clase.py`: limpieza, segmentación, hallazgos e índice temporal.
- `material_estudio.py`: Word, flashcards y preguntas.
- `enriquecedor_argos.py`: referencias documentales sin índice propio.

### Conocimiento local

- `biblioteca_medica.py`: importación y catálogo.
- `extractor_documentos.py`: extracción por página.
- `indice_sqlite.py`: único motor de recuperación FTS5.
- `chat_argos.py`: presentación extractiva de resultados del FTS5.

## Flujo secuencial

```text
transcripcion.txt
      ↓
correccion_medica.py
      ↓
transcripcion_medica_revisada.txt
      ↓
transcripciones.fuente_vigente()
      ↓
pipeline_clase.py
      ↓
material_estudio.py
      ↓
indice_sqlite.py
      ↓
enriquecedor_argos.py
```

`transcripcion_limpia.txt` es siempre una salida. No puede alimentar correcciones ni futuros reprocesamientos.

## Concurrencia

- Solo puede existir una instancia de ARGOS por usuario y, por tanto, una sola cola.
- Las clases y las reconstrucciones manuales de FTS5 pasan por esa misma cola.
- `orquestador.py` crea `.argos_procesando.lock` dentro de cada clase.
- Una segunda apertura muestra un aviso y no crea otra ventana ni otra cola.
- Los bloqueos incorporan identidad de proceso para detectar PID reutilizados.
- `biblioteca_medica.py` serializa las operaciones que modifican su catálogo.
- Cada etapa actualiza `estado_argos.json` mediante escritura atómica.
- Los estados `procesando` huérfanos se convierten en errores reprocesables al reiniciar.
- No existe sondeo de `pipeline_clase.json` ni espera silenciosa por aparición de archivos.

## Trazabilidad

Toda respuesta futura deberá distinguir:

- contenido de clase original o revisado;
- contenido de apuntes;
- contenido de tratados o artículos;
- inferencias generadas por IA.

Las clases conservan minuto. Los documentos conservan archivo y página.

## Búsqueda

SQLite FTS5 es el único motor. El chat y el enriquecedor son consumidores del mismo índice y del mismo contrato de resultados.

## Instalador

```text
argos_app.py → ARGOS.spec → installer.iss → ARGOS-Setup.exe
```

Los modelos se descargan en el primer uso para evitar un instalador de varios gigabytes.
