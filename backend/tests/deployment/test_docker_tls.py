"""Opt-in tests use only uniquely named, isolated Docker projects and volumes."""

import base64
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(os.getenv("TLS_DOCKER_TESTS") != "1", reason="requires isolated Docker integration runner")


@pytest.fixture
def stack():
    name = "tls-check-" + uuid.uuid4().hex[:12]
    directory = ROOT / ".deploy" / name
    directory.mkdir(parents=True)
    command = ["docker", "compose", "--project-name", name, "-f", str(directory / "compose.json")]
    def run(*args):
        return subprocess.run([*command, *args], capture_output=True, text=True, check=True).stdout.strip()
    yield name, directory, run
    if (directory / "compose.json").exists():
        subprocess.run([*command, "down", "-v", "--remove-orphans"], check=True, capture_output=True)
    shutil.rmtree(directory)


def rendered_service(directory, filename, service, name):
    for source in ROOT.glob("docker-compose*.yml"):
        shutil.copy(source, directory / source.name)
    shutil.copy(ROOT / ".env.example", directory / ".env")
    result = subprocess.run(["docker", "compose", "--project-name", name, "-f", str(directory / "docker-compose.yml"), "-f", str(directory / filename), "config", "--format", "json"],
                            env={**os.environ, "DOMAIN": "app.test", "STACK_NAME": name}, capture_output=True, check=True, text=True)
    return json.loads(result.stdout)["services"][service]


def base_services(directory):
    (directory / "backend.conf").write_text('server { listen 8000; location / { return 200 \'{"status":"ok"}\'; } }')
    (directory / "media").mkdir()
    (directory / "media/audio.wav").write_bytes(b"audio")
    (directory / "maintenance").mkdir()
    (directory / "maintenance/index.html").write_text("maintenance")
    return {
        "backend": {"image": "nginx:alpine", "volumes": [f"{directory}/backend.conf:/etc/nginx/conf.d/default.conf:ro"]},
        "frontend": {"image": "ecosignal-tls-frontend-test:local", "depends_on": ["backend"], "volumes": [f"{directory}/media:/usr/share/nginx/media:ro", f"{directory}/maintenance:/usr/share/nginx/maintenance:ro"]},
    }


def tool(target, *args, directory=None):
    command = ["docker", "run", "--rm", "--network", f"container:{target}"]
    if directory:
        command += ["--mount", f"type=bind,source={directory},target=/test,readonly"]
    command += ["ecosignal-tls-tools:local", *args]
    subprocess.run(command, capture_output=True, text=True, check=True)


def test_static_container_reload_preserves_id(stack, certificate_factory):
    name, directory, run = stack
    services = base_services(directory)
    cert, key = certificate_factory()
    shutil.copy(cert, directory / "cert.pem")
    shutil.copy(key, directory / "key.pem")
    frontend = services["frontend"]
    frontend["environment"] = {"DOMAIN": "app.test", "NGINX_ENVSUBST_FILTER": "^DOMAIN$"}
    frontend["volumes"] += [f"{directory}:/etc/nginx/tls:ro", f"{ROOT}/frontend/nginx/https.conf.template:/etc/nginx/templates/default.conf.template:ro"]
    (directory / "compose.json").write_text(json.dumps({"services": services}))
    run("up", "-d")
    target = run("ps", "-q", "frontend")
    args = ["probe", "--domain", "app.test", "--pin", "--cert", "/test/cert.pem", "--path", "/", "--path", "/api/v1/health", "--path", "/sounds/audio.wav"]
    tool(target, *args, directory=directory)
    before = run("exec", "-T", "frontend", "cat", "/var/run/nginx.pid")
    second_cert, second_key = certificate_factory()
    # Atomic file replacement exercises the whole-directory bind mount.
    shutil.copy(second_cert, directory / "next-cert.pem")
    shutil.copy(second_key, directory / "next-key.pem")
    (directory / "next-cert.pem").replace(directory / "cert.pem")
    (directory / "next-key.pem").replace(directory / "key.pem")
    run("exec", "-T", "frontend", "nginx", "-t")
    run("exec", "-T", "frontend", "nginx", "-s", "reload")
    tool(target, *args, directory=directory)
    assert run("ps", "-q", "frontend") == target
    assert run("exec", "-T", "frontend", "cat", "/var/run/nginx.pid") == before


