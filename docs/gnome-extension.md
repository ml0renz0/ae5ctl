# ae5ctl — Extensión GNOME Shell 46

## Componentes

- gnome/ae5ctl@ml0renz0.github.io/extension.js — integración Quick Settings.
- alsa.js — procesos GJS asíncronos con límite temporal y cancelación.
- alsa-logic.mjs — parser puro con tests Node.js de fixtures ALSA.
- tools/build_extension.py — crea ZIP reproducible sin Debian ni Python
  como runtime de usuario final.

## Gate físico

Antes de sustituir el programa antiguo, validar en GNOME 46: enable/disable,
visualización del indicador, detección de la AE-5 correcta, auriculares,
altavoces, cambios realizados por otros clientes, suspensión, reconexión
y recuperación ante errores.

Nunca confundir el selector físico ALSA con una ruta de PipeWire ni declarar
que se ha aplicado un preset por coincidencia de valores. Tampoco se
restauran automáticamente perfiles completos o ganancia/DSP.

## Distribución

La etiqueta de PR build-gnome activa la subida de un artefacto ZIP de 24 h.
En releases de versión se publica el mismo formato y el checksum.
El check CI required sigue siendo estable. La publicación en
extensions.gnome.org requiere licencia apropiada, revisión técnica y pruebas
reales adicionales.
