"""Check version consistency and a built Debian package without system installs."""

import os
import runpy
import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest

from ae5ctl import __version__

ROOT = Path(__file__).parents[1]


def test_installed_project_version_matches_cli_version():
    assert version("ae5ctl") == __version__


@pytest.mark.skipif(
    shutil.which("dpkg-deb") is None or not Path("/usr/bin/python3").exists(),
    reason="Debian packaging requires dpkg-deb and system Python",
)
def test_debian_package_contents_and_extracted_command(tmp_path, monkeypatch):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "src", source / "src")
    shutil.copy2(ROOT / "README.md", source / "README.md")
    builder = runpy.run_path(str(ROOT / "packaging/build_deb.py"))
    monkeypatch.setitem(builder["main"].__globals__, "ROOT", source)
    builder["main"]()

    package = source / "dist" / f"ae5ctl_{__version__}_all.deb"
    assert package.is_file()
    metadata = subprocess.run(
        ["dpkg-deb", "--field", str(package)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "Package: ae5ctl\n" in metadata
    assert f"Version: {__version__}\n" in metadata
    assert "Architecture: all\n" in metadata
    assert "Depends: python3 (>= 3.10)\n" in metadata

    extracted = tmp_path / "extracted"
    subprocess.run(["dpkg-deb", "--extract", str(package), str(extracted)], check=True)
    launcher = extracted / "usr/bin/ae5ctl"
    modules = extracted / "usr/lib/python3/dist-packages"
    assert launcher.stat().st_mode & 0o777 == 0o755
    assert (modules / "ae5ctl/cli.py").is_file()
    assert not list(extracted.rglob("__pycache__"))
    assert not list(extracted.rglob("ae5-switcher.py"))

    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(modules)
    result = subprocess.run(
        [str(launcher), "--version"],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"ae5ctl {__version__}"
    assert not result.stderr
