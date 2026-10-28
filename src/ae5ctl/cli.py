"""Read-only card discovery and ALSA state diagnostics."""

import argparse
import json
import math
import sys
from dataclasses import asdict

from ae5ctl.alsa import AlsaBackend, AlsaError, Status

SELECTION_ERRORS = {
    "no_card",
    "card_not_found",
    "ambiguous_card",
    "no_control",
    "ambiguous_control",
    "unknown_output",
}
DIAGNOSTIC_NOTES = [
    "Solo se consulta ALSA; no se cambia ningún control ni perfil de audio.",
    "La selección ALSA no demuestra que salga audio por el conector esperado.",
    "Los perfiles de Ubuntu y el fallo tras suspensión requieren diagnóstico adicional.",
]


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("debe ser un entero positivo") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("debe ser un entero positivo")
    return parsed


def positive_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "debe ser un número positivo finito"
        ) from error
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("debe ser un número positivo finito")
    return parsed


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="ae5ctl",
        description="Consulta tarjetas y salida ALSA sin cambiar la configuración.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in [
        ("cards", "listar tarjetas ALSA"),
        ("status", "leer la salida seleccionada en ALSA"),
        ("doctor", "diagnosticar la lectura ALSA (no repara el audio)"),
    ]:
        command = commands.add_parser(name, help=help_text, description=help_text)
        command.add_argument("--json", action="store_true", help="salida JSON")
        if name != "cards":
            command.add_argument("--card", help="ID ALSA exacto o índice de tarjeta")
            command.add_argument(
                "--numid", type=positive_int, help="numid del selector de salida"
            )
            command.add_argument(
                "--timeout",
                type=positive_timeout,
                default=3.0,
                metavar="SEGUNDOS",
                help="tiempo máximo por comando amixer (predeterminado: 3)",
            )
    return root


def status_dict(status: Status) -> dict:
    return {"scope": "alsa", **asdict(status)}


def error_dict(error: AlsaError) -> dict[str, str]:
    return {"code": error.code, "message": str(error)}


def exit_code(error: AlsaError) -> int:
    return 3 if error.code in SELECTION_ERRORS else 4


def print_json(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def print_status(value: dict) -> None:
    card = value["card"]
    control = value["control"]
    print(f"Tarjeta: {card['id']} (índice {card['index']}) — {card['name']}")
    print(f"Control: {control['name']} (numid={control['numid']})")
    print(f"Salida ALSA seleccionada: {value['output']}")
    print("Esta lectura no confirma que se oiga audio.")


def doctor(backend: AlsaBackend, args: argparse.Namespace) -> int:
    report = {
        "ok": False,
        "scope": "alsa",
        "cards": [],
        "status": None,
        "errors": [],
        "notes": DIAGNOSTIC_NOTES,
    }
    result = 0
    try:
        report["cards"] = [asdict(card) for card in backend.cards()]
        report["status"] = status_dict(backend.status(card=args.card, numid=args.numid))
        report["ok"] = True
    except AlsaError as error:
        report["errors"].append(error_dict(error))
        result = exit_code(error)
    if args.json:
        print_json(report)
    else:
        print(
            "Diagnóstico ALSA: "
            + ("lectura correcta" if report["ok"] else "incompleto")
        )
        for card in report["cards"]:
            print(f"Tarjeta disponible: {card['index']} [{card['id']}] {card['name']}")
        if report["status"] is not None:
            print_status(report["status"])
        for error in report["errors"]:
            print(f"Error [{error['code']}]: {error['message']}", file=sys.stderr)
        for note in report["notes"]:
            print(note)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    backend = AlsaBackend(timeout=getattr(args, "timeout", 3.0))
    if args.command == "doctor":
        return doctor(backend, args)
    try:
        if args.command == "cards":
            cards = [asdict(card) for card in backend.cards()]
            if args.json:
                print_json({"cards": cards})
            else:
                for card in cards:
                    print(f"{card['index']} [{card['id']}] {card['name']}")
                if not cards:
                    print("No hay tarjetas ALSA disponibles.")
        else:
            status = status_dict(backend.status(card=args.card, numid=args.numid))
            if args.json:
                print_json(status)
            else:
                print_status(status)
    except AlsaError as error:
        if args.json:
            print_json({"error": error_dict(error)})
        else:
            print(f"Error [{error.code}]: {error}", file=sys.stderr)
        return exit_code(error)
    return 0
