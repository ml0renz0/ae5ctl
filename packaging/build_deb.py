#!/usr/bin/env python3
"""Build a reproducible development .deb without root, pip or a network."""

import argparse
import gzip
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from email.utils import formatdate
from pathlib import Path

import tomllib

PACKAGE = "ae5ctl"
MAINTAINER = "Marcos Lorenzo de Santiago <11718206+ml0renz0@users.noreply.github.com>"
HOMEPAGE = "https://github.com/ml0renz0/ae5ctl"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def debian_version(upstream_version: str, revision: str = "1") -> str:
    """Map the supported stable/dev Python versions to Debian ordering."""
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)*)(?:\.dev([0-9]+))?", upstream_version)
    if not match:
        raise ValueError(
            "Versión no admitida: use una versión numérica estable o .devN."
        )
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+~]*", revision):
        raise ValueError("La revisión Debian debe empezar por un dígito y ser segura.")
    version = match[1]
    if match[2] is not None:
        version += "~dev" + match[2]
    return version + "-" + revision


def read_project_metadata(root: Path) -> dict:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    if project["name"] != PACKAGE:
        raise ValueError("Este generador empaqueta únicamente ae5ctl.")
    if project.get("dependencies", []):
        raise ValueError("Declare las nuevas dependencias Python en el paquete Debian.")
    if project.get("scripts", {}).get(PACKAGE) != "ae5ctl.cli:main":
        raise ValueError("El ejecutable Python ha cambiado; revise el launcher Debian.")
    minimum = re.fullmatch(
        r">=\s*([0-9]+\.[0-9]+(?:\.[0-9]+)?)", project["requires-python"]
    )
    if not minimum:
        raise ValueError("Revise la dependencia Debian para requires-python.")
    description = project["description"]
    if not description or "\n" in description or "\r" in description:
        raise ValueError("La descripción debe ocupar una sola línea.")
    return {**project, "minimum_python": minimum[1]}


