# ae5ctl · Control de Sound Blaster AE-5 para GNOME

**Nuevo formato principal: GNOME Shell Extension (ZIP).** Compatible inicialmente
con GNOME Shell 46 de Ubuntu 24.04. No exige instalar la CLI Python, GTK/Ayatana
ni un paquete Debian. Se integra en Quick Settings.

## Funciones disponibles

La primera extensión incluye un indicador de la salida física actual,
la selección entre auriculares y altavoces y un botón de refresco. Detecta
la AE-5 desde ALSA y descubre dinámicamente el selector físico sin fijar
el número de tarjeta ni el numid. Antes de escribir comprueba de nuevo la
identidad de tarjeta, enumerado y valor; después verifica el cambio.

Las consultas y escrituras usan Gio.Subprocess asíncrono, sin shell ni root.
**No modifica el volumen, DSP, PipeWire ni presets.** La gestión visual de
presets, EQ, efectos y wizard gráfico forman parte del roadmap posterior.

## Instalación

Necesitas Ubuntu con GNOME Shell 46 y las utilidades ALSA:

```bash
gnome-shell --version
sudo apt install alsa-utils
```

Descarga el ZIP de extensión desde la PR (artefacto opcional build-gnome) o
desde GitHub Releases cuando exista una versión etiquetada. Si procede de
Actions, el artefacto exterior es otro ZIP: extráelo primero para obtener
ae5ctl@ml0renz0.github.io.shell-extension.zip.

```bash
gnome-extensions install --force ./ae5ctl@ml0renz0.github.io.shell-extension.zip
gnome-extensions enable ae5ctl@ml0renz0.github.io
gnome-extensions info ae5ctl@ml0renz0.github.io
```

Si la sesión Wayland aún no reconoce la extensión, cierra sesión y vuelve a
entrar. Abre Quick Settings y despliega ae5ctl. Para desinstalar:

```bash
gnome-extensions disable ae5ctl@ml0renz0.github.io
gnome-extensions uninstall ae5ctl@ml0renz0.github.io
```

## Desarrollo y CI

```bash
node --test tests/gnome/*.test.mjs
python3 tools/build_extension.py
unzip -t dist/ae5ctl@ml0renz0.github.io.shell-extension.zip
```

El pipeline ejecuta pruebas de parser GJS (Node 22), revisión sintáctica
de los módulos, construcción ZIP y regresiones heredadas Python. El check
estable CI required depende de los dos bloques. Las PR ordinarias no
almacenan artefactos; la etiqueta de PR **build-gnome** conserva el ZIP
un día. Las etiquetas Git vX.Y.Z en main generan releases del ZIP.
**No se fabrican ni distribuyen paquetes Debian.**

## Qué sigue pendiente

La nueva extensión **no se ha probado todavía en GNOME Shell 46 ni en una
Sound Blaster AE-5 física**. Los tests simulan respuestas ALSA y no verifican
sonido. Hay que validar enable/disable, conectores, suspensión, hotplug y
cambios externos. También falta comparar el DSP y volumen del programa
antiguo antes de retirarlo.

Los fuentes Python, el wizard de terminal y ae5-switcher.py quedan en el
repositorio solo como referencia de migración. **No están en el ZIP ni son
dependencias de la extensión**.

[Roadmap](docs/roadmap-control-center.md) ·
[Guía de pruebas GNOME](docs/gnome-extension.md) ·
[PR #4](https://github.com/ml0renz0/ae5ctl/pull/4)
