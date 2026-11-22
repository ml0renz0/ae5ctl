"""Interactive audio wizard with explicit ALSA consent and test-tone playback.

Uses paplay through pipewire-pulse/PulseAudio. Never changes the default sink,
system volume, user profiles or PipeWire routes. The operator confirms hearing.
"""

import json
import math
import os
import struct
import subprocess
import tempfile
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ae5ctl.alsa import AlsaBackend
from ae5ctl.profiles import (
    HEADPHONES_FILE,
    SPEAKERS_FILE,
    ProfileError,
    compare_profiles,
)
from ae5ctl.validation import run_validation


class ProbeError(Exception):
    """The optional audio test could not run."""


@dataclass(frozen=True)
class Sink:
    name: str
    label: str
    alsa_card: int | None


def _run(
    command: list[str],
    runner: Callable[..., subprocess.CompletedProcess],
    timeout: float,
) -> str:
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
            timeout=timeout,
            env={**os.environ, "LC_ALL": "C"},
        )
    except FileNotFoundError as exc:
        raise ProbeError(
            f"No existe {command[0]}. Instala pulseaudio-utils en Ubuntu."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"Tiempo de espera agotado en {command[0]}.") from exc
    except OSError as exc:
        raise ProbeError(f"No se pudo ejecutar {command[0]}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()[:250]
        raise ProbeError(f"{command[0]} falló: {detail or result.returncode}")
    return result.stdout


def discover_sinks(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[Sink]:
    """Find PulseAudio-compatible sinks and their *optional* ALSA card index."""
    response = _run(["pactl", "-f", "json", "list", "sinks"], runner, 5)
    try:
        data = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ProbeError("pactl no devolvió una lista de salidas JSON válida.") from exc
    if isinstance(data, dict):
        data = data.get("sinks")
    if not isinstance(data, list):
        raise ProbeError("pactl devolvió un formato de salidas no reconocido.")
    sinks = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        props = entry.get("properties", {})
        if not isinstance(props, dict):
            props = {}
        raw_card = props.get("alsa.card")
        card_index = int(str(raw_card)) if str(raw_card).isdigit() else None
        label = entry.get("description") or props.get("device.description") or name
        sinks.append(Sink(name, str(label), card_index))
    if not sinks:
        raise ProbeError("No se han encontrado salidas de audio de PipeWire/PulseAudio.")
    return sinks


def choose_sink(
    sinks: list[Sink],
    card_index: int,
    ask: Callable[[str], str],
    say: Callable[[str], None],
) -> Sink | None:
    """Auto-select only an unambiguous ALSA match, otherwise ask the user."""
    matches = [sink for sink in sinks if sink.alsa_card == card_index]
    if len(matches) == 1:
        chosen = matches[0]
        say(f"Salida de audio vinculada a la AE-5: {chosen.label} ({chosen.name}).")
        return chosen
    candidates = matches or sinks
    if not matches:
        say("AVISO: PipeWire no informa qué salida corresponde a la tarjeta ALSA.")
        say("Elige explícitamente el dispositivo de sonido de la AE-5.")
    else:
        say("Se encontraron varias salidas de la AE-5. Elige cuál probar.")
    for number, sink in enumerate(candidates, start=1):
        say(f"  {number}. {sink.label} [{sink.name}]")
    for _ in range(3):
        choice = ask("Número de salida (0 para cancelar): ").strip()
        if choice == "0" or not choice:
            return None
        if choice.isdecimal() and 1 <= int(choice) <= len(candidates):
            selected = candidates[int(choice) - 1]
            say(f"Se probará: {selected.label}.")
            return selected
        say("Opción inválida; introduce un número de la lista o 0.")
    return None


def make_tone(destination: Path) -> None:
    """Create a quiet 0.7-second PCM tone; no network or bundled sound files."""
    rate = 48000
    frames = int(rate * 0.7)
    fade = int(rate * 0.03)
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        for frame in range(frames):
            envelope = min(1.0, frame / fade, (frames - 1 - frame) / fade)
            value = int(32767 * 0.09 * envelope * math.sin(2 * math.pi * 440 * frame / rate))
            output.writeframesraw(struct.pack("<h", value))


def run_wizard(
    backend: AlsaBackend,
    *,
    card: str | None = None,
    numid: int | None = None,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    profiles: Callable[..., dict] = compare_profiles,
) -> int:
    """Drive six visible steps; return 0 only after three heard tones and recovery."""
    say("=== ae5ctl · asistente de comprobación AE-5 ===")
    say("PASO 1/6 · Identificar tarjeta, selector y perfiles")
    initial = backend.status(card=card, numid=numid)
    say(f"Tarjeta: {initial.card.id}, índice {initial.card.index}")
    say(f"Selector: {initial.control.name} (numid={initial.control.numid})")
    try:
        result = profiles(HEADPHONES_FILE, SPEAKERS_FILE)
    except ProfileError as error:
        say(f"Aviso: no se han podido comparar los perfiles antiguos: {error}")
    else:
        count = result["summary"]["different_controls"]
        nonrouting = result["summary"]["possible_non_routing_changes"]
        say(f"Perfiles: {count} controles diferentes; {nonrouting} no son rutas.")
        if nonrouting:
            say("AVISO: la conmutación simple NO reproduce ajustes de ganancia/DSP.")
    say("PASO 2/6 · Seleccionar el dispositivo de reproducción")
    try:
        sinks = discover_sinks(runner)
        selected = choose_sink(sinks, initial.card.index, ask, say)
    except ProbeError as error:
        say(f"No se puede iniciar la prueba auditiva: {error}")
        return 5
    except (KeyboardInterrupt, EOFError):
        say("Wizard interrumpido antes de modificar ALSA.")
        return 130
    if selected is None:
        say("Cancelado: no se ha modificado ALSA.")
        return 5

    say("Se reproducirá un tono corto con volumen digital moderado.")
    say("Baja el volumen físico si estás usando auriculares.")
    say("No se modificará el dispositivo predeterminado de PipeWire.")
    try:
        with tempfile.TemporaryDirectory(prefix="ae5ctl-wizard-") as tmp:
            tone = Path(tmp) / "tone.wav"
            make_tone(tone)

            def sample(output: str) -> bool:
                say(f"Reproduciendo señal de prueba para {output}…")
                try:
                    _run(["paplay", f"--device={selected.name}", str(tone)], runner, 10)
                except ProbeError as error:
                    say(f"ERROR de reproducción: {error}")
                    return False
                return True

            def step(number: int, label: str) -> None:
                say(f"PASO {number}/6 · {label}")

            return run_validation(
                backend,
                card=initial.card.id,
                numid=initial.control.numid,
                apply=True,
                ask=ask,
                say=say,
                sample=sample,
                on_step=step,
            )
    except (KeyboardInterrupt, EOFError):
        say("Wizard interrumpido antes de una nueva escritura.")
        return 130
