"""Exercise CLI -> ALSA backend -> amixer command boundaries without audio hardware."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from ae5ctl import cli
from ae5ctl.alsa import AlsaBackend

CARDS = (
    " 2 [USB]: USB-Audio - USB Audio\n"
    " 7 [Creative]: HDA-Intel - Sound BlasterX AE-5\n"
)
CONTROLS = (
    "numid=9,iface=MIXER,name='Master Playback Volume'\n"
    "numid=43,iface=MIXER,name='Output Select'\n"
)
VOLUME = (
    "numid=9,iface=MIXER,name='Master Playback Volume'\n"
    " ; type=INTEGER,access=rw------,values=1,min=0,max=100,step=0\n"
    " : values=70\n"
)


def enum(value: int) -> str:
    return (
        "numid=43,iface=MIXER,name='Output Select'\n"
        " ; type=ENUMERATED,access=rw------,values=1,items=3\n"
        " ; Item #0 'Headphone'\n"
        " ; Item #1 'Speakers'\n"
        " ; Item #2 'Auto'\n"
        f" : values={value}\n"
    )


@pytest.fixture
def simulated_ae5(monkeypatch, tmp_path):
    cards_file = tmp_path / "asound-cards"
    cards_file.write_text(CARDS, encoding="utf-8")
    state = {"item": 0, "writes": 0, "readback_fails": False, "hotplug": False}

    def run(command, **kwargs):
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 3.0
        assert command[:3] == ["amixer", "-c", "7"]
        action = tuple(command[3:])
        if action == ("controls",):
            return subprocess.CompletedProcess(command, 0, CONTROLS, "")
        if action == ("cget", "numid=9"):
            return subprocess.CompletedProcess(command, 0, VOLUME, "")
        if action == ("cget", "numid=43"):
            if state["readback_fails"] and state["writes"]:
                return subprocess.CompletedProcess(command, 1, "", "readback failed")
            if state["hotplug"]:
                cards_file.write_text(
                    CARDS.replace("[Creative]", "[Replacement]").replace(
                        "Sound BlasterX AE-5", "Unrelated device"
                    ),
                    encoding="utf-8",
                )
            return subprocess.CompletedProcess(command, 0, enum(state["item"]), "")
        if action in {
            ("cset", "numid=43", "0"),
            ("cset", "numid=43", "1"),
        }:
            state["writes"] += 1
            state["item"] = int(action[-1])
            return subprocess.CompletedProcess(command, 0, enum(state["item"]), "")
        raise AssertionError(f"Unexpected amixer invocation: {command}")

    runner = Mock(side_effect=run)
    monkeypatch.setattr(
        cli,
        "AlsaBackend",
        lambda timeout: AlsaBackend(cards_path=cards_file, runner=runner, timeout=timeout),
    )
    return state, runner


def test_switch_dry_run_emits_exact_command_and_never_writes(simulated_ae5, capsys):
    state, runner = simulated_ae5
    assert cli.main(["switch", "speakers", "--dry-run", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["dry_run"] is True
    assert data["previous_output"] == "headphones"
    assert data["output"] == "speakers"
    assert data["item_index"] == 1
    assert data["planned_command"] == [
        "amixer", "-c", "7", "cset", "numid=43", "1"
    ]
    assert state["item"] == 0
    assert state["writes"] == 0
    assert all("cset" not in call.args[0] for call in runner.call_args_list)


def test_noop_dry_run_does_not_plan_unnecessary_write(simulated_ae5, capsys):
    state, runner = simulated_ae5
    assert cli.main(["switch", "headphones", "--dry-run", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["changed"] is False
    assert data["planned_command"] is None
    assert data["item_index"] == 0
    assert state["writes"] == 0
    assert all("cset" not in call.args[0] for call in runner.call_args_list)


def test_toggle_dry_run_and_two_real_transitions(simulated_ae5, capsys):
    state, runner = simulated_ae5
    assert cli.main(["toggle", "--dry-run", "--json"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["output"] == "speakers"
    assert state["writes"] == 0

    assert cli.main(["switch", "speakers", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["changed"] is True
    assert result["output"] == "speakers"
    assert state["writes"] == 1
    assert state["item"] == 1

    assert cli.main(["toggle", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["output"] == "headphones"
    assert state["writes"] == 2
    assert state["item"] == 0
    assert all(call.args[0][2] == "7" for call in runner.call_args_list)


def test_changed_card_identity_refuses_write(simulated_ae5, capsys):
    state, runner = simulated_ae5
    state["hotplug"] = True
    assert cli.main(["switch", "speakers", "--json"]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["error"]["code"] == "card_changed"
    assert state["writes"] == 0
    assert all("cset" not in call.args[0] for call in runner.call_args_list)


def test_failed_readback_after_write_reports_uncertain_state(simulated_ae5, capsys):
    state, runner = simulated_ae5
    state["readback_fails"] = True
    assert cli.main(["switch", "speakers", "--json"]) == 4
    error = json.loads(capsys.readouterr().out)["error"]
    assert error["code"] == "verify_failed"
    assert "ae5ctl status" in error["message"]
    assert state["item"] == 1
    assert state["writes"] == 1


def test_dry_run_text_clearly_identifies_itself(simulated_ae5, capsys):
    state, _ = simulated_ae5
    assert cli.main(["toggle", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "no se ha escrito" in output
    assert "amixer -c 7 cset numid=43 1" in output
    assert state["writes"] == 0
