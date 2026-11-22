"""Six-step wizard tests: simulated PulseAudio, ALSA and user input only."""

import json
import subprocess
import wave
from collections import deque

from ae5ctl.wizard import Sink, choose_sink, discover_sinks, run_wizard
from test_validation import FakeBackend


def answers(*values):
    responses = deque(values)

    def ask(_message):
        return responses.popleft()

    return ask


def fake_audio(*, match=True, missing_tool=None):
    commands = []

    def runner(command, **kwargs):
        assert kwargs["shell"] is False
        commands.append(command)
        if command[0] == missing_tool:
            raise FileNotFoundError(command[0])
        if command[:5] == ["pactl", "-f", "json", "list", "sinks"]:
            props = {"alsa.card": "7"} if match else {}
            payload = [
                {
                    "name": "alsa_output.pci-creative.analog-stereo",
                    "description": "AE-5 Analog Stereo",
                    "properties": props,
                }
            ]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[0] == "paplay":
            assert command[1] == "--device=alsa_output.pci-creative.analog-stereo"
            with wave.open(command[-1], "rb") as sound:
                assert sound.getnchannels() == 1
                assert sound.getframerate() == 48000
                assert sound.getnframes() > 20000
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(f"Unexpected command: {command}")

    return runner, commands


def test_fully_guided_wizard_plays_three_tones_and_restores_original():
    backend = FakeBackend()
    runner, commands = fake_audio()
    output = []
    result = run_wizard(
        backend,
        ask=answers("sí", "CAMBIAR", "sí", "sí"),
        say=output.append,
        runner=runner,
        profiles=lambda *_: {
            "summary": {"different_controls": 2, "possible_non_routing_changes": 1}
        },
    )
    assert result == 0
    assert backend.writes == ["speakers", "headphones"]
    assert sum(c[0] == "paplay" for c in commands) == 3
    assert any("PASO 1/6" in text for text in output)
    assert any("PASO 6/6" in text for text in output)
    assert any("PASS" in text for text in output)
    assert any("ganancia/DSP" in text for text in output)


def test_wizard_no_heard_audio_does_not_write():
    backend = FakeBackend()
    runner, commands = fake_audio()
    assert run_wizard(
        backend, ask=answers("no"), runner=runner, profiles=lambda *_: {
            "summary": {"different_controls": 0, "possible_non_routing_changes": 0}
        }
    ) == 5
    assert backend.writes == []
    assert sum(c[0] == "paplay" for c in commands) == 1


def test_wizard_missing_audio_utility_stops_before_writing():
    backend = FakeBackend()
    runner, commands = fake_audio(missing_tool="pactl")
    assert run_wizard(backend, runner=runner, ask=lambda _: "s") == 5
    assert backend.writes == []
    assert not any(c[0] == "paplay" for c in commands)


def test_wizard_multiple_sinks_require_explicit_selection():
    all_sinks = [
        Sink("one", "AE-5 Stereo", 7),
        Sink("two", "AE-5 Surround", 7),
        Sink("three", "HDMI", 2),
    ]
    lines = []
    selected = choose_sink(all_sinks, 7, answers("9", "2"), lines.append)
    assert selected.name == "two"
    assert "HDMI" not in " ".join(lines)


def test_unknown_sink_mapping_requires_manual_selection_not_default():
    sinks = [Sink("hdmi", "HDMI", 2), Sink("creative", "Creative", None)]
    output = []
    assert choose_sink(sinks, 7, answers("2"), output.append).name == "creative"
    assert "AVISO" in " ".join(output)
    assert choose_sink(sinks, 7, answers("0"), output.append) is None


def test_probe_matches_only_selected_card_index():
    runner, _ = fake_audio()
    sinks = discover_sinks(runner)
    assert sinks[0].alsa_card == 7


def test_wizard_playback_failure_after_switch_restores_card():
    backend = FakeBackend()
    runner, commands = fake_audio()
    counter = {"sound": 0}

    def flaky(cmd, **kwargs):
        if cmd[0] == "paplay":
            counter["sound"] += 1
            if counter["sound"] == 2:
                return subprocess.CompletedProcess(cmd, 1, "", "device lost")
        return runner(cmd, **kwargs)

    assert run_wizard(
        backend,
        ask=answers("s", "CAMBIAR"),
        runner=flaky,
        profiles=lambda *_: {
            "summary": {"different_controls": 0, "possible_non_routing_changes": 0}
        },
    ) == 5
    assert backend.writes == ["speakers", "headphones"]


def test_wizard_interruption_before_changing_exits_cleanly():
    backend = FakeBackend()
    runner, _ = fake_audio(match=False)

    def interrupt(_):
        raise KeyboardInterrupt

    assert run_wizard(backend, ask=interrupt, runner=runner) == 130
    assert backend.writes == []


def test_wizard_no_audio_writes_until_selected_sink_confirmed():
    backend = FakeBackend()
    runner, commands = fake_audio(match=False)
    assert run_wizard(
        backend, ask=answers("0"), runner=runner
    ) == 5
    assert backend.writes == []
    assert not any(cmd[0] == "paplay" for cmd in commands)
