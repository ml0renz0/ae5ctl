**Aviso:** el formato principal pasa a ser GNOME Extensions. Para probar
la versión GJS consulta [la guía GNOME](gnome-extension.md).
Los comandos CLI descritos más abajo son de la implementación anterior,
conservada para contrastar el comportamiento; no son necesarios al
instalar el ZIP.

---

# Validación física de ae5ctl en Ubuntu

Esta es una **prueba manual**: el programa no puede medir si realmente sale
sonido por un conector. Los tests de CI usan respuestas ALSA sintéticas.
No elimines todavía `ae5-switcher.py` ni los dos ficheros de estado originales.
No hay autostart ni reparación automática de la suspensión.

## 1. Preparación segura: sin modificar audio

Instala el proyecto en un entorno virtual (README) y deja conectados los
auriculares y altavoces que quieras contrastar. Usa tu sesión normal de usuario
de Ubuntu; **no** ejecutes el validador con `sudo`.

```bash
.venv/bin/ae5ctl cards --json
.venv/bin/ae5ctl doctor --pipewire --profiles --json
.venv/bin/ae5ctl validate
```

Si la AE-5 no se detecta de forma inequívoca, usa `cards` para elegir el
identificador real y repite con `--card ID_ALSA`. Si hay varios controles
compatibles, identifica el correcto con `amixer -c ID_ALSA controls` y usa
`--numid N`. No copies los números de los fixtures de CI.

Revisa primero la sección `profiles` del diagnóstico. Si hay diferencias de
ganancia, volumen, muteo o posibles efectos DSP, **no asumas que la nueva
conmutación sustituye a la restauración de perfiles**. Los archivos
`~/.config/ae5-{headphones,speakers}.state` se leen, nunca se restauran
automáticamente. Si faltan, el informe marca el error de forma opcional.

## 2. Wizard auditivo automático y guiado

Se recomienda ejecutar **una sola orden** con el audio físico conectado:

```bash
sudo apt install pulseaudio-utils
.venv/bin/ae5ctl wizard
# Si es necesario especificar la tarjeta:
.venv/bin/ae5ctl wizard --card ID_ALSA
```

El programa realiza seis pasos, mostrando cada uno en pantalla: identifica
tarjeta, selector y perfiles; descubre qué salida PipeWire/PulseAudio pertenece
a la AE-5 (si no puede asociarla, pide que elijas); reproduce un tono breve
mediante `paplay --device` por la salida seleccionada; pregunta si se oye;
solicita autorización explícita `CAMBIAR` antes de modificar el selector ALSA;
reproduce otro tono y vuelve a preguntar. Finalmente intenta restaurar la
salida inicial y reproduce un tercer tono para pedir confirmación final.

Puedes responder `s` o `n` en cada prueba; no tienes que abrir otro
reproductor, pegar comandos ni preparar un archivo WAV. El wizard genera un
tono a nivel digital moderado y borra su fichero temporal al terminar; **baja
antes el volumen de auriculares/altavoces**. No cambia el sink predeterminado
de PipeWire, volúmenes del sistema, DSP o perfiles ALSA. Requiere que el
servidor de sonido de la sesión esté funcionando. Si `pactl` no expone la
asociación ALSA, la selección del sink es explícita y el wizard advierte que
no puede verificar esa asociación automáticamente.

Cancelar antes de confirmar `CAMBIAR` no escribe en ALSA. Una vez enviada la
conmutación, el programa intenta recuperar el selector original incluso ante
errores o Ctrl+C. Fallos de hardware, hotplug o cambios ajenos pueden impedir
la restauración; el asistente informa de ese estado incierto. El código 0
requiere tres respuestas auditivas afirmativas y confirmación del selector
original; 5 indica prueba incompleta y 130, interrupción.

`ae5ctl validate` conserva el modo de solo lectura; `validate --apply`
ejecuta este mismo wizard.

## 3. Indicador GTK/Ayatana en GNOME

Cuando la prueba CLI anterior resulte satisfactoria, en una terminal de la
misma sesión gráfica:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
# Si el venv no ve el paquete gi del sistema, créalo con --system-site-packages.
.venv/bin/ae5ctl tray --card ID_ALSA --interval 5
```

Comprueba manualmente lo siguiente: el icono aparece en el área de indicadores
de GNOME; el menú muestra la salida real; puedes seleccionar auriculares y
altavoces y escuchar el cambio; el icono se actualiza tras cambiar de salida
desde otra terminal; el estado desconocido no permite operaciones de escritura;
el botón de refresco recupera la visualización; y cerrar el indicador no deja
el escritorio bloqueado.

Para probar el refresco externo, **no uses a la vez el validador interactivo**:
haz la prueba desde otra terminal, con una sola operación cada vez.

```bash
.venv/bin/ae5ctl switch speakers --dry-run
.venv/bin/ae5ctl switch speakers
.venv/bin/ae5ctl status
```

Después restaura manualmente la selección inicial si la cambiaste.
Esta fase es específica de escritorio; no se reproduce en la CI sin GTK.

## 4. Qué registrar

| Prueba | Resultado a apuntar |
| --- | --- |
| Tarjeta y selector | ID ALSA, numid y etiquetas enumeradas |
| Perfiles | Diferencias de volumen, ganancia, muteo y DSP |
| Audio inicial | ¿Se oye? Sí/no |
| Audio conmutado | ¿Se oye? Sí/no |
| Selector original restaurado | ¿Se oye y coincide el estado ALSA? |
| Bandeja GNOME | Icono, menús, refresco, errores, cierre |
| Suspensión | Solo si reaparece el fallo tras actualizar Ubuntu |

Para compartir resultados, pega el JSON de `doctor --pipewire --profiles`
y las observaciones auditivas **tras revisar posibles datos personales**
en nombres de dispositivos o rutas locales. Si algún paso falla, anota qué
se veía y qué se oía: son evidencias distintas.

No añadas arranque automático de bandeja ni retires el script anterior antes
de completar y revisar esta validación.
