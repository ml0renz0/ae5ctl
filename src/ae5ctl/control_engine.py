"""Fail-closed ALSA transaction engine; intentionally NOT exposed to the CLI.

No real controls are certified yet. A caller must supply a trusted, exact
control approval; user presets and driver 'rw' flags are never approvals.
Test it with simulated ALSA before allowing physical writes in a later phase.
"""

from dataclasses import dataclass

from ae5ctl.alsa import AlsaBackend, AlsaError, Card
from ae5ctl.capabilities import scan_capabilities
from ae5ctl.control_plans import contract, fingerprint, normalize


@dataclass(frozen=True)
class ControlApproval:
    """Private policy input, not serializable from a user preset."""

    contract_fingerprint: str
    permitted_targets: frozenset[tuple[str, ...]]


def _read_exact(backend: AlsaBackend, plan: dict) -> tuple[str, ...]:
    report = scan_capabilities(
        backend, card=plan["card"]["id"], numid=plan["lookup_numid"]
    )
    if report["card"] != plan["card"]:
        raise AlsaError("card_changed", "La identidad de la tarjeta cambió.")
    if not report["ok"] or len(report["controls"]) != 1:
        if report["errors"]:
            issue = report["errors"][0]
            raise AlsaError(issue["code"], issue["message"])
        raise AlsaError("control_changed", "El control dejó de estar disponible.")
    current = report["controls"][0]
    if contract(report["card"], current) != plan["contract"]:
        raise AlsaError("control_changed", "Los metadatos ALSA del control cambiaron.")
    return tuple(normalize(current, ",".join(current["values"])))


def _restore_after_attempt(
    backend: AlsaBackend,
    plan: dict,
    previous: tuple[str, ...],
    target: tuple[str, ...],
    issue: str,
) -> None:
    """Only restore if current value still equals the value WE requested."""
    try:
        actual = _read_exact(backend, plan)
    except AlsaError as exc:
        raise AlsaError(
            "recovery_uncertain",
            f"{issue}; no se pudo verificar el estado para restaurar: {exc}",
        ) from exc
    if actual == previous:
        raise AlsaError(
            "apply_failed_unchanged", f"{issue}; ALSA conserva el valor inicial."
        )
    if actual != target:
        raise AlsaError(
            "recovery_skipped_external",
            f"{issue}; un cambio externo impide restaurar sin sobrescribirlo.",
        )
    try:
        _write(backend, plan, previous)
        recovered = _read_exact(backend, plan)
    except (AlsaError, KeyboardInterrupt) as exc:
        raise AlsaError(
            "recovery_failed",
            f"{issue}; la recuperación se intentó pero no pudo verificarse: {exc}",
        ) from exc
    if recovered != previous:
        raise AlsaError(
            "recovery_failed",
            f"{issue}; ALSA no confirmó la restauración del valor inicial.",
        )
    raise AlsaError(
        "apply_failed_restored",
        f"{issue}; la selección inicial fue restaurada y verificada.",
    )


def _write(backend: AlsaBackend, plan: dict, values: tuple[str, ...]) -> None:
    # The card was verified in _read_exact immediately before this call.
    backend._run(
        Card(**plan["card"]),
        "cset",
        f"numid={plan['lookup_numid']}",
        ",".join(values),
    )


def apply_certified_control(
    backend: AlsaBackend,
    plan: dict,
    *,
    approval: ControlApproval | None = None,
) -> dict:
    """Apply and verify a *certified* control, with conditional rollback.

    This internal API is not reachable from the CLI, presets or GNOME. No
    control approval is shipped. It cannot guarantee atomic ALSA compare/set.
    """
    if (
        approval is None
        or not isinstance(approval, ControlApproval)
        or plan.get("write_policy") == "blocked"
        or not plan.get("driver_reports_writable", False)
        or approval.contract_fingerprint != plan.get("contract_fingerprint")
        or approval.contract_fingerprint != fingerprint(plan["contract"])
    ):
        raise AlsaError(
            "not_certified", "El control no dispone de aprobación de escritura."
        )
    previous = tuple(plan["previous_values"])
    target = tuple(plan["requested_values"])
    if target not in approval.permitted_targets:
        raise AlsaError(
            "not_certified", "El valor solicitado no tiene aprobación de escritura."
        )

    # Fail closed on stale state and metadata; recheck immediately before cset.
    if _read_exact(backend, plan) != previous:
        raise AlsaError("state_changed", "La lectura del plan ya no está vigente.")
    if previous == target:
        return {"changed": False, "verified": True, "output_values": list(previous)}
    if _read_exact(backend, plan) != previous:
        raise AlsaError("state_changed", "Otro cliente cambió ALSA antes de cset.")
    try:
        _write(backend, plan, target)
    except (AlsaError, KeyboardInterrupt) as exc:
        _restore_after_attempt(backend, plan, previous, target, str(exc))
    try:
        observed = _read_exact(backend, plan)
    except AlsaError as exc:
        _restore_after_attempt(backend, plan, previous, target, str(exc))
    if observed != target:
        _restore_after_attempt(
            backend, plan, previous, target, "La escritura no se verificó."
        )
    return {"changed": True, "verified": True, "output_values": list(observed)}
