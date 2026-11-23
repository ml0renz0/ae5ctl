# ae5ctl

Herramienta en desarrollo para consultar y cambiar la salida de una Creative
Sound BlasterX AE-5 en Linux, desde una CLI y una bandeja gráfica opcional.

## Estado actual

La CLI `ae5ctl` consulta las tarjetas, el control de salida y la selección ALSA
sin depender de GTK. Interpreta los índices enumerados y admite `Headphone` y
`Headphones`. Los comandos `switch` y `toggle` cambian **solo el selector ALSA**
y comprueban el resultado; no restauran perfiles de volumen o DSP. La validación
en una AE-5 física sigue pendiente de contraste.

El punto de partida es [`ae5-switcher.py`](ae5-switcher.py), conservado sin cambios
como referencia. Utiliza GTK 3, AppIndicator3 y dos perfiles ALSA para alternar
entre auriculares y altavoces; es independiente de la CLI nueva.

Las fases 00 y 01 preparan documentación, pruebas, CI y diagnóstico de lectura. El
[plan de desarrollo](docs/plan.md) incluye investigar el fallo de audio tras
reanudar Ubuntu: cambiar de estéreo a 5.1 y volver a estéreo desde Ajustes → Sonido
recupera el audio, según lo observado por el usuario. Su causa sigue pendiente.

## Centro de control AE-5: ampliación del alcance

La hoja de ruta [Control Center](docs/roadmap-control-center.md) contempla
controles DSP, EQ, mixer, grabación, presets, perfiles de PipeWire y extensión
GNOME, con funciones restringidas (Direct Mode, OutFX, RGB, Scout Mode)
sujetas a investigación y a pruebas en hardware real.

`ae5ctl capabilities --json` es el primer paso: inspecciona únicamente
la tarjeta ALSA seleccionada y registra el tipo, acceso anunciado por el driver,
valores actuales, opciones y rangos de sus controles. El informe **no modifica
audio y no autoriza escribir ningún control**. Las categorías inferidas por
nombre son pistas para diseñar la UI, no pruebas de compatibilidad:

```bash
ae5ctl capabilities --json
ae5ctl capabilities --card Creative --json
```

La siguiente etapa ya permite **previsualizar cambios tipados de solo lectura**
sin modificar controles ALSA. Por ejemplo, usando los números reales
descubiertos en tu máquina:

```bash
ae5ctl controls plan 11 50,50 --card Creative --json
ae5ctl controls plan 43 Speakers --card Creative
```

Esos números son ilustrativos, no constantes de la AE-5. Se validan rangos,
canales y enumerados, pero `can_apply` siempre es `false` hasta certificar
la seguridad del motor de escritura.

Las lecturas incompletas se identifican como tales y devuelven código 4, aun
cuando se puedan conservar controles leídos correctamente. Revisa nombres de
dispositivos antes de compartir el JSON. Se conservarán la CLI y el `.deb`
durante la transición hasta verificar la extensión GNOME en una AE-5 real.

## Uso rápido

La ayuda es autocontenida y no necesita hardware ni entorno gráfico:

```bash
ae5ctl                    # Mostrar la ayuda general
ae5ctl --help             # Comandos, ejemplos, límites y códigos de salida
ae5ctl --version          # Versión instalada
ae5ctl cards --help       # Ayuda para listar dispositivos
ae5ctl status --help      # Opciones --card, --numid y --timeout
ae5ctl switch --help      # Seleccionar una salida con verificación
ae5ctl toggle --help      # Alternar la salida física ALSA
ae5ctl switch speakers --dry-run --json # Previsualizar sin escribir
ae5ctl tray --help        # Indicador GTK/Ayatana opcional
ae5ctl doctor --help      # Diagnóstico y limitaciones
ae5ctl profiles diff --help # Comparar perfiles alsactl guardados
```

Para descubrir la tarjeta, comprobar la salida y conmutarla:

