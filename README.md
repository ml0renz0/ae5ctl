# ae5ctl

Herramientas para Creative Sound BlasterX AE-5. Proyecto en fase 00: estructura,
script original preservado, pruebas de regresión y CI. Todavía no cambia salidas.

## Desarrollo

Python 3.10 o posterior. Desde la raíz del repositorio:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
ae5ctl --help
ae5ctl --version
python -m pytest --cov=ae5ctl --cov-report=term-missing
ruff check .
ruff format --check .
python -m build
```

El núcleo no necesita GTK ni ALSA para instalarse. Las pruebas usan simulaciones
y nunca restauran perfiles ni cambian controles de audio. La prueba marcada
`xfail` documenta el fallo original al interpretar valores ALSA numéricos; un
éxito inesperado falla la suite para obligar a revisar esa expectativa.

El original está en `legacy/ae5-switcher.py`, con sus limitaciones documentadas.
No se incluye una licencia hasta que el titular elija una.

## Próximas fases

01: detección y parsing ALSA; 02: cambio y toggle con verificación; 03: CLI y
diagnóstico; 04: perfiles; 05: bandeja; 06: integración de audio; 07: distribución;
08: auditoría y release. Se trabajará por fases pequeñas y revisables.

Antes de reemplazar los perfiles originales hay que comparar los archivos
`ae5-headphones.state` y `ae5-speakers.state`: podrían incluir ajustes DSP.
La conmutación real requiere una AE-5; la bandeja requiere sesión gráfica.

## CI/CD y desarrollo basado en trunk (TBD)

Trabajar con ramas cortas y PR pequeñas hacia `main`. Antes de cada nueva
release, incrementar `project.version` y `ae5ctl.__version__` juntos y actualizar
el changelog. Las PR fallan si su versión ya tiene una etiqueta. CI comprueba Python 3.10, 3.12 y 3.13, lint, formato, pruebas y build.

Cada push a `main` (incluidos los merges) ejecuta toda la matriz de CI y,
si pasa, crea una GitHub Release con etiqueta `v<versión>`, wheel, sdist y paquete
Debian `.deb` (`Architecture: all`). Una versión ya publicada desde otro commit
produce un error: hay que incrementar la versión antes de integrar. Reejecutar
el mismo commit permite recuperar la subida de paquetes sin mover la etiqueta.
La release permanece como borrador hasta que se han subido todos los paquetes.
No publica en PyPI y no necesita tokens externos: usa `github.token` con permiso
de escritura únicamente en el job de publicación.

En GitHub, configurar una regla de protección de `main` que exija PR y los tres
checks de CI, impida force-push y borrado. El workflow está preparado; esas
reglas del servidor todavía no se han aplicado. La primera integración publicará
`v0.0.1`; la validación local no publica releases.

## Paquete Debian

En Debian/Ubuntu, con `dpkg-deb` disponible:

```bash
python3 packaging/build_deb.py
sudo apt install ./dist/ae5ctl_0.0.1_all.deb
ae5ctl --version
```

Requiere Python del sistema 3.10 o posterior. No usa pip durante la instalación
y no incluye el script legacy ni dependencias GTK. La CLI actual solo ofrece
ayuda y versión. Las releases adjuntan el `.deb`; no se configura un repositorio
APT.
