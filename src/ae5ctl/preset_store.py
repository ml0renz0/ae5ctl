"""Versioned, non-executable, user-scoped AE-5 presets.

Presets describe desired ALSA values by *semantic* control identity. They
never authorize a cset, load Python, or apply a driver/firmware setting.
"""

import json
import os
import re
import tempfile
from pathlib import Path

from ae5ctl.alsa import AlsaError
from ae5ctl.capabilities import scan_capabilities
from ae5ctl.control_plans import normalize

SCHEMA_VERSION = 1
MAX_BYTES = 128 * 1024
MAX_CONTROLS = 64
MAX_VALUES = 16
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z")
IDENTITY = ("iface", "name", "index", "device", "subdevice")
TYPES = {"BOOLEAN", "INTEGER", "INTEGER64", "ENUMERATED"}


class PresetError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _dict(value, fields, required):
    if (
        type(value) is not dict
        or not required <= value.keys()
        or not value.keys() <= fields
    ):
        raise PresetError("invalid_preset", "Estructura JSON del preset inválida.")


def _string(value, label, limit=128):
    if type(value) is not str or not value or len(value) > limit or "\0" in value:
        raise PresetError("invalid_preset", f"Campo {label} inválido.")
    return value


def _name(value):
    if type(value) is not str or not NAME_PATTERN.fullmatch(value):
        raise PresetError(
            "invalid_name",
            "Nombre inválido: use 1-48 letras ASCII, números, - o _.",
        )
    return value


def _key(entry):
    return tuple(entry["identity"][field] for field in IDENTITY)


def validate(document):
    """Strict schema: unknown fields, duplicate controls, unsafe types are rejected."""
    _dict(
        document,
        {"schema_version", "name", "description", "card_id", "controls"},
        {"schema_version", "name", "card_id", "controls"},
    )
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise PresetError("unsupported_schema", "Versión del preset no soportada.")
    _name(document["name"])
    _string(document["card_id"], "card_id", 64)
    desc = document.get("description", "")
    if type(desc) is not str or len(desc) > 500 or "\0" in desc:
        raise PresetError("invalid_preset", "Descripción inválida.")
    entries = document["controls"]
    if type(entries) is not list or len(entries) > MAX_CONTROLS:
        raise PresetError("invalid_preset", "El preset excede el límite de controles.")
    seen = set()
    for entry in entries:
        _dict(entry, {"identity", "type", "values"}, {"identity", "type", "values"})
        identity = entry["identity"]
        _dict(identity, set(IDENTITY), set(IDENTITY))
        _string(identity["iface"], "iface", 32)
        _string(identity["name"], "nombre de control")
        for field in ("index", "device", "subdevice"):
            value = identity[field]
            if type(value) is not int or not 0 <= value <= 65535:
                raise PresetError(
                    "invalid_preset", f"Coordenada ALSA {field} inválida."
                )
        if _key(entry) in seen:
            raise PresetError("duplicate_control", "El preset repite un control.")
        seen.add(_key(entry))
        if type(entry["type"]) is not str or entry["type"] not in TYPES:
            raise PresetError(
                "unsupported_type", "Tipo ALSA no compatible con presets."
            )
        values = entry["values"]
        if type(values) is not list or not 1 <= len(values) <= MAX_VALUES:
            raise PresetError("invalid_preset", "Número de valores ALSA inválido.")
        for value in values:
            _string(value, "valor de control")
    return document


def _decode(text: str):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise PresetError("duplicate_json_key", f"Clave JSON duplicada: {key}.")
            obj[key] = value
        return obj

    try:
        return validate(json.loads(text, object_pairs_hook=unique))
    except (ValueError, TypeError, RecursionError) as exc:
        raise PresetError(
            "invalid_json", "No se pudo interpretar el JSON del preset."
        ) from exc