```bash
ae5ctl cards
ae5ctl status
ae5ctl switch speakers --dry-run --json
ae5ctl toggle --dry-run
ae5ctl switch headphones
ae5ctl switch speakers
ae5ctl toggle
ae5ctl validate                      # Diagnóstico previo de solo lectura
ae5ctl wizard                        # Wizard: tonos, preguntas y restauración
ae5ctl validate --apply              # Alias de ae5ctl wizard
ae5ctl doctor --json
ae5ctl doctor --pipewire --json  # Inspección opcional, solo lectura
ae5ctl capabilities --json      # Descubrimiento de controles; nunca escribe
ae5ctl doctor --profiles --json  # Diagnóstico + perfiles originales
ae5ctl doctor --pipewire --profiles --json  # Informe combinado, solo lectura
ae5ctl profiles diff --json       # Comparación sin escribir en ALSA
```

**Previsualización segura:** `switch --dry-run` y `toggle --dry-run` leen el
selector actual, muestran el `numid` y la opción enumerada que usarían y
construyen el comando `amixer cset` previsto, **sin ejecutarlo**. No garantizan
que, entre la previsualización y un cambio posterior, la tarjeta o sus
controles sigan siendo iguales. El cambio efectivo vuelve a comprobar la
identidad de la tarjeta, su enumerado y el valor seleccionado antes de
escribir, y verifica el selector tras escribir. Si otro cliente cambia la salida
durante la operación, se cancela sin escribir; la comprobación no es atómica.

**Advertencia:** `switch` y `toggle` escriben únicamente el control enumerado
de la tarjeta ALSA seleccionada. No restauran los perfiles
`~/.config/ae5-{headphones,speakers}.state`, ni ajustan ganancia, DSP, volumen,
perfiles de PipeWire o rutas de aplicaciones. Si el sonido dependía de esos
ajustes, compare los perfiles originales antes de sustituir la aplicación GTK.
No se han probado todavía los cambios físicos en el equipo real.

## CI/CD: paquetes solo con etiqueta

Las PR ordinarias y los commits a `main` pasan lint y tests sin construir
archivos `.deb`. Para activar la validación Debian de una PR, se aplica
la etiqueta de GitHub `build-deb`; para publicar se envía una etiqueta Git
de versión `v<version>` apuntando a un commit integrado en `main`.
Ninguna etiqueta está aplicada a la PR #4.

El pytest habitual excluye las pruebas que generan paquetes. Para ejecutarlas
expresamente: `python -m pytest -m package`. Los paquetes solo se conservan
en GitHub Releases cuando publicamos una versión. En PR con `build-deb`,
el `.deb` y su SHA-256 probados se pueden descargar como ZIP desde **Actions →
ejecución de CI → Artifacts**, con retención de un día. Las PR normales no
generan artefactos. Más detalles en [empaquetado](docs/deb-packages.md).

## Comparar perfiles ALSA originales (solo lectura)

El antiguo `ae5-switcher.py` llamaba a `alsactl restore` con dos instantáneas
completas. La nueva conmutación directa solo escribe el selector físico;
**no es equivalente a restaurar un perfil entero** si también cambian el
volumen, los interruptores de reproducción, la ganancia o el DSP.

Para identificar esas diferencias sin modificar dispositivos ni necesitar
la tarjeta conectada:

```bash
ae5ctl profiles diff
ae5ctl profiles diff --json
ae5ctl profiles diff --headphones /ruta/auriculares.state \
                     --speakers /ruta/altavoces.state
```

Los valores predeterminados proceden del script original:
`~/.config/ae5-headphones.state` y `~/.config/ae5-speakers.state`. Si no
existen, se devuelve un error explícito. No se crean ni se generan nuevos
estados, y **nunca se invoca `alsactl restore` ni `amixer`** durante la
comparación.

El análisis empareja controles por tarjeta, interfaz, nombre, índice y
subdispositivo, no por `control.N` (`numid`). Muestra todas las diferencias,
incluidas las de otras tarjetas, y avisa si los archivos contienen varias.
La clasificación de cambios en rutas, niveles/muteo, posible DSP y otros
es orientativa, basada exclusivamente en nombres; no demuestra qué hace
realmente un control. Los metadatos de comentarios `alsactl` no se comparan:
solo los valores guardados. Los archivos deben ajustarse al formato habitual
de `alsactl store` y no superar 2 MiB cada uno.

