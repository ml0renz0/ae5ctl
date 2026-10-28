"""Exercise the read-only CLI with an injected ALSA backend, without hardware."""

import json
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest

from ae5ctl import cli
from ae5ctl.alsa import AlsaBackend, AlsaError, Card, EnumControl, Status


@pytest.fixture
def backend(monkeypatch):
    card = Card(index=3, id="Creative", name="Sound BlasterX AE-5")
    control = EnumControl(
        numid=37,
        name="Output Select",
        items={0: "Speakers", 1: "Headphone"},
        values=(1,),
    )
    instance = Mock(spec=["cards", "status"])
    instance.cards.return_value = [card]
    instance.status.return_value = Status(
        card=card, control=control, output="headphones"
    )
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
        [],
        ["switch", "headphones"],
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
