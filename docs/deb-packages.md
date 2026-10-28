# Paquetes .deb y firma OpenSSL

El paquete actual contiene la CLI de lectura ALSA. No incluye la bandeja GTK,
perfiles de audio, servicios, reglas de suspensión ni recuperación automática.
La licencia sigue pendiente de elección; generar el artefacto de desarrollo no
equivale a publicarlo ni a conceder permisos de redistribución.

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

La arquitectura `all` significa que el contenido Python es independiente de la
CPU; la instalación necesita Linux con Python >= 3.10 y `alsa-utils`. La CLI se
instala en `/usr/bin/ae5ctl`, los módulos en
`/usr/lib/python3/dist-packages/ae5ctl` y la documentación en
`/usr/share/doc/ae5ctl`. Los scripts de instalación y retirada solo gestionan
bytecode Python; no modifican el audio.

```bash
cd dist
sha256sum -c ae5ctl_0.1.0~dev0-1_all.deb.sha256
sudo apt install ./ae5ctl_0.1.0~dev0-1_all.deb
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
cmp /tmp/deb-a/ae5ctl_0.1.0~dev0-1_all.deb /tmp/deb-b/ae5ctl_0.1.0~dev0-1_all.deb
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
python3 packaging/sign_deb.py dist/ae5ctl_0.1.0~dev0-1_all.deb \
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
  -signature ae5ctl_0.1.0~dev0-1_all.deb.sig \
  ae5ctl_0.1.0~dev0-1_all.deb
```

El resultado debe ser `Verified OK` y código de salida 0. Un checksum SHA-256
detecta cambios, pero por sí solo no autentica al autor. La firma separada de
OpenSSL no es una firma GPG de Debian ni un repositorio APT firmado; `apt install`
no comprueba este `.sig` automáticamente.

## GitHub Actions

El workflow **Debian package** se ejecuta manualmente desde Actions. Genera el
paquete, comprueba instalación y eliminación en contenedores Ubuntu 22.04 y
24.04, y guarda el artefacto `ae5ctl-deb`. No publica releases ni un repositorio
APT.

Para activar su opción `sign`, configura estos secretos del repositorio:

- `DEB_SIGNING_KEY`: contenido PEM de tu clave privada cifrada.
- `DEB_SIGNING_PASSWORD`: contraseña de esa clave.

La firma solo se ejecuta al solicitarla. Si falta algún secreto o la clave no
funciona, el job falla; no publica un paquete presentado como firmado. Los
archivos privados se crean en el directorio temporal del runner, con permisos
restringidos, y se eliminan al terminar el paso. El artefacto contiene solamente
el `.deb`, su `.sha256` y, si se firmó, el `.sig` y la clave pública.

Las claves temporales usadas en los tests son exclusivamente de prueba y no se
conservan como claves de distribución. La firma con tu identidad queda pendiente
hasta que proporciones los secretos por la configuración segura de GitHub.
