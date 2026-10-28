"""Exercise encrypted-key signing and tamper detection with a temporary test key."""

import importlib.util
import secrets
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "packaging" / "sign_deb.py"
spec = importlib.util.spec_from_file_location("ae5ctl_deb_signing", SCRIPT)
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)

pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None, reason="requires OpenSSL"
)


@pytest.fixture(scope="module")
def signing_key(tmp_path_factory):
    directory = tmp_path_factory.mktemp("signing")
    password = directory / "password"
    password.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    password.chmod(0o600)
    private = directory / "private.pem"
    subprocess.run(
        [
            "openssl",
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-aes-256-cbc",
            "-pass",
            f"file:{password}",
            "-out",
            str(private),
        ],
        check=True,
        capture_output=True,
    )
    private.chmod(0o600)
    yield private, password
    private.unlink()
    password.unlink()


def test_encrypted_key_signature_verifies_and_rejects_tampering(tmp_path, signing_key):
    private, password = signing_key
    package = tmp_path / "example.deb"
    package.write_bytes(b"Synthetic package payload for signing tests")
    public = tmp_path / "public.pem"

    signature = signing.sign_deb(package, private, password, public_key_output=public)

    assert signature == Path(str(package) + ".sig")
    assert "PUBLIC KEY" in public.read_text()
    assert "PRIVATE KEY" not in public.read_text()
    command = [
        "openssl",
        "dgst",
        "-sha256",
        "-verify",
        str(public),
        "-signature",
        str(signature),
        str(package),
    ]
    assert subprocess.run(command, capture_output=True).returncode == 0
    package.write_bytes(package.read_bytes() + b"tampered")
    assert subprocess.run(command, capture_output=True).returncode != 0


def test_wrong_password_does_not_publish_signature(tmp_path, signing_key):
    private, _ = signing_key
    package = tmp_path / "example.deb"
    package.write_bytes(b"Synthetic package payload")
    wrong_password = tmp_path / "wrong-password"
    wrong_password.write_text(secrets.token_urlsafe(32))
    public = tmp_path / "public.pem"

    with pytest.raises(ValueError, match="OpenSSL"):
        signing.sign_deb(package, private, wrong_password, public_key_output=public)

    assert not Path(str(package) + ".sig").exists()
    assert not public.exists()


@pytest.mark.parametrize("destination", ["key", "password", "package"])
def test_outputs_cannot_replace_input_files(tmp_path, signing_key, destination):
    private, password = signing_key
    package = tmp_path / "example.deb"
    package.write_bytes(b"Synthetic package payload")
    paths = {"key": private, "password": password, "package": package}
    original = paths[destination].read_bytes()

    with pytest.raises(ValueError, match="sobrescribir"):
        signing.sign_deb(package, private, password, output=paths[destination])

    assert paths[destination].read_bytes() == original
