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

## 2. Prueba auditiva de la CLI

Con una muestra de música o de audio reproduciéndose **por tu cuenta** desde
Ubuntu y un volumen moderado, ejecuta:

```bash
.venv/bin/ae5ctl validate --apply --card ID_ALSA
```

El asistente identifica el selector, pregunta si oyes la salida actual y
requiere teclear **CAMBIAR** antes de escribir. Tras alternar el control,
pregunta si se oye la salida de destino. A continuación intenta restaurar
la selección ALSA original **aunque la otra salida no se oiga o pulses
Ctrl+C**. Por último pregunta si vuelve a escucharse la salida inicial.

- Sin `--apply`: solo lecturas, ninguna pregunta ni escritura.
- Sin respuesta afirmativa o sin autorización `CAMBIAR`: ninguna escritura.
- Si otro programa cambia el selector durante la preparación, el motor rechaza
  la escritura obsoleta. Evita acciones simultáneas en la bandeja.
- Si la tarjeta se desconecta o cambia de identidad, la restauración puede
  fallar: se indica expresamente y debes revisar `ae5ctl status`.
- La recuperación automática se refiere **solo al selector ALSA**, nunca a
  perfiles completos, volúmenes, DSP ni rutas de PipeWire.
- Código 0: respuestas auditivas afirmativas y valor ALSA inicial confirmado.
  Código 5: prueba incompleta/no satisfactoria. 130: interrumpida.

No se envía sonido de prueba desde la herramienta. Escuchar es la única manera
de confirmar en esta fase qué conector está funcionando. El resultado por sí
solo **no valida la equivalencia con el script antiguo**.

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
