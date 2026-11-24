"""Assemble a reproducible GNOME Shell extension, no .deb or Python runtime."""

import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UUID = "ae5ctl@ml0renz0.github.io"
SOURCE = ROOT / "gnome" / UUID
FILES = ("metadata.json", "extension.js", "alsa.js", "alsa-logic.mjs")


def build(destination):
    metadata = json.loads((SOURCE / "metadata.json").read_text(encoding="utf-8"))
    if metadata["uuid"] != UUID or metadata["shell-version"] != ["46"]:
        raise ValueError("Invalid GNOME metadata")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (SOURCE / name).read_bytes())
    return destination


def main():
    parser = argparse.ArgumentParser(description="Build the ae5ctl GNOME ZIP")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / (UUID + ".shell-extension.zip"),
    )
    args = parser.parse_args()
    print(build(args.output))


if __name__ == "__main__":
    main()
