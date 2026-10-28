"""Synthetic ALSA responses; no subprocesses or real audio devices are used."""

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from ae5ctl.alsa import AlsaBackend, AlsaError, Card, parse_cards, parse_enum_control

CARDS = """ 2 [USB            ]: USB-Audio - USB Audio
                      USB Device
 7 [Creative       ]: HDA-Intel - HDA Creative
                      Sound BlasterX AE-5 at 0xf000 irq 22
"""
CONTROL_LIST = """numid=11,iface=MIXER,name='Master Playback Volume'
numid=43,iface=MIXER,name='Output Select'
"""
INTEGER = """numid=11,iface=MIXER,name='Master Playback Volume'
  ; type=INTEGER,access=rw------,values=2,min=0,max=100,step=0
  : values=60,60
"""


def enum_response(
    *,
    numid=43,
    headphone="Headphone",
    values="2",
    count=1,
    options=None,
):
    # Auto and reversed labels prevent hardcoding 0=headphones, 1=speakers.
    if options is None:
        options = {0: "Auto", 1: "Speakers", 2: headphone}
    items = "\n".join(f"  ; Item #{key} '{label}'" for key, label in options.items())
    return (
        f"numid={numid},iface=MIXER,name='Output Select'\n"
        f"  ; type=ENUMERATED,access=rw------,values={count},items={len(options)}\n"
        f"{items}\n  : values={values}\n"
    )


@pytest.fixture
def make_backend(tmp_path):
    def make(*, cards=CARDS, responses=None, runner=None):
        path = tmp_path / "cards"
        path.write_text(cards, encoding="utf-8")
        if runner is None:
            if responses is None:
                responses = {
                    ("controls",): CONTROL_LIST,
                    ("cget", "numid=11"): INTEGER,
                    ("cget", "numid=43"): enum_response(),
                }

            def respond(command, **kwargs):
                return subprocess.CompletedProcess(
                    command, 0, responses[tuple(command[3:])], ""
                )

            runner = Mock(side_effect=respond)
        return AlsaBackend(cards_path=path, runner=runner), runner

    return make


def assert_code(code, callback):
    with pytest.raises(AlsaError) as caught:
        callback()
    assert caught.value.code == code
    assert str(caught.value)


def test_cards_keep_ids_indices_and_continuation_description():
    cards = parse_cards(CARDS)

    assert cards[0] == Card(2, "USB", "USB-Audio - USB Audio USB Device")
    assert cards[1].index == 7
    assert cards[1].id == "Creative"
    assert "AE-5" in cards[1].name


def test_numeric_longname_does_not_block_other_card_selection(make_backend):
    backend, _ = make_backend(cards=CARDS.replace("USB Device", "1235:8211 at usb-1"))

    assert backend.cards()[0].name.endswith("1235:8211 at usb-1")
    assert backend.status().card.id == "Creative"


@pytest.mark.parametrize("text", ["", "\n", "--- no soundcards ---\n"])
def test_parse_empty_cards(text):
    assert parse_cards(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "invalid cards",
        "0 [ ]: Missing identity",
        "0 [one]: First\n0 [two]: Second",
        "0 [one]: First\n  1 [broken header",
    ],
)
def test_malformed_cards_are_not_silently_partial(text):
    assert_code("parse_error", lambda: parse_cards(text))


@pytest.mark.parametrize("label", ["Headphone", "Headphones", "hEaDpHoNeS"])
def test_enum_numeric_values_map_to_actual_item_indices(label):
    control = parse_enum_control(enum_response(headphone=label, values="1"))

    assert control.numid == 43
    assert control.name == "Output Select"
    assert control.items == {0: "Auto", 1: "Speakers", 2: label}
    assert control.values == (1,)


