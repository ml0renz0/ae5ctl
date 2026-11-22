# Paquetes .deb y firma OpenSSL

El paquete contiene la CLI de lectura y conmutación del selector ALSA y el
subcomando opcional `tray` y el comparador `profiles diff`. Este último usa
solo Python estándar y lee archivos del usuario; no requiere ALSA conectada.
No instala las dependencias GTK automáticamente ni
incluye perfiles de audio, servicios, reglas de suspensión o reparación automática.
`doctor --pipewire` necesita `pactl` (`pulseaudio-utils`) solo cuando se solicita;
ambos conjuntos de dependencias opcionales se indican mediante `Suggests`.
La licencia sigue pendiente de elección. La publicación automática de builds
no concede por sí misma permisos de redistribución del código.

## Generar e instalar

Desde la raíz del proyecto, con Python >= 3.11 y `dpkg-deb` disponible:

```bash
python3 packaging/build_deb.py
```

La generación no usa root ni descarga dependencias. La versión se obtiene de
`pyproject.toml`: `0.1.0.dev0` pasa a `0.1.0~dev0-1` para respetar el orden de
versiones Debian. Se admiten versiones numéricas estables y `.devN`; otras
variantes se rechazan hasta definir su conversión. Para una nueva revisión del
mismo código upstream:

```bash
python3 packaging/build_deb.py --revision 2 --output-dir dist
```

El archivo usa la versión Python: `ae5ctl_0.1.0.dev0-1_all.deb`. El campo
`Version` interno conserva `0.1.0~dev0-1`; APT usa ese campo para ordenar las
versiones. GitHub Releases sustituye `~` en los nombres de archivos, lo que
rompería la referencia del checksum tras la descarga. Por eso el nombre usa
`.devN` y, si una revisión contiene `~`, lo representa como `_`. Como `_` no se
admite en la revisión de entrada, `1~x` y `1.x` generan nombres distintos.

La arquitectura `all` significa que el contenido Python es independiente de la
CPU; la instalación necesita Linux con Python >= 3.10 y `alsa-utils`. La CLI se
instala en `/usr/bin/ae5ctl`, los módulos en
`/usr/lib/python3/dist-packages/ae5ctl` y la documentación en
`/usr/share/doc/ae5ctl`. Los scripts de instalación y retirada solo gestionan
bytecode Python; no modifican el audio.

```bash
cd dist
sha256sum -c ae5ctl_0.1.0.dev0-1_all.deb.sha256
sudo apt install ./ae5ctl_0.1.0.dev0-1_all.deb
ae5ctl --help
ae5ctl doctor --json
sudo apt remove ae5ctl
```

`doctor` devuelve código 3 y `no_card` si no hay tarjeta ALSA. Eso es un resultado
de diagnóstico esperado, no una confirmación de audio funcional.

El generador toma `SOURCE_DATE_EPOCH` del entorno o del último commit Git. Sin
historial Git hay que proporcionarlo explícitamente. Dos ejecuciones con el
mismo contenido, fecha, versión y herramientas producen el mismo archivo:

```bash
SOURCE_DATE_EPOCH=1700000000 python3 packaging/build_deb.py --output-dir /tmp/deb-a
SOURCE_DATE_EPOCH=1700000000 python3 packaging/build_deb.py --output-dir /tmp/deb-b
cmp /tmp/deb-a/ae5ctl_0.1.0.dev0-1_all.deb /tmp/deb-b/ae5ctl_0.1.0.dev0-1_all.deb
```

## Clave privada cifrada

Puedes reutilizar tu clave PEM de OpenSSL si es adecuada para firmar. Para crear
una nueva clave RSA de 3072 bits en tu equipo, fuera del checkout:

```bash
install -d -m 700 "$HOME/.config/ae5ctl/signing"
umask 077
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 \
  -aes-256-cbc -out "$HOME/.config/ae5ctl/signing/private.pem"
```

OpenSSL pedirá la contraseña de forma interactiva. No la escribas en argumentos,
en archivos versionados ni en el chat. Conserva una copia segura de la clave.
No se genera ninguna clave permanente durante la construcción del paquete.

Para usar el script de firma, proporciona la contraseña mediante un archivo
privado fuera del repositorio. Este ejemplo de Bash lo crea temporalmente sin
imprimirla ni guardarla en el historial como argumento:

```bash
umask 077
password_file=$(mktemp)
trap 'rm -f -- "$password_file"' EXIT
read -r -s -p 'Contraseña de la clave: ' signing_password
printf '\n'
printf '%s' "$signing_password" > "$password_file"
unset signing_password
python3 packaging/sign_deb.py dist/ae5ctl_0.1.0.dev0-1_all.deb \
  --key "$HOME/.config/ae5ctl/signing/private.pem" \
  --passphrase-file "$password_file" \
  --public-key-output dist/signing-public.pem
rm -f -- "$password_file"
trap - EXIT
```

