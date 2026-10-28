#!/bin/sh
# Run only inside a disposable Debian/Ubuntu container as root.
set -eu

if [ "$(id -u)" -ne 0 ] || [ ! -f /.dockerenv ]; then
    echo "Ejecuta esta prueba dentro de un contenedor desechable como root." >&2
    exit 1
fi
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo "Uso: sh smoke_deb.sh /ruta/paquete.deb" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends "$1"
test "$(dpkg-query -W -f='${Status}' ae5ctl)" = "install ok installed"
ae5ctl --help
python3 -m ae5ctl --help
ae5ctl cards --json > /tmp/ae5ctl-cards.json
python3 - <<'PY'
import json
from pathlib import Path

report = json.loads(Path('/tmp/ae5ctl-cards.json').read_text())
assert isinstance(report['cards'], list)
PY

# A container without /proc/asound/cards must report missing hardware explicitly.
if [ ! -e /proc/asound/cards ]; then
    result=0
    ae5ctl doctor --json > /tmp/ae5ctl-doctor.json || result=$?
    test "$result" -eq 3
    python3 - <<'PY'
import json
from pathlib import Path

report = json.loads(Path('/tmp/ae5ctl-doctor.json').read_text())
assert report['ok'] is False
assert report['errors'][0]['code'] == 'no_card'
PY
fi

command -v amixer
test -d /usr/lib/python3/dist-packages/ae5ctl/__pycache__
apt-get remove -y ae5ctl
test ! -e /usr/bin/ae5ctl
test ! -e /usr/lib/python3/dist-packages/ae5ctl
echo "PASS: instalación, CLI y eliminación completas del paquete Debian."
