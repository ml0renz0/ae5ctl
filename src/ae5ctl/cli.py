"""Sound BlasterX AE-5 read, diagnosis and verified output selection."""

import argparse
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path

from ae5ctl import __version__
from ae5ctl.alsa import AlsaBackend, AlsaError, Status, SwitchPlan, SwitchResult
from ae5ctl.audio_session import inspect_audio_session
from ae5ctl.capabilities import scan_capabilities
from ae5ctl.control_plans import plan_control
from ae5ctl.preset_store import (
    PresetError,
    PresetStore,
    compare,
    new_preset,
    read_control,
    remove_control,
    set_control,
)
from ae5ctl.profiles import (
    HEADPHONES_FILE,
    SPEAKERS_FILE,
    ProfileError,
    compare_profiles,
)

SELECTION_ERRORS = {
    "no_card",
    "card_not_found",
    "ambiguous_card",
    "no_control",
    "ambiguous_control",
    "unknown_output",
    "ambiguous_output",
    "card_changed",
    "control_changed",
    "state_changed",
    "invalid_control",
    "invalid_value",
    "ambiguous_value",
    "unsupported_type",
}
DIAGNOSTIC_NOTES = [
    "El comando doctor es de solo lectura; no modifica controles ni perfiles.",
    "La selección ALSA no demuestra que salga audio por el conector esperado.",
    "La lectura ALSA no revela las rutas del servidor de audio.",
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
    "ambiguous_output": (
        "Examine las opciones con amixer y especifique el selector correcto."
    ),
    "verify_failed": (
        "El resultado es incierto: ejecute ae5ctl status antes de reintentar."
    ),
    "card_changed": "La tarjeta cambió. Compruebe ae5ctl cards y consulte de nuevo.",
    "control_changed": "El selector se reconfiguró. Consulte ae5ctl status y reintente.",
    "state_changed": "Otro cliente modificó la salida. Consulte ae5ctl status.",
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
            "switch y toggle modifican solo el selector físico ALSA de la tarjeta."
        ),
        epilog=(
            "EJEMPLOS\n"
            "  ae5ctl cards                Lista tarjetas y sus ID ALSA\n"
            "  ae5ctl status               Consulta la salida seleccionada\n"
            "  ae5ctl status --card Creative --json\n"
            "  ae5ctl switch headphones    Selecciona auriculares\n"
            "  ae5ctl switch speakers      Selecciona altavoces\n"
            "  ae5ctl toggle               Alterna ambas salidas\n"
            "  ae5ctl validate             Inspección guiada sin modificar ALSA\n"
            "  ae5ctl wizard               Wizard auditivo de seis pasos\n"
            "  ae5ctl validate --apply     Alias del wizard auditivo\n"
            "  ae5ctl switch speakers --dry-run  Previsualiza sin cambiar audio\n"
            "  ae5ctl tray                  Indicador de bandeja (GTK/Ayatana)\n"
            "  ae5ctl doctor --json        Diagnóstico ALSA estructurado\n"
            "  ae5ctl doctor --pipewire    Inspección del servidor de audio\n"
            "  ae5ctl doctor --profiles    Incluye los perfiles ALSA guardados\n"
            "  ae5ctl capabilities --json  Descubre controles de la AE-5 (solo lectura)\n"
            "  ae5ctl profiles diff        Compara perfiles alsactl guardados\n"
            "  ae5ctl presets list         Presets JSON del usuario\n"
            "  ae5ctl presets diff gaming  Compara preset con ALSA (solo lectura)\n\n"
            "La conmutación NO restaura perfiles de volumen, ganancia ni DSP.\n"
            "La lectura ALSA no garantiza que el audio sea audible.\n\n"
            "AYUDA DETALLADA\n"
            "  ae5ctl <comando> --help\n\n"
            "CÓDIGOS DE SALIDA\n"
            "  0 correcto · 2 argumentos · 3 selección · 4 error ALSA\n"
            "  5 validación no completada · 130 interrumpida\n\n"
            "Más información: https://github.com/ml0renz0/ae5ctl"
        ),
    )
    root.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="mostrar la versión instalada y salir",
    )
    commands = root.add_subparsers(dest="command", required=True, metavar="COMANDO")
    details = {
        "cards": (
            "Lista todas las tarjetas ALSA. No consulta ni modifica controles.",
            "EJEMPLOS\n"
            "  ae5ctl cards\n"
            "  ae5ctl cards --json\n\n"
            "Use el ID entre corchetes en status --card ID_ALSA.",
        ),
        "status": (
            "Lee la salida del selector de auriculares/altavoces de la AE-5.",
            "EJEMPLOS\n"
            "  ae5ctl status\n"
            "  ae5ctl status --card Creative\n"
            "  ae5ctl status --card Creative --numid 37 --json\n\n"
            "Primero ejecute 'ae5ctl cards' para identificar el ID ALSA.\n"
            "Use --numid solo si hay varios selectores o conoce el control.\n"
            "La selección ALSA no garantiza que se oiga audio.",
        ),
        "doctor": (
            "Diagnostica la detección y lectura ALSA, sin reparar el audio.",
            "EJEMPLOS\n"
            "  ae5ctl doctor\n"
            "  ae5ctl doctor --card Creative --json\n"
            "  ae5ctl doctor --pipewire --json\n"
            "  ae5ctl doctor --pipewire --profiles --json\n\n"
            "--pipewire usa pactl (PipeWire o PulseAudio).\n"
            "--profiles compara los dos .state originales, si existen.\n"
            "Son lecturas opcionales; no modifican perfiles ni rutas.",
        ),
        "capabilities": (
            "Inventaría todos los controles ALSA de una tarjeta sin escribir.",
            "EJEMPLOS\n"
            "  ae5ctl capabilities\n"
            "  ae5ctl capabilities --json\n"
            "  ae5ctl capabilities --card Creative --json\n"
            "  ae5ctl capabilities --card Creative --numid 43 --json\n\n"
            "Incluye tipo, rango, acceso y clasificación orientativa.\n"
            "Ningún control queda autorizado para escritura con este inventario.",
        ),
        "switch": (
            "Selecciona auriculares o altavoces modificando solo el control ALSA.",
            "EJEMPLOS\n"
            "  ae5ctl switch headphones\n"
            "  ae5ctl switch speakers --card Creative --json\n"
            "  ae5ctl switch speakers --dry-run --json\n\n"
            "--dry-run muestra el cset previsto SIN ejecutarlo.\n"
            "Lee el selector, cambia su índice y comprueba el resultado.\n"
            "No modifica volumen, DSP ni perfiles PipeWire.",
        ),
        "toggle": (
            "Alterna según el valor real del selector ALSA.",
            "EJEMPLOS\n"
            "  ae5ctl toggle\n"
            "  ae5ctl toggle --card Creative --json\n"
            "  ae5ctl toggle --dry-run\n\n"
            "--dry-run calcula la próxima salida sin modificar ALSA.\n"
            "No se basa en un archivo de último estado ni restaura perfiles.",
        ),
        "wizard": (
            "Comprueba ambas salidas con tonos y confirmaciones paso a paso.",
            "EJEMPLOS\n"
            "  ae5ctl wizard\n"
            "  ae5ctl wizard --card Creative\n\n"
            "Detecta la salida PipeWire/PulseAudio correspondiente a la tarjeta.\n"
            "Emite tonos mediante paplay y pregunta si se oyen.\n"
            "Solo escribe en ALSA tras autorización CAMBIAR; restaura el selector.",
        ),
        "validate": (
            "Inspecciona el selector y guía una prueba auditiva opcional.",
            "EJEMPLOS\n"
            "  ae5ctl validate\n"
            "  ae5ctl validate --card Creative\n"
            "  ae5ctl validate --apply --card Creative\n\n"
            "Sin --apply: solo lectura; no reproduce sonido.\n"
            "Con --apply: inicia el mismo wizard que 'ae5ctl wizard'.\n"
            "Solicita autorización 'CAMBIAR' antes de tocar ALSA.\n"
            "No certifica DSP, volumen, PipeWire ni la bandeja GNOME.",
        ),
        "controls": (
            "Previsualiza controles tipados sin escribir en ALSA.",
            "EJEMPLOS\n"
            "  ae5ctl controls plan 11 40,40 --card Creative --json\n"
            "  ae5ctl controls plan 43 Speakers --card Creative\n"
            "Todos los resultados son de solo lectura; no hay cset.",
        ),
        "presets": (
            "Gestiona presets JSON versionados por usuario, sin aplicarlos.",
            "EJEMPLOS\n"
            "  ae5ctl presets create gaming --card Creative\n"
            "  ae5ctl presets capture music --card Creative --numid 11\n"
            "  ae5ctl presets set gaming --numid 11 --values 50,50\n"
            "  ae5ctl presets diff gaming --json\n"
            "  ae5ctl presets export gaming /tmp/gaming.json\n\n"
            "No hay aplicación de presets ni escrituras ALSA en esta fase.",
        ),
        "profiles": (
            "Inspecciona los perfiles ALSA guardados; nunca ejecuta alsactl.",
            "EJEMPLOS\n"
            "  ae5ctl profiles diff\n"
            "  ae5ctl profiles diff --json\n"
            "  ae5ctl profiles diff --headphones /tmp/hp.state "
            "--speakers /tmp/spk.state\n\n"
            "La comparación es de solo lectura y no necesita hardware.",
        ),
        "tray": (
            "Muestra un indicador GTK 3/Ayatana conectado al motor ALSA.",
            "EJEMPLOS\n"
            "  ae5ctl tray\n"
            "  ae5ctl tray --card Creative --interval 5\n\n"
            "Necesita una sesión gráfica, python3-gi y AyatanaAppIndicator3.\n"
            "No restaura perfiles DSP ni cambia rutas PipeWire.\n"
            "Las consultas y escrituras ALSA se ejecutan fuera del hilo GTK.",
        ),
    }
    for name, help_text in [
        ("cards", "listar tarjetas ALSA y obtener sus ID"),
        ("status", "consultar la salida física seleccionada"),
        ("doctor", "diagnosticar la lectura ALSA (sin reparar audio)"),
        ("capabilities", "inventariar controles ALSA de forma segura"),
        ("controls", "previsualizar valores tipados sin modificar ALSA"),
        ("presets", "gestionar presets JSON de usuario sin aplicarlos"),
        ("switch", "seleccionar auriculares o altavoces"),
        ("toggle", "alternar la salida ALSA"),
        ("validate", "consultar o validar la salida AE-5"),
        ("wizard", "probar ambas salidas mediante asistente guiado"),
        ("tray", "mostrar el indicador gráfico opcional"),
        ("profiles", "comparar perfiles ALSA guardados (solo lectura)"),
    ]:
        description, epilog = details[name]
        command = commands.add_parser(
            name,
            help=help_text,
            description=description,
            epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        if name == "presets":
            tasks = command.add_subparsers(
                dest="preset_action", required=True, metavar="ACCIÓN"
            )
            for action, label in [
                ("list", "listar los presets guardados"),
                ("show", "consultar un preset"),
                ("create", "crear un preset vacío"),
                ("capture", "capturar controles elegidos explícitamente"),
                ("set", "guardar el valor deseado de un control"),
                ("remove", "retirar un control del preset"),
                ("delete", "borrar un preset"),
                ("diff", "comparar valores con ALSA, sin escribir"),
                ("export", "exportar un preset JSON"),
                ("import", "importar un preset JSON validado"),
            ]:
                task = tasks.add_parser(action, help=label)
                if action not in {"list", "import"}:
                    task.add_argument("name", help="nombre del preset")
                if action == "import":
                    task.add_argument("path", type=Path)
                if action == "export":
                    task.add_argument("path", type=Path)
                if action in {"create", "capture"}:
                    task.add_argument("--card", required=True, metavar="ID_ALSA")
                    task.add_argument("--description", default="")
                if action in {"capture", "set"}:
                    task.add_argument(
                        "--numid",
                        type=positive_int,
                        action="append" if action == "capture" else "store",
                        required=True,
                    )
                if action == "set":
                    task.add_argument("--values", required=True, metavar="VALORES")
                if action == "remove":
                    task.add_argument("--control", required=True, metavar="NOMBRE")
                if action in {"import", "export"}:
                    task.add_argument("--force", action="store_true")
                if action in {"capture", "set", "diff"}:
                    task.add_argument(
                        "--timeout", type=positive_timeout, default=3.0
                    )
                task.add_argument("--json", action="store_true")
            continue
        if name == "controls":
            tasks = command.add_subparsers(
                dest="control_action", required=True, metavar="ACCIÓN"
            )
            plan = tasks.add_parser(
                "plan", help="validar valores propuestos sin modificar el control"
            )
            plan.add_argument("numid", type=positive_int)
            plan.add_argument("values", help="un valor por canal separado por coma")
            plan.add_argument("--card", metavar="ID_ALSA")
            plan.add_argument("--json", action="store_true")
            plan.add_argument("--timeout", type=positive_timeout, default=3.0)
            continue
        if name == "profiles":
            tasks = command.add_subparsers(
                dest="profile_action", required=True, metavar="ACCIÓN"
            )
            compare = tasks.add_parser(
                "diff",
                help="comparar los valores guardados sin modificar ALSA",
                description="Compara dos ficheros alsactl store por nombre e interfaz.",
                formatter_class=argparse.RawDescriptionHelpFormatter,
                epilog=(
                    "EJEMPLOS\n"
                    "  ae5ctl profiles diff\n"
                    "  ae5ctl profiles diff --json\n"
                    "  ae5ctl profiles diff --headphones /tmp/hp.state "
                    "--speakers /tmp/spk.state\n\n"
                    "Los valores son guardados; no se comprueba la tarjeta real."
                ),
            )
            compare.add_argument(
                "--headphones",
                type=Path,
                default=HEADPHONES_FILE,
                metavar="FICHERO",
                help=(
                    "perfil auriculares; por defecto: ~/.config/ae5-headphones.state"
                ),
            )
            compare.add_argument(
                "--speakers",
                type=Path,
                default=SPEAKERS_FILE,
                metavar="FICHERO",
                help=("perfil altavoces; por defecto: ~/.config/ae5-speakers.state"),
            )
            compare.add_argument(
                "--json", action="store_true", help="imprimir JSON para scripts"
            )
            continue
        if name not in {"tray", "validate", "wizard"}:
            command.add_argument(
                "--json", action="store_true", help="imprimir JSON para scripts"
            )
        if name == "tray":
            command.add_argument(
                "--interval",
                type=positive_int,
                default=5,
                metavar="SEGUNDOS",
                help="refresco automático en segundos (predeterminado: 5)",
            )
        if name == "doctor":
            command.add_argument(
                "--pipewire",
                action="store_true",
                help="consultar servidor y salidas mediante pactl (solo lectura)",
            )
            command.add_argument(
                "--profiles",
                action="store_true",
                help="incluir la comparación de los .state originales (solo lectura)",
            )
        if name in {"switch", "toggle"}:
            command.add_argument(
                "--dry-run",
                action="store_true",
                help="mostrar el cambio y comando ALSA previstos sin escribir",
            )
        if name == "validate":
            command.add_argument(
                "--apply",
                action="store_true",
                help="autorizar prueba interactiva que puede cambiar ALSA",
            )
        if name == "switch":
            command.add_argument(
                "output",
                choices=("headphones", "speakers"),
                help="salida física de destino",
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


def switch_dict(result: SwitchResult) -> dict:
    return {
        **status_dict(result.after),
        "previous_output": result.before.output,
        "changed": result.changed,
    }


def plan_dict(plan: SwitchPlan) -> dict:
    before = plan.before
    return {
        "scope": "alsa",
        "dry_run": True,
        "card": asdict(before.card),
        "control": asdict(before.control),
        "previous_output": before.output,
        "output": plan.target,
        "item_index": plan.item_index,
        "changed": plan.changed,
        "planned_command": (
            [
                "amixer",
                "-c",
                str(before.card.index),
                "cset",
                f"numid={before.control.numid}",
                str(plan.item_index),
            ]
            if plan.changed
            else None
        ),
    }


def print_plan(value: dict) -> None:
    print("Previsualización ALSA: no se ha escrito ningún control.")
    print(f"Salida actual: {value['previous_output']}")
    print(f"Salida prevista: {value['output']}")
    if value["changed"]:
        print("Comando previsto: " + " ".join(value["planned_command"]))
    else:
        print("La salida ya está seleccionada: no sería necesaria una escritura.")


def print_switch(value: dict) -> None:
    suffix = "cambiada" if value["changed"] else "ya seleccionada (sin cambios)"
    print(f"Salida ALSA: {value['previous_output']} → {value['output']} ({suffix})")
    print("Solo se ha modificado el selector ALSA; no se han restaurado perfiles.")


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


def print_profile_diff(report: dict) -> None:
    summary = report["summary"]
    print("Comparación de perfiles ALSA guardados (solo lectura)")
    print(f"Auriculares: {report['headphones_file']}")
    print(f"Altavoces: {report['speakers_file']}")
    print(
        f"Controles: {summary['controls_headphones']} / "
        f"{summary['controls_speakers']}; sin cambios: "
        f"{summary['unchanged_controls']}; distintos: "
        f"{summary['different_controls']}"
    )
    for diff in report["differences"]:
        print(f"  [{diff['card']}] {diff['name']} ({diff['category']}):")
        left = diff["headphones"] or {}
        right = diff["speakers"] or {}
        for key in sorted(set(left) | set(right)):
            before = str(left.get(key, "<ausente>"))[:120]
            after = str(right.get(key, "<ausente>"))[:120]
            print(f"    {key}: {before} -> {after}")
    for warning in report["warnings"]:
        print(f"AVISO: {warning}")
    for note in report["notes"]:
        print(f"Nota: {note}")


def profiles_command(args: argparse.Namespace) -> int:
    try:
        report = compare_profiles(args.headphones, args.speakers)
    except ProfileError as error:
        if args.json:
            print_json({"error": {"code": error.code, "message": str(error)}})
        else:
            print(f"Error [{error.code}]: {error}", file=sys.stderr)
        return 4
    if args.json:
        print_json(report)
    else:
        print_profile_diff(report)
    return 0


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
    if args.pipewire:
        report["audio_session"] = inspect_audio_session(timeout=args.timeout)
    if args.profiles:
        try:
            comparison = compare_profiles(HEADPHONES_FILE, SPEAKERS_FILE)
        except ProfileError as error:
            report["profiles"] = {
                "ok": False,
                "error": {"code": error.code, "message": str(error)},
            }
        else:
            report["profiles"] = {"ok": True, "comparison": comparison}
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
        if args.pipewire:
            session = report["audio_session"]
            if session["available"]:
                print(f"Servidor de audio: {session['server_name'] or 'desconocido'}")
                print(
                    f"Salida predeterminada: {session['default_sink'] or 'no indicada'}"
                )
                for sink in session["sinks"]:
                    print(f"Salida disponible: {sink['name']} ({sink['state']})")
                for card in session["cards"]:
                    print(f"Tarjeta del servidor: {card['name']}")
            else:
                print("Servidor de audio: pactl no disponible o sin conexión.")
            for issue in session["errors"]:
                print(f"Aviso audio [{issue['code']}]: {issue['message']}")
            for note in session["notes"]:
                print(note)
        if args.profiles:
            profiles = report["profiles"]
            if profiles["ok"]:
                print_profile_diff(profiles["comparison"])
            else:
                error = profiles["error"]
                print(f"Aviso perfiles [{error['code']}]: {error['message']}")
        for note in report["notes"]:
            print(note)
    return result


def presets_command(args: argparse.Namespace) -> int:
    """File operations do not instantiate the ALSA backend."""
    store = PresetStore()
    try:
        action = args.preset_action
        if action == "list":
            output = {"schema_version": 1, "presets": store.list()}
        elif action == "show":
            output = store.read(args.name)
        elif action == "create":
            output = store.save(
                new_preset(args.name, args.card, args.description)
            )
        elif action == "delete":
            store.delete(args.name)
            output = {"deleted": args.name}
        elif action == "import":
            output = store.import_file(args.path, overwrite=args.force)
        elif action == "export":
            store.export_file(args.name, args.path, overwrite=args.force)
            output = {"exported": args.name, "path": str(args.path)}
        elif action == "remove":
            document = store.read(args.name)
            output = store.save(
                remove_control(document, args.control), overwrite=True
            )
        else:
            document = None
            if action in {"set", "diff"}:
                document = store.read(args.name)
            backend = AlsaBackend(timeout=args.timeout)
            if action == "diff":
                output = compare(document, backend)
            elif action == "set":
                entry = read_control(
                    backend, document["card_id"], args.numid, args.values
                )
                output = store.save(set_control(document, entry), overwrite=True)
            elif action == "capture":
                if len(args.numid) != len(set(args.numid)):
                    raise PresetError(
                        "duplicate_control", "Se repite un numid en la captura."
                    )
                document = new_preset(args.name, args.card, args.description)
                for number in args.numid:
                    entry = read_control(backend, args.card, number)
                    set_control(document, entry)
                output = store.save(document)
            else:
                raise PresetError("invalid_action", "Acción de presets desconocida.")
    except PresetError as error:
        if args.json:
            print_json({"error": {"code": error.code, "message": str(error)}})
        else:
            print(f"Error preset [{error.code}]: {error}", file=sys.stderr)
        return 4
    except AlsaError as error:
        if args.json:
            print_json({"error": error_dict(error)})
        else:
            print_error(error)
        return exit_code(error)

    if args.json:
        print_json(output)
    elif action == "list":
        for preset in output["presets"]:
            print(
                f"{preset['name']} [{preset['card_id']}]: "
                f"{preset['controls']} controles"
            )
        if not output["presets"]:
            print("No hay presets guardados.")
    elif action == "diff":
        print(f"Preset {output['preset']}: comparación ALSA de solo lectura")
        for control in output["controls"]:
            print(f"  {control['identity']['name']}: {control['status']}")
        print("NO se ha aplicado ningún control ni ajuste DSP.")
    elif action in {"delete", "export"}:
        print(f"Operación {action} completada: {args.name}.")
    else:
        print(
            f"Preset {output['name']} [{output['card_id']}]: "
            f"{len(output['controls'])} controles; solo configuración guardada."
        )
        print("No se ha aplicado ningún cambio al hardware.")
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments:
        parser().print_help()
        return 0
    args = parser().parse_args(arguments)
    if args.command == "profiles":
        return profiles_command(args)
    if args.command == "presets":
        return presets_command(args)
    if args.command == "tray":
        from ae5ctl.tray import run_tray

        return run_tray(
            card=args.card,
            numid=args.numid,
            timeout=args.timeout,
            interval=args.interval,
        )
    backend = AlsaBackend(timeout=getattr(args, "timeout", 3.0))
    if args.command == "doctor":
        return doctor(backend, args)
    try:
        if args.command == "wizard" or (args.command == "validate" and args.apply):
            from ae5ctl.wizard import run_wizard

            return run_wizard(backend, card=args.card, numid=args.numid)
        if args.command == "validate":
            from ae5ctl.validation import run_validation

            return run_validation(backend, card=args.card, numid=args.numid)
        if args.command == "controls":
            result = plan_control(
                backend, card=args.card, numid=args.numid, requested=args.values
            )
            if args.json:
                print_json(result)
            else:
                print(
                    f"Vista previa de {result['identity']['name']}: "
                    f"{result['previous_values']} → {result['requested_values']}"
                )
                print("SOLO LECTURA: el control ALSA NO se ha modificado.")
                print(result["reason"])
            return 0
        if args.command == "capabilities":
            report = scan_capabilities(backend, card=args.card, numid=args.numid)
            if args.json:
                print_json(report)
            else:
                selected = report["card"]
                print(f"Inventario ALSA: {selected['id']} — {selected['name']}")
                for control in report["controls"]:
                    print(
                        f"  {control['numid']} · {control['name']} "
                        f"[{control['type']}; {control['family']}; "
                        f"{control['write_policy']}]"
                    )
                for error in report["errors"]:
                    print(f"  Aviso [{error['numid']}]: {error['message']}")
                print("SOLO LECTURA: ningún control habilitado para escritura.")
            return 0 if report["ok"] else 4
        if args.command == "cards":
            cards = [asdict(card) for card in backend.cards()]
            if args.json:
                print_json({"cards": cards})
            else:
                for card in cards:
                    print(f"{card['index']} [{card['id']}] {card['name']}")
                if not cards:
                    print("No hay tarjetas ALSA disponibles.")
        elif args.command == "status":
            status = status_dict(backend.status(card=args.card, numid=args.numid))
            if args.json:
                print_json(status)
            else:
                print_status(status)
        else:
            if args.dry_run:
                if args.command == "switch":
                    plan = backend.plan_switch(
                        args.output, card=args.card, numid=args.numid
                    )
                else:
                    plan = backend.plan_toggle(card=args.card, numid=args.numid)
                preview = plan_dict(plan)
                if args.json:
                    print_json(preview)
                else:
                    print_plan(preview)
            else:
                if args.command == "switch":
                    changed = backend.switch(
                        args.output, card=args.card, numid=args.numid
                    )
                else:
                    changed = backend.toggle(card=args.card, numid=args.numid)
                outcome = switch_dict(changed)
                if args.json:
                    print_json(outcome)
                else:
                    print_switch(outcome)
    except AlsaError as error:
        if args.json:
            print_json({"error": error_dict(error)})
        else:
            print_error(error)
        return exit_code(error)
    return 0
