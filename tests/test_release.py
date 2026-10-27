"""Exercise release orchestration with local fake Git and GitHub executables."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40


@pytest.fixture
def release_runner(tmp_path):
    project = tmp_path / "project"
    (project / "packaging").mkdir(parents=True)
    (project / "dist").mkdir()
    shutil.copy2(ROOT / "packaging/release.sh", project / "packaging/release.sh")
    (project / "pyproject.toml").write_text('[project]\nversion = "0.0.1"\n')
    for name in (
        "ae5ctl-0.0.1-py3-none-any.whl",
        "ae5ctl-0.0.1.tar.gz",
        "ae5ctl_0.0.1_all.deb",
    ):
        (project / "dist" / name).write_bytes(b"test artifact")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake = (
        f"#!{sys.executable}\n"
        + """
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["MOCK_CALLS"], "a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
if name == "git":
    assert args[:3] == ["ls-remote", "--tags", "origin"], args
    print(os.environ.get("MOCK_GIT_REFS", ""))
elif args[0] == "api":
    if os.environ.get("MOCK_API_FAILURE"):
        sys.exit(1)
    print(os.environ.get("MOCK_RELEASE_INFO", ""))
elif args[:2] == ["release", "upload"]:
    if os.environ.get("MOCK_UPLOAD_FAILURE"):
        sys.exit(1)
elif args[:2] not in (["release", "create"], ["release", "edit"]):
    raise AssertionError(args)
"""
    )
    for name in ("git", "gh"):
        executable = binaries / name
        executable.write_text(fake)
        executable.chmod(0o755)
    # The workflow's Python 3.12+ is selected without relying on host PATH.
    (binaries / "python").symlink_to(sys.executable)
    log = tmp_path / "calls.jsonl"

    def run(**configuration):
        environment = os.environ.copy()
        environment.update(
            PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
            GH_REPO="owner/ae5ctl",
            GITHUB_SHA=COMMIT,
            MOCK_CALLS=str(log),
            **configuration,
        )
        if log.exists():
            log.unlink()
        result = subprocess.run(
            ["bash", str(project / "packaging/release.sh")],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        return result, calls

    return run


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Release runner uses tomllib")
def test_new_release_is_draft_until_all_assets_upload(release_runner):
    result, calls = release_runner()
    assert result.returncode == 0, result.stderr
    release_calls = [call for call in calls if call[:2] == ["gh", "release"]]
    assert [call[2] for call in release_calls] == ["create", "upload", "edit"]
    assert "--draft" in release_calls[0]
    assert COMMIT in release_calls[0]
    assert release_calls[1] == [
        "gh",
        "release",
        "upload",
        "v0.0.1",
        "dist/ae5ctl-0.0.1-py3-none-any.whl",
        "dist/ae5ctl-0.0.1.tar.gz",
        "dist/ae5ctl_0.0.1_all.deb",
        "--clobber",
    ]
    assert "--draft=false" in release_calls[-1]


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Release runner uses tomllib")
def test_retry_recovers_draft_and_replaces_partial_assets(release_runner):
    result, calls = release_runner(MOCK_RELEASE_INFO=f"true\t{COMMIT}")
    assert result.returncode == 0, result.stderr
    commands = [call[2] for call in calls if call[:2] == ["gh", "release"]]
    assert commands == ["upload", "edit"]
    assert any("--clobber" in call for call in calls)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Release runner uses tomllib")
def test_retry_of_published_commit_only_recovers_assets(release_runner):
    result, calls = release_runner(
        MOCK_GIT_REFS=f"{COMMIT}\trefs/tags/v0.0.1",
        MOCK_RELEASE_INFO="false\tmain",
    )
    assert result.returncode == 0, result.stderr
    commands = [call[2] for call in calls if call[:2] == ["gh", "release"]]
    assert commands == ["upload"]


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Release runner uses tomllib")
def test_tag_of_other_commit_requires_version_bump(release_runner):
    result, calls = release_runner(MOCK_GIT_REFS=f"{OTHER_COMMIT}\trefs/tags/v0.0.1")
    assert result.returncode != 0
    assert "increment project.version" in result.stderr
    assert all(call[0] != "gh" for call in calls)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Release runner uses tomllib")
def test_annotated_tag_uses_peeled_commit(release_runner):
    result, calls = release_runner(
        MOCK_GIT_REFS=(
            f"{OTHER_COMMIT}\trefs/tags/v0.0.1\n{COMMIT}\trefs/tags/v0.0.1^{{}}"
        ),
        MOCK_RELEASE_INFO=f"true\t{COMMIT}",
    )
    assert result.returncode == 0, result.stderr
    assert any(call[:3] == ["gh", "release", "upload"] for call in calls)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Release runner uses tomllib")
def test_upload_failure_does_not_publish(release_runner):
    result, calls = release_runner(MOCK_UPLOAD_FAILURE="1")
    assert result.returncode != 0
    assert not any(call[:3] == ["gh", "release", "edit"] for call in calls)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Release runner uses tomllib")
def test_api_failure_is_not_treated_as_missing_release(release_runner):
    result, calls = release_runner(MOCK_API_FAILURE="1")
    assert result.returncode != 0
    assert not any(call[:2] == ["gh", "release"] for call in calls)


@pytest.mark.skipif(sys.version_info < (3, 11), reason="Release runner uses tomllib")
def test_draft_without_tag_for_other_commit_requires_version_bump(release_runner):
    result, calls = release_runner(MOCK_RELEASE_INFO=f"true\t{OTHER_COMMIT}")
    assert result.returncode != 0
    assert "increment project.version" in result.stderr
    assert not any(call[:2] == ["gh", "release"] for call in calls)