El script crea `PAQUETE.deb.sig`, exporta opcionalmente la clave pública y
comprueba la firma antes de publicarla en la carpeta de salida. No registra la
contraseña ni modifica el `.deb`. Si reconstruyes el paquete con contenido
distinto, debes volver a firmarlo.

## Verificar

Obtén la clave pública por un canal de confianza y verifica el archivo exacto
antes de instalarlo:

```bash
openssl dgst -sha256 -verify signing-public.pem \
  -signature ae5ctl_0.1.0.dev0-1_all.deb.sig \
  ae5ctl_0.1.0.dev0-1_all.deb
```

El resultado debe ser `Verified OK` y código de salida 0. Un checksum SHA-256
detecta cambios, pero por sí solo no autentica al autor. La firma separada de
OpenSSL no es una firma GPG de Debian ni un repositorio APT firmado; `apt install`
no comprueba este `.sig` automáticamente.

## CI/CD: Debian bajo demanda

Las PR sin etiqueta y los pushes normales a `main` ejecutan Ruff, pytest
(sin pruebas de empaquetado) y `CI required`. No construyen archivos `.deb`.
El empaquetado tiene únicamente dos activadores explícitos:

- **Etiqueta de PR `build-deb`:** ejecutar pruebas de empaquetado, generar
  un `.deb` y comprobar la instalación y retirada en contenedores Ubuntu
  22.04 y 24.04. Si se quita la etiqueta, los siguientes commits de esa PR
  ya no generan paquetes. La PR #4 no lleva la etiqueta.
- **Etiqueta Git de versión `v<version>`:** iniciar una release desde el
  código ya fusionado en `main`. El nombre debe coincidir exactamente
  con `[project].version` de `pyproject.toml` y el commit debe pertenecer
  a `main`. Por ejemplo, para `0.1.0.dev0`:

  ```bash
  git switch main
  git pull --ff-only
  git tag -a v0.1.0.dev0 -m "ae5ctl 0.1.0.dev0"
  git push origin v0.1.0.dev0
  ```

  Solo entonces se prueban y generan los paquetes para su firma y publicación
  en GitHub Releases. Se reutiliza la **misma etiqueta Git**, sin inventar
  ninguna `build-<run>` adicional.

El check estable `CI required` continúa siendo el requisito de protección de
`main`. Exige Python/lint siempre y, cuando se haya pedido expresamente
Debian con una etiqueta, también exige que pasen sus pruebas y ambos smoke tests.
Sin etiqueta, espera que el job Debian figure como `skipped`.

**No se emplea `upload-artifact` ni `download-artifact` para los paquetes.**
El `.deb` de validación permanece en el runner temporal y se elimina al acabar
el job. El job exclusivo de release reconstruye la misma versión y revisión
desde la misma etiqueta, firma el paquete y deja los cuatro archivos
(`.deb`, `.deb.sha256`, `.deb.sig`, `signing-public.pem`) únicamente en
GitHub Releases. Esto evita consumir almacenamiento de artefactos de Actions;
los logs y la caché de pip mantienen su propia política de retención.

Las pruebas que crean paquetes se marcan `package` y están excluidas incluso
del pytest predeterminado en local:

```bash
python -m pytest                   # Sin compilar .deb
python -m pytest -m package        # Pruebas de empaquetado bajo demanda
python3 packaging/build_deb.py    # Construcción manual explícita
```

Las PR no reciben secretos de firma ni permisos de publicación. Solo el job de
release etiquetada usa `contents: write` y los secretos. La release comienza
como borrador y se publica después de descargar y verificar checksums y firma.
Las releases y etiquetas históricas no se eliminan al introducir este cambio.

### Secretos de firma

Los secretos del repositorio usados por el job de publicación son:

- `DEB_SIGNING_KEY`: contenido PEM de tu clave privada cifrada.
- `DEB_SIGNING_PASSWORD`: contraseña de esa clave.

La firma solo se ejecuta tras validar una etiqueta Git de versión. Si falta
algún secreto o la clave no funciona, el job falla antes de crear la release. Los
archivos privados se crean en el directorio temporal del runner, con permisos
restringidos, y se eliminan al terminar el paso. Se publican solamente el `.deb`,
su checksum, la firma y la clave pública. Las claves privadas nunca forman parte
de los artefactos.

Las claves temporales usadas en los tests son exclusivamente de prueba y no se
conservan como claves de distribución. Los secretos se suministran por la
configuración segura de GitHub, nunca mediante el chat.
