"""Read ALSA card and enumerated-control state without a desktop dependency."""

import math
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class AlsaError(Exception):
    """A failed read with a stable code for CLI consumers."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Card:
    index: int
    id: str
    name: str


@dataclass(frozen=True)
class EnumControl:
    numid: int
    name: str
    items: dict[int, str]
    values: tuple[int, ...]


@dataclass(frozen=True)
class Status:
    card: Card
    control: EnumControl
    output: str


_CARD = re.compile(r"^\s*(\d+)\s+\[([^\]]+)\]\s*:\s*(.+)$")
_CARD_START = re.compile(r"^\s*\d+\s+\[")
_AE5 = re.compile(r"(?<![a-z0-9])ae[- ]?5(?![a-z0-9])", re.IGNORECASE)
_NUMID = re.compile(r"^\s*numid=(\d+)(?:,|$)")
_NAME = re.compile(r"(?:^|,)name='(.*)'(?:,|$)")
_TYPE = re.compile(r"\btype=([A-Z][A-Z0-9_]*)\b")
_ITEM = re.compile(r"^\s*;\s*Item #(\d+) '(.*)'\s*$")
_VALUES = re.compile(r"^\s*:\s*values=(.*?)\s*$")


def _parse_error(message: str) -> AlsaError:
    return AlsaError("parse_error", message)


def parse_cards(text: str) -> list[Card]:
    """Parse /proc/asound/cards, retaining continuation descriptions."""
    cards: list[Card] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.strip() == "--- no soundcards ---" and not cards:
            continue
        match = _CARD.match(line)
        if match:
            index, card_id, name = match.groups()
            card = Card(int(index), card_id.strip(), name.strip())
            if not card.id or any(existing.index == card.index for existing in cards):
                raise _parse_error("Identidad de tarjeta ALSA vacía o duplicada.")
            cards.append(card)
        elif cards and line[:1].isspace() and not _CARD_START.match(line):
            previous = cards[-1]
            cards[-1] = Card(
                previous.index, previous.id, previous.name + " " + line.strip()
            )
        else:
            raise _parse_error("No se puede interpretar la lista de tarjetas ALSA.")
    return cards


def _header(line: str) -> tuple[int, str]:
    number = _NUMID.match(line)
    name = _NAME.search(line)
    if not number or not name or int(number[1]) < 1:
        raise _parse_error("Cabecera de control ALSA inválida.")
    # amixer/libasound print names inside quotes without shell escaping them.
    return int(number[1]), name[1]


def parse_enum_control(text: str) -> EnumControl:
    """Resolve numeric values through their explicit Item #N labels."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise _parse_error("ALSA no devolvió el control solicitado.")
    numid, name = _header(lines[0])
    metadata = [line for line in lines[1:] if _TYPE.search(line)]
    if len(metadata) != 1 or _TYPE.search(metadata[0])[1] != "ENUMERATED":
        raise _parse_error("El control no es un enumerado ALSA válido.")
    item_count = re.search(r"\bitems=(\d+)\b", metadata[0])
    value_count = re.search(r"\bvalues=(\d+)\b", metadata[0])
    if not item_count or not value_count:
        raise _parse_error("Faltan los tamaños del control enumerado ALSA.")

    items: dict[int, str] = {}
    values: tuple[int, ...] | None = None
    for line in lines[1:]:
        item = _ITEM.match(line)
        selection = _VALUES.match(line)
        if item:
            index, label = int(item[1]), item[2]
            if index in items:
                raise _parse_error("ALSA devolvió un índice enumerado duplicado.")
            if index >= int(item_count[1]):
                raise _parse_error("ALSA devolvió un índice enumerado fuera de rango.")
            items[index] = label
        elif selection:
            if values is not None or not re.fullmatch(
                r"-?\d+(?:\s*,\s*-?\d+)*", selection[1]
            ):
                raise _parse_error("Valores enumerados ALSA inválidos o duplicados.")
            values = tuple(int(value) for value in selection[1].split(","))
        elif "Item #" in line:
            raise _parse_error("Opción enumerada ALSA mal formada.")
    if (
        not items
        or len(items) != int(item_count[1])
        or set(items) != set(range(int(item_count[1])))
        or values is None
        or len(values) != int(value_count[1])
    ):
        raise _parse_error("La respuesta enumerada ALSA está incompleta.")
    return EnumControl(numid, name, items, values)


def _output(label: str) -> str | None:
    return {
        "headphone": "headphones",
        "headphones": "headphones",
        "speaker": "speakers",
        "speakers": "speakers",
    }.get(label.strip().casefold())


