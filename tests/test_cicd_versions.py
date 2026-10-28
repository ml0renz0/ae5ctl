"""Check that automated Debian builds remain upgradeable between CI runs."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "packaging" / "build_deb.py"

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11)
    or shutil.which("dpkg") is None
    or shutil.which("dpkg-deb") is None,
    reason="CI package version checks require build Python >= 3.11 and dpkg",
)


@pytest.fixture
def debian_version():
    spec = importlib.util.spec_from_file_location("ae5ctl_ci_builder", BUILDER)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder.debian_version


@pytest.mark.parametrize(
    "older,newer",
    [
        (("0.1.0.dev0", "1+ci.2.1"), ("0.1.0.dev0", "1+ci.10.1")),
        (("0.1.0.dev0", "1+ci.10.1"), ("0.1.0.dev0", "1+ci.10.2")),
        (("0.1.0.dev0", "1+ci.999.1"), ("0.1.0.dev1", "1+ci.1.1")),
        (("0.1.0.dev9", "1+ci.999.1"), ("0.1.0", "1+ci.1.1")),
    ],
)
def test_ci_revisions_follow_debian_upgrade_order(debian_version, older, newer):
    result = subprocess.run(
        [
            "dpkg",
            "--compare-versions",
            debian_version(*older),
            "lt",
            debian_version(*newer),
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_ci_revision_is_preserved_in_the_installable_archive(tmp_path):
    revision = "1+ci.10.2"
    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--revision",
            revision,
            "--output-dir",
            str(tmp_path),
        ],
        env={**os.environ, "SOURCE_DATE_EPOCH": "1700000000"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    (archive,) = tmp_path.glob("*.deb")
    version = subprocess.run(
        ["dpkg-deb", "--field", str(archive), "Version"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    ).stdout.strip()

    assert version.endswith("-" + revision)
    assert archive.name == f"ae5ctl_{version}_all.deb"
    assert archive.with_suffix(".deb.sha256").is_file()
