"""Validate, install and verify deployment certificates without host dependencies."""

import argparse
import hashlib
import http.client
import ipaddress
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

CERTIFICATE = re.compile(
    rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.DOTALL
)


def openssl(*args: str) -> str:
    result = subprocess.run(
        ["openssl", *args], capture_output=True, text=True, timeout=10, check=False
    )
    if result.returncode:
        raise ValueError("OpenSSL could not validate the certificate material")
    return result.stdout.strip()


def valid_domain(domain: str) -> None:
    if len(domain) > 253 or not all(
        re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
        for label in domain.split(".")
    ):
        raise ValueError("DOMAIN must be a hostname without a scheme, port or path")


def check_certificate(path: Path, domain: str | None = None) -> str:
    dates = dict(line.split("=", 1) for line in openssl("x509", "-in", str(path), "-noout", "-dates").splitlines())
    now = time.time()
    if ssl.cert_time_to_seconds(dates["notBefore"]) > now:
        raise ValueError("TLS certificate is not yet valid")
    remaining = ssl.cert_time_to_seconds(dates["notAfter"]) - now
    if remaining <= 0:
        raise ValueError("TLS certificate has expired")
    if remaining < 30 * 86400:
        expiry = datetime.fromtimestamp(ssl.cert_time_to_seconds(dates["notAfter"]), UTC).strftime("%Y-%m-%d %H:%M:%S")
        print(f"WARNING: TLS certificate expires within 30 days ({expiry} UTC)", file=sys.stderr)
    if domain:
        valid_domain(domain)
        try:
            ipaddress.ip_address(domain)
            option = "-checkip"
        except ValueError:
            option = "-checkhost"
        try:
            match = openssl("x509", "-in", str(path), "-noout", option, domain)
        except ValueError as error:
            raise ValueError("TLS certificate does not cover DOMAIN") from error
        if "does match certificate" not in match:
            raise ValueError("TLS certificate does not cover DOMAIN")
    der = ssl.PEM_cert_to_DER_cert(CERTIFICATE.search(path.read_bytes())[0].decode())
    return hashlib.sha256(der).hexdigest()


def validate(cert: Path, key: Path, domain: str) -> str:
    data = cert.read_bytes()
    blocks = CERTIFICATE.findall(data)
    if not blocks or CERTIFICATE.sub(b"", data).strip():
        raise ValueError("TLS certificate must contain only PEM certificates")
    with tempfile.TemporaryDirectory() as directory:
        for index, block in enumerate(blocks):
            part = Path(directory) / f"{index}.pem"
            part.write_bytes(block)
            fingerprint = check_certificate(part, domain if index == 0 else None)
            if index == 0:
                leaf_fingerprint = fingerprint
    if b"ENCRYPTED" in key.read_bytes():
        raise ValueError("TLS private key must not require a password")
    # OpenSSL checks key parsing and the leaf/public-key match without prompting.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key, password="")
    return leaf_fingerprint


def atomic_copy(source: Path, destination: Path) -> None:
    pending = destination.with_suffix(".pending")
    try:
        with source.open("rb") as src, pending.open("wb") as dst:
            os.chmod(pending, 0o600)
            shutil.copyfileobj(src, dst)
        pending.replace(destination)
    finally:
        pending.unlink(missing_ok=True)


def install(cert: Path, key: Path, directory: Path, domain: str) -> None:
    # Validate the copied pair too, so source replacement during copying cannot pass unnoticed.
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=directory) as temporary:
        candidate = Path(temporary)
        atomic_copy(cert, candidate / "cert.pem")
        atomic_copy(key, candidate / "key.pem")
        validate(candidate / "cert.pem", candidate / "key.pem", domain)
        for name in ("cert.pem", "key.pem"):
            backup = directory / (name + ".previous")
            if (directory / name).is_file():
                atomic_copy(directory / name, backup)
            else:
                backup.unlink(missing_ok=True)
        try:
            for name in ("cert.pem", "key.pem"):
                atomic_copy(candidate / name, directory / name)
        except BaseException:
            restore(directory)
            raise


def restore(directory: Path) -> None:
    for name in ("cert.pem", "key.pem"):
        backup = directory / (name + ".previous")
        if backup.is_file():
            atomic_copy(backup, directory / name)
        else:
            (directory / name).unlink(missing_ok=True)


def tls_context(expected: str | None) -> ssl.SSLContext:
    context = ssl.create_default_context()
    if expected:
        # Private CAs need not be in the tool trust store: pin the validated leaf instead.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def probe(domain: str, host: str, port: int, expected: str | None, paths: list[str], secure: bool) -> None:
    context = tls_context(expected) if secure else None
    with socket.create_connection((host, port), timeout=3) as raw:
        if secure:
            with context.wrap_socket(raw, server_hostname=domain) as connection:
                der = connection.getpeercert(binary_form=True)
                if expected and hashlib.sha256(der).hexdigest() != expected:
                    raise ValueError("The HTTPS endpoint is not serving the requested certificate")
    for path in paths:
        with socket.create_connection((host, port), timeout=3) as raw:
            connection = context.wrap_socket(raw, server_hostname=domain) if secure else raw
            try:
                if secure and expected and hashlib.sha256(connection.getpeercert(binary_form=True)).hexdigest() != expected:
                    raise ValueError("The HTTPS endpoint changed certificates during verification")
                connection.sendall(f"GET {path} HTTP/1.1\r\nHost: {domain}\r\nConnection: close\r\n\r\n".encode())
                response = http.client.HTTPResponse(connection)
                response.begin()
                if response.status != 200:
                    raise ValueError(f"Endpoint {path} returned HTTP {response.status}")
            finally:
                if secure:
                    connection.close()


def wait_ready(domain: str, host: str, port: int, cert: Path | None, timeout: int, paths: list[str], secure: bool) -> None:
    expected = check_certificate(cert, domain) if cert else None
    deadline = time.monotonic() + timeout
    while True:
        try:
            probe(domain, host, port, expected, paths, secure)
            return
        except (OSError, ValueError, http.client.HTTPException) as error:
            if time.monotonic() >= deadline:
                raise ValueError(f"Endpoint verification failed: {error}") from error
            time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["validate", "install", "restore", "probe"])
    parser.add_argument("--cert", type=Path, default=Path("/source/cert.pem"))
    parser.add_argument("--key", type=Path, default=Path("/source/key.pem"))
    parser.add_argument("--directory", type=Path, default=Path("/state"))
    parser.add_argument("--domain", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--pin", action="store_true")
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--path", action="append", default=[])
    args = parser.parse_args()
    valid_domain(args.domain)
    if args.action == "validate":
        print(validate(args.cert, args.key, args.domain))
    elif args.action == "install":
        install(args.cert, args.key, args.directory, args.domain)
    elif args.action == "restore":
        restore(args.directory)
    else:
        wait_ready(args.domain, args.host, args.port, args.cert if args.pin else None, args.timeout, args.path, not args.http)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
