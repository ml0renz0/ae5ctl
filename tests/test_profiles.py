"""Synthetic alsactl state snapshots; no real cards, alsactl or amixer."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from ae5ctl import cli
from ae5ctl.profiles import (
    MAX_BYTES,
    ProfileError,
    compare_profiles,
    load_state,
    parse_state,
)


def snapshot(
    *,
    route="Headphone",
    volume="35",
    numids=(1, 2),
    card="Creative",
    another_card=False,
):
    data = f"""# Synthetic alsactl store output
state.{card} {{
    control.{numids[0]} {{
        iface MIXER
        name 'Output Select'
        value '{route}'
        comment {{
            access 'read write'
            type ENUMERATED
            count 1
            item.0 Headphone
            item.1 Speakers
        }}
    }}
    control.{numids[1]} {{
        iface MIXER
        name 'Master Playback Volume'
        value.0 {volume}
        value.1 {volume}
        comment {{
            type INTEGER
            count 2
            range '0 - 100'
        }}
    }}
}}
"""
    if another_card:
        data += """state.HDMI {
    control.3 {
        iface MIXER
        name 'PCM Playback Switch'
        value true
        comment { type BOOLEAN count 1 }
    }
}
"""
    return data


@pytest.fixture
def state_files(tmp_path):
    def write(headphones, speakers):
        first = tmp_path / "headphones.state"
        second = tmp_path / "speakers.state"
        first.write_text(headphones, encoding="utf-8")
        second.write_text(speakers, encoding="utf-8")
        return first, second

    return write


def test_diff_only_reports_changed_values_and_flags_volume(state_files):
    hp, spk = state_files(
        snapshot(route="Headphone", volume="35"),
        snapshot(route="Speakers", volume="80"),
    )
    report = compare_profiles(hp, spk)

    assert report["scope"] == "saved_alsa_profiles"
    assert report["summary"]["controls_headphones"] == 2
    assert report["summary"]["controls_speakers"] == 2
    assert report["summary"]["different_controls"] == 2
    assert report["summary"]["possible_non_routing_changes"] == 1
    assert report["summary"]["affected_cards"] == ["Creative"]
    by_name = {row["name"]: row for row in report["differences"]}
    assert by_name["Output Select"]["category"] == "possible_routing"
    assert by_name["Master Playback Volume"]["category"] == "level_or_mute"
    assert by_name["Master Playback Volume"]["headphones"] == {
        "value.0": "35",
        "value.1": "35",
    }
    assert by_name["Master Playback Volume"]["speakers"]["value.0"] == "80"
    assert "restauración" in report["warnings"][0]


def test_control_numbers_not_used_as_identity(state_files):
    hp, spk = state_files(
        snapshot(numids=(1, 2)),
        snapshot(numids=(80, 99)),
    )
    report = compare_profiles(hp, spk)
    assert report["summary"]["different_controls"] == 0
    assert report["summary"]["unchanged_controls"] == 2


def test_renumbered_changed_control_keeps_both_numids(state_files):
    hp, spk = state_files(
        snapshot(numids=(1, 2), route="Headphone"),
        snapshot(numids=(80, 99), route="Speakers"),
    )
    report = compare_profiles(hp, spk)
    assert report["summary"]["different_controls"] == 1
    row = report["differences"][0]
    assert row["headphones_numid"] == 1
    assert row["speakers_numid"] == 80


def test_multi_card_snapshots_are_not_silently_reduced_to_ae5(state_files):
    hp, spk = state_files(
        snapshot(another_card=True),
        snapshot(route="Speakers", another_card=True),
    )
    report = compare_profiles(hp, spk)
    assert report["summary"]["cards_headphones"] == 2
    assert report["summary"]["affected_cards"] == ["Creative"]
    assert any("varias tarjetas ALSA" in item for item in report["warnings"])


def test_missing_card_and_control_are_explicit(state_files):
    hp, spk = state_files(
        snapshot(another_card=True),
        snapshot(route="Speakers"),
    )
    report = compare_profiles(hp, spk)
    statuses = {item["status"] for item in report["differences"]}
    assert statuses == {"changed", "only_headphones"}
    assert sorted(report["summary"]["affected_cards"]) == ["Creative", "HDMI"]


def test_control_names_preserve_spaces_and_quoted_punctuation():
    text = """state.Creative {
  control.4 {
    iface MIXER
    name 'Owner\\'s Audio #1'
    index 1
    value 'Left / Right'
    comment { type ENUMERATED count 1 }
  }
}
"""
    # ALSA names with special characters must not turn into separate keys.
    cards = parse_state(text)
    control = next(iter(cards["Creative"].values()))
    assert control.name == "Owner's Audio #1"
    assert control.index == "1"
    assert control.values == (("value", "Left / Right"),)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "state.Creative {",
        "state.Creative { control.1 { iface MIXER name A value 1 }",
        "state.Creative { control.1 { iface MIXER name A } }",
        "state.Creative { control.1 { iface MIXER name A value { x 1 } } }",
        "state.Creative { control.1 { iface MIXER name A value 1 value 2 } }",
        "state.Creative { control.x { iface MIXER name A value 1 } }",
        "state.Creative { control.1 { iface MIXER name A value 'unfinished } }",
        "state.Creative { control.1 { iface MIXER name A value 1 } } }",
        "root.A { control.1 { iface MIXER name A value 1 } }",
    ],
)
def test_invalid_input_is_rejected_not_partially_accepted(text):
    with pytest.raises(ProfileError) as exc:
        parse_state(text)
    assert exc.value.code == "invalid_profile"


def test_duplicate_semantic_identity_is_rejected():
    text = """state.Creative {
    control.1 { iface MIXER name 'Output Select' value Headphone }
    control.2 { iface MIXER name 'Output Select' value Speakers }
}
"""
    with pytest.raises(ProfileError, match="duplicado"):
        parse_state(text)


def test_file_missing_and_oversize_fail_safely(tmp_path):
    with pytest.raises(ProfileError) as missing:
        load_state(tmp_path / "missing")
    assert missing.value.code == "file_missing"

    huge = tmp_path / "too-big.state"
    huge.write_bytes(b"x" * (MAX_BYTES + 1))
    with pytest.raises(ProfileError) as oversized:
        load_state(huge)
    assert oversized.value.code == "file_too_large"


def test_default_profiles_command_does_not_access_alsa(monkeypatch, tmp_path, capsys):
    hp, spk = (
        tmp_path / "headphones.state",
        tmp_path / "speakers.state",
    )
    hp.write_text(snapshot(), encoding="utf-8")
    spk.write_text(snapshot(route="Speakers"), encoding="utf-8")

    # Any ALSA access or process execution is a regression in read-only mode.
    monkeypatch.setattr(cli, "AlsaBackend", Mock(side_effect=AssertionError("ALSA")))
    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=AssertionError("subprocess invoked"))
    )

    assert cli.main(
        [
            "profiles",
            "diff",
            "--headphones",
            str(hp),
            "--speakers",
            str(spk),
            "--json",
        ]
    ) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["different_controls"] == 1


def test_command_text_and_missing_file_contract(state_files, capsys, tmp_path):
    hp, spk = state_files(snapshot(), snapshot(route="Speakers"))
    args = [
        "profiles",
        "diff",
        "--headphones",
        str(hp),
        "--speakers",
        str(spk),
    ]
    assert cli.main(args) == 0
    assert "Output Select" in capsys.readouterr().out

    missing = tmp_path / "absent"
    assert cli.main([*args, "--headphones", str(missing), "--json"]) == 4
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["error"]["code"] == "file_missing"


def test_profiles_help_is_available_without_hardware(monkeypatch, capsys):
    monkeypatch.setattr(cli, "AlsaBackend", Mock(side_effect=AssertionError))
    for argv in (["profiles", "--help"], ["profiles", "diff", "--help"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(argv)
        assert exc.value.code == 0
        assert "diff" in capsys.readouterr().out


def test_compare_identical_snapshots_avoids_false_safety_claims(state_files):
    hp, spk = state_files(snapshot(), snapshot())
    report = compare_profiles(hp, spk)
    assert report["summary"]["different_controls"] == 0
    assert any("no se ha probado" in warning for warning in report["warnings"])
