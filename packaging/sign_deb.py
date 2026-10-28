#!/usr/bin/env python3
"""Create and verify an OpenSSL detached signature without exposing a passphrase."""

import argparse
import os
import subprocess
import tempfile
from pathlib import Path


def openssl(*arguments: str) -> None:
    try:
        result = subprocess.run(
            ["openssl", *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as error:
        raise ValueError("No se encuentra openssl.") from error
    if result.returncode:
        # OpenSSL reads the password itself; neither its value nor key material is logged.
        raise ValueError(
            "OpenSSL no pudo completar la firma o su verificación. "
            "Comprueba la clave y el archivo de contraseña."
        )


def publish(source: Path, destination: Path) -> None:
    """Atomically publish a non-secret artifact in its destination filesystem."""
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(source.read_bytes())
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


def sign_deb(
    package: Path,
    key: Path,
    passphrase_file: Path,
    output: Path | None = None,
    public_key_output: Path | None = None,
) -> Path:
    package, key, passphrase_file = (
        path.resolve() for path in (package, key, passphrase_file)
    )
    for path in (package, key, passphrase_file):
        if not path.is_file():
            raise ValueError(f"No existe el archivo requerido: {path}")
    if package.suffix != ".deb":
        raise ValueError("El archivo que se firma debe tener extensión .deb.")
    output = output.resolve() if output else Path(str(package) + ".sig")
    public = public_key_output.resolve() if public_key_output else None
    protected = {package, key, passphrase_file}
    if output in protected or public in protected or public == output:
        raise ValueError("Las salidas no pueden sobrescribir los archivos de entrada.")
    for destination in (output, public):
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ae5ctl-sign-", dir=output.parent) as temp:
        signature = Path(temp) / "package.sig"
        public_key = Path(temp) / "public.pem"
        openssl(
            "dgst",
            "-sha256",
            "-sign",
            str(key),
            "-passin",
            f"file:{passphrase_file}",
            "-out",
            str(signature),
            str(package),
        )
        openssl(
            "pkey",
            "-in",
            str(key),
            "-passin",
            f"file:{passphrase_file}",
            "-pubout",
            "-out",
            str(public_key),
        )
        openssl(
            "dgst",
            "-sha256",
            "-verify",
            str(public_key),
            "-signature",
            str(signature),
            str(package),
        )
        publish(signature, output)
        if public is not None:
            publish(public_key, public)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--key", required=True, type=Path, help="clave privada PEM")
    parser.add_argument(
        "--passphrase-file",
        required=True,
        type=Path,
        help="archivo privado de contraseña",
    )
    parser.add_argument("--output", type=Path, help="por defecto: PAQUETE.deb.sig")
    parser.add_argument(
        "--public-key-output", type=Path, help="exportar clave pública PEM"
    )
    args = parser.parse_args(argv)
    try:
        signature = sign_deb(
            args.package,
            args.key,
            args.passphrase_file,
            args.output,
            args.public_key_output,
        )
    except (ValueError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(signature)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
