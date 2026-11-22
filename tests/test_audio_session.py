"""Probe pactl deterministically without connecting to a real audio server."""

import subprocess
from unittest.mock import Mock

import pytest

from ae5ctl.audio_session import inspect_audio_session

PIPEWIRE_INFO = """Server String: /run/user/1000/pulse/native
Server Name: PulseAudio (on PipeWire 1.0.5)
Default Sink: alsa_output.pci-0000_09_00.0.analog-stereo
"""
SINKS = (
    "62\talsa_output.pci-0000_09_00.0.analog-stereo\tPipeWire\t"
    "s32le 2ch 48000Hz\tRUNNING\n"
    "63\talsa_output.usb-Audio.analog-stereo\tPipeWire\t"
    "s16le 2ch 44100Hz\tSUSPENDED\n"
)
CARDS = "40\talsa_card.pci-0000_09_00.0\tmodule-alsa-card.c\n"


def runner_with(*, info=PIPEWIRE_INFO, sinks=SINKS, cards=CARDS):
    responses = {
        ("pactl", "info"): info,
        ("pactl", "list", "short", "sinks"): sinks,
        ("pactl", "list", "short", "cards"): cards,
    }

    def respond(command, **kwargs):
        assert command[0] == "pactl"
        assert kwargs["shell"] is False
        assert kwargs["check"] is False
        assert kwargs["timeout"] == 5
        assert kwargs["env"]["LC_ALL"] == "C"
        return subprocess.CompletedProcess(command, 0, responses[tuple(command)], "")

    return Mock(side_effect=respond)


def test_pipewire_identification_and_default_sink_are_explicit():
    runner = runner_with()
    report = inspect_audio_session(timeout=5, runner=runner)
    assert report["available"] is True
    assert report["server_kind"] == "pipewire"
    assert report["server_name"] == "PulseAudio (on PipeWire 1.0.5)"
    assert report["default_sink"].startswith("alsa_output.")
    assert report["sinks"] == [
        {
            "index": 62,
            "name": "alsa_output.pci-0000_09_00.0.analog-stereo",
            "state": "RUNNING",
        },
        {
            "index": 63,
            "name": "alsa_output.usb-Audio.analog-stereo",
            "state": "SUSPENDED",
        },
    ]
    assert report["cards"] == [{"index": 40, "name": "alsa_card.pci-0000_09_00.0"}]
    assert report["errors"] == []
    assert runner.call_count == 3


@pytest.mark.parametrize(
    "name,expected",
    [
        ("PulseAudio", "pulseaudio"),
        ("PulseAudio (on PipeWire 1.2.0)", "pipewire"),
        ("Some other server", "unknown"),
    ],
)
def test_pactl_does_not_automatically_mean_pipewire(name, expected):
    report = inspect_audio_session(
        timeout=5, runner=runner_with(info=f"Server Name: {name}\n")
    )
    assert report["server_kind"] == expected


def test_missing_pactl_reports_unavailable_observation_not_absence_of_pipewire():
    runner = Mock(side_effect=FileNotFoundError("pactl"))
    report = inspect_audio_session(timeout=5, runner=runner)
    assert report["available"] is False
    assert report["server_kind"] == "unknown"
    assert report["errors"][0]["code"] == "command_missing"
    runner.assert_called_once()


def test_timeout_is_bounded_and_reported():
    runner = Mock(side_effect=subprocess.TimeoutExpired(["pactl", "info"], 5))
    report = inspect_audio_session(timeout=5, runner=runner)
    assert report["available"] is False
    assert report["errors"][0]["code"] == "command_timeout"


def test_failed_server_connection_is_not_a_success():
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            ["pactl", "info"], 1, "", "Connection refused"
        )
    )
    report = inspect_audio_session(timeout=5, runner=runner)
    assert report["available"] is False
    assert report["server_kind"] == "unknown"
    assert "Connection refused" in report["errors"][0]["message"]


def test_short_list_retains_valid_entries_when_some_are_malformed():
    report = inspect_audio_session(
        timeout=5,
        runner=runner_with(sinks=SINKS + "corrupt entry\n", cards=CARDS + "invalid\n"),
    )
    assert len(report["sinks"]) == 2
    assert len(report["cards"]) == 1
    assert len(report["errors"]) == 2
    assert all(error["code"] == "parse_error" for error in report["errors"])


def test_partial_query_failure_keeps_independent_observations():
    standard = runner_with()

    def runner(command, **kwargs):
        if command == ["pactl", "list", "short", "sinks"]:
            return subprocess.CompletedProcess(command, 1, "", "Failure")
        return standard(command, **kwargs)

    report = inspect_audio_session(timeout=5, runner=runner)
    assert report["available"] is True
    assert report["sinks"] == []
    assert len(report["cards"]) == 1
    assert report["errors"][0]["code"] == "command_failed"


def test_missing_server_name_stays_unknown():
    report = inspect_audio_session(
        timeout=5, runner=runner_with(info="Default Sink: placeholder\n")
    )
    assert report["available"] is True
    assert report["server_kind"] == "unknown"
    assert report["errors"][0]["code"] == "parse_error"
