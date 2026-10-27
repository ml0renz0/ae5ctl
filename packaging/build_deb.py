#!/usr/bin/env python3
"""Build a Debian package with the standard library and dpkg-deb."""

import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Use the package's version without requiring an editable installation.
    namespace = {}
    exec((ROOT / "src/ae5ctl/__init__.py").read_text(), namespace)
    version = namespace["__version__"]
    output = ROOT / "dist" / f"ae5ctl_{version}_all.deb"
    output.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ae5ctl-deb-") as temporary:
        stage = Path(temporary) / "ae5ctl"
        control = stage / "DEBIAN"
        control.mkdir(parents=True)
        (control / "control").write_text(
            f"Package: ae5ctl\nVersion: {version}\n"
            "Section: sound\nPriority: optional\nArchitecture: all\n"
            "Maintainer: ae5ctl contributors <noreply@users.noreply.github.com>\n"
            "Depends: python3 (>= 3.10)\n"
            "Description: Sound BlasterX AE-5 control tools\n"
            " Development baseline with help and version commands.\n"
        )
        modules = stage / "usr/lib/python3/dist-packages/ae5ctl"
        shutil.copytree(
            ROOT / "src/ae5ctl",
            modules,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        binary = stage / "usr/bin/ae5ctl"
        binary.parent.mkdir(parents=True)
        binary.write_text(
            "#!/usr/bin/python3\nfrom ae5ctl.cli import main\n"
            "raise SystemExit(main())\n"
        )
        binary.chmod(0o755)
        docs = stage / "usr/share/doc/ae5ctl"
        docs.mkdir(parents=True)
        shutil.copy2(ROOT / "README.md", docs / "README.md")
        # Normalize restrictive host umasks for system-wide installation.
        stage.chmod(0o755)
        for path in stage.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        binary.chmod(0o755)
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(stage), str(output)],
            check=True,
        )
    print(output)


if __name__ == "__main__":
    main()
