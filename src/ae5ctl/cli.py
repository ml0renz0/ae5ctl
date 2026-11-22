"""Read-only card discovery and ALSA state diagnostics."""

import argparse
import json
import math
import sys
from dataclasses import asdict

from ae5ctl import __version__
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
    "No se inspeccionan perfiles ni rutas PipeWire/WirePlumber.",
]


ERROR_HINTS = {
    "no_card": "Compruebe la conexión con 'ae5ctl cards' y 'cat /proc/asound/cards'.",
    "card_not_found": "Ejecute 'ae5ctl cards' y use el ID indicado con --card.",
    "ambiguous_card": "Ejecute 'ae5ctl cards' e indique --card ID_ALSA.",
    "no_control": (
        "Verifique la tarjeta con 'ae5ctl cards' y examine sus controles con amixer."
    ),
    "ambiguous_control": (
        "Use 'amixer -c ID_ALSA controls' para identificar el selector "
        "y luego --numid N."
    ),
    "unknown_output": (
        "Revise el selector indicado con 'amixer -c ID_ALSA cget numid=N'."
    ),
    "command_missing": "Instale alsa-utils (Ubuntu: 'sudo apt install alsa-utils').",
    "command_timeout": "Pruebe --timeout 10 y compruebe que ALSA responde.",
    "command_failed": "Revise el mensaje de amixer y los permisos de la tarjeta ALSA.",
    "parse_error": (
        "Guarde 'ae5ctl doctor --json' para reportar un formato ALSA no reconocido."
    ),
    "unreadable_cards": "Compruebe los permisos de /proc/asound/cards.",
}


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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Control y diagnóstico de Sound BlasterX AE-5 en Linux.\n"
            "Versión actual: consultas ALSA de solo lectura; NO cambia el audio."
        ),
        epilog=(
            "EJEMPLOS\n"
            "  ae5ctl cards                Lista tarjetas y sus ID ALSA\n"
            "  ae5ctl status               Consulta la salida seleccionada\n"
            "  ae5ctl status --card Creative --json\n"
            "  ae5ctl doctor --json        Diagnóstico estructurado\n\n"
            "AYUDA DETALLADA\n"
            "  ae5ctl <comando> --help\n\n"
            "CÓDIGOS DE SALIDA\n"
            "  0 correcto · 2 argumentos · 3 selección · 4 error ALSA\n\n"
            "Más información: https://github.com/ml0renz0/ae5ctl"
        ),
    )
    root.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}",
        help="mostrar la versión instalada y salir",
    )
    commands = root.add_subparsers(dest="command", required=True, metavar="COMANDO")
    details = {
        "cards": (
            "Lista todas las tarjetas ALSA. No consulta ni modifica controles.",
            "EJEMPLOS\n"
            "  ae5ctl cards\n"
            "  ae5ctl cards --json\n\n"
            "Use el ID entre corchetes en status --card ID_ALSA."
        ),
        "status": (
            "Lee la salida del selector de auriculares/altavoces de la AE-5.",
            "EJEMPLOS\n"
            "  ae5ctl status\n"
            "  ae5ctl status --card Creative\n"
            "  ae5ctl status --card Creative --numid 37 --json\n\n"
            "Primero ejecute 'ae5ctl cards' para identificar el ID ALSA.\n"
            "Use --numid solo si hay varios selectores o conoce el control.\n"
            "La selección ALSA no garantiza que se oiga audio."
        ),
        "doctor": (
            "Diagnostica la detección y lectura ALSA, sin reparar el audio.",
            "EJEMPLOS\n"
            "  ae5ctl doctor\n"
            "  ae5ctl doctor --card Creative --json\n\n"
            "No modifica perfiles PipeWire, controles ALSA ni servicios.\n"
            "El diagnóstico PipeWire/WirePlumber todavía no está implementado."
        ),
    }
    for name, help_text in [
        ("cards", "listar tarjetas ALSA y obtener sus ID"),
        ("status", "consultar la salida física seleccionada"),
        ("doctor", "diagnosticar la lectura ALSA (sin reparar audio)"),
    ]:
        description, epilog = details[name]
        command = commands.add_parser(
            name,
            help=help_text,
            description=description,
            epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        command.add_argument(
            "--json", action="store_true", help="imprimir JSON para scripts"
        )
        if name != "cards":
            command.add_argument(
                "--card",
                metavar="ID_ALSA",
                help="ID exacto o índice; consulte 'ae5ctl cards'",
            )
            command.add_argument(
                "--numid",
                type=positive_int,
                metavar="N",
                help="identificador del selector ALSA; opcional",
            )
            command.add_argument(
                "--timeout",
                type=positive_timeout,
                default=3.0,
                metavar="SEGUNDOS",
                help="límite por consulta amixer (predeterminado: 3)",
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


def print_error(error: AlsaError) -> None:
    print(f"Error [{error.code}]: {error}", file=sys.stderr)
    hint = ERROR_HINTS.get(error.code)
    if hint:
        print(f"Sugerencia: {hint}", file=sys.stderr)


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
            print_error(AlsaError(error["code"], error["message"]))
        for note in report["notes"]:
            print(note)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        parser().print_help()
        return 0
    args = parser().parse_args(arguments)
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
            print_error(error)
        return exit_code(error)
    return 0
