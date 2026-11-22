# Plan de desarrollo

## Objetivo y evidencia disponible

Crear un motor ALSA con CLI que funcione sin escritorio y una bandeja gráfica
opcional. Debe distinguir la salida configurada, el último cambio solicitado y
un estado desconocido, y comprobar los resultados antes de anunciar un cambio
correcto.

El script original está conservado en `ae5-switcher.py`. Se han identificado
defectos de parsing, selección de controles, construcción de comandos y alcance
de restauración. Los ejemplos `Creative`, `Output Select`, `Headphone` y sus
índices no se consideran configuración confirmada de la tarjeta del usuario.

También se investigará el audio tras reanudar Ubuntu: después de una suspensión
deja de funcionar correctamente y se recupera al cambiar estéreo → 5.1 → estéreo
en Ajustes → Sonido. Este síntoma no determina si el fallo está en ALSA, el
controlador, PipeWire, PulseAudio o el gestor de sesión.

## Decisión de arquitectura (noviembre de 2026)

Se mantiene ALSA para los controles físicos específicos de Creative y se prevé
incorporar PipeWire/WirePlumber para observar perfiles, puertos y rutas. No se
cambiará el backend a PipeWire sin comprobar primero qué capa controla realmente
el selector de la AE-5. La CLI de lectura seguirá funcionando sin escritorio.

La incidencia de suspensión documentada ocurrió antes de una actualización de
Ubuntu. Tras actualizar, el usuario todavía no ha observado que se reproduzca.
Por tanto no se implementa recuperación automática ni se prioriza su investigación:
el procedimiento de capturas posterior solo se activará si reaparece el fallo.

## Fases

| Fase | Trabajo | Evidencia para completarla |
| --- | --- | --- |
| 00 · Base | Preservar el original, documentar el alcance, preparar herramientas, tests y CI. | Las pruebas se ejecutan sin GTK ni hardware; el original permanece intacto y los defectos conocidos quedan explícitos. |
| 01 · Lectura ALSA y diagnóstico | Separar la lectura del estado de la interfaz, interpretar enumerados, seleccionar la tarjeta sin ambigüedad y ofrecer una CLI mínima de consulta. | Tests de controles, errores y tarjeta ausente; contraste temprano con salidas reales de la AE-5. |
| 02 · Suspensión (condicional) | Investigar únicamente si vuelve a reproducirse tras la actualización de Ubuntu. | Capturas comparables antes del fallo, durante él y tras recuperarlo; no introducir hooks especulativos. |
| 03 · Conmutación y perfiles | Conmutación ALSA directa implementada en PR #4; comparar perfiles originales y validar en hardware físico. | Confirmar efectos del selector real y preservar DSP, ganancia y volumen; pruebas reales sin alterar otras tarjetas. |
| 04 · Bandeja | Implementada bandeja GTK3/Ayatana opcional y asíncrona en PR #4; falta validación en una sesión GNOME real. | Comprobar iconos, menú y estado tras cambios externos sin bloquear el escritorio. |
| 05 · Instalación y validación | Documentar instalación, uso y recuperación; añadir distribución y arranque automático cuando el flujo sea fiable. | Comprobación en Ubuntu con auriculares, altavoces y varios ciclos de suspensión; límites conocidos documentados antes de publicar. |

La validación con hardware empieza en la fase 01 y continúa en cada cambio de
comportamiento. No se pospone íntegramente a una release final.

El flujo de integración es TBD: ramas cortas y PR hacia `main`, con revisión y
el check `CI required` antes de fusionar. No se hace push directo a `main`.
La publicación automática ocurre después de integrar, desde `main`.

Se reutiliza la rama `codex/ae5ctl-deb-signing`, partiendo de `main` para cada
PR. Tras fusionar se elimina la rama remota; el borrado comprueba que su punta
sigue siendo la integrada para conservar cualquier trabajo posterior.

## Empaquetado adelantado

A petición del usuario, se adelanta de la fase 05 la generación de paquetes
`.deb` de la CLI actual, su firma con una clave OpenSSL cifrada y su publicación
automática mediante CI/CD tras superar las comprobaciones de `main`. Las
instrucciones están en [Paquetes .deb y firma OpenSSL](deb-packages.md). Esto no
añade funcionalidades de audio ni resuelve la suspensión. Las compilaciones se
publican como prereleases; la elección de licencia, la validación con hardware y
un posible repositorio APT siguen pendientes.

## Usabilidad de CLI (PR de seguimiento)

Se añade ayuda general y por subcomando con ejemplos, versión, códigos de salida,
restricciones de solo lectura y sugerencias en errores de texto. El formato JSON
y sus códigos de salida permanecen estables; las pruebas verifican el contenido
de la ayuda sin acceder a ALSA. Tras esta mejora, la siguiente prioridad funcional
es implementar la conmutación de salidas, con validación en hardware.

## Bandeja GTK/Ayatana opcional (PR #4)