@pytest.mark.parametrize(
    "response",
    [
        "",
        INTEGER,
        enum_response().replace("items=3", "items=4"),
        enum_response().replace("values=1,items", "values=2,items"),
        enum_response().replace("Item #2", "Item #0"),
        enum_response().replace(": values=2", ": values=Headphone"),
        enum_response() + "  : values=1\n",
        enum_response().replace("; Item #2 'Headphone'", "; Item #2 malformed"),
        enum_response().replace("  ; Item #1 'Speakers'\n", ""),
        enum_response(options={0: "Headphone", 2: "Speakers"}),
        enum_response(options={0: "Headphone", 1: "Speakers", 4: "Auto"}),
    ],
)
def test_malformed_enumerated_control_is_an_error(response):
    assert_code("parse_error", lambda: parse_enum_control(response))


def test_apostrophes_and_backslashes_are_literal_amixer_labels():
    response = enum_response(
        options={0: "Owner's Output", 1: r"Raw\Output"}, values="0"
    )
    response = response.replace("name='Output Select'", "name='Owner's Output',index=1")

    control = parse_enum_control(response)

    assert control.name == "Owner's Output"
    assert control.items == {0: "Owner's Output", 1: r"Raw\Output"}


def test_status_auto_detects_from_description_and_skips_integer_controls(make_backend):
    backend, runner = make_backend()

    status = backend.status()

    assert status.card.id == "Creative"
    assert status.output == "headphones"
    assert status.control.numid == 43
    assert [call.args[0] for call in runner.call_args_list] == [
        ["amixer", "-c", "7", "controls"],
        ["amixer", "-c", "7", "cget", "numid=11"],
        ["amixer", "-c", "7", "cget", "numid=43"],
    ]


@pytest.mark.parametrize("control_type", ["INTEGER64", "IEC958", "BOOLEAN", "BYTES"])
def test_other_alsa_types_are_skipped_during_discovery(make_backend, control_type):
    backend, _ = make_backend(
        responses={
            ("controls",): CONTROL_LIST,
            ("cget", "numid=11"): INTEGER.replace(
                "type=INTEGER,", f"type={control_type},"
            ),
            ("cget", "numid=43"): enum_response(),
        }
    )

    assert backend.status().output == "headphones"


def test_subprocess_uses_arguments_timeout_and_stable_locale(make_backend, monkeypatch):
    monkeypatch.setenv("TEST_AE5_PROXY", "retained")
    backend, runner = make_backend()
    backend.status()

    for call in runner.call_args_list:
        assert isinstance(call.args[0], list)
        assert call.kwargs["shell"] is False
        assert call.kwargs["timeout"] == 3.0
        assert call.kwargs["encoding"] == "utf-8"
        assert call.kwargs["errors"] == "replace"
        assert call.kwargs["env"]["LC_ALL"] == "C"
        assert call.kwargs["env"]["TEST_AE5_PROXY"] == "retained"


@pytest.mark.parametrize("selector", ["7", "Creative"])
def test_explicit_index_or_id_and_numid_override(make_backend, selector):
    backend, runner = make_backend()

    assert backend.status(selector, 43).output == "headphones"
    runner.assert_called_once()
    assert runner.call_args.args[0] == ["amixer", "-c", "7", "cget", "numid=43"]


@pytest.mark.parametrize(
    "name", ["HDA Creative", "CA0132", "AE-50", "AE5X", "Other AE-7"]
)
def test_auto_selection_does_not_guess_generic_or_other_devices(make_backend, name):
    backend, runner = make_backend(cards=f"7 [Creative]: {name}\n")

    assert_code("card_not_found", backend.status)
    runner.assert_not_called()


@pytest.mark.parametrize("name", ["AE-5", "AE5", "Sound BlasterX AE-5 Plus"])
def test_auto_selection_accepts_delimited_model_name(make_backend, name):
    backend, _ = make_backend(cards=f"7 [Creative]: {name}\n")
    assert backend.status().output == "headphones"


def test_multiple_ae5_cards_require_explicit_selection(make_backend):
    backend, runner = make_backend(cards=CARDS + "8 [Other]: Sound BlasterX AE-5\n")

    assert_code("ambiguous_card", backend.status)
    runner.assert_not_called()


