"""Build and inspect the real Debian archive without installing it on the host."""

import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from email.parser import Parser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "packaging" / "build_deb.py"
EPOCH = "1700000000"

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11)
    or sys.platform != "linux"
    or shutil.which("dpkg-deb") is None,
    reason="Debian archive checks require Linux, dpkg-deb and build Python >= 3.11",
)


def build(output, *, extra=(), epoch=EPOCH):
    return subprocess.run(
        [sys.executable, str(BUILDER), "--output-dir", str(output), *extra],
        capture_output=True,
        text=True,
        env={**os.environ, "SOURCE_DATE_EPOCH": epoch},
        cwd=output.parent,
        timeout=30,
        check=False,
    )


def dpkg(*arguments, text=True):
    return subprocess.run(
        ["dpkg-deb", *map(str, arguments)],
        capture_output=True,
        text=text,
        timeout=15,
        check=True,
    ).stdout


@pytest.fixture(scope="module")
def archive(tmp_path_factory):
    directory = tmp_path_factory.mktemp("deb-build")
    result = build(directory / "output")
    assert result.returncode == 0, result.stderr
    archives = list((directory / "output").glob("*.deb"))
    assert len(archives) == 1
    return archives[0]


@pytest.fixture(scope="module")
def extracted(archive, tmp_path_factory):
    directory = tmp_path_factory.mktemp("deb-extract")
    payload, control = directory / "payload", directory / "control"
    dpkg("--extract", archive, payload)
    dpkg("--control", archive, control)
    return payload, control


def test_metadata_matches_project_and_declares_runtime_dependencies(archive):
    import tomllib

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    metadata = Parser().parsestr(dpkg("--field", archive))

    assert metadata["Package"] == project["name"] == "ae5ctl"
    assert metadata["Version"] == project["version"].replace(".dev", "~dev") + "-1"
    assert metadata["Architecture"] == "all"
    assert metadata["Section"] == "sound"
    assert "python3:any (>= 3.10)" in metadata["Depends"]
    assert "alsa-utils" in metadata["Depends"]
    assert "github.com/ml0renz0/ae5ctl" in metadata["Homepage"]
    assert metadata["Maintainer"]
    assert int(metadata["Installed-Size"]) > 0
    assert archive.name == f"ae5ctl_{project['version']}-1_all.deb"


def test_archive_has_root_ownership_and_safe_permissions(archive):
    with tarfile.open(
        fileobj=io.BytesIO(dpkg("--fsys-tarfile", archive, text=False))
    ) as tar:
        members = tar.getmembers()

    assert members
    for member in members:
        assert (member.uid, member.gid) == (0, 0)
        assert member.isdir() or member.isfile(), member.name
        expected_mode = (
            0o755 if member.isdir() or member.name.endswith("/bin/ae5ctl") else 0o644
        )
        assert member.mode == expected_mode, member.name


def test_payload_contains_current_cli_without_desktop_or_build_files(extracted):
    payload, _ = extracted
    module_root = payload / "usr/lib/python3/dist-packages/ae5ctl"
    expected = {path.name for path in (ROOT / "src/ae5ctl").glob("*.py")}

    assert {path.name for path in module_root.iterdir()} == expected
    for source in (ROOT / "src/ae5ctl").glob("*.py"):
        assert (module_root / source.name).read_bytes() == source.read_bytes()
    for path in payload.rglob("*"):
        assert path.name not in {"ae5-switcher.py", "tests", ".venv", "__pycache__"}
        assert path.suffix not in {".pyc", ".pyo", ".deb"}
    launcher = payload / "usr/bin/ae5ctl"
    assert launcher.read_text().splitlines()[0] == "#!/usr/bin/python3"
    assert "ae5ctl.cli import main" in launcher.read_text()
    assert stat.S_IMODE(launcher.stat().st_mode) == 0o755
    documentation = payload / "usr/share/doc/ae5ctl"
    assert (documentation / "copyright").is_file()
    assert (documentation / "changelog.Debian.gz").is_file()


def test_maintainer_scripts_only_manage_python_bytecode(extracted):
    _, control = extracted
    for name, operation in [("postinst", "py3compile"), ("prerm", "py3clean")]:
        script = control / name
        contents = script.read_text()
        assert contents.startswith("#!/bin/sh\n")
        assert operation in contents
        assert "ae5ctl" in contents
        assert stat.S_IMODE(script.stat().st_mode) == 0o755
        assert all(word not in contents for word in ["amixer", "alsactl", "systemctl"])


def test_package_checksums_cover_payload_and_archive(archive, extracted):
    payload, control = extracted
    entries = {}
    for line in (control / "md5sums").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        entries[name] = digest
        assert hashlib.md5((payload / name).read_bytes()).hexdigest() == digest
    files = {
        path.relative_to(payload).as_posix()
        for path in payload.rglob("*")
        if path.is_file()
    }
    assert entries.keys() == files
    checksum = archive.with_suffix(".deb.sha256").read_text().split()
    assert checksum == [hashlib.sha256(archive.read_bytes()).hexdigest(), archive.name]


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="requires sha256sum")
def test_release_asset_names_preserve_checksums_after_download(archive, tmp_path):
    output = tmp_path / "revisions"
    for revision in ("1~x", "1.x"):
        result = build(output, extra=("--revision", revision))
        assert result.returncode == 0, result.stderr
    archives = [archive, *sorted(output.glob("*.deb"))]
    assert len(archives) == 3, "Distinct revisions must not overwrite each other"
    upstream = dpkg("--field", archive, "Version").strip().rsplit("-", 1)[0]
    assert {dpkg("--field", path, "Version").strip() for path in archives} == {
        f"{upstream}-1",
        f"{upstream}-1~x",
        f"{upstream}-1.x",
    }

    downloaded = tmp_path / "downloaded"
    downloaded.mkdir()
    for package in archives:
        for asset in (package, package.with_suffix(".deb.sha256")):
            # Reproduce the observed GitHub Releases filename normalization.
            destination = downloaded / asset.name.replace("~", ".")
            assert not destination.exists(), "Release asset names must not collide"
            shutil.copyfile(asset, destination)
    for checksum in downloaded.glob("*.sha256"):
        result = subprocess.run(
            ["sha256sum", "-c", checksum.name],
            cwd=downloaded,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_extracted_python_module_runs_without_installed_project(extracted, tmp_path):
    payload, _ = extracted
    module_root = payload / "usr/lib/python3/dist-packages"
    result = subprocess.run(
        [sys.executable, "-S", "-m", "ae5ctl", "--help"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": str(module_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        cwd=tmp_path,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "{cards,status,doctor}" in result.stdout
    assert result.stderr == ""


def test_repeated_builds_with_same_epoch_are_identical(archive, tmp_path):
    output = tmp_path / "second-build"
    result = build(output)

    assert result.returncode == 0, result.stderr
    assert (output / archive.name).read_bytes() == archive.read_bytes()


@pytest.mark.parametrize("epoch", ["-1", "not-an-epoch"])
def test_invalid_epoch_does_not_create_archive(tmp_path, epoch):
    output = tmp_path / "invalid-epoch"
    result = build(output, epoch=epoch)

    assert result.returncode != 0
    assert not list(output.glob("*.deb"))


@pytest.mark.parametrize("revision", ["../escape", "1\nDepends: bad", ""])
def test_invalid_revision_does_not_create_archive(tmp_path, revision):
    output = tmp_path / "invalid-revision"
    result = build(output, extra=("--revision", revision))

    assert result.returncode != 0
    assert not list(output.glob("*.deb"))
