"""Read-only, versioned ALSA capability inventory for the future GNOME UI.

No cset, alsactl, sudo, shell=True, mixer write or DSP change is permitted.
Driver-reported rw access is *not* authority to write a control.
"""

import re
from collections import Counter
from dataclasses import asdict

from ae5ctl.alsa import AlsaBackend, AlsaError, _header

MAX_CONTROLS = 512
MAX_LIST_CHARS = 128 * 1024
MAX_CGET_CHARS = 32 * 1024

_TYPE = re.compile(r"\btype=([A-Z][A-Z0-9_]*)\b")
_ACCESS = re.compile(r"\baccess=([^,\s]+)")
_VALUE_COUNT = re.compile(r"\bvalues=(\d+)\b")
_ITEM_COUNT = re.compile(r"\bitems=(\d+)\b")
_RANGE = re.compile(r"\b(min|max|step)=(-?\d+)\b")
_INTERFACE = re.compile(r"(?:^|,)iface=([^,]+)")
_COORDINATES = {
    name: re.compile(rf"(?:^|,){name}=(\\d+)(?:,|$)")
    for name in ("index", "device", "subdevice")
}
_ITEMS = re.compile(r"^\s*;\s*Item #(\d+) '(.*)'\s*$")
_VALUES = re.compile(r"^\s*:\s*values=(.*)$")
_BLOCKED = re.compile(
    r"out[ -]?fx|direct[ -]?mode|rgb|led|gpio|firmware|flash|"
    r"headphone\s+(?:impedance|gain)|output\s+gain",
    re.IGNORECASE,
)
_FAMILIES = (
    ("equalizer", re.compile(r"equaliz|\beq\b|eq preset|tone control", re.I)),
    (
        "dsp",
        re.compile(
            r"crystal|surround|x[ -]?bass|smart vol|dialog|sbx|"
            r"scout|sound filter|acoustic|effect|\bfx\b",
            re.I,
        ),
    ),
    ("recording", re.compile(r"microphone|\bmic\b|input|record|capture", re.I)),
    ("routing", re.compile(r"output|speaker|headphone|route|channel|port", re.I)),
    ("levels", re.compile(r"volume|gain|boost|mute|level|playback switch", re.I)),
    ("lighting", re.compile(r"rgb|led|light|strip", re.I)),
)


def classify(name: str) -> tuple[str, str]:
    """Conservative hints, not claims about control behavior or write safety."""
    if _BLOCKED.search(name):
        return "restricted", "blocked"
    for family, pattern in _FAMILIES:
        if pattern.search(name):
            return family, "unverified"
    return "other", "unverified"


def _coordinate(header: str, key: str) -> int:
    found = _COORDINATES[key].search(header)
    return int(found[1]) if found else 0


