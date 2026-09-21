import hashlib
import importlib.util
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("certificates", ROOT / "scripts/tls/certificates.py")
tls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tls)


def test_validate_accepts_private_ca_certificate(certificate_factory):
    cert, key = certificate_factory()
    assert tls.validate(cert, key, "app.test") == hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()


@pytest.mark.parametrize("kwargs,domain,message", [
    ({"start": -90, "end": -1}, "app.test", "expired"),
    ({"start": 2}, "app.test", "not yet valid"),
    ({}, "other.test", "does not cover"),
    ({"encrypted": True}, "app.test", "password"),
])
def test_validate_rejects_unusable_certificate(certificate_factory, kwargs, domain, message):
    cert, key = certificate_factory(**kwargs)
    with pytest.raises(ValueError, match=message):
        tls.validate(cert, key, domain)


def test_validate_warns_before_expiry(certificate_factory, capsys):
    cert, key = certificate_factory(end=10)
    tls.validate(cert, key, "app.test")
    assert "30 days" in capsys.readouterr().err


def test_validate_rejects_mismatched_key(certificate_factory):
    cert, _ = certificate_factory()
    _, key = certificate_factory()
    with pytest.raises(ssl.SSLError):
        tls.validate(cert, key, "app.test")


@pytest.mark.parametrize("content", [b"garbage", b"-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----", b""])
def test_validate_rejects_corrupt_certificate(certificate_factory, content):
    cert, key = certificate_factory()
    cert.write_bytes(content)
    with pytest.raises(ValueError):
        tls.validate(cert, key, "app.test")


def test_validate_rejects_missing_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        tls.validate(tmp_path / "missing", tmp_path / "key", "app.test")


def test_validate_rejects_corrupt_key(certificate_factory):
    cert, key = certificate_factory()
    key.write_text("invalid")
    with pytest.raises(ssl.SSLError):
        tls.validate(cert, key, "app.test")


@pytest.mark.parametrize("domain", ["https://app.test", "app.test:443", "a;return", "-app.test", "a..test", "a" * 254])
def test_validate_rejects_invalid_domain(domain):
    with pytest.raises(ValueError, match="DOMAIN"):
        tls.valid_domain(domain)


def test_validate_rejects_ip_without_ip_san(certificate_factory):
    cert, key = certificate_factory()
    with pytest.raises(ValueError, match="does not cover"):
        tls.validate(cert, key, "127.0.0.1")


def test_install_and_restore_keep_private_backup(certificate_factory, tmp_path):
    first = certificate_factory()
    second = certificate_factory()
    state = tmp_path / "state"
    tls.install(*first, state, "app.test")
    tls.install(*second, state, "app.test")
    assert (state / "cert.pem").read_bytes() == second[0].read_bytes()
    assert (state / "key.pem").stat().st_mode & 0o777 == 0o600
    tls.restore(state)
    assert (state / "cert.pem").read_bytes() == first[0].read_bytes()
    assert (state / "key.pem").read_bytes() == first[1].read_bytes()


def test_install_failure_restores_previous_pair(certificate_factory, tmp_path, monkeypatch):
    state = tmp_path / "state"
    first = certificate_factory()
    tls.install(*first, state, "app.test")
    original = tls.atomic_copy
    def fail(source, destination):
        if destination == state / "key.pem" and source.name == "key.pem":
            raise OSError("disk failure")
        original(source, destination)
    monkeypatch.setattr(tls, "atomic_copy", fail)
    with pytest.raises(OSError, match="disk failure"):
        tls.install(*certificate_factory(), state, "app.test")
    assert (state / "cert.pem").read_bytes() == first[0].read_bytes()


def test_restore_first_install_removes_pair(certificate_factory, tmp_path):
    state = tmp_path / "state"
    tls.install(*certificate_factory(), state, "app.test")
    tls.restore(state)
    assert not (state / "key.pem").exists()


def test_invalid_install_does_not_replace_active_pair(certificate_factory, tmp_path):
    state = tmp_path / "state"
    first = certificate_factory()
    tls.install(*first, state, "app.test")
    with pytest.raises(ValueError):
        tls.install(*certificate_factory("other.test"), state, "app.test")
    assert (state / "cert.pem").read_bytes() == first[0].read_bytes()