El subcomando `ae5ctl tray` usa el motor ALSA existente con un controlador
asíncrono de una operación a la vez; GLib actualiza los controles en el hilo
principal. Las dependencias gráficas se importan únicamente al arrancar `tray`,
de modo que las otras órdenes y CI continúan funcionando sin GTK. No hay
autostart ni restauración de perfiles. Pendiente probar el indicador y el
control de la tarjeta real en Ubuntu GNOME.

## Avance en conmutación (PR #4)

`switch headphones`, `switch speakers` y `toggle` utilizan el selector ALSA
real, sin índice fijo, con `cset` acotado a la tarjeta seleccionada y lectura
posterior de confirmación. Se evitan escrituras cuando la salida ya está
seleccionada; los comandos no restauran perfiles completos ni tocan PipeWire.
Las pruebas usan hardware simulado. Falta contrastar en la AE-5 real que los
perfiles originales no incluyeran DSP, ganancia o volumen necesarios antes de
retirar el script gráfico y declarar la conmutación validada.

## Estado de la fase 01

El motor y la CLI de lectura están implementados sin dependencias gráficas. Se
pueden listar tarjetas con `cards`, consultar el selector con `status` y obtener
un diagnóstico ALSA, incluidos fallos parciales, con `doctor`. La interpretación
de enumerados usa sus índices y etiquetas reales, sin fijar un orden ni depender
del plural `Headphones`. La selección ambigua exige `--card` o `--numid`.

Las consultas no modifican audio. La cobertura con datos sintéticos permite
validar el código en la nube, pero el contraste de lectura en la AE-5 real sigue
pendiente. No se considera validada la conmutación ni resuelta la suspensión.

### Contraste de lectura en Ubuntu

Tras la instalación de desarrollo descrita en el README, ejecutar desde el
repositorio y revisar los resultados:

```bash
.venv/bin/ae5ctl cards --json
.venv/bin/ae5ctl status --json
.venv/bin/ae5ctl doctor --json
```

Si el nombre no identifica el modelo o la selección es ambigua, repetir `status`
y `doctor` con `--card ID_ALSA`, usando el ID mostrado por `cards`. Añadir
`--numid N` solo cuando se conozca el control correcto. Los nombres y números de
los ejemplos sintéticos no son configuración para el hardware.

El objetivo de este contraste es confirmar que la tarjeta, el control y la
opción seleccionada coinciden con el equipo. Un código de salida 0 certifica la
consulta, no que se oiga audio ni que el perfil de Ubuntu sea correcto.

## Criterios de la fase 00

- Preparación reproducible desde un checkout limpio con las instrucciones del
  README y herramientas de desarrollo fijadas.
- Pruebas de las funciones originales que cubran estados enumerados, variantes
  de nombres, tarjeta ausente y fallos de comandos.
- Ningún acceso a ALSA real ni necesidad de pantalla o bindings GTK durante CI.
- Muestras sintéticas identificadas y dependencias externas simuladas.
- Defectos pendientes con motivo concreto y `xfail(strict=True)`, sin convertir
  fallos desconocidos en resultados esperados.
- Tests y lint ejecutados en CI. No se añaden todavía servicios, automatización
  de releases ni módulos vacíos para funcionalidades futuras.

## Investigación de la suspensión

La captura inicial será de solo lectura y comparará tres estados del mismo
equipo, conservando qué salida se estaba usando:

1. Audio correcto antes de suspender.
2. Audio averiado después de reanudar, antes de cambiar ajustes.
3. Audio recuperado tras estéreo → 5.1 → estéreo en Ajustes → Sonido de Ubuntu.

Se registrarán versión de Ubuntu y kernel, gestor de audio en uso, identidad de
la tarjeta, controles ALSA, perfil activo, puertos, salida predeterminada y los
registros relevantes del intervalo. La comparación debe mostrar qué restablece
realmente el cambio de perfil. No se supondrá que PipeWire está instalado ni que
un valor ALSA correcto demuestra que sale audio por el conector esperado.

La CLI de la fase 01 permite repetir las consultas ALSA anteriores en los tres
estados. Los perfiles, puertos y registros del gestor de audio requieren aún
capturas adicionales en la fase 02; `doctor` no recoge ni compara esos datos.

Los datos del equipo real se incorporarán como fixtures revisadas cuando estén
disponibles, evitando información personal innecesaria. Su ausencia no bloquea
la preparación de las pruebas sintéticas ni el trabajo de la fase 00.

Si hace falta una recuperación desde `ae5ctl`, se implementará después de aislar
la operación mínima. Debe conservar la salida elegida, los volúmenes y los
ajustes DSP necesarios, y validarse durante varios ciclos con auriculares y
altavoces. No se añadirá un hook automático de suspensión basándose únicamente
en el síntoma.

## Decisiones pendientes

- Confirmar nombres e identificadores de tarjeta y controles en la AE-5 real.
- Comparar `ae5-headphones.state` y `ae5-speakers.state`: no se retirará la
  restauración ni se afirmará equivalencia con el modo directo sin esa revisión.
- Definir la compatibilidad mínima de Ubuntu y la licencia antes de distribuir.
- Posponer control avanzado DSP, soporte de otras tarjetas y cambios automáticos
  de rutas PipeWire hasta completar el flujo principal.
