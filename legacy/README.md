# Script original

`ae5-switcher.py` se conserva tal como aparece en el traspaso del 27 de octubre
 de 2026. No forma parte del paquete nuevo ni se importa desde la CLI.

Requiere Linux, GTK3, AppIndicator3, ALSA y una sesión gráfica. Ejecutarlo puede
restaurar perfiles ALSA y modificar el audio. No ejecutarlo en CI.

Limitaciones conocidas: `shell=True`, restauración sin limitar tarjeta, lectura
incorrecta de índices enumerados y dependencia de marcadores/perfiles locales.
Las pruebas aíslan GTK y simulan las llamadas externas; no validan hardware.
