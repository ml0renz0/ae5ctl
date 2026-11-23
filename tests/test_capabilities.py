"""Capability discovery never writes hardware or assumes an AE-5 DSP layout."""

import json
import subprocess

import pytest

from ae5ctl import cli
from ae5ctl.alsa import AlsaBackend, AlsaError
from ae5ctl.capabilities import classify, parse_control_detail, scan_capabilities

CARDS = """ 7 [Creative       ]: HDA-Intel - HDA Creative
                      Sound BlasterX AE-5 at 0xf000 irq 22
"""
CONTROLS = """numid=11,iface=MIXER,name='Master Playback Volume'
numid=43,iface=MIXER,name='Output Select'
numid=74,iface=MIXER,name='OutFX Switch'
"""
VOLUME = """numid=11,iface=MIXER,name='Master Playback Volume'
  ; type=INTEGER,access=rw------,values=2,min=0,max=100,step=0
  : values=60,60
"""
OUTPUT = """numid=43,iface=MIXER,name='Output Select'
  ; type=ENUMERATED,access=rw------,values=1,items=2
  ; Item #0 'Headphone'
  ; Item #1 'Speakers'
  : values=0
"""
OUTFX = """numid=74,iface=MIXER,name='OutFX Switch'
  ; type=BOOLEAN,access=rw------,values=1
  : values=off
"""


@pytest.fixture
def backend(tmp_path):
    path = tmp_path / "cards"
    path.write_text(CARDS, encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        assert command[:3] == ["amixer", "-c", "7"]
        assert kwargs["shell"] is False
        calls.append(command[3:])
        payload = {
            ("controls",): CONTROLS,
            ("cget", "numid=11"): VOLUME,
            ("cget", "numid=43"): OUTPUT,
            ("cget", "numid=74"): OUTFX,
        }[tuple(command[3:])]
        return subprocess.CompletedProcess(command, 0, payload, "")

    return AlsaBackend(cards_path=path, runner=runner), calls


def test_discovery_inventories_all_types_without_any_write(backend):
    device, commands = backend
    report = scan_capabilities(device)
    assert report["schema_version"] == 1
    assert report["ok"] is True
    assert report["card"]["id"] == "Creative"
    assert report["summary"]["discovered"] == 3
    assert report["summary"]["driver_reports_writable"] == 3
    assert report["summary"]["editable_by_ae5ctl"] == 0
    assert report["summary"]["blocked"] == 1
    by_name = {item["name"]: item for item in report["controls"]}
    assert by_name["Master Playback Volume"]["values"] == ["60", "60"]
    assert by_name["Master Playback Volume"]["range"] == {
        "min": 0, "max": 100, "step": 0
    }
    assert by_name["Output Select"]["items"] == {"0": "Headphone", "1": "Speakers"}
    assert by_name["Output Select"]["family"] == "routing"
    assert by_name["OutFX Switch"]["write_policy"] == "blocked"
    assert all(not item["editable_by_ae5ctl"] for item in report["controls"])
    assert commands == [
        ["controls"],
        ["cget", "numid=11"],
        ["cget", "numid=43"],
        ["cget", "numid=74"],
    ]


def test_specific_numid_does_not_enumerate_other_controls(backend):
    device, calls = backend
    report = scan_capabilities(device, card="Creative", numid=43)
    assert [control["numid"] for control in report["controls"]] == [43]
    assert calls == [["cget", "numid=43"]]


@pytest.mark.parametrize(
    "name",
    ["OutFX Switch", "Direct Mode", "Headphone Gain", "RGB Strip", "Flash Firmware"],
)
def test_dangerous_controls_blocked_by_default(name):
    family, policy = classify(name)
    assert family == "restricted"
    assert policy == "blocked"


def test_readonly_driver_flags_still_never_authorize_writes():
    source = VOLUME.replace("access=rw------", "access=r-------")
    item = parse_control_detail(source, 11)
    assert item["driver_reports_writable"] is False
    assert item["editable_by_ae5ctl"] is False


def test_partial_error_keeps_valid_items_and_exits_nonzero(backend, capsys, monkeypatch):
    device, calls = backend
    original = device._read

    def failing(card, *args):
        if args == ("cget", "numid=43"):
            raise AlsaError("command_failed", "permission denied")
        return original(card, *args)

    monkeypatch.setattr(device, "_read", failing)
    report = scan_capabilities(device)
    assert report["ok"] is False
    assert report["summary"]["discovered"] == 2
    assert report["errors"][0]["numid"] == 43

    monkeypatch.setattr(cli, "AlsaBackend", lambda **kwargs: device)
    assert cli.main(["capabilities", "--json"]) == 4
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["errors"][0]["code"] == "command_failed"
    assert all("cset" not in call for call in calls)


def test_duplicate_numid_is_rejected_before_cget(backend, monkeypatch):
    device, calls = backend
    original = device._read

    def duplicate(card, *args):
        if args == ("controls",):
            return CONTROLS + CONTROLS.splitlines()[0] + "\n"
        return original(card, *args)

    monkeypatch.setattr(device, "_read", duplicate)
    with pytest.raises(AlsaError, match="duplicado"):
        scan_capabilities(device)
    assert calls == []


def test_mismatched_numid_and_incomplete_enum_fail_closed():
    with pytest.raises(AlsaError, match="distinto"):
        parse_control_detail(OUTPUT, 99)
    with pytest.raises(AlsaError, match="incompleto"):
        parse_control_detail(OUTPUT.replace("  ; Item #1 'Speakers'\n", ""), 43)


def test_cli_scans_selected_card_and_json_contract(backend, monkeypatch, capsys):
    device, calls = backend
    monkeypatch.setattr(cli, "AlsaBackend", lambda **kwargs: device)
    assert cli.main(["capabilities", "--card", "Creative", "--numid", "43", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["scope"] == "alsa_capabilities"
    assert result["summary"]["discovered"] == 1
    assert calls == [["cget", "numid=43"]]


def test_capabilities_help_rejects_unsupported_interval(capsys):
    with pytest.raises(SystemExit) as exited:
        cli.main(["capabilities", "--help"])
    assert exited.value.code == 0
    help_text = capsys.readouterr().out
    assert "--json" in help_text and "--numid" in help_text
    with pytest.raises(SystemExit) as exited:
        cli.main(["wizard", "--interval", "1"])
    assert exited.value.code == 2


def test_read_only_inventory_does_not_deduce_effect_support_from_driver():
    item = parse_control_detail(
        VOLUME.replace("Master Playback Volume", "FX Crystalizer"), 11
    )
    assert item["family"] == "dsp"
    assert item["write_policy"] == "unverified"
    assert item["editable_by_ae5ctl"] is False
