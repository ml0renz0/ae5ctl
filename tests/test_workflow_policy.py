"""Guard the opt-in build policy against accidental artifact generation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pytest_default_skips_real_debian_builds():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "-m 'not package'" in project
    for name in ("test_deb_package.py", "test_cicd_versions.py"):
        tests = (ROOT / "tests" / name).read_text(encoding="utf-8")
        assert "pytest.mark.package" in tests


def test_workflow_builds_debian_only_when_explicitly_requested():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    deb = workflow.split("\n  deb:\n", 1)[1].split("\n  required:\n", 1)[0]
    required = workflow.split("\n  required:\n", 1)[1].split("\n  publish:\n", 1)[0]
    publish = workflow.split("\n  publish:\n", 1)[1]

    assert "if: >-" in deb
    assert "github.event_name == 'pull_request'" in deb
    assert "build-deb" in deb
    assert "refs/tags/v" in deb
    assert "python -m pytest -m package" in deb
    assert "github.event_name == 'push'" in publish
    assert "refs/tags/v" in publish
    assert "github.ref == 'refs/heads/main'" not in publish
    assert 'tag="$GITHUB_REF_NAME"' in publish
    assert "BUILD_DEB" in required and "DEB_RESULT" in required
    assert "actions/upload-artifact" not in workflow
    assert "actions/download-artifact" not in workflow


def test_workflow_handles_label_changes():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "      - labeled\n" in workflow
    assert "      - unlabeled\n" in workflow
