"""Exercise the read-only CLI with an injected ALSA backend, without hardware."""

import json
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from ae5ctl import cli
from ae5ctl.alsa import AlsaBackend, AlsaError, Card, EnumControl, Status, SwitchResult


@pytest.fixture
def backend(monkeypatch):
    card = Card(index=3, id="Creative", name="Sound BlasterX AE-5")
    control = EnumControl(
        numid=37,
        name="Output Select",
        items={0: "Speakers", 1: "Headphone"},
        values=(1,),
    )
    instance = Mock(spec=["cards", "status", "switch", "toggle"])
    instance.cards.return_value = [card]
    instance.status.return_value = Status(
        card=card, control=control, output="headphones"
    )
    after = Status(card=card, control=control, output="speakers")
    outcome = SwitchResult(
        before=instance.status.return_value,
        after=after,
        changed=True,
    )
    instance.switch.return_value = outcome
    instance.toggle.return_value = outcome
    factory = Mock(return_value=instance)
    monkeypatch.setattr(cli, "AlsaBackend", factory)
    return instance, factory


def test_cards_json_lists_identity_without_querying_controls(backend, capsys):
    instance, _ = backend

    assert cli.main(["cards", "--json"]) == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report == {
        "cards": [{"index": 3, "id": "Creative", "name": "Sound BlasterX AE-5"}]
    }
    assert captured.err == ""
    instance.cards.assert_called_once_with()
    instance.status.assert_not_called()


def test_status_json_reports_selected_item_and_alsa_scope(backend, capsys):
    instance, _ = backend

    assert cli.main(["status", "--json"]) == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report["scope"] == "alsa"
    assert report["card"]["id"] == "Creative"
    assert report["control"]["numid"] == 37
    assert report["control"]["items"]["1"] == "Headphone"
    assert report["control"]["values"] == [1]
    assert report["output"] == "headphones"
    instance.cards.assert_not_called()


@pytest.mark.parametrize("command", ["status", "doctor"])
def test_selection_and_timeout_reach_backend(backend, capsys, command):
    instance, factory = backend

    assert (
        cli.main(
            [
                command,
                "--card",
                "Creative",
                "--numid",
                "37",
                "--timeout",
                "1.5",
                "--json",
            ]
        )
        == 0
    )

    json.loads(capsys.readouterr().out)
    factory.assert_called_once_with(timeout=1.5)
    instance.status.assert_called_once_with(card="Creative", numid=37)


@pytest.mark.parametrize(
    "code,expected_exit",
    [
        ("no_card", 3),
        ("card_not_found", 3),
        ("ambiguous_card", 3),
        ("no_control", 3),
        ("ambiguous_control", 3),
        ("unknown_output", 3),
        ("command_missing", 4),
        ("command_failed", 4),
        ("command_timeout", 4),
        ("parse_error", 4),
        ("unreadable_cards", 4),
    ],
)
def test_status_errors_have_machine_readable_codes(
    backend, capsys, code, expected_exit
):
    instance, _ = backend
    instance.status.side_effect = AlsaError(code, "Synthetic ALSA failure")

    assert cli.main(["status", "--json"]) == expected_exit

    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {"code": code, "message": "Synthetic ALSA failure"}
    }


def test_cards_errors_use_same_json_contract(backend, capsys):
    instance, _ = backend
    instance.cards.side_effect = AlsaError("unreadable_cards", "Permission denied")

    assert cli.main(["cards", "--json"]) == 4

    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "error": {"code": "unreadable_cards", "message": "Permission denied"}
    }
    assert captured.err == ""
    instance.status.assert_not_called()


def test_text_error_uses_stderr(backend, capsys):
    instance, _ = backend
    instance.status.side_effect = AlsaError("ambiguous_card", "Select a card")

    assert cli.main(["status"]) == 3

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Select a card" in captured.err