def _supports_outputs(control: EnumControl) -> bool:
    modes = {_output(label) for label in control.items.values()}
    return {"headphones", "speakers"} <= modes


class AlsaBackend:
    """Read-only operations: controls and cget; never restore or cset."""

    def __init__(
        self,
        *,
        cards_path: Path = Path("/proc/asound/cards"),
        timeout: float = 3.0,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("El tiempo límite debe ser positivo y finito.")
        self.cards_path = Path(cards_path)
        self.timeout = timeout
        self.runner = runner if runner is not None else subprocess.run

    def cards(self) -> list[Card]:
        try:
            text = self.cards_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return []
        except OSError as error:
            raise AlsaError(
                "unreadable_cards", f"No se pueden leer las tarjetas ALSA: {error}"
            ) from error
        return parse_cards(text)

    def _select_card(self, selector: str | None) -> Card:
        cards = self.cards()
        if not cards:
            raise AlsaError("no_card", "No se encontraron tarjetas ALSA.")
        if selector is None:
            matches = [card for card in cards if _AE5.search(card.id + " " + card.name)]
        else:
            matches = [
                card
                for card in cards
                if selector == card.id or selector == str(card.index)
            ]
        if not matches:
            if selector is None:
                raise AlsaError(
                    "card_not_found",
                    "No se identifica una AE-5. Consulte cards y seleccione --card ID.",
                )
            raise AlsaError(
                "card_not_found", f"No existe la tarjeta ALSA {selector!r}."
            )
        if len(matches) != 1:
            raise AlsaError(
                "ambiguous_card", "Hay varias tarjetas posibles; seleccione --card."
            )
        return matches[0]

    def _read(self, card: Card, *arguments: str) -> str:
        command = ["amixer", "-c", str(card.index), *arguments]
        try:
            result = self.runner(
                command,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env={**os.environ, "LC_ALL": "C"},
            )
        except FileNotFoundError as error:
            raise AlsaError(
                "command_missing", "No se encuentra amixer; instale alsa-utils."
            ) from error
        except subprocess.TimeoutExpired as error:
            raise AlsaError(
                "command_timeout", "La consulta ALSA superó el tiempo límite."
            ) from error
        except OSError as error:
            raise AlsaError(
                "command_failed", f"No se puede ejecutar amixer: {error}"
            ) from error
        if result.returncode:
            detail = result.stderr.strip()[:400] or "sin diagnóstico"
            raise AlsaError(
                "command_failed", f"amixer falló ({result.returncode}): {detail}"
            )
        return result.stdout

    def _control(self, card: Card, numid: int) -> EnumControl:
        text = self._read(card, "cget", f"numid={numid}")
        control = parse_enum_control(text)
        if control.numid != numid:
            raise _parse_error("ALSA devolvió un control distinto al solicitado.")
        return control

    def status(self, card: str | None = None, numid: int | None = None) -> Status:
        selected = self._select_card(card)
        if numid is not None:
            if numid < 1:
                raise AlsaError("no_control", "El numid debe ser positivo.")
            control = self._control(selected, numid)
            if not _supports_outputs(control):
                raise AlsaError(
                    "no_control", "El control no ofrece auriculares y altavoces."
                )
        else:
            controls: list[EnumControl] = []
            seen: set[int] = set()
            for line in self._read(selected, "controls").splitlines():
                if not line.strip():
                    continue
                number, _ = _header(line)
                if number in seen:
                    raise _parse_error("ALSA devolvió un numid duplicado.")
                seen.add(number)
                text = self._read(selected, "cget", f"numid={number}")
                metadata = _TYPE.search(text)
                if metadata is None:
                    raise _parse_error("Falta el tipo de un control ALSA.")
                if metadata[1] != "ENUMERATED":
                    continue
                candidate = parse_enum_control(text)
                if candidate.numid != number:
                    raise _parse_error(
                        "ALSA devolvió un control distinto al solicitado."
                    )
                if _supports_outputs(candidate):
                    controls.append(candidate)
            if not controls:
                raise AlsaError(
                    "no_control",
                    "No se encontró un selector de auriculares y altavoces.",
                )
            if len(controls) != 1:
                raise AlsaError(
                    "ambiguous_control", "Hay varios selectores; indique --numid."
                )
            control = controls[0]
        if len(control.values) != 1:
            raise AlsaError(
                "unknown_output", "El selector tiene varios valores activos."
            )
        label = control.items.get(control.values[0])
        output = _output(label) if label is not None else None
        if output is None:
            raise AlsaError(
                "unknown_output", "La salida seleccionada no se puede interpretar."
            )
        return Status(selected, control, output)
