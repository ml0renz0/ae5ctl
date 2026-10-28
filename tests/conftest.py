"""Load the original script without a desktop or access to audio commands."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.fixture
def legacy(monkeypatch, tmp_path):
    """Import definitions only; every subprocess is blocked unless explicitly mocked."""
    gi = ModuleType("gi")
    gi.require_version = Mock()
    repository = ModuleType("gi.repository")
    repository.Gtk = SimpleNamespace()
    repository.AppIndicator3 = SimpleNamespace()
    repository.GLib = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repository)

    script = Path(__file__).resolve().parents[1] / "ae5-switcher.py"
    spec = importlib.util.spec_from_file_location("ae5_legacy_under_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.subprocess = SimpleNamespace(
        PIPE=subprocess.PIPE,
        run=Mock(
            side_effect=AssertionError("Real subprocesses are forbidden in tests")
        ),
    )
    module.HEAD_STATE = str(tmp_path / "ae5-headphones.state")
    module.SPK_STATE = str(tmp_path / "ae5-speakers.state")
    module.MARK_FILE = str(tmp_path / "ae5-current")
    return module


@pytest.fixture
def alsa_fixture():
    def read(name):
        return (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")

    return read