def test_doctor_pipewire_is_opt_in_and_preserves_alsa_exit_code(
    backend, monkeypatch, capsys
):
    probe = Mock(
        return_value={
            "available": True,
            "server_kind": "pipewire",
            "server_name": "PulseAudio (on PipeWire 1.0)",
            "default_sink": "alsa_output.pci-0000_01_00.0",
            "sinks": [],
            "cards": [],
            "errors": [],
            "notes": [],
        }
    )
    monkeypatch.setattr(cli, "inspect_audio_session", probe)
    assert cli.main(["doctor", "--pipewire", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["audio_session"]["server_kind"] == "pipewire"
    assert report["ok"] is True
    probe.assert_called_once_with(timeout=3.0)

    assert cli.main(["doctor", "--json"]) == 0
    assert "audio_session" not in json.loads(capsys.readouterr().out)
    assert probe.call_count == 1


def test_missing_pactl_does_not_fail_valid_alsa_doctor(backend, monkeypatch, capsys):
    probe = Mock(
        return_value={
            "available": False,
            "server_kind": "unknown",
            "server_name": None,
            "default_sink": None,
            "sinks": [],
            "cards": [],
            "errors": [{"code": "command_missing", "message": "pactl no existe"}],
            "notes": [],
        }
    )
    monkeypatch.setattr(cli, "inspect_audio_session", probe)
    assert cli.main(["doctor", "--pipewire", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["audio_session"]["available"] is False
    assert report["audio_session"]["errors"][0]["code"] == "command_missing"


def test_optional_audio_diagnostics_run_even_when_alsa_fails(
    backend, monkeypatch, capsys
):
    instance, _ = backend
    instance.status.side_effect = AlsaError("no_control", "Sin selector")
    probe = Mock(
        return_value={
            "available": True,
            "server_name": "PulseAudio",
            "default_sink": "sink",
            "sinks": [],
            "cards": [],
            "errors": [],
            "notes": [],
        }
    )
    monkeypatch.setattr(cli, "inspect_audio_session", probe)
    assert cli.main(["doctor", "--pipewire", "--json"]) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["audio_session"]["available"] is True
    probe.assert_called_once_with(timeout=3.0)


def test_optional_audio_text_report_does_not_change_alsa_result(
    backend, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli,
        "inspect_audio_session",
        Mock(
            return_value={
                "available": True,
                "server_name": "PulseAudio (on PipeWire)",
                "default_sink": "sink.0",
                "sinks": [{"name": "sink.0", "state": "RUNNING"}],
                "cards": [{"name": "card.0"}],
                "errors": [],
                "notes": ["Solo consulta"],
            }
        ),
    )
    assert cli.main(["doctor", "--pipewire"]) == 0
    output = capsys.readouterr().out
    assert "PulseAudio (on PipeWire)" in output
    assert "Salida predeterminada: sink.0" in output
    assert "card.0" in output
    assert "Solo consulta" in output


def test_doctor_reports_scope_and_selected_state(backend, capsys):
    assert cli.main(["doctor", "--json"]) == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report["ok"] is True
    assert report["scope"] == "alsa"
    assert report["cards"][0]["id"] == "Creative"
    assert report["status"]["output"] == "headphones"
    assert report["errors"] == []
    assert report["notes"]
    assert all(isinstance(note, str) for note in report["notes"])


def test_doctor_preserves_card_listing_when_status_fails(backend, capsys):
    instance, _ = backend
    instance.status.side_effect = AlsaError("no_control", "No compatible control")

    assert cli.main(["doctor", "--json"]) == 3

    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["cards"][0]["id"] == "Creative"
    assert report["status"] is None
    assert report["errors"] == [
        {"code": "no_control", "message": "No compatible control"}
    ]


def test_doctor_stops_if_card_listing_fails(backend, capsys):
    instance, _ = backend
    instance.cards.side_effect = AlsaError("no_card", "No audio devices")

    assert cli.main(["doctor", "--json"]) == 3

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report["ok"] is False
    assert report["cards"] == []
    assert report["status"] is None
    assert report["errors"] == [{"code": "no_card", "message": "No audio devices"}]
    instance.status.assert_not_called()


@pytest.mark.parametrize("command", ["cards", "status", "doctor"])
def test_text_commands_return_readable_output(backend, capsys, command):
    assert cli.main([command]) == 0

    captured = capsys.readouterr()
    assert "Creative" in captured.out
    assert captured.err == ""


@pytest.mark.parametrize(
    "argv",
    [
        ["--help"],
        ["cards", "--help"],
        ["status", "--help"],
        ["doctor", "--help"],
    ],
)
def test_help_does_not_instantiate_backend(backend, capsys, argv):
    _, factory = backend

    with pytest.raises(SystemExit) as error:
        cli.main(argv)

    assert error.value.code == 0
    assert capsys.readouterr().out
    factory.assert_not_called()


@pytest.mark.parametrize(
    "argv",
    [
        ["switch"],
        ["switch", "invalid"],
        ["status", "--numid", "0"],
        ["status", "--numid", "-1"],
        ["status", "--numid", "not-a-number"],
        ["status", "--timeout", "0"],
        ["status", "--timeout", "-1"],
        ["status", "--timeout", "nan"],
        ["status", "--timeout", "inf"],
        ["doctor", "--timeout", "-inf"],
    ],
)
def test_invalid_arguments_fail_before_accessing_audio(backend, capsys, argv):
    _, factory = backend

    with pytest.raises(SystemExit) as error:
        cli.main(argv)

    assert error.value.code == 2
    assert capsys.readouterr().err
    factory.assert_not_called()


@pytest.fixture
def real_backend(monkeypatch, tmp_path):
    """Use synthetic /proc data and the actual backend with no real processes."""
    cards_path = tmp_path / "cards"
    cards_path.write_text(
        " 3 [Creative ]: HDA-Intel - Sound BlasterX AE-5\n", encoding="utf-8"
    )
    runner = Mock()
    monkeypatch.setattr(
        cli,
        "AlsaBackend",
        lambda **kwargs: AlsaBackend(cards_path=cards_path, runner=runner, **kwargs),
    )
    return runner


def test_status_integration_resolves_numeric_value_to_json(real_backend, capsys):
    command = ["amixer", "-c", "3", "cget", "numid=37"]
    real_backend.return_value = CompletedProcess(
        command,
        0,
        "numid=37,iface=MIXER,name='Output Select'\n"
        "  ; type=ENUMERATED,access=rw------,values=1,items=2\n"
        "  ; Item #0 'Speakers'\n"
        "  ; Item #1 'Headphone'\n"
        "  : values=1\n",
        "",
    )

    assert cli.main(["status", "--card", "Creative", "--numid", "37", "--json"]) == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report["card"]["id"] == "Creative"
    assert report["control"]["values"] == [1]
    assert report["output"] == "headphones"
    real_backend.assert_called_once()
    assert real_backend.call_args.args[0] == command
    assert real_backend.call_args.kwargs["shell"] is False


def test_doctor_integration_preserves_amixer_failure(real_backend, capsys):
    command = ["amixer", "-c", "3", "controls"]
    real_backend.return_value = CompletedProcess(command, 1, "", "Access denied")

    assert cli.main(["doctor", "--card", "Creative", "--json"]) == 4

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report["ok"] is False
    assert report["cards"][0]["id"] == "Creative"
    assert report["status"] is None
    assert report["errors"][0]["code"] == "command_failed"
    assert "Access denied" in report["errors"][0]["message"]
    real_backend.assert_called_once()
    assert real_backend.call_args.args[0] == command
    assert real_backend.call_args.kwargs["shell"] is False


def test_no_arguments_displays_main_help_without_alsa(backend, capsys):
    _, factory = backend
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    for text in ("COMANDO", "EJEMPLOS", "CÓDIGOS DE SALIDA", "--version"):
        assert text in out
    factory.assert_not_called()


@pytest.mark.parametrize(
    "argv, required",
    [
        (["--help"], ("cards", "status", "doctor", "EJEMPLOS", "--version")),
        (["cards", "--help"], ("--json", "EJEMPLOS", "ae5ctl cards")),
        (
            ["status", "--help"],
            ("--card", "--numid", "--timeout", "EJEMPLOS", "ae5ctl cards"),
        ),
        (
            ["doctor", "--help"],
            ("--json", "--card", "--timeout", "--pipewire", "EJEMPLOS"),
        ),
        (
            ["switch", "--help"],
            ("--card", "--numid", "--dry-run", "headphones", "speakers", "EJEMPLOS"),
        ),
        (["toggle", "--help"], ("--card", "--numid", "--dry-run", "EJEMPLOS")),
        (["tray", "--help"], ("--card", "--interval", "Ayatana", "EJEMPLOS")),
    ],
)
def test_help_explains_usage_without_accessing_hardware(
    backend, capsys, argv, required
):
    _, factory = backend
    with pytest.raises(SystemExit) as error:
        cli.main(argv)
    assert error.value.code == 0
    output = capsys.readouterr().out
    for text in required:
        assert text in output
    factory.assert_not_called()


def test_version_is_available_without_alsa(backend, capsys):
    from ae5ctl import __version__

    _, factory = backend
    with pytest.raises(SystemExit) as error:
        cli.main(["--version"])
    assert error.value.code == 0
    assert capsys.readouterr().out.strip() == f"ae5ctl {__version__}"
    factory.assert_not_called()


def test_version_tracks_pyproject():
    from pathlib import Path

    from ae5ctl import __version__

    project = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert f'version = "{__version__}"' in project


def test_human_readable_error_has_actionable_hint(backend, capsys):
    instance, _ = backend
    instance.status.side_effect = AlsaError("card_not_found", "Tarjeta no detectada")
    assert cli.main(["status"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Sugerencia:" in captured.err
    assert "ae5ctl cards" in captured.err


def test_json_error_does_not_include_human_hint(backend, capsys):
    instance, _ = backend
    instance.status.side_effect = AlsaError("card_not_found", "Tarjeta no detectada")
    assert cli.main(["status", "--json"]) == 3
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {"code": "card_not_found", "message": "Tarjeta no detectada"}
    }


@pytest.mark.parametrize(
    "argv, method, expected_args",
    [
        (["switch", "speakers"], "switch", ("speakers",)),
        (["toggle"], "toggle", ()),
    ],
)
def test_output_actions_expose_readback_json(
    backend, capsys, argv, method, expected_args
):
    instance, _ = backend
    assert cli.main([*argv, "--card", "Creative", "--numid", "37", "--json"]) == 0

    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report["scope"] == "alsa"
    assert report["previous_output"] == "headphones"
    assert report["output"] == "speakers"
    assert report["changed"] is True
    getattr(instance, method).assert_called_once_with(
        *expected_args, card="Creative", numid=37
    )


def test_switch_text_explains_scope(backend, capsys):
    assert cli.main(["switch", "speakers"]) == 0
    output = capsys.readouterr().out
    assert "headphones" in output
    assert "speakers" in output
    assert "perfiles" in output


def test_write_verification_failure_preserves_json_contract(backend, capsys):
    instance, _ = backend
    instance.switch.side_effect = AlsaError("verify_failed", "No confirmado")
    assert cli.main(["switch", "speakers", "--json"]) == 4
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "error": {"code": "verify_failed", "message": "No confirmado"}
    }


def test_write_failure_shows_recovery_hint(backend, capsys):
    instance, _ = backend
    instance.toggle.side_effect = AlsaError("verify_failed", "No confirmado")
    assert cli.main(["toggle"]) == 4
    captured = capsys.readouterr()
    assert "ae5ctl status" in captured.err


def test_tray_delegates_without_instantiating_cli_backend(backend, monkeypatch):
    from ae5ctl import tray

    _, factory = backend
    start = Mock(return_value=0)
    monkeypatch.setattr(tray, "run_tray", start)
    assert cli.main(["tray", "--card", "Creative", "--interval", "7"]) == 0
    start.assert_called_once_with(card="Creative", numid=None, timeout=3.0, interval=7)
    factory.assert_not_called()


@pytest.mark.parametrize("args", [["tray", "--json"], ["tray", "--interval", "0"]])
def test_tray_invalid_args_fail_before_loading_gui(backend, capsys, args):
    _, factory = backend
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    factory.assert_not_called()


def test_validate_cli_delegates_flags_without_gui_or_alsa_writes(backend, monkeypatch):
    from ae5ctl import validation

    requested = Mock(return_value=0)
    monkeypatch.setattr(validation, "run_validation", requested)
    assert cli.main(["validate", "--apply", "--card", "Creative", "--numid", "43"]) == 0
    requested.assert_called_once_with(backend[0], card="Creative", numid=43, apply=True)


def test_validate_help_does_not_access_hardware(backend, capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["validate", "--help"])
    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "--apply" in output
    assert "--card" in output
    assert "CAMBIAR" in output


def test_validate_rejects_json_before_accessing_hardware(backend, capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["validate", "--json"])
    assert result.value.code == 2
    assert "--json" in capsys.readouterr().err
