"""Read-only comparison of alsactl store snapshots (never restore profiles)."""

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

HEADPHONES_FILE = Path("~/.config/ae5-headphones.state")
SPEAKERS_FILE = Path("~/.config/ae5-speakers.state")
MAX_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 12

_ROUTING = re.compile(r"output|route|selector|mux|port|channel|jack", re.I)
_LEVEL = re.compile(r"volume|gain|boost|attenuat|level|mute|playback switch", re.I)
_DSP = re.compile(
    r"crystal|surround|equaliz|eq\\b|bass|treble|scout|dialog|effect|dsp",
    re.I,
)


class ProfileError(Exception):
    """A profile read or parse error with a stable CLI code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StoredControl:
    numid: int
    iface: str
    name: str
    index: str
    device: str
    subdevice: str
    values: tuple[tuple[str, str], ...]

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        return (self.iface, self.name, self.index, self.device, self.subdevice)


def _syntax(message: str) -> ProfileError:
    return ProfileError("invalid_profile", message)


def _blocks(text: str) -> dict:
    """Parse ALSA key/value and nested brace blocks; reject unsupported syntax."""
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars="{}")
        lex.whitespace_split = True
        lex.commenters = "#"
        raw_tokens = list(lex)
    except ValueError as exc:
        raise _syntax(f"Comillas o escapes inválidos: {exc}") from exc

    tokens: list[str] = []
    for token in raw_tokens:
        if token and set(token) <= {"{", "}"}:
            tokens.extend(token)
        else:
            tokens.append(token)

    cursor = 0

    def parse(*, nested: bool = False, depth: int = 0) -> dict:
        nonlocal cursor
        if depth > MAX_DEPTH:
            raise _syntax("Anidamiento de bloques ALSA excesivo.")
        entries: dict = {}
        while cursor < len(tokens):
            key = tokens[cursor]
            cursor += 1
            if key == "}":
                if not nested:
                    raise _syntax("Cierre de bloque sin apertura.")
                return entries
            if key == "{" or key in entries:
                raise _syntax(f"Clave inesperada o repetida: {key!r}.")
            if cursor == len(tokens):
                raise _syntax(f"Falta valor o bloque para {key!r}.")
            value = tokens[cursor]
            cursor += 1
            if value == "{":
                entries[key] = parse(nested=True, depth=depth + 1)
            elif value == "}":
                raise _syntax(f"Valor ausente para {key!r}.")
            else:
                entries[key] = value
        if nested:
            raise _syntax("Bloque ALSA sin cierre.")
        return entries

    return parse()


def parse_state(text: str) -> dict[str, dict]:
    """Extract cards and value fields, ignoring metadata and renumbered numids."""
    root = _blocks(text)
    if not root:
        raise _syntax("El fichero de estado ALSA está vacío.")
    cards: dict[str, dict] = {}
    for card_key, body in root.items():
        if not card_key.startswith("state.") or not isinstance(body, dict):
            raise _syntax(f"Bloque principal no reconocido: {card_key!r}.")
        card_name = card_key[6:]
        if not card_name:
            raise _syntax("El identificador de tarjeta ALSA está vacío.")
        controls: dict[tuple, StoredControl] = {}
        for control_key, data in body.items():
            if not re.fullmatch(r"control\.[0-9]+", control_key):
                raise _syntax(f"Bloque ALSA no reconocido: {control_key!r}.")
            if not isinstance(data, dict):
                raise _syntax(f"El control {control_key} no es un bloque.")
            iface, name = data.get("iface"), data.get("name")
            if not isinstance(iface, str) or not isinstance(name, str):
                raise _syntax(f"Falta interfaz o nombre en {card_key}/{control_key}.")
            if not iface or not name:
                raise _syntax(f"Interfaz o nombre vacío en {card_key}/{control_key}.")
            for key in ("index", "device", "subdevice"):
                if key in data and not isinstance(data[key], str):
                    raise _syntax(f"Identidad inválida en {card_key}/{control_key}.")
            raw_values = {
                key: val
                for key, val in data.items()
                if key == "value" or key.startswith("value.")
            }
            if not raw_values or any(
                not isinstance(value, str) for value in raw_values.values()
            ):
                raise _syntax(
                    f"Valores ausentes o no simples en {card_key}/{control_key}."
                )
            control = StoredControl(
                numid=int(control_key.split(".", 1)[1]),
                iface=iface,
                name=name,
                index=data.get("index", "0"),
                device=data.get("device", "0"),
                subdevice=data.get("subdevice", "0"),
                values=tuple(sorted(raw_values.items())),
            )
            if control.identity in controls:
                raise _syntax(
                    f"Control duplicado por identidad en {card_key}: {name!r}."
                )
            controls[control.identity] = control
        if not controls:
            raise _syntax(f"No hay controles en {card_key}.")
        cards[card_name] = controls
    return cards


def load_state(path: Path) -> dict[str, dict]:
    """Read at most MAX_BYTES; never call alsactl or write to disk."""
    resolved = path.expanduser()
    try:
        with resolved.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
    except FileNotFoundError as exc:
        raise ProfileError("file_missing", f"No existe: {resolved}") from exc
    except OSError as exc:
        raise ProfileError(
            "unreadable_file", f"No se puede leer {resolved}: {exc}"
        ) from exc
    if len(data) > MAX_BYTES:
        raise ProfileError("file_too_large", f"El perfil supera 2 MiB: {resolved}")
    try:
        return parse_state(data.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise _syntax(f"El perfil no es UTF-8: {resolved}") from exc
    except ProfileError as exc:
        raise _syntax(f"Perfil {resolved}: {exc}") from exc


def _category(name: str) -> str:
    # A heuristic for review, never a claim about the physical AE-5 behavior.
    if _LEVEL.search(name):
        return "level_or_mute"
    if _DSP.search(name):
        return "possible_dsp"
    if _ROUTING.search(name) or "headphone" in name.lower():
        return "possible_routing"
    return "other"


def compare_profiles(headphones_path: Path, speakers_path: Path) -> dict:
    """Compare saved values by semantic identity, not control number."""
    headphones = load_state(headphones_path)
    speakers = load_state(speakers_path)
    differences = []
    unchanged = 0
    all_cards = sorted(set(headphones) | set(speakers))
    count_headphones = sum(len(v) for v in headphones.values())
    count_speakers = sum(len(v) for v in speakers.values())
    for card in all_cards:
        head_controls = headphones.get(card, {})
        spk_controls = speakers.get(card, {})
        for key in sorted(set(head_controls) | set(spk_controls)):
            head = head_controls.get(key)
            spk = spk_controls.get(key)
            if head is not None and spk is not None and head.values == spk.values:
                unchanged += 1
                continue
            reference = head or spk
            assert reference is not None
            differences.append(
                {
                    "card": card,
                    "iface": reference.iface,
                    "name": reference.name,
                    "index": reference.index,
                    "device": reference.device,
                    "subdevice": reference.subdevice,
                    "category": _category(reference.name),
                    "status": (
                        "changed"
                        if head is not None and spk is not None
                        else "only_headphones" if head is not None else "only_speakers"
                    ),
                    "headphones_numid": head.numid if head else None,
                    "speakers_numid": spk.numid if spk else None,
                    "headphones": dict(head.values) if head else None,
                    "speakers": dict(spk.values) if spk else None,
                }
            )

    nonrouting = sum(
        d["category"] != "possible_routing" for d in differences
    )
    affected_cards = sorted({d["card"] for d in differences})
    warnings = []
    if len(all_cards) > 1:
        warnings.append(
            "Los perfiles contienen varias tarjetas ALSA. Una restauración "
            "completa de alsactl podría afectar a tarjetas ajenas a la AE-5."
        )
    if nonrouting:
        warnings.append(
            f"{nonrouting} diferencias no identificadas como rutas. La conmutación "
            "directa de ae5ctl no reproduce volumen, ganancia, muteo ni DSP."
        )
    if not differences:
        warnings.append(
            "Los valores guardados son iguales; no se ha probado que los "
            "perfiles seleccionen salidas físicas distintas."
        )
    return {
        "scope": "saved_alsa_profiles",
        "headphones_file": str(headphones_path.expanduser()),
        "speakers_file": str(speakers_path.expanduser()),
        "summary": {
            "cards_headphones": len(headphones),
            "cards_speakers": len(speakers),
            "controls_headphones": count_headphones,
            "controls_speakers": count_speakers,
            "unchanged_controls": unchanged,
            "different_controls": len(differences),
            "possible_non_routing_changes": nonrouting,
            "affected_cards": affected_cards,
        },
        "differences": differences,
        "warnings": warnings,
        "notes": [
            "La clasificación por nombre del control es orientativa.",
            "Los números control.N se muestran para consulta, no para emparejar.",
            "No se ha ejecutado alsactl ni se ha modificado ALSA.",
        ],
    }
