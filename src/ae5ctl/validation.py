"""Guided AE-5 hardware validation: read-only unless explicitly authorized.

The user, not the program, verifies whether sound actually reaches each jack.
No audio is played, ALSA profiles are never restored and GUI state is untouched.
"""

from collections.abc import Callable

from ae5ctl.alsa import AlsaBackend, AlsaError

NO_WRITE_ERRORS = {"state_changed", "control_changed", "card_changed"}


def _heard(ask: Callable[[str], str], question: str) -> bool:
    return ask(question).strip().casefold() in {"s", "si", "sí"}


def run_validation(
    backend: AlsaBackend,
    *,
    card: str | None = None,
    numid: int | None = None,
    apply: bool = False,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> int:
    """Inspect, optionally toggle with explicit consent, then attempt recovery.

    Returns 0 only for a successful guided sound check, 5 if not completed
    successfully, and 130 on user interruption. Initial ALSA errors propagate
    to the CLI's existing error handling.
    """
    initial = backend.status(card=card, numid=numid)
    pinned_card = initial.card.id
    pinned_numid = initial.control.numid
    plan = backend.plan_toggle(card=pinned_card, numid=pinned_numid)
    if plan.before != initial:
        raise AlsaError(
            "state_changed",
            "La salida ALSA cambió durante la preparación de la prueba.",
        )

    say(
        f"Tarjeta ALSA: {pinned_card} (índice {initial.card.index}), "
        f"selector {initial.control.name!r} (numid={pinned_numid})"
    )
    say(f"Salida inicial: {initial.output}; destino: {plan.target}.")
    say("La lectura ALSA no demuestra que los conectores produzcan audio.")
    say("Esta prueba no modifica ganancia, volumen, DSP ni perfiles PipeWire.")
    if not apply:
        say("SOLO LECTURA: no se ha enviado ningún cambio ALSA.")
        say("Use --apply para iniciar una prueba auditiva con autorización manual.")
        return 0

    say("Pon una muestra de sonido en reproducción desde Ubuntu.")
    say("El programa NO genera sonido ni guarda perfiles ALSA.")
    attempted = False
    alternate_audible = False
    interrupted = False
    failure: str | None = None
    restored = False
    try:
        if not _heard(ask, "¿Se oye la salida inicial? [s/N] "):
            failure = "No se confirmó audio en la salida inicial."
        elif ask(
            f"Escribe CAMBIAR para pasar a {plan.target} [cancelar]: "
        ).strip() != "CAMBIAR":
            failure = "La escritura ALSA no ha sido autorizada."
        else:
            attempted = True
            try:
                switched = backend.switch(
                    plan.target, card=pinned_card, numid=pinned_numid
                )
                if not switched.changed:
                    failure = "La salida ya había cambiado; prueba no concluyente."
                else:
                    alternate_audible = _heard(
                        ask, f"¿Se oye audio por {plan.target}? [s/N] "
                    )
                    if not alternate_audible:
                        failure = "No se confirmó audio en la salida alternativa."
            except AlsaError as error:
                if error.code in NO_WRITE_ERRORS:
                    # The engine explicitly refused cset. Do not override
                    # an external change by attempting to restore our snapshot.
                    attempted = False
                failure = f"Conmutación ALSA fallida [{error.code}]: {error}"
    except (KeyboardInterrupt, EOFError):
        interrupted = True
        failure = "La validación se interrumpió."
    finally:
        if attempted:
            say(f"Intentando restaurar la selección inicial: {initial.output}.")
            try:
                result = backend.switch(
                    initial.output, card=pinned_card, numid=pinned_numid
                )
                restored = result.after.output == initial.output
            except AlsaError as error:
                failure = f"Restauración ALSA fallida [{error.code}]: {error}"
            if restored:
                say("ALSA confirma de nuevo la selección inicial.")
            else:
                say("ALERTA: no se ha confirmado la restauración del selector.")
                say("Revisa 'ae5ctl status' antes de cualquier cambio adicional.")
                say("No se han restaurado perfiles ni ajustes DSP.")

    if interrupted:
        say(failure or "La validación se interrumpió.")
        return 130
    if failure:
        say(f"Validación incompleta: {failure}")
        return 5
    if not attempted or not restored or not alternate_audible:
        say("Validación incompleta: no se han verificado ambas salidas.")
        return 5
    try:
        if not _heard(ask, "¿Vuelve a oírse la salida inicial? [s/N] "):
            say("Validación incompleta: no se confirmó audio tras restaurar.")
            return 5
    except (KeyboardInterrupt, EOFError):
        say("Validación interrumpida tras restaurar el selector.")
        return 130

    say("PASS: ambas salidas audibles y selector ALSA inicial restaurado.")
    say("La bandeja GNOME y la equivalencia DSP requieren pruebas independientes.")
    return 0