**No restaure perfiles completos para probar esta función.** Antes de
sustituir el script original será necesario revisar el resultado con los
archivos reales del equipo. Las pruebas automáticas utilizan perfiles sintéticos.

Para reunir en un único JSON el selector ALSA y el contraste con los dos
archivos originales, usa `ae5ctl doctor --profiles --json`. Para añadir el
diagnóstico del servidor de audio, usa `--pipewire`. Ambas opciones son
estrictamente de solo lectura. La sección `profiles.ok` confirma únicamente que
se han comparado los archivos; **no** que los perfiles sean equivalentes ni
que se haya probado el hardware. Si falta un fichero, se muestra el error
`profiles.error`, sin alterar el código de salida del diagnóstico ALSA.
Sin `--profiles`, el JSON anterior no cambia. El informe puede incluir
identificadores de dispositivos: revísalo antes de publicarlo.

## Wizard de validación auditiva

`ae5ctl wizard` es el flujo recomendado para probar el selector físico,
sin seguir manualmente una serie de comandos. Usa `pactl` para localizar una
salida de audio asociada a la tarjeta ALSA y `paplay` (compatible con
PipeWire mediante `pipewire-pulse`) para generar tres tonos cortos a bajo
nivel digital; **no cambia el sink predeterminado**. Necesita el paquete
`pulseaudio-utils`.

```bash
sudo apt install pulseaudio-utils
ae5ctl wizard
# o indicar la tarjeta ALSA si no se detecta automáticamente
ae5ctl wizard --card ID_ALSA
```

El asistente identifica la AE-5, revisa diferencias de perfiles si están
disponibles, elige una salida de reproducción verificable o te deja escoger,
reproduce un tono por la salida actual y pregunta si lo oyes. Solo tras teclear
`CAMBIAR` conmuta el control ALSA, reproduce otro tono y pregunta de nuevo.
Al terminar intenta restaurar la selección original, emite un tercer tono y
solicita la última confirmación. Si hay errores o cancelación, explica si ha
podido restaurar ALSA. No asegura equivalencia DSP ni sustituye las pruebas
visuales de GNOME.

`ae5ctl validate` sigue siendo de solo lectura y `validate --apply` es
un alias del wizard. Guía completa: [validación en Ubuntu](docs/validation-ubuntu.md).

## Indicador de bandeja (opcional)

`ae5ctl tray` recupera el menú de auriculares, altavoces, alternar y salir del
script original. Usa GTK 3 y AyatanaAppIndicator3, pero las consultas y los
cambios ALSA se ejecutan en un hilo de trabajo; el menú se actualiza desde
el hilo principal de GTK. Refresca el estado real cada cinco segundos y muestra
los errores sin suponer que la última selección solicitada tuvo éxito. Después
de detectar la tarjeta y el selector una vez, reutiliza esos identificadores
para evitar escanear todos los controles ALSA en cada ciclo. Si la consulta
falla, descarta la caché y vuelve a detectar el hardware en el siguiente ciclo.

