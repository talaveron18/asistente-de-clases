# Interfaz ARGOS 0.7

## Criterio

ARGOS utiliza patrones generales de producto habituales en aplicaciones de
productividad: navegación lateral, barra de estado persistente, composición por
tarjetas y una ficha por elemento. La ejecución es propia y no reproduce marca,
textos, ilustraciones, código, colores, proporciones ni jerarquía literal de
ningún producto de referencia.

## Recorrido principal

1. **Inicio**: elegir entre grabar una clase o importar un archivo y recuperar
   rápidamente las clases recientes.
2. **Grabar clase**: indicar materia y título, comprobar la entrada detectada,
   vigilar la señal y leer la transcripción en directo.
3. **Importar archivo**: transcribir audios y vídeos existentes.
4. **Mis clases**: buscar y abrir clases dentro de ARGOS.
5. **Ficha de clase**: consultar resumen, apuntes, transcripción revisada,
   preguntas y tarjetas sin abrir archivos manualmente.
6. **Biblioteca**: gestionar fuentes médicas locales.
7. **Preguntar a ARGOS**: consultar la memoria local manteniendo visibles las
   fuentes de cada respuesta.
8. **Estado y procesos**: actualizar una clase o la memoria sin exponer nombres
   técnicos de la implementación.

## Grabación persistente

El estado, el cronómetro y el botón **Detener y guardar** permanecen en la barra
superior al cambiar de sección. La navegación no detiene la captura ni modifica
la cola de transcripción incremental.

## Identidad visual

- Fondo azul noche y paneles azul pizarra.
- Acento azul para acciones normales.
- Rojo coral reservado para grabar y detener.
- Verde para estados correctos y ámbar para trabajos pendientes.
- Marca tipográfica ARGOS sin mascota ni recursos visuales ajenos.

## Validación de publicación

Toda versión instalable debe superar las pruebas automatizadas, el empaquetado,
la carga real de Faster-Whisper y el ciclo de instalación y desinstalación en
Windows antes de entregarse al usuario.
