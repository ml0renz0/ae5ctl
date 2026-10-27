"""Characterize the original without importing GTK or touching real audio."""

import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def legacy(monkeypatch):
    gi = ModuleType("gi")
    gi.require_version = Mock()
    repository = ModuleType("gi.repository")
    repository.Gtk = Mock()
    repository.AppIndicator3 = Mock()
    repository.GLib = Mock()
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)
    path = Path(__file__).parents[1] / "legacy" / "ae5-switcher.py"
    namespace = runpy.run_path(str(path))
    return namespace


@pytest.mark.parametrize("mode", ["headphones", "speakers"])
def test_marker_round_trip(legacy, tmp_path, mode):
    marker = tmp_path / "config" / "current"
    legacy["mark_set"].__globals__["MARK_FILE"] = str(marker)
    legacy["mark_set"](mode)
    assert legacy["mark_get"]() == mode


def test_missing_and_invalid_marker(legacy, tmp_path):
    marker = tmp_path / "current"
    legacy["mark_get"].__globals__["MARK_FILE"] = str(marker)
    assert legacy["mark_get"]() is None
    marker.write_text("invalid")
    assert legacy["mark_get"]() is None


def test_enum_absent_does_not_run_commands(legacy):
    runner = Mock(side_effect=AssertionError("unexpected command"))
    legacy["current_from_enum"].__globals__["sh"] = runner
    assert legacy["current_from_enum"](None, "7") is None
    assert legacy["current_from_enum"](0, None) is None
    runner.assert_not_called()


@pytest.mark.xfail(strict=True, reason="Phase 01: map numeric ALSA enum to item name")
def test_numeric_enum_reports_selected_output(legacy):
    output = """numid=7,iface=MIXER,name='Output Select'
  ; type=ENUMERATED,access=rw------,values=1,items=2
  ; Item #0 'Speakers'
  ; Item #1 'Headphones'
  : values=1
"""
    runner = Mock(return_value=SimpleNamespace(stdout=output))
    legacy["current_from_enum"].__globals__["sh"] = runner
    assert legacy["current_from_enum"](0, "7") == "headphones"
