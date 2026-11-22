"""Read-only inspection via the PulseAudio-compatible pactl protocol.

A successful pactl response does not imply that the server is PipeWire.
"""

import os
import subprocess
from collections.abc import Callable

NOTE = (
    "pactl usa la API compatible con PulseAudio, también ofrecida por "
    "pipewire-pulse. Sus salidas no se corresponden necesariamente con "
    "el selector físico de la Sound BlasterX AE-5."
)


def _invoke(
    command: list[str],
    runner: Callable[..., subprocess.CompletedProcess],
    timeout: float,
) -> tuple[str | None, dict[str, str] | None]:
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except FileNotFoundError:
        return None, {
            "code": "command_missing",
            "message": "Falta pactl (Ubuntu: sudo apt install pulseaudio-utils).",
        }
    except subprocess.TimeoutExpired:
        return None, {
            "code": "command_timeout",
            "message": f"Tiempo de espera agotado: {' '.join(command)}.",
        }
    except OSError as exc:
        return None, {
            "code": "command_failed",
            "message": f"No se pudo ejecutar pactl: {exc}",
        }
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return None, {
            "code": "command_failed",
            "message": f"{' '.join(command)} falló: {detail or result.returncode}",
        }
    return result.stdout, None


def _short_list(text: str, *, with_state: bool) -> tuple[list[dict], int]:
    entries: list[dict] = []
    invalid = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) < 2 or not fields[0].isdigit():
            invalid += 1
            continue
        entry = {"index": int(fields[0]), "name": fields[1]}
        if with_state:
            # Last column of "pactl list short sinks" is RUNNING/IDLE/SUSPENDED.
            if len(fields) < 5:
                invalid += 1
                continue
            entry["state"] = fields[-1]
        entries.append(entry)
    return entries, invalid


def inspect_audio_session(
    *,
    timeout: float = 3.0,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict:
    """Query server, default sink and devices without changing the audio state."""
    report: dict = {
        "available": False,
        "server_kind": "unknown",
        "server_name": None,
        "default_sink": None,
        "sinks": [],
        "cards": [],
        "errors": [],
        "notes": [NOTE],
    }
    information, error = _invoke(["pactl", "info"], runner, timeout)
    if error is not None:
        report["errors"].append(error)
        return report

    report["available"] = True
    fields = {}
    for line in information.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"Server Name", "Default Sink"}:
            fields[key.strip()] = value.strip()
    report["server_name"] = fields.get("Server Name") or None
    report["default_sink"] = fields.get("Default Sink") or None
    if report["server_name"]:
        name = report["server_name"].lower()
        if "pipewire" in name:
            report["server_kind"] = "pipewire"
        elif "pulseaudio" in name:
            report["server_kind"] = "pulseaudio"
    else:
        report["errors"].append(
            {
                "code": "parse_error",
                "message": "pactl info no indica el nombre del servidor.",
            }
        )

    for category, command, with_state in (
        ("sinks", ["pactl", "list", "short", "sinks"], True),
        ("cards", ["pactl", "list", "short", "cards"], False),
    ):
        response, command_error = _invoke(command, runner, timeout)
        if command_error is not None:
            report["errors"].append(command_error)
            continue
        entries, invalid = _short_list(response, with_state=with_state)
        report[category] = entries
        if invalid:
            report["errors"].append(
                {
                    "code": "parse_error",
                    "message": f"{invalid} registros inválidos en {' '.join(command)}.",
                }
            )
    return report
