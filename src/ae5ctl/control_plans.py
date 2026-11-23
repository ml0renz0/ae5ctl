"""Read-only, type-aware ALSA control change plans.

A preview is never permission to write: no cset or other ALSA mutation here.
"""

from ae5ctl.alsa import AlsaBackend, AlsaError
from ae5ctl.capabilities import scan_capabilities


def normalize(control: dict, requested: str) -> list[str]:
    """Validate one requested value per control channel, using live ALSA metadata."""
    if not requested or len(requested) > 1024:
        raise AlsaError("invalid_value", "Se necesita un valor no vacío.")
    parts = [value.strip() for value in requested.split(",")]
    previous = control["values"]
    if len(parts) != len(previous) or not all(parts):
        raise AlsaError(
            "invalid_value",
            f"Se necesitan {len(previous)} valores separados por coma.",
        )
    kind = control["type"]
    if kind == "BOOLEAN":
        positives = {"on", "yes", "true", "1"}
        negatives = {"off", "no", "false", "0"}
        output = []
        for part in parts:
            if part.casefold() in positives:
                output.append("on")
            elif part.casefold() in negatives:
                output.append("off")
            else:
                raise AlsaError("invalid_value", "Booleano inválido; use on/off.")
        return output
    if kind in {"INTEGER", "INTEGER64"}:
        limits = control["range"]
        if not {"min", "max"} <= limits.keys():
            raise AlsaError("invalid_control", "Faltan límites del control.")
        minimum, maximum = limits["min"], limits["max"]
        step = limits.get("step", 0)
        if minimum > maximum or step < 0:
            raise AlsaError("invalid_control", "Límites ALSA incoherentes.")
        output = []
        for part in parts:
            if not part.removeprefix("-").isdecimal():
                raise AlsaError("invalid_value", "El valor debe ser entero.")
            value = int(part)
            if not minimum <= value <= maximum:
                raise AlsaError("invalid_value", "Valor fuera de rango ALSA.")
            if step and (value - minimum) % step:
                raise AlsaError("invalid_value", "Incremento ALSA no respetado.")
            output.append(str(value))
        return output
    if kind == "ENUMERATED":
        items = control["items"]
        output = []
        for part in parts:
            if part in items:
                output.append(part)
                continue
            matches = [
                index
                for index, label in items.items()
                if label.casefold() == part.casefold()
            ]
            if len(matches) != 1:
                code = "ambiguous_value" if matches else "invalid_value"
                raise AlsaError(code, f"Opción ALSA no única o inexistente: {part}.")
            output.append(matches[0])
        return output
    raise AlsaError(
        "unsupported_type",
        f"Tipo de control {kind!r} no soportado por el plan.",
    )


def plan_control(
    backend: AlsaBackend, *, card: str | None, numid: int, requested: str
) -> dict:
    """Produce typed before/after values and a non-authorizing semantic ID."""
    report = scan_capabilities(backend, card=card, numid=numid)
    if report["errors"]:
        first = report["errors"][0]
        raise AlsaError(first["code"], first["message"])
    if not report["ok"] or len(report["controls"]) != 1:
        raise AlsaError("no_control", "No se pudo leer el control solicitado.")
    control = report["controls"][0]
    if not control["iface"] or not control["name"]:
        raise AlsaError("invalid_control", "Falta identidad ALSA del control.")
    values = normalize(control, requested)
    current = control["values"]
    if control["type"] == "BOOLEAN":
        current = [
            "on"
            if value.casefold() in {"1", "on", "true"}
            else "off"
            if value.casefold() in {"0", "off", "false"}
            else value
            for value in current
        ]
    return {
        "schema_version": 1,
        "scope": "alsa_control_plan",
        "dry_run": True,
        "card": report["card"],
        "identity": {
            "card_id": report["card"]["id"],
            "iface": control["iface"],
            "name": control["name"],
            "index": control["index"],
            "device": control["device"],
            "subdevice": control["subdevice"],
        },
        "lookup_numid": control["numid"],
        "type": control["type"],
        "previous_values": current,
        "requested_values": values,
        "changed": current != values,
        "write_policy": control["write_policy"],
        "driver_reports_writable": control["driver_reports_writable"],
        "can_apply": False,
        "reason": (
            "Control restringido; no se permiten escrituras."
            if control["write_policy"] == "blocked"
            else "Control pendiente de validación en la AE-5 física."
        ),
        "notes": [
            "Solo lectura: este plan nunca llama a amixer cset.",
            "El numid no es una identidad estable para presets.",
        ],
    }
