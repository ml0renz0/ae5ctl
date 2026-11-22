"""Headless validation of the guided AE-5 hardware check."""

from collections import deque

import pytest

from ae5ctl.alsa import AlsaError, Card, EnumControl, Status, SwitchPlan, SwitchResult
from ae5ctl.validation import run_validation


class FakeBackend:
    def __init__(self):
        self.card = Card(7, "Creative", "Sound BlasterX AE-5")
        self.control = EnumControl(
            43, "Output Select", {0: "Headphone", 1: "Speakers"}, (0,)
        )
        self.output = "headphones"
        self.writes = []
        self.error_on_first: str | None = None
        self.restore_error = False

    def status(self, card=None, numid=None):
        assert card in {None, "Creative"}
        assert numid in {None, 43}
        item = 0 if self.output == "headphones" else 1
        control = EnumControl(43, "Output Select", self.control.items, (item,))
        return Status(self.card, control, self.output)

    def plan_toggle(self, card=None, numid=None):
        before = self.status(card=card, numid=numid)
        target = "speakers" if before.output == "headphones" else "headphones"
        item = 1 if target == "speakers" else 0
        return SwitchPlan(before, target, item, True)

    def switch(self, output, card=None, numid=None):
        before = self.status(card=card, numid=numid)
        if self.restore_error and output == "headphones":
            raise AlsaError("verify_failed", "restoration unavailable")
        if self.error_on_first and output == "speakers":
            code = self.error_on_first
            if code == "verify_failed":
                self.output = "speakers"
                self.writes.append(output)
            raise AlsaError(code, "synthetic switch failure")
        self.output = output
        changed = before.output != output
        if changed:
            self.writes.append(output)
        return SwitchResult(before, self.status(card=card, numid=numid), changed)


def answers(*values):
    responses = deque(values)

    def ask(_question):
        return responses.popleft()

    return ask


def test_read_only_is_default_and_never_prompts():
    backend = FakeBackend()
    text = []
    assert (
        run_validation(
            backend, ask=lambda _: pytest.fail("unexpected prompt"), say=text.append
        )
        == 0
    )
    assert backend.writes == []
    assert any("SOLO LECTURA" in line for line in text)


def test_two_confirmed_audible_outputs_and_restored_initial_selection():
    backend = FakeBackend()
    text = []
    result = run_validation(
        backend,
        apply=True,
        ask=answers("sí", "CAMBIAR", "s", "s"),
        say=text.append,
    )
    assert result == 0
    assert backend.writes == ["speakers", "headphones"]
    assert backend.output == "headphones"
    assert any("PASS" in line for line in text)


@pytest.mark.parametrize("responses", [("n",), ("s", "NO")])
def test_refusing_audio_or_consent_never_writes(responses):
    backend = FakeBackend()
    assert run_validation(backend, apply=True, ask=answers(*responses)) == 5
    assert backend.writes == []


def test_unheard_alternate_output_is_restored_and_fails():
    backend = FakeBackend()
    assert run_validation(backend, apply=True, ask=answers("s", "CAMBIAR", "n")) == 5
    assert backend.writes == ["speakers", "headphones"]
    assert backend.output == "headphones"


def test_ctrl_c_during_second_audio_prompt_attempts_restoration():
    backend = FakeBackend()
    prompts = iter(["s", "CAMBIAR"])

    def ask(_question):
        try:
            return next(prompts)
        except StopIteration:
            raise KeyboardInterrupt from None

    assert run_validation(backend, apply=True, ask=ask) == 130
    assert backend.writes == ["speakers", "headphones"]


def test_readback_failure_after_write_still_attempts_to_restore():
    backend = FakeBackend()
    backend.error_on_first = "verify_failed"
    text = []
    assert (
        run_validation(
            backend, apply=True, ask=answers("s", "CAMBIAR"), say=text.append
        )
        == 5
    )
    assert backend.writes == ["speakers", "headphones"]
    assert backend.output == "headphones"
    assert any("Validación incompleta" in line for line in text)


@pytest.mark.parametrize("code", ["state_changed", "control_changed", "card_changed"])
def test_refused_write_does_not_undo_external_state(code):
    backend = FakeBackend()
    backend.error_on_first = code
    assert run_validation(backend, apply=True, ask=answers("s", "CAMBIAR")) == 5
    assert backend.writes == []


def test_restore_failure_reports_uncertainty_and_no_pass():
    backend = FakeBackend()
    backend.restore_error = True
    text = []
    assert (
        run_validation(
            backend,
            apply=True,
            ask=answers("s", "CAMBIAR", "s"),
            say=text.append,
        )
        == 5
    )
    assert backend.output == "speakers"
    assert any("ALERTA" in line for line in text)
    assert not any("PASS" in line for line in text)


def test_initial_selection_moved_during_plan_aborts_without_writing():
    backend = FakeBackend()
    original_plan = backend.plan_toggle

    def changed_plan(**kwargs):
        backend.output = "speakers"
        return original_plan(**kwargs)

    backend.plan_toggle = changed_plan
    with pytest.raises(AlsaError) as caught:
        run_validation(backend, apply=True, ask=lambda _: pytest.fail("prompt"))
    assert caught.value.code == "state_changed"
    assert backend.writes == []


def test_external_switch_to_target_is_not_undone():
    backend = FakeBackend()

    def external_switch(output, card=None, numid=None):
        before = backend.status(card=card, numid=numid)
        backend.output = output
        return SwitchResult(before, backend.status(card=card, numid=numid), False)

    backend.switch = external_switch
    text = []
    assert run_validation(
        backend, apply=True, ask=answers("s", "CAMBIAR"), say=text.append
    ) == 5
    assert backend.output == "speakers"
    assert not any("Intentando restaurar" in line for line in text)
