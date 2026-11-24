"""Guard CI transition: no Debian jobs or packages, keep required gate."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_extension_is_primary_ci_artifact():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "build-gnome" in workflow
    assert "build-deb" not in workflow
    assert "  deb:" not in workflow
    assert "Publish GNOME extension" in workflow
    assert "CI required" in workflow
    assert "git merge-base --is-ancestor" in workflow
    assert "retention-days: 1" in workflow
    assert "actions/download-artifact" not in workflow


def test_python_regressions_are_no_longer_package_scoped():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "-m 'not package'" not in project
    assert "Debian packages" not in project