En Ubuntu 22.04/24.04, instale las dependencias gráficas mediante APT:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
ae5ctl tray
ae5ctl tray --card Creative --interval 5
```

La instalación del paquete `.deb` no exige las dependencias gráficas para
preservar el modo CLI sin escritorio. En un entorno virtual, cree el venv con
`python3 -m venv --system-site-packages .venv` para acceder a `python3-gi`
instalado con APT. El indicador necesita una sesión gráfica y soporte de
indicadores del escritorio; su aspecto puede variar entre GNOME y otras sesiones.
Si ALSA falla o el estado es desconocido, el menú desactiva las acciones que
escriben en el hardware hasta que una lectura posterior confirme la salida;
«Actualizar estado» permanece disponible. Si el usuario eligió un índice
numérico de tarjeta, la bandeja lo fija al ID ALSA detectado para no cambiar
silenciosamente a otra tarjeta cuando el índice se reutilice tras un hotplug.
No se configura arranque automático hasta validar el comportamiento en la AE-5
física. Tampoco restaura perfiles `alsactl` ni modifica PipeWire.

Si `status` no identifica la tarjeta de forma inequívoca, use el ID mostrado en
`cards` con `--card`; indique `--numid` únicamente si hay varios selectores
o conoce su identificador. El diagnóstico `doctor --pipewire` consulta `pactl`
para conocer el servidor de audio, su salida predeterminada y las salidas/tarjetas
disponibles. Identifica PipeWire mediante el nombre devuelto por el servidor,
sin confundirlo con PulseAudio. **No inspecciona los perfiles detallados de
WirePlumber ni garantiza correspondencia con el selector físico de la AE-5.**
Si falta `pactl`, instale `pulseaudio-utils`; es una dependencia opcional.
Las respuestas JSON de `doctor` solo incluyen `audio_session` cuando se indica
`--pipewire`, y un fallo de esta inspección opcional no modifica el código de
salida del diagnóstico ALSA.

## Instalación y consultas

Se necesita Linux y Python 3.10 o posterior. `status`, `doctor`, `switch` y `toggle` utilizan `amixer`,
incluido en el paquete `alsa-utils` de Ubuntu. El paquete Python usa únicamente la
biblioteca estándar; no necesita PyGObject ni escritorio. Desde la raíz del
repositorio:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . -r requirements-dev.txt
.venv/bin/ae5ctl cards
.venv/bin/ae5ctl status
.venv/bin/ae5ctl doctor --json
```

También se puede usar `.venv/bin/python -m ae5ctl`. La consulta `cards` lee
`/proc/asound/cards` y no requiere `amixer`.

La selección automática exige un identificador o descripción que reconozca
AE-5. `HDA Creative` y `CA0132` por sí solos no demuestran el modelo: consulta
`cards` y selecciona el ID ALSA exacto o su índice con `--card`. Si hay varias
tarjetas o varios selectores compatibles, se informa de la ambigüedad en lugar de
usar el primero. `--numid` permite indicar un selector concreto, que también se
valida. No se asumen IDs ni números de control de otro equipo.

Por ejemplo, tras sustituir los valores por los de tu equipo:

```bash
.venv/bin/ae5ctl status --card ID_ALSA --numid 37 --timeout 5 --json
```

`--timeout` limita cada operación `amixer` y `pactl`, en segundos. Los comandos
de consulta y conmutación admiten `--json`; `tray` es únicamente gráfico. Los resultados y errores en JSON se escriben en la salida
estándar; en modo texto, los errores se escriben en la salida de errores.
`doctor` conserva las tarjetas ya leídas y explica los fallos de diagnóstico.

| Código de salida | Significado |
| --- | --- |
| 0 | Consulta completada; `cards` puede devolver una lista vacía. |
| 2 | Argumentos inválidos. |
| 3 | Tarjeta o control ausente o ambiguo, o salida desconocida. |
| 4 | Dependencia ausente, comando fallido, permiso, tiempo límite o respuesta inválida. |
| 5 | Validación interactiva incompleta o no satisfactoria. |
| 130 | Validación interactiva interrumpida. |

`cards`, `status` y `doctor` son de solo lectura; `switch` y `toggle` sí modifican
el selector de salida ALSA y verifican que queda seleccionado. Una selección
ALSA correcta no demuestra que salga audio por el conector esperado. `doctor`
todavía no inspecciona perfiles de PipeWire ni WirePlumber; la incidencia previa
a la actualización de Ubuntu no se ha vuelto a observar.

## Desarrollo

Después de la instalación anterior:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Las pruebas cubren el motor ALSA, la inspección opcional del servidor de
audio y la CLI, además de caracterizar el script original con dependencias y comandos simulados. No necesitan PyGObject, GTK, una
sesión gráfica ni una tarjeta de sonido, y no deben escribir en ALSA. Las muestras
ALSA sintéticas se identifican como tales; no demuestran cómo se comporta el
hardware del usuario.