def test_http_container_serves_all_routes(stack):
    _, directory, run = stack
    (directory / "compose.json").write_text(json.dumps({"services": base_services(directory)}))
    run("up", "-d")
    tool(run("ps", "-q", "frontend"), "probe", "--domain", "app.test", "--http", "--port", "80", "--path", "/", "--path", "/api/v1/health", "--path", "/sounds/audio.wav")


def test_acme_issues_and_renews_single_domain(stack, certificate_factory):
    name, directory, run = stack
    services = base_services(directory)
    frontend = rendered_service(directory, "docker-compose.https.yml", "frontend", name)
    services["frontend"]["labels"] = frontend["labels"]
    services["frontend"]["labels"]["traefik.docker.network"] = f"{name}_default"
    services["frontend"]["labels"]["ecosignal.test"] = name
    cert, key = certificate_factory("pebble")
    shutil.copy(cert, directory / "pebble.pem")
    shutil.copy(key, directory / "pebble.key")
    pebble = {"pebble": {"listenAddress": "0.0.0.0:14000", "managementListenAddress": "0.0.0.0:15000", "certificate": "/test/pebble.pem", "privateKey": "/test/pebble.key", "httpPort": 80, "tlsPort": 443, "profiles": {"default": {"description": "Integration tests", "validityPeriod": 300}}}}
    (directory / "pebble.json").write_text(json.dumps(pebble))
    services["pebble"] = {"image": "ghcr.io/letsencrypt/pebble:latest", "command": ["-config", "/test/pebble.json"], "environment": {"PEBBLE_VA_NOSLEEP": "1", "PEBBLE_WFE_NONCEREJECT": "0"}, "volumes": [f"{directory}:/test:ro"]}
    config = subprocess.run(["docker", "compose", "--env-file", str(directory / ".env"), "-f", str(ROOT / "docker-compose.traefik.yml"), "config", "--format", "json"], env={**os.environ, "STACK_NAME": name}, capture_output=True, check=True, text=True)
    ingress = json.loads(config.stdout)["services"]["traefik"]
    command = [arg for arg in ingress["command"] if not arg.startswith("--certificatesresolvers.le.acme.caserver=")]
    command += ["--certificatesresolvers.le.acme.caserver=https://pebble:14000/dir", "--certificatesresolvers.le.acme.certificatesduration=1", f'--providers.docker.constraints=Label(`ecosignal.test`, `{name}`)']
    ingress = {"image": ingress["image"], "command": command, "depends_on": ["pebble"], "environment": {"LEGO_CA_CERTIFICATES": "/test/pebble.pem"}, "labels": {"ecosignal.test": name}, "networks": {"default": {"aliases": ["app.test"]}}, "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro", "acme:/certificates", f"{directory}:/test:ro"]}
    services["traefik"] = ingress
    (directory / "compose.json").write_text(json.dumps({"services": services, "volumes": {"acme": {}}}))
    run("up", "-d")
    def current_certificate():
        try:
            content = run("exec", "-T", "traefik", "cat", "/certificates/acme.json")
            entries = json.loads(content)["le"]["Certificates"]
            assert len(entries) == 1 and entries[0]["domain"]["main"] == "app.test"
            return base64.b64decode(entries[0]["certificate"])
        except (subprocess.CalledProcessError, KeyError, TypeError, json.JSONDecodeError):
            return None
    deadline = time.monotonic() + 120
    first = None
    while time.monotonic() < deadline:
        first = current_certificate()
        if first:
            break
        time.sleep(2)
    assert first, run("logs", "traefik")
    (directory / "issued.pem").write_bytes(first)
    tool(run("ps", "-q", "traefik"), "probe", "--domain", "app.test", "--pin", "--cert", "/test/issued.pem", "--path", "/", "--path", "/api/v1/health", "--path", "/sounds/audio.wav", directory=directory)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        renewed = current_certificate()
        if renewed and renewed != first:
            break
        time.sleep(2)
    assert renewed != first, "ACME certificate was not renewed"
    (directory / "issued.pem").write_bytes(renewed)
    tool(run("ps", "-q", "traefik"), "probe", "--domain", "app.test", "--pin", "--cert", "/test/issued.pem", directory=directory)
