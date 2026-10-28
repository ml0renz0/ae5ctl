"""Characterization and explicit expected failures for the original ALSA code."""

from subprocess import CompletedProcess
from unittest.mock import Mock, mock_open

import pytest


@pytest.mark.parametrize(
    "cards",
    ["", "--- no soundcards ---\n", " 1 [USB ]: USB-Audio - USB Audio\n"],
)
def test_no_matching_card_returns_unknown(legacy, monkeypatch, cards):
    read_cards = mock_open(read_data=cards)
    monkeypatch.setattr(legacy, "open", read_cards, raising=False)

    assert legacy.find_ae5_card_index() is None
    read_cards.assert_called_once_with("/proc/asound/cards")


def test_missing_proc_file_returns_unknown(legacy, monkeypatch):
    monkeypatch.setattr(
        legacy, "open", Mock(side_effect=FileNotFoundError), raising=False
    )

    assert legacy.find_ae5_card_index() is None


def test_recognized_card_uses_index_from_fixture(legacy, monkeypatch):
    monkeypatch.setattr(
        legacy,
        "open",
        mock_open(read_data=" 3 [AE5 ]: HDA-Intel - Sound BlasterX AE-5\n"),
        raising=False,
    )

    assert legacy.find_ae5_card_index() == 3


@pytest.mark.parametrize("card,control", [(None, "37"), (3, None)])
def test_missing_card_or_control_does_not_invoke_amixer(legacy, card, control):
    assert legacy.current_from_enum(card, control) is None
    legacy.subprocess.run.assert_not_called()


def test_no_card_skips_control_discovery(legacy):
    assert legacy.find_hp_speakers_enum(None) is None
    legacy.subprocess.run.assert_not_called()


@pytest.mark.parametrize("reader", ["current_from_enum", "find_hp_speakers_enum"])
def test_amixer_failure_returns_unknown_in_legacy_code(legacy, reader):
    command = Mock(return_value=CompletedProcess("amixer", 1, "", "No such card"))
    legacy.subprocess.run = command

    function = getattr(legacy, reader)
    result = function(3, "37") if reader == "current_from_enum" else function(3)

    assert result is None
    command.assert_called_once()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Legacy notify interpolates the message into a shell command",
)
def test_notification_keeps_apostrophe_as_literal_argument(legacy):
    command = Mock(return_value=CompletedProcess("notify-send", 0, "", ""))
    legacy.subprocess.run = command
    message = "Can't restore state"

    legacy.notify(message)

    assert command.call_args.args[0] == ["notify-send", "AE-5", message]
    assert command.call_args.kwargs.get("shell", False) is False


@pytest.mark.parametrize(
    "filename,expected",
    [("output-headphone.txt", "headphones"), ("output-speakers.txt", "speakers")],
)
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="Legacy parser searches words in numeric values= instead of resolving Item indices",
)
def test_numeric_enum_resolves_selected_item(
    legacy, monkeypatch, alsa_fixture, filename, expected
):
    monkeypatch.setattr(
        legacy,
        "sh",
        Mock(return_value=CompletedProcess("amixer", 0, alsa_fixture(filename), "")),
    )

    assert legacy.current_from_enum(3, "37") == expected


@pytest.mark.parametrize(
    "filename",
    [
        "output-plural.txt",
        pytest.param(
            "output-headphone.txt",
            marks=pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="Legacy control discovery rejects singular Headphone",
            ),
        ),
    ],
)
def test_discovers_output_control(legacy, monkeypatch, alsa_fixture, filename):
    def command(cmd):
        stdout = (
            alsa_fixture("controls.txt")
            if cmd.endswith(" controls")
            else alsa_fixture(filename)
        )
        return CompletedProcess(cmd, 0, stdout, "")

    monkeypatch.setattr(legacy, "sh", command)

    assert legacy.find_hp_speakers_enum(3) == "37"
