# ae5ctl · Roadmap del centro de control para GNOME

**Visión:** control completo de lo que *realmente exponga y permita manejar de
forma segura* una Sound BlasterX AE-5 desde Linux, sin depender de Windows.
La cobertura de hardware/firmware se determina con inventario y ensayos
reproducibles, nunca asumiendo que un control del driver funciona en toda AE-5.

## Arquitectura objetivo

- **Capa hardware ALSA:** inventario, lectura y cambios validados de parámetros.
  En principio `amixer` sin shell; jamás `alsactl restore` global como método
  predeterminado ni permisos root por comodidad.
- **Capa de sesión PipeWire/WirePlumber:** perfiles, puertos, canales y
  dispositivos por las APIs disponibles. No se confunde un sink con el
  selector físico de auriculares/altavoces.
- **Modelo de capacidades:** catálogo versionado con identidades semánticas;
  los numid e índices ALSA solo son identificadores efímeros de una sesión.
- **Modelo de presets:** JSON versionado con validación de tipos, mínimos,
  máximos, dependencias, compatibilidad, dry-run, diff, cambios reversibles
  y exportación/importación segura. Los presets no son snapshots completos.
- **GNOME:** extensión GJS con Quick Settings para salida/preset y preferencias
  gráficas independientes para mixer, DSP, EQ, diagnóstico y wizard.
  No bloquear el hilo de Shell; usar operaciones asíncronas y desconectar
  callbacks al deshabilitar. No duplicar reglas de seguridad entre GUI y CLI.
- **Distribución:** ZIP de extensión, controlado por CI. La CLI y el Debian
  existente siguen disponibles mientras se valida equivalencia funcional.

## Fases con gates

| Fase | Entregable verificable | Gate |
| --- | --- | --- |
| 01 · Inventario | `ae5ctl capabilities --json`; todos los controles de la tarjeta, errores por control, esquema v1, clases de riesgo | Tests con fixtures + evidencia real en AE-5 |
| 02 · Backend tipado | Lectura, escritura controlada, comparación con estado previo, verificación, rollback y errores diferenciados | Ningún control desconocido o peligroso se escribe |
| 03 · Presets | CRUD JSON, diffs, import/export, aplicación transaccional en lo posible | Compatibilidad y rollback probados en hardware |
| 04 · Extensión GNOME | Quick Settings GJS para salida física/presets y estado real | GNOME 46 primero; enable/disable/reload sin fugas |
| 05 · Wizard gráfico | Señal acústica por destino explícito, confirmación de usuario y restauración | Pruebas de interrupción, silencio, hotplug y fallo |
| 06 · PipeWire | Gestión de perfiles/sinks/puertos con identificación ALSA inequívoca | No cambiar el sink ajeno ni rutas sin consentimiento |
| 07 · Mixer y DSP | Canales, volumen, EQ, SBX, micrófono/entrada, lecturas y presets | Matriz de controles/firmware y comprobación auditiva |
| 08 · Avanzado | Investigación de Scout, Direct Mode, OutFX, RGB y funciones propietarias | No se promete paridad Windows; unsafe bloqueado |
| 09 · Entrega | CI unit/integ, validación manual, artefacto ZIP etiquetado y publicación | Licencia, compatibilidad, accesibilidad y rollback |

Las fases pueden descomponerse en PR pequeñas; la PR #4 conserva la
continuidad mientras completamos el inventario y fijamos interfaces.
No es un calendario ni una afirmación de que todas las funciones sean viables.

## Contrato de capacidades v1

`ae5ctl capabilities [--card ID] [--numid N] [--json]`

Respuesta: `schema_version=1`, `scope=alsa_capabilities`, `ok`, tarjeta,
`controls[]`, `errors[]`, `summary` y `notes`. Cada control incluye
`numid`, nombre, interfaz, tipo, acceso, valores actuales, opciones,
rangos, familia, política de escritura y `editable_by_ae5ctl=false`.

- **No invasivo:** solo `amixer controls` y `amixer cget`.
- **Parcialidad visible:** un control fallido no borra datos válidos de otros;
  el comando devuelve exit 4 y `ok=false`.
- **Límites:** acota cantidad de controles y tamaño de las respuestas.
- **Aislamiento:** el usuario selecciona una tarjeta explícita si hay duda.
- **No autorización:** `access=rw` expresa el flag ALSA; **no equivale a
  certificación de seguridad**.
- **Controles restringidos:** OutFX, Direct Mode, RGB/GPIO/LED, firmware y
  ganancia sensible no tienen operación de escritura hasta una revisión
  específica; nunca se fuerza un control con `numid` hardcoded.

## Seguridad y calidad

No root, ni `shell=True`, ni firmware/flasheo automático, ni manipulación de
registros PCI, ni importación ciega de perfiles de terceros. Un control no
identificado se expone en lectura pero no se escribe. Las operaciones DSP no
deben ejecutarse simultáneamente desde UI y wizard. La aplicación debe avisar
de acciones que puedan producir sonidos inesperadamente altos.

Los tests CI usan fixtures, nunca tocan ALSA física. La validación manual
documenta kernel, `snd_hda_codec_ca0132`, tarjeta, tipos/rangos y qué se oye
realmente. `doctor --pipewire --profiles --json` y `capabilities --json`
serán las dos fuentes iniciales para construir esa matriz. La UI solo mostrará
como activas las funciones verificadas o explícitamente experimentales.

## Fuentes de referencia

- Kernel Linux: `sound/hda/codecs/ca0132.c` (y ruta anterior
  `sound/pci/hda/patch_ca0132.c`).
- Documentación de GNOME Shell/GJS:
  https://gjs.guide/extensions/topics/quick-settings.html
- Proyecto de investigación AE-5:
  https://github.com/klimovich008/ae5-linux-control

Se revisarán las licencias de cualquier código externo antes de reutilizarlo.


## Fase 02 · planificación tipada (PR #4)

`ae5ctl controls plan NUMID VALORES` prepara diffs de BOOLEAN, INTEGER,
INTEGER64 y ENUMERATED a partir del inventario real. Verifica cantidades,
rangos, saltos y opciones ambiguas, y registra una identidad semántica del
control (interfaz, nombre, índice, dispositivo y subdispositivo). Todos los
planes indican `can_apply=false`, incluidos los controles de riesgo.
Las escrituras controladas, rollback y activación de DSP requieren aún
certificación física; no hay un comando general de escritura.
