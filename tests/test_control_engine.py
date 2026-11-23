"""Transaction simulation: no real ALSA hardware or approvals in production."""

import subprocess

import pytest

from ae5ctl.alsa import AlsaBackend, AlsaError
from ae5ctl.control_engine import ControlApproval, apply_certified_control
from ae5ctl.control_plans import plan_control


class SimulatedCard:
    def __init__(self, tmp_path, *, name="Master Playback Volume"):
        self.cards_path = tmp_path / "cards"
        self.cards_path.write_text(
            " 7 [Creative       ]: HDA-Intel - HDA Creative\n"
            "                      Sound BlasterX AE-5\n",
            encoding="utf-8",
        )
        self.name = name
        self.values = ["40", "40"]
        self.calls = []
        self.write_error_after_mutation = False
        self.external_after_write = None
        self.fail_rollback = False
        self.interrupt_after_write = False
        self.on_read = None
        self.reads = 0
        self.backend = AlsaBackend(cards_path=self.cards_path, runner=self.run)

    def run(self, command, **kwargs):
        assert kwargs["shell"] is False
        assert command[:3] == ["amixer", "-c", "7"]
        action = command[3:]
        self.calls.append(action)
        if action == ["cget", "numid=11"]:
            self.reads += 1
            if self.on_read:
                self.on_read(self)
            value = ",".join(self.values)
            payload = (
                f"numid=11,iface=MIXER,name='{self.name}'\n"
                "  ; type=INTEGER,access=rw------,values=2,min=0,max=100,step=1\n"
                f"  : values={value}\n"
            )
            return subprocess.CompletedProcess(command, 0, payload, "")
        if action[:2] == ["cset", "numid=11"]:
            if self.fail_rollback and action[2] == "40,40":
                return subprocess.CompletedProcess(command, 1, "", "rollback failed")
            self.values = action[2].split(",")
            if self.external_after_write is not None:
                self.values = list(self.external_after_write)
            if self.interrupt_after_write:
                self.interrupt_after_write = False
                raise KeyboardInterrupt
            if self.write_error_after_mutation:
                self.write_error_after_mutation = False
                return subprocess.CompletedProcess(command, 1, "", "I/O failure")
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"Unexpected ALSA operation: {action}")

    def plan(self, request="50,50"):
        return plan_control(self.backend, card="Creative", numid=11, requested=request)

    def approved(self, plan):
        return ControlApproval(
            contract_fingerprint=plan["contract_fingerprint"],
            permitted_targets=frozenset({tuple(plan["requested_values"])}),
        )

    def writes(self):
        return [call for call in self.calls if call[0] == "cset"]


def test_no_certification_means_no_write(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan)
    assert error.value.code == "not_certified"
    assert not sim.writes()


def test_simulated_certification_checks_and_verifies_exact_output(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()
    result = apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert result == {"changed": True, "verified": True, "output_values": ["50", "50"]}
    assert sim.values == ["50", "50"]
    assert sim.writes() == [["cset", "numid=11", "50,50"]]


def test_disallowed_target_is_rejected_before_write(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()
    approval = ControlApproval(
        contract_fingerprint=plan["contract_fingerprint"],
        permitted_targets=frozenset({("60", "60")}),
    )
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan, approval=approval)
    assert error.value.code == "not_certified"
    assert not sim.writes()


def test_changed_state_before_write_is_rejected(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()
    sim.values = ["41", "41"]
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert error.value.code == "state_changed"
    assert not sim.writes()


def test_changed_control_metadata_is_rejected(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()
    sim.name = "Unexpected hardware control"
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert error.value.code == "control_changed"
    assert not sim.writes()


def test_stale_second_read_blocks_before_write(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()

    def race(device):
        if device.reads == 3:
            device.values = ["44", "44"]

    sim.on_read = race
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert error.value.code == "state_changed"
    assert not sim.writes()


def test_failed_cset_that_changed_value_is_conditionally_rolled_back(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()
    sim.write_error_after_mutation = True
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert error.value.code == "apply_failed_restored"
    assert sim.values == ["40", "40"]
    assert sim.writes() == [
        ["cset", "numid=11", "50,50"],
        ["cset", "numid=11", "40,40"],
    ]


def test_interrupted_cset_that_changed_value_is_rolled_back(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()
    sim.interrupt_after_write = True
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert error.value.code == "apply_failed_restored"
    assert sim.values == ["40", "40"]


def test_external_change_after_write_is_never_overwritten(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()
    sim.external_after_write = ["33", "33"]
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert error.value.code == "recovery_skipped_external"
    assert sim.values == ["33", "33"]
    assert len(sim.writes()) == 1


def test_recovery_failure_is_reported_not_hidden(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan()
    sim.write_error_after_mutation = True
    sim.fail_rollback = True
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert error.value.code == "recovery_failed"
    assert sim.values == ["50", "50"]
    assert len(sim.writes()) == 2


def test_blocked_controls_stay_blocked_even_with_approval(tmp_path):
    sim = SimulatedCard(tmp_path, name="OutFX Switch")
    plan = sim.plan()
    with pytest.raises(AlsaError) as error:
        apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert error.value.code == "not_certified"
    assert not sim.writes()


def test_no_op_does_not_write_but_requires_approval(tmp_path):
    sim = SimulatedCard(tmp_path)
    plan = sim.plan(request="40,40")
    result = apply_certified_control(sim.backend, plan, approval=sim.approved(plan))
    assert result["changed"] is False
    assert not sim.writes()
