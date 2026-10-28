# ae5ctl

Herramienta en desarrollo para consultar y cambiar la salida de una Creative
Sound BlasterX AE-5 en Linux, desde una CLI y una bandeja gráfica opcional.

## Estado actual

La CLI `ae5ctl` consulta las tarjetas, el control de salida y la selección ALSA
sin depender de GTK. Interpreta los índices enumerados y admite `Headphone` y
`Headphones`. Todavía no cambia salidas, restaura perfiles ni repara el audio
después de suspender. La lectura en una AE-5 física sigue pendiente de contraste.

El punto de partida es [`ae5-switcher.py`](ae5-switcher.py), conservado sin cambios
como referencia. Utiliza GTK 3, AppIndicator3 y dos perfiles ALSA para alternar
entre auriculares y altavoces; es independiente de la CLI nueva.

Las fases 00 y 01 preparan documentación, pruebas, CI y diagnóstico de lectura. El
[plan de desarrollo](docs/plan.md) incluye investigar el fallo de audio tras
reanudar Ubuntu: cambiar de estéreo a 5.1 y volver a estéreo desde Ajustes → Sonido
recupera el audio, según lo observado por el usuario. Su causa sigue pendiente.

## Instalación y consultas

Se necesita Linux y Python 3.10 o posterior. `status` y `doctor` utilizan `amixer`,
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

`--timeout` limita cada consulta `amixer`, en segundos. `cards`, `status` y
`doctor` admiten `--json`. Los errores de lectura en JSON se escriben en la salida
estándar; en modo texto, los errores se escriben en la salida de errores.
`doctor` conserva las tarjetas ya leídas y explica los fallos de diagnóstico.

| Código de salida | Significado |
| --- | --- |
| 0 | Consulta completada; `cards` puede devolver una lista vacía. |
| 2 | Argumentos inválidos. |
| 3 | Tarjeta o control ausente o ambiguo, o salida desconocida. |
| 4 | Dependencia ausente, comando fallido, permiso, tiempo límite o respuesta inválida. |

Estas consultas no modifican controles ALSA ni perfiles de Ubuntu. Una selección
ALSA legible no demuestra que salga audio por el conector esperado. `doctor`
todavía no inspecciona perfiles de PipeWire/PulseAudio ni determina la causa del
fallo de suspensión.

## Desarrollo

Después de la instalación anterior:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

Las pruebas cubren el motor y la CLI nuevos, además de caracterizar el script
original con dependencias y comandos simulados. No necesitan PyGObject, GTK, una
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
paquete resultante es `dist/ae5ctl_0.1.0~dev0-1_all.deb`, con su checksum
`.deb.sha256`. Instala la CLI con Python del sistema y declara `python3 >= 3.10`
y `alsa-utils` como dependencias. No incluye el script gráfico original.

En Ubuntu, instala el archivo local con APT para resolver las dependencias:

```bash
sudo apt install ./dist/ae5ctl_0.1.0~dev0-1_all.deb
ae5ctl doctor --json
sudo apt remove ae5ctl
```

Trabajamos con TBD: ramas cortas y PR hacia `main`. El
[flujo CI/CD](docs/deb-packages.md#cicd-automático) valida las PR y, al fusionarlas
en `main`, genera, prueba, firma y publica automáticamente el `.deb` en
[Releases](https://github.com/ml0renz0/ae5ctl/releases). No requiere crear etiquetas
ni ejecutar workflows manualmente. La firma es separada: APT no verifica los
archivos `.sig` de OpenSSL automáticamente.

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
la CLI como paquete Python o generar un `.deb` de desarrollo. CI/CD publica las
compilaciones verificadas de `main` como prereleases. El arranque automático y la
validación funcional con hardware siguen pendientes, al igual que la elección
de licencia del proyecto.