@pytest.fixture
def nginx_server(certificate_factory, tmp_path):
    if not shutil.which("nginx"):
        pytest.skip("requires the deployment test image")
    cert, key = certificate_factory()
    state = tmp_path / "state"
    tls.install(cert, key, state, "app.test")
    html = tmp_path / "html"
    html.mkdir()
    (html / "index.html").write_text("ecoSignal test")
    (html / "long.bin").write_bytes(b"a" * 128 * 1024)
    media = tmp_path / "media"
    media.mkdir()
    (media / "audio.wav").write_bytes(b"test audio")
    maintenance = tmp_path / "maintenance"
    maintenance.mkdir()
    (maintenance / "index.html").write_text("maintenance")
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        def log_message(self, *_args):
            pass
    backend = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    sockets = []
    for _ in range(2):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sockets.append(sock)
    http_port, https_port = [sock.getsockname()[1] for sock in sockets]
    for sock in sockets:
        sock.close()
    routes = (ROOT / "frontend/nginx/routes.conf").read_text().replace("http://backend:8000", f"http://127.0.0.1:{backend.server_port}")
    routes = routes.replace("/usr/share/nginx/html", str(html)).replace("/usr/share/nginx/media", str(media)).replace("/usr/share/nginx/maintenance", str(maintenance))
    route_file = tmp_path / "routes.conf"
    route_file.write_text(routes + f'\nlocation = /long.bin {{ root {html}; limit_rate 32k; }}\n')
    https = (ROOT / "frontend/nginx/https.conf.template").read_text().replace("${DOMAIN}", "app.test").replace("listen 80;", f"listen {http_port};").replace("listen 443 ssl;", f"listen {https_port} ssl;").replace("/etc/nginx/tls", str(state)).replace("/etc/nginx/includes/routes.conf", str(route_file))
    config = tmp_path / "nginx.conf"
    config.write_text(f"user root;\npid {tmp_path}/nginx.pid;\nerror_log {tmp_path}/error.log;\nevents {{}}\nhttp {{ access_log off; {https} }}")
    process = subprocess.Popen(["nginx", "-c", str(config), "-g", "daemon off;"])
    tls.wait_ready("app.test", "127.0.0.1", https_port, state / "cert.pem", 5, [], True)
    yield state, config, https_port, http_port, process, maintenance
    process.send_signal(signal.SIGQUIT)
    process.wait(timeout=10)
    backend.shutdown()


def test_nginx_routes_and_maintenance(nginx_server):
    state, _, port, http_port, _, maintenance = nginx_server
    tls.wait_ready("app.test", "127.0.0.1", port, state / "cert.pem", 0, ["/", "/api/v1/health", "/sounds/audio.wav"], True)
    conn = tls.http.client.HTTPConnection("127.0.0.1", http_port)
    conn.request("GET", "/api/test?q=1", headers={"Host": "attacker.test"})
    response = conn.getresponse()
    assert response.status == 301
    assert response.getheader("Location") == "https://app.test/api/test?q=1"
    conn.close()
    (maintenance / "maintenance.flag").touch()
    with pytest.raises(ValueError, match="503"):
        tls.wait_ready("app.test", "127.0.0.1", port, state / "cert.pem", 0, ["/"], True)


def test_nginx_reload_changes_certificate_without_interrupting_request(nginx_server, certificate_factory):
    state, config, port, _, process, _ = nginx_server
    first = state.joinpath("cert.pem").read_bytes()
    context = tls.tls_context(tls.check_certificate(state / "cert.pem", "app.test"))
    raw = socket.create_connection(("127.0.0.1", port))
    connection = context.wrap_socket(raw, server_hostname="app.test")
    connection.sendall(b"GET /long.bin HTTP/1.1\r\nHost: app.test\r\nConnection: close\r\n\r\n")
    response = tls.http.client.HTTPResponse(connection)
    response.begin()
    assert response.read(1) == b"a"
    pid = process.pid
    tls.install(*certificate_factory(), state, "app.test")
    subprocess.run(["nginx", "-t", "-c", str(config)], check=True)
    subprocess.run(["nginx", "-s", "reload", "-c", str(config)], check=True)
    tls.wait_ready("app.test", "127.0.0.1", port, state / "cert.pem", 5, ["/api/v1/health"], True)
    assert process.pid == pid and process.poll() is None
    assert state.joinpath("cert.pem").read_bytes() != first
    assert len(response.read()) == 128 * 1024 - 1
    connection.close()


def test_nginx_invalid_reload_keeps_old_certificate(nginx_server, certificate_factory):
    state, config, port, _, process, _ = nginx_server
    first = state / "cert.pem.previous"
    old = (state / "cert.pem").read_bytes()
    tls.install(*certificate_factory(), state, "app.test")
    (state / "key.pem").write_text("invalid")
    assert subprocess.run(["nginx", "-t", "-c", str(config)], capture_output=True).returncode != 0
    assert first.read_bytes() == old
    tls.wait_ready("app.test", "127.0.0.1", port, first, 0, [], True)
    with pytest.raises(ValueError, match="requested certificate"):
        tls.wait_ready("app.test", "127.0.0.1", port, state / "cert.pem", 0, [], True)
    tls.restore(state)
    assert process.poll() is None


def test_probe_rejects_untrusted_public_certificate(nginx_server):
    _, _, port, _, _, _ = nginx_server
    with pytest.raises(ValueError, match="verification failed"):
        tls.wait_ready("app.test", "127.0.0.1", port, None, 0, [], True)


def test_wait_retries_until_ready(monkeypatch):
    calls = []
    def probe(*_args):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("not ready")
    monkeypatch.setattr(tls, "probe", probe)
    monkeypatch.setattr(tls.time, "sleep", lambda _: None)
    tls.wait_ready("app.test", "127.0.0.1", 80, None, 5, [], False)
    assert len(calls) == 2


@pytest.mark.parametrize("action", ["validate", "install", "restore", "probe"])
def test_cli_dispatches_actions(action, certificate_factory, tmp_path, monkeypatch):
    cert, key = certificate_factory()
    monkeypatch.setattr(sys, "argv", ["certificates.py", action, "--domain", "app.test", "--cert", str(cert), "--key", str(key), "--directory", str(tmp_path / "state")])
    monkeypatch.setattr(tls, "wait_ready", lambda *_args: None)
    tls.main()


def test_cli_reports_validation_error():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/tls/certificates.py"), "validate", "--domain", "invalid;"], capture_output=True, text=True)
    assert result.returncode == 1
    assert "ERROR:" in result.stderr