def _load(path: Path):
    if path.is_symlink() or not path.is_file():
        raise PresetError(
            "file_missing", "Fichero inexistente o enlace simbólico no permitido."
        )
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError as exc:
        raise PresetError("file_error", f"No se pudo leer {path.name}: {exc}") from exc
    if len(raw) > MAX_BYTES:
        raise PresetError("file_too_large", "Preset demasiado grande.")
    try:
        return _decode(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise PresetError("invalid_json", "El preset debe estar en UTF-8.") from exc


def _write(path: Path, document: dict, *, overwrite=False):
    validate(document)
    raw = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise PresetError("file_too_large", "Preset demasiado grande.")
    parent = path.parent
    if parent.is_symlink():
        raise PresetError("unsafe_directory", "Directorio de presets enlazado.")
    tmp = None
    try:
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if parent.is_symlink() or not parent.is_dir():
            raise PresetError("unsafe_directory", "Directorio de presets inseguro.")
        with tempfile.NamedTemporaryFile(
            dir=parent, prefix=".ae5ctl-", delete=False
        ) as out:
            tmp = Path(out.name)
            os.fchmod(out.fileno(), 0o600)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        if overwrite:
            os.replace(tmp, path)
        else:
            # Atomic create without replacing an existing file, including links.
            os.link(tmp, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise PresetError(
            "already_exists", "Ya existe un preset con ese nombre."
        ) from exc
    except OSError as exc:
        raise PresetError(
            "file_error", f"No se pudo guardar {path.name}: {exc}"
        ) from exc
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


class PresetStore:
    def __init__(self, root=None):
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        self.root = Path(root) if root is not None else base / "ae5ctl" / "presets"

    def _path(self, name):
        if self.root.is_symlink():
            raise PresetError("unsafe_directory", "Directorio de presets enlazado.")
        return self.root / (_name(name) + ".json")

    def list(self):
        if not self.root.exists():
            return []
        if self.root.is_symlink() or not self.root.is_dir():
            raise PresetError("unsafe_directory", "Directorio de presets inseguro.")
        result = []
        for path in sorted(self.root.glob("*.json")):
            doc = _load(path)
            if path.stem != doc["name"]:
                raise PresetError(
                    "invalid_preset", "Nombre de archivo y preset no coinciden."
                )
            result.append(
                {
                    "name": doc["name"],
                    "card_id": doc["card_id"],
                    "description": doc.get("description", ""),
                    "controls": len(doc["controls"]),
                }
            )
        return result

    def read(self, name):
        doc = _load(self._path(name))
        if doc["name"] != name:
            raise PresetError(
                "invalid_preset", "Nombre de preset no coincide con el archivo."
            )
        return doc

    def save(self, document, *, overwrite=False):
        validate(document)
        _write(self._path(document["name"]), document, overwrite=overwrite)
        return document

    def duplicate(self, source, destination):
        """Copy one validated preset without touching the source or ALSA."""
        document = self.read(source)
        document["name"] = _name(destination)
        return self.save(document)

    def delete(self, name):
        path = self._path(name)
        if path.is_symlink() or not path.is_file():
            raise PresetError("file_missing", "Preset no encontrado.")
        try:
            path.unlink()
        except OSError as exc:
            raise PresetError(
                "file_error", f"No se pudo borrar el preset: {exc}"
            ) from exc

    def import_file(self, source, *, overwrite=False):
        return self.save(_load(Path(source)), overwrite=overwrite)

    def export_file(self, name, destination, *, overwrite=False):
        doc = self.read(name)
        _write(Path(destination), doc, overwrite=overwrite)
        return doc


def new_preset(name, card_id, description=""):
    return validate(
        {
            "schema_version": SCHEMA_VERSION,
            "name": name,
            "description": description,
            "card_id": card_id,
            "controls": [],
        }
    )


def _semantic(control):
    return {name: control[name] for name in IDENTITY}


def _values_for_preset(control, requested):
    normalized = normalize(control, requested)
    if control["type"] == "ENUMERATED":
        return [control["items"][value] for value in normalized]
    return normalized


def read_control(backend, card_id, numid, desired=None):
    """Read exactly one control; persist semantic identity, never numid."""
    report = scan_capabilities(backend, card=card_id, numid=numid)
    if not report["ok"]:
        error = report["errors"][0]
        raise AlsaError(error["code"], error["message"])
    if len(report["controls"]) != 1:
        raise PresetError(
            "control_missing", "El control solicitado no está disponible."
        )
    if report["card"]["id"] != card_id:
        raise PresetError("card_mismatch", "Identidad de tarjeta inesperada.")
    control = report["controls"][0]
    if desired is None:
        desired = ",".join(control["values"])
    return {
        "identity": _semantic(control),
        "type": control["type"],
        "values": _values_for_preset(control, desired),
    }


def set_control(document, entry):
    """Replace a semantically identical control or append a new one."""
    validate(document)
    validate(
        {
            "schema_version": 1,
            "name": "test",
            "card_id": document["card_id"],
            "controls": [entry],
        }
    )
    controls = document["controls"]
    for index, previous in enumerate(controls):
        if _key(previous) == _key(entry):
            if previous["type"] != entry["type"]:
                raise PresetError("control_changed", "El tipo de control ha cambiado.")
            controls[index] = entry
            break
    else:
        if len(controls) >= MAX_CONTROLS:
            raise PresetError("invalid_preset", "Límite de controles alcanzado.")
        controls.append(entry)
    controls.sort(key=_key)
    return validate(document)


def remove_control(document, control_name):
    _string(control_name, "nombre de control")
    matching = [
        entry
        for entry in document["controls"]
        if entry["identity"]["name"] == control_name
    ]
    if not matching:
        raise PresetError("control_missing", "El preset no contiene ese control.")
    if len(matching) > 1:
        raise PresetError(
            "ambiguous_control",
            "Nombre duplicado; es necesario identificar el control.",
        )
    document["controls"].remove(matching[0])
    return validate(document)


def compare(document, backend):
    """Read-only semantic diff against ONE ALSA card; NEVER apply values."""
    validate(document)
    report = scan_capabilities(backend, card=document["card_id"])
    return compare_report(document, report)


def compare_report(document, report):
    """Compare with a previously fetched ALSA snapshot; no further hardware IO."""
    validate(document)
    if not report["ok"]:
        error = report["errors"][0]
        raise AlsaError(error["code"], error["message"])
    if report["card"]["id"] != document["card_id"]:
        raise PresetError("card_mismatch", "La identidad de tarjeta no coincide.")
    indexed = {}
    for control in report["controls"]:
        indexed.setdefault(tuple(control[name] for name in IDENTITY), []).append(
            control
        )
    results = []
    compatible = True
    for entry in document["controls"]:
        matches = indexed.get(_key(entry), [])
        item = {
            "identity": dict(entry["identity"]),
            "type": entry["type"],
            "requested_values": list(entry["values"]),
            "current_values": None,
            "status": None,
            "write_policy": None,
        }
        if len(matches) != 1:
            item["status"] = "missing" if not matches else "ambiguous"
            compatible = False
        elif matches[0]["type"] != entry["type"]:
            item["status"] = "type_mismatch"
            compatible = False
        else:
            live = matches[0]
            try:
                wanted = normalize(live, ",".join(entry["values"]))
            except AlsaError:
                item["status"] = "incompatible_value"
                compatible = False
            else:
                current = normalize(live, ",".join(live["values"]))
                item["current_values"] = current
                item["requested_values"] = wanted
                item["write_policy"] = live["write_policy"]
                item["status"] = "same" if current == wanted else "different"
                if live["write_policy"] == "blocked":
                    item["status"] = "restricted"
                    compatible = False
        results.append(item)
    return {
        "schema_version": 1,
        "scope": "alsa_preset_diff",
        "preset": document["name"],
        "card_id": document["card_id"],
        "compatible": compatible,
        "can_apply": False,
        "controls": results,
        "summary": {
            "total": len(results),
            "same": sum(entry["status"] == "same" for entry in results),
            "different": sum(entry["status"] == "different" for entry in results),
            "unavailable": sum(
                entry["status"] not in {"same", "different"} for entry in results
            ),
        },
        "notes": [
            "Comparación únicamente: no se ha escrito ningún control ALSA.",
            "Ningún preset autoriza aplicar controles sin certificar.",
        ],
    }


def overview(store: PresetStore, backend, *, card_id: str | None = None) -> dict:
    """One read-only hardware scan per ALSA card for all saved presets.

    A matching preset is NOT proof of audible audio or an applied preset.
    Errors are recorded per card and never cause a write or a false match.
    """
    if card_id is not None:
        _string(card_id, "card_id", 64)
    presets = [
        entry
        for entry in store.list()
        if card_id is None or entry["card_id"] == card_id
    ]
    reports = {}
    results = []
    errors = []
    for item in presets:
        card = item["card_id"]
        if card not in reports:
            try:
                reports[card] = scan_capabilities(backend, card=card)
            except AlsaError as exc:
                reports[card] = {
                    "ok": False,
                    "errors": [{"code": exc.code, "message": str(exc)}],
                }
        report = reports[card]
        entry = {
            "name": item["name"],
            "description": item["description"],
            "card_id": card,
            "control_count": item["controls"],
            "status": "unavailable",
            "compatible": False,
            "can_apply": False,
            "summary": None,
        }
        if not report["ok"]:
            issue = (
                report["errors"][0]
                if report.get("errors")
                else {
                    "code": "inventory_incomplete",
                    "message": "El inventario ALSA no está completo.",
                }
            )
            entry["error"] = issue
            if not any(error["card_id"] == card for error in errors):
                errors.append({"card_id": card, **issue})
        else:
            diff = compare_report(store.read(item["name"]), report)
            entry["compatible"] = diff["compatible"]
            entry["summary"] = diff["summary"]
            if not item["controls"]:
                entry["status"] = "empty"
            elif not diff["compatible"]:
                entry["status"] = "incompatible"
            elif diff["summary"]["different"]:
                entry["status"] = "different"
            else:
                entry["status"] = "matching"
        results.append(entry)
    return {
        "schema_version": 1,
        "scope": "alsa_preset_overview",
        "ok": not errors,
        "read_only": True,
        "can_apply": False,
        "presets": results,
        "errors": errors,
        "summary": {
            "total": len(results),
            "matching": sum(p["status"] == "matching" for p in results),
            "different": sum(p["status"] == "different" for p in results),
            "incompatible": sum(p["status"] == "incompatible" for p in results),
            "unavailable": sum(p["status"] == "unavailable" for p in results),
            "empty": sum(p["status"] == "empty" for p in results),
            "scanned_cards": len(reports),
        },
        "notes": [
            "Vista de solo lectura. Coincidir no significa que el audio sea audible.",
            "No se ha seleccionado, cargado ni aplicado ningún preset.",
            "La extensión GNOME no debe tratar matching como perfil activo.",
        ],
    }