Los defectos pendientes del original se registran con `xfail(strict=True)`: un
fallo esperado no equivale a una funcionalidad correcta, y un éxito inesperado
obliga a revisar el caso. El motor nuevo tiene sus propias pruebas normales; no
hereda esos fallos esperados. Ruff excluye el original para preservar la
referencia y comprueba el código nuevo.

## Paquetes Debian

Se puede generar un `.deb` de desarrollo sin root, pip ni conexión de red:

```bash
python3 packaging/build_deb.py
```

El generador requiere Python 3.11 o posterior y `dpkg-deb` (paquete `dpkg`). El
paquete resultante es `dist/ae5ctl_0.1.0.dev0-1_all.deb`, con su checksum
`.deb.sha256`. Instala la CLI con Python del sistema y declara `python3 >= 3.10`
y `alsa-utils` como dependencias. No incluye el script gráfico original.
El nombre conserva la versión Python; el campo `Version` del paquete mantiene
`0.1.0~dev0-1` para respetar el orden de versiones Debian.

En Ubuntu, instala el archivo local con APT para resolver las dependencias:

```bash
sudo apt install ./dist/ae5ctl_0.1.0.dev0-1_all.deb
ae5ctl doctor --json
sudo apt remove ae5ctl
```

Trabajamos mediante PR hacia `main`. El
[flujo CI/CD](docs/deb-packages.md#cicd-debian-bajo-demanda) valida el código sin
generar paquetes en las PR ordinarias ni al fusionar. Solo `build-deb` en una
PR ejecuta la prueba opcional de empaquetado; **únicamente una etiqueta Git
de versión `v<version>` aplicada a un commit de `main`** construye, prueba,
firma y publica el `.deb` en
[Releases](https://github.com/ml0renz0/ae5ctl/releases). La firma es separada:
APT no verifica los archivos `.sig` de OpenSSL automáticamente.

## Limitaciones del script original

- Busca nombres de salida en `values=`, aunque los controles enumerados usan
  índices numéricos; la lectura puede devolver un estado desconocido.
- Exige `Headphones` y rechaza la variante `Headphone`.
- Construye comandos con `shell=True`; los apóstrofos rompen el escape de las
  notificaciones y el contenido interpolado puede interpretarse como shell.
- Restaura perfiles sin seleccionar una tarjeta. Puede modificar otras tarjetas
  incluidas en esos archivos y activar la inicialización de ALSA si falla la
  restauración.
- Importa `AppIndicator3`, ausente en la imagen Debian 13 usada para preparar el
  entorno. `AyatanaAppIndicator3` es otro namespace y requiere adaptar el código.

El uso real del original requiere las utilidades `amixer`, `alsactl` y
`notify-send`, los bindings gráficos correspondientes, una sesión de escritorio y
los perfiles `~/.config/ae5-headphones.state` y
`~/.config/ae5-speakers.state` del equipo real. No se proporcionan perfiles
inventados ni se asume que los de dos equipos sean intercambiables.

Antes de sustituir la restauración por un cambio directo de salida, se compararán
los perfiles: pueden contener diferencias necesarias de ganancia, DSP o volumen.
La modalidad predeterminada sigue pendiente de esa evidencia.

## Contribuciones y distribución

Los cambios se organizan por fases verificables. Las pruebas sin hardware y las
comprobaciones manuales con la AE-5 se documentarán por separado. Se puede instalar
la CLI como paquete Python o generar un `.deb` de desarrollo. CI/CD publica
las versiones etiquetadas y verificadas de `main` como prereleases. El arranque automático y la
validación funcional con hardware siguen pendientes, al igual que la elección
de licencia del proyecto.


### Motor de escritura seguro (fase experimental, no habilitado)

El código incluye `control_engine`, un motor transaccional probado contra ALSA
simulado. Revalida la tarjeta y los metadatos antes de cambiar valores,
verifica la respuesta y contempla rollback condicionado para no pisar cambios
de terceros. **No hay todavía `ae5ctl controls set` ni autorizaciones reales
para DSP, ecualización, volumen o ganancia.** Que el controlador diga
`access=rw` no certifica un control. La capacidad de escritura solo se
habilitará tras pruebas físicas y una revisión explícita de seguridad.
