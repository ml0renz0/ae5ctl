import subprocess
import sys

import pytest


@pytest.mark.parametrize("args", [[], ["--help"], ["--version"]])
def test_module_entry_point(args):
    result = subprocess.run(
        [sys.executable, "-m", "ae5ctl", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "ae5ctl" in result.stdout
    assert not result.stderr


def test_unknown_command_is_rejected():
    result = subprocess.run(
        [sys.executable, "-m", "ae5ctl", "switch"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_main_displays_baseline_help(capsys):
    from ae5ctl.cli import main

    assert main([]) == 0
    assert "audio commands coming soon" in capsys.readouterr().out