def parse_control_detail(text: str, expected_numid: int) -> dict:
    """Parse cget metadata and current values; unknown kinds stay opaque."""
    if len(text) > MAX_CGET_CHARS:
        raise AlsaError("parse_error", "Respuesta cget excesivamente grande.")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise AlsaError("parse_error", "Respuesta cget vacía.")
    numid, name = _header(lines[0])
    if numid != expected_numid:
        raise AlsaError("parse_error", "cget devolvió un numid distinto.")
    iface = _INTERFACE.search(lines[0])
    metadata = [line for line in lines[1:] if _TYPE.search(line)]
    if len(metadata) != 1:
        raise AlsaError("parse_error", "cget sin metadatos de tipo únicos.")
    control_type = _TYPE.search(metadata[0])[1]
    access_match = _ACCESS.search(metadata[0])
    access = access_match[1] if access_match else None
    count_match = _VALUE_COUNT.search(metadata[0])
    count = int(count_match[1]) if count_match else None
    limits = {key: int(value) for key, value in _RANGE.findall(metadata[0])}
    item_labels: dict[int, str] = {}
    selections: list[str] | None = None
    for line in lines[1:]:
        item = _ITEMS.match(line)
        value = _VALUES.match(line)
        if item:
            index = int(item[1])
            if index in item_labels:
                raise AlsaError("parse_error", "cget incluye opciones duplicadas.")
            item_labels[index] = item[2]
        elif value:
            if selections is not None:
                raise AlsaError("parse_error", "cget incluye valores duplicados.")
            selections = [part.strip() for part in value[1].split(",")]
    if selections is None or any(not value for value in selections):
        raise AlsaError("parse_error", "cget sin valor actual interpretable.")
    if count is not None and count != len(selections):
        raise AlsaError("parse_error", "cget tiene un número de valores incoherente.")
    if control_type == "ENUMERATED":
        count_items = _ITEM_COUNT.search(metadata[0])
        if (
            count_items is None
            or int(count_items[1]) != len(item_labels)
            or not item_labels
            or set(item_labels) != set(range(len(item_labels)))
        ):
            raise AlsaError("parse_error", "cget enumerado incompleto.")
        if any(not v.isdecimal() or int(v) not in item_labels for v in selections):
            raise AlsaError("parse_error", "cget enumerado contiene índices inválidos.")
    family, policy = classify(name)
    return {
        "numid": numid,
        "name": name,
        "iface": iface[1] if iface else None,
        "index": _coordinate(lines[0], "index"),
        "device": _coordinate(lines[0], "device"),
        "subdevice": _coordinate(lines[0], "subdevice"),
        "type": control_type,
        "access": access,
        "driver_reports_writable": bool(access and "w" in access[:2]),
        "values": selections,
        "items": {str(key): item_labels[key] for key in sorted(item_labels)},
        "range": limits,
        "family": family,
        "write_policy": policy,
        "editable_by_ae5ctl": False,
    }


def scan_capabilities(
    backend: AlsaBackend,
    *,
    card: str | None = None,
    numid: int | None = None,
) -> dict:
    """Inventory exactly one selected ALSA card, without changing audio."""
    selected = backend._select_card(card)
    if numid is not None:
        if numid < 1:
            raise AlsaError("no_control", "numid debe ser un entero positivo.")
        numbers = [numid]
    else:
        listing = backend._read(selected, "controls")
        if len(listing) > MAX_LIST_CHARS:
            raise AlsaError("parse_error", "Demasiados datos en amixer controls.")
        numbers = []
        seen: set[int] = set()
        for line in listing.splitlines():
            if not line.strip():
                continue
            number, _name = _header(line)
            if number in seen:
                raise AlsaError(
                    "parse_error", "amixer controls incluye numid duplicado."
                )
            seen.add(number)
            numbers.append(number)
            if len(numbers) > MAX_CONTROLS:
                raise AlsaError("parse_error", "Demasiados controles ALSA.")
    controls = []
    errors = []
    for number in numbers:
        try:
            text = backend._read(selected, "cget", f"numid={number}")
            controls.append(parse_control_detail(text, number))
        except AlsaError as error:
            errors.append({"numid": number, "code": error.code, "message": str(error)})
    families = Counter(control["family"] for control in controls)
    return {
        "schema_version": 1,
        "scope": "alsa_capabilities",
        "ok": not errors,
        "card": asdict(selected),
        "controls": controls,
        "errors": errors,
        "summary": {
            "discovered": len(controls),
            "failed": len(errors),
            "by_family": dict(sorted(families.items())),
            "driver_reports_writable": sum(
                c["driver_reports_writable"] for c in controls
            ),
            "editable_by_ae5ctl": 0,
            "blocked": sum(c["write_policy"] == "blocked" for c in controls),
        },
        "notes": [
            "Inventario de solo lectura; no se ha ejecutado cset ni alsactl.",
            "access=rw indica capacidad del driver, NO seguridad de escritura.",
            "Las familias se infieren por nombres; no prueban soporte funcional.",
            "OutFX, Direct Mode, ganancia sensible y RGB quedan bloqueados.",
            "El índice y numid pueden cambiar: no se deben persistir como identidad.",
        ],
    }
