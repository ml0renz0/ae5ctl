"""Exercise marker fallback and switch outcomes without constructing GTK objects."""

from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("mode", ["headphones", "speakers"])
def test_marker_roundtrip_in_isolated_directory(legacy, mode):
    legacy.mark_set(mode)

    assert legacy.mark_get() == mode


@pytest.mark.parametrize("contents", [None, "", "invalid"])
def test_absent_or_invalid_marker_is_unknown(legacy, contents):
    if contents is not None:
        Path(legacy.MARK_FILE).write_text(contents, encoding="utf-8")

    assert legacy.mark_get() is None


@pytest.mark.parametrize(
    "actual,marker,expected",
    [
        ("headphones", "speakers", "speakers"),
        ("speakers", "headphones", "headphones"),
        (None, "headphones", "speakers"),
        (None, "speakers", "headphones"),
        (None, None, "headphones"),
    ],
)
def test_toggle_prefers_read_state_then_marker(
    legacy, monkeypatch, actual, marker, expected
):
    indicator = legacy.Indicator.__new__(legacy.Indicator)
    indicator.card, indicator.numid = 3, "37"
    indicator.to_headphones = Mock()
    indicator.to_speakers = Mock()
    monkeypatch.setattr(legacy, "current_from_enum", Mock(return_value=actual))
    if marker is not None:
        legacy.mark_set(marker)

    indicator.toggle()

    selected = getattr(indicator, f"to_{expected}")
    unselected = (
        indicator.to_speakers if expected == "headphones" else indicator.to_headphones
    )
    selected.assert_called_once_with()
    unselected.assert_not_called()


@pytest.mark.parametrize("mode", ["headphones", "speakers"])
@pytest.mark.parametrize("returncode", [0, 1])
def test_restore_failure_does_not_persist_success(
    legacy, monkeypatch, mode, returncode
):
    indicator = legacy.Indicator.__new__(legacy.Indicator)
    indicator.ensure_states = Mock(return_value=True)
    indicator.refresh = Mock()
    restore = Mock(
        return_value=CompletedProcess("alsactl", returncode, "", "restore failed")
    )
    mark_set = Mock()
    notify = Mock()
    monkeypatch.setattr(legacy, "restore", restore)
    monkeypatch.setattr(legacy, "mark_set", mark_set)
    monkeypatch.setattr(legacy, "notify", notify)

    getattr(indicator, f"to_{mode}")()

    expected_file = legacy.HEAD_STATE if mode == "headphones" else legacy.SPK_STATE
    restore.assert_called_once_with(expected_file)
    if returncode == 0:
        mark_set.assert_called_once_with(mode)
    else:
        mark_set.assert_not_called()
        notify.assert_called_once_with("Error: restore failed")
    indicator.refresh.assert_called_once_with()


def test_missing_profiles_do_not_restore_audio(legacy, monkeypatch):
    indicator = legacy.Indicator.__new__(legacy.Indicator)
    restore = Mock()
    notify = Mock()
    monkeypatch.setattr(legacy, "restore", restore)
    monkeypatch.setattr(legacy, "notify", notify)

    indicator.to_headphones()

    restore.assert_not_called()
    notify.assert_called_once()
    assert "Faltan estados ALSA" in notify.call_args.args[0]