def test_duplicate_ids_are_not_resolved_by_first_match(make_backend):
    backend, runner = make_backend(cards=CARDS + "8 [Creative]: Another card\n")

    assert_code("ambiguous_card", lambda: backend.status("Creative"))
    runner.assert_not_called()


def test_explicit_missing_card_is_not_fallback_to_auto(make_backend):
    backend, runner = make_backend()

    assert_code("card_not_found", lambda: backend.status("missing"))
    runner.assert_not_called()


def test_missing_proc_file_gives_empty_cards_and_no_card_status(tmp_path):
    runner = Mock()
    backend = AlsaBackend(cards_path=tmp_path / "missing", runner=runner)

    assert backend.cards() == []
    assert_code("no_card", backend.status)
    runner.assert_not_called()


def test_permission_failure_reading_proc_is_reported(monkeypatch):
    monkeypatch.setattr(Path, "read_text", Mock(side_effect=PermissionError("denied")))

    assert_code("unreadable_cards", AlsaBackend(runner=Mock()).cards)


@pytest.mark.parametrize(
    "error,code",
    [
        (FileNotFoundError(), "command_missing"),
        (PermissionError("denied"), "command_failed"),
        (subprocess.TimeoutExpired("amixer", 3), "command_timeout"),
    ],
)
def test_command_exceptions_have_distinct_codes(make_backend, error, code):
    backend, _ = make_backend(runner=Mock(side_effect=error))

    assert_code(code, backend.status)


def test_nonzero_amixer_status_is_not_an_unknown_or_empty_control(make_backend):
    backend, _ = make_backend(
        runner=Mock(return_value=subprocess.CompletedProcess("amixer", 1, "", "denied"))
    )

    with pytest.raises(AlsaError, match="denied") as caught:
        backend.status()
    assert caught.value.code == "command_failed"


def test_no_compatible_control_is_explicit(make_backend):
    backend, _ = make_backend(
        responses={
            ("controls",): "numid=11,iface=MIXER,name='Master Playback Volume'\n",
            ("cget", "numid=11"): INTEGER,
        }
    )

    assert_code("no_control", backend.status)


def test_unrelated_enum_is_not_treated_as_output_selector(make_backend):
    backend, _ = make_backend(
        responses={
            ("controls",): "numid=43,iface=MIXER,name='Clock Source'\n",
            ("cget", "numid=43"): enum_response(options={0: "Internal", 1: "External"}),
        }
    )

    assert_code("no_control", backend.status)


def test_multiple_compatible_controls_require_numid(make_backend):
    backend, runner = make_backend(
        responses={
            ("controls",): CONTROL_LIST
            + "numid=44,iface=MIXER,name='Secondary Output'\n",
            ("cget", "numid=11"): INTEGER,
            ("cget", "numid=43"): enum_response(),
            ("cget", "numid=44"): enum_response(numid=44),
        }
    )

    assert_code("ambiguous_control", backend.status)
    assert backend.status(numid=44).control.numid == 44
    assert runner.call_args.args[0][-1] == "numid=44"


@pytest.mark.parametrize("values,count", [("2,1", 2), ("12", 1), ("-1", 1)])
def test_unknown_or_multiple_active_values_are_not_guessed(make_backend, values, count):
    backend, _ = make_backend(
        responses={("cget", "numid=43"): enum_response(values=values, count=count)}
    )

    assert_code("unknown_output", lambda: backend.status(numid=43))


def test_a_third_selected_output_remains_unknown(make_backend):
    backend, _ = make_backend(
        responses={
            ("cget", "numid=43"): enum_response(
                values="0", options={0: "Auto", 1: "Speakers", 2: "Headphone"}
            )
        }
    )

    assert_code("unknown_output", lambda: backend.status(numid=43))


def test_wrong_control_returned_by_amixer_is_not_accepted(make_backend):
    backend, _ = make_backend(responses={("cget", "numid=43"): enum_response(numid=44)})

    assert_code("parse_error", lambda: backend.status(numid=43))


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeouts_are_rejected(timeout):
    with pytest.raises(ValueError):
        AlsaBackend(timeout=timeout, runner=Mock())
