"""Ensure GNOME ZIP is complete, safe, and independent of Debian packaging."""

import importlib.util
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_has_gnome_metadata_at_root_and_no_python(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "builder", ROOT / "tools" / "build_extension.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    archive = builder.build(tmp_path / "extension.zip")
    with zipfile.ZipFile(archive) as zipped:
        assert set(zipped.namelist()) == set(builder.FILES)
        metadata = json.loads(zipped.read("metadata.json"))
        assert metadata["uuid"] == "ae5ctl@ml0renz0.github.io"
        assert metadata["shell-version"] == ["46"]
        assert "extension.js" in zipped.namelist()
        assert all("src/" not in path for path in zipped.namelist())


def test_ci_uses_only_gnome_archive_and_conditional_upload():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "build-gnome" in workflow
    assert "build-deb" not in workflow
    assert "  deb:" not in workflow
    assert "  gnome:" in workflow
    assert "node --test" in workflow
    assert "retention-days: 1" in workflow
    assert workflow.count("actions/upload-artifact@v4") == 1
    assert "needs: [python, gnome]" in workflow