def source_date_epoch(root: Path, environ: dict[str, str] | None = None) -> int:
    """Use an explicit timestamp, or the last commit, never the current time."""
    environ = os.environ if environ is None else environ
    value = environ.get("SOURCE_DATE_EPOCH")
    if value is None:
        try:
            value = subprocess.check_output(
                ["git", "-C", str(root), "log", "-1", "--format=%ct"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise ValueError(
                "Sin historial Git, defina SOURCE_DATE_EPOCH para generar el paquete."
            ) from error
    if not re.fullmatch(r"[0-9]+", value) or int(value) > 253402300799:
        raise ValueError("SOURCE_DATE_EPOCH debe ser un entero entre 0 y 253402300799.")
    return int(value)


def write_file(path: Path, contents: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    path.chmod(mode)


def compressed(contents: bytes) -> bytes:
    stream = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
        archive.write(contents)
    return stream.getvalue()


def stage_package(
    root: Path, stage: Path, project: dict, version: str, epoch: int
) -> None:
    """Copy only source modules and package-specific documents into the payload."""
    source = root / "src" / PACKAGE
    modules = sorted(
        path
        for path in source.rglob("*.py")
        if "__pycache__" not in path.relative_to(source).parts
    )
    required = {"__init__.py", "__main__.py", "cli.py", "alsa.py"}
    if not required <= {str(path.relative_to(source)) for path in modules}:
        raise ValueError("Faltan módulos requeridos de ae5ctl en src/.")
    for path in modules:
        if path.is_symlink():
            raise ValueError(f"No se empaquetan módulos enlazados: {path.name}")
        destination = stage / "usr/lib/python3/dist-packages" / PACKAGE
        write_file(destination / path.relative_to(source), path.read_bytes())

    templates = root / "packaging/debian"
    write_file(stage / "usr/bin/ae5ctl", (templates / "ae5ctl").read_bytes(), 0o755)
    write_file(stage / "DEBIAN/postinst", (templates / "postinst").read_bytes(), 0o755)
    write_file(stage / "DEBIAN/prerm", (templates / "prerm").read_bytes(), 0o755)
    docs = stage / "usr/share/doc" / PACKAGE
    write_file(docs / "README.md.gz", compressed((root / "README.md").read_bytes()))
    write_file(docs / "copyright", (templates / "copyright").read_bytes())
    changelog = (
        f"{PACKAGE} ({version}) unstable; urgency=low\n\n"
        "  * Development package of the read-only ALSA diagnostic CLI.\n"
        "  * Upstream license selection and physical AE-5 validation remain pending.\n\n"
        f" -- {MAINTAINER}  {formatdate(epoch, localtime=False)}\n"
    )
    write_file(docs / "changelog.Debian.gz", compressed(changelog.encode("utf-8")))

    payload = sorted(
        path
        for path in stage.rglob("*")
        if path.is_file() and path.relative_to(stage).parts[0] != "DEBIAN"
    )
    # Debian's Installed-Size is an estimate in KiB, rounded up per file.
    installed_size = sum((path.stat().st_size + 1023) // 1024 for path in payload)
    checksums = "".join(
        f"{hashlib.md5(path.read_bytes()).hexdigest()}  {path.relative_to(stage)}\n"
        for path in payload
    )
    write_file(stage / "DEBIAN/md5sums", checksums.encode("utf-8"))
    control = (
        f"Package: {PACKAGE}\n"
        f"Version: {version}\n"
        "Architecture: all\n"
        "Section: sound\n"
        "Priority: optional\n"
        f"Maintainer: {MAINTAINER}\n"
        f"Depends: python3:any (>= {project['minimum_python']}), alsa-utils\n"
        f"Installed-Size: {installed_size}\n"
        f"Homepage: {HOMEPAGE}\n"
        f"Description: {project['description']}\n"
        " Lists ALSA cards and reads enumerated headphone/speaker selectors.\n"
        " Includes read-only diagnostics; no desktop or audio configuration changes.\n"
        " This is a development build with hardware validation still pending.\n"
    )
    write_file(stage / "DEBIAN/control", control.encode("utf-8"))
    for path in sorted(stage.rglob("*")):
        if path.is_dir():
            path.chmod(0o755)
        os.utime(path, (epoch, epoch), follow_symlinks=False)
    stage.chmod(0o755)
    os.utime(stage, (epoch, epoch))


def build_deb(
    project_root: Path,
    output_dir: Path,
    revision: str = "1",
    epoch: int | None = None,
) -> Path:
    root = project_root.resolve()
    project = read_project_metadata(root)
    version = debian_version(project["version"], revision)
    if epoch is None:
        epoch = source_date_epoch(root)
    else:
        epoch = source_date_epoch(root, {"SOURCE_DATE_EPOCH": str(epoch)})
    if shutil.which("dpkg-deb") is None:
        raise ValueError("No se encuentra dpkg-deb; instale el paquete dpkg.")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    result = output_dir / f"{PACKAGE}_{version}_all.deb"
    with tempfile.TemporaryDirectory(prefix=".ae5ctl-build-", dir=output_dir) as work:
        stage = Path(work) / "root"
        stage.mkdir()
        stage_package(root, stage, project, version, epoch)
        temporary_deb = Path(work) / result.name
        subprocess.run(
            [
                "dpkg-deb",
                "--build",
                "--root-owner-group",
                "--threads-max=1",
                "-Zxz",
                str(stage),
                str(temporary_deb),
            ],
            env={**os.environ, "SOURCE_DATE_EPOCH": str(epoch)},
            check=True,
        )
        checksum = hashlib.sha256(temporary_deb.read_bytes()).hexdigest()
        temporary_checksum = Path(work) / (result.name + ".sha256")
        temporary_checksum.write_text(f"{checksum}  {result.name}\n", encoding="utf-8")
        temporary_checksum.chmod(0o644)
        os.replace(temporary_deb, result)
        os.replace(temporary_checksum, result.with_name(result.name + ".sha256"))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "dist")
    parser.add_argument(
        "--revision", default="1", help="revisión Debian (predeterminado: 1)"
    )
    args = parser.parse_args(argv)
    try:
        result = build_deb(PROJECT_ROOT, args.output_dir, args.revision)
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Error al generar el paquete: {error}", file=sys.stderr)
        return 1
    print(result)
    print(result.with_name(result.name + ".sha256"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
