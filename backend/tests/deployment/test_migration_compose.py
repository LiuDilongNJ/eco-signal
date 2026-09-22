"""Tests for migration Compose profile and media service selection."""

import json
import os
import shlex
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "scripts/migration-compose.sh"


def run_bash(script: str, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("environment", "media_mode", "expected", "unexpected"),
    [
        (
            "local",
            "direct-mount",
            ["-f", "docker-compose.override.yml", "-f", "docker-compose.media-direct.yml"],
            ["--profile", "production"],
        ),
        (
            "staging",
            "managed",
            ["--profile", "production", "-f", "docker-compose.yml"],
            ["docker-compose.override.yml", "docker-compose.media-direct.yml"],
        ),
        (
            "production",
            "direct-mount",
            ["--profile", "production", "-f", "docker-compose.media-direct.yml"],
            ["docker-compose.override.yml"],
        ),
    ],
)
def test_configure_migration_compose_uses_environment_profile(
    environment, media_mode, expected, unexpected
):
    result = run_bash(
        f"""set -euo pipefail
source {shlex.quote(str(HELPER))}
configure_migration_compose {shlex.quote(environment)} test-stack {shlex.quote(media_mode)}
printf '%s\n' "${{DOCKER_COMPOSE[@]}}"
"""
    )

    assert result.returncode == 0, result.stderr
    arguments = result.stdout.splitlines()
    for value in expected:
        assert value in arguments
    for value in unexpected:
        assert value not in arguments


def make_fake_commands(tmp_path: Path) -> tuple[Path, Path]:
    command_log = tmp_path / "commands.log"
    fake_compose = tmp_path / "fake-compose"
    fake_compose.write_text(
        """#!/usr/bin/env bash
printf 'compose:%s\n' "$*" >> "$COMMAND_LOG"
case "$1" in
  config)
    [[ "${CONFIG_STATUS:-0}" == 0 ]] || exit "$CONFIG_STATUS"
    printf '%s\n' "$CONFIGURED_SERVICES"
    ;;
  ps)
    service="${3:-}"
    case " ${RUNNING_SERVICES:-} " in
      *" $service "*) printf 'container-%s\n' "$service" ;;
    esac
    ;;
  up) ;;
esac
"""
    )
    fake_compose.chmod(0o755)

    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        """#!/usr/bin/env bash
printf 'docker:%s\n' "$*" >> "$COMMAND_LOG"
if [[ "$1" == inspect ]]; then
  printf 'true\n'
fi
"""
    )
    fake_docker.chmod(0o755)
    return fake_compose, command_log


def run_recreation(
    tmp_path: Path,
    *,
    configured_services: str,
    running_services: str,
    config_status: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fake_compose, command_log = make_fake_commands(tmp_path)
    script = f"""set -euo pipefail
source {shlex.quote(str(HELPER))}
DOCKER_COMPOSE=({shlex.quote(str(fake_compose))})
info() {{ :; }}
warn() {{ :; }}
success() {{ :; }}
load_active_media_services
printf 'active:%s\n' "${{MIGRATION_ACTIVE_MEDIA_SERVICES[*]}}"
recreate_running_media_services direct-mount
"""
    result = run_bash(
        script,
        env={
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "COMMAND_LOG": str(command_log),
            "CONFIGURED_SERVICES": configured_services,
            "RUNNING_SERVICES": running_services,
            "CONFIG_STATUS": str(config_status),
        },
    )
    commands = command_log.read_text().splitlines() if command_log.exists() else []
    return result, commands


def test_local_recreation_ignores_running_service_outside_active_profile(tmp_path):
    result, commands = run_recreation(
        tmp_path,
        configured_services="db\nbackend\nworker\nfrontend",
        running_services="backend worker worker-analysis frontend",
    )

    assert result.returncode == 0, result.stderr
    assert "active:backend worker frontend" in result.stdout
    up_command = next(command for command in commands if command.startswith("compose:up "))
    assert up_command.endswith("backend worker frontend")
    assert "worker-analysis" not in "\n".join(commands)


def test_production_recreation_includes_analysis_worker(tmp_path):
    result, commands = run_recreation(
        tmp_path,
        configured_services="db\nbackend\nworker\nworker-analysis\nfrontend",
        running_services="backend worker worker-analysis frontend",
    )

    assert result.returncode == 0, result.stderr
    up_command = next(command for command in commands if command.startswith("compose:up "))
    assert up_command.endswith("backend worker worker-analysis frontend")


def test_recreation_does_not_start_stopped_active_service(tmp_path):
    result, commands = run_recreation(
        tmp_path,
        configured_services="backend\nworker\nfrontend",
        running_services="backend frontend",
    )

    assert result.returncode == 0, result.stderr
    up_command = next(command for command in commands if command.startswith("compose:up "))
    assert up_command.endswith("backend frontend")
    assert "container-worker" not in "\n".join(commands)


def test_no_running_media_service_skips_compose_up(tmp_path):
    result, commands = run_recreation(
        tmp_path,
        configured_services="backend\nworker\nfrontend",
        running_services="",
    )

    assert result.returncode == 0, result.stderr
    assert not any(command.startswith("compose:up ") for command in commands)


def test_compose_config_failure_stops_before_recreation(tmp_path):
    result, commands = run_recreation(
        tmp_path,
        configured_services="backend",
        running_services="backend",
        config_status=23,
    )

    assert result.returncode == 1
    assert "Unable to resolve services" in result.stderr
    assert commands == ["compose:config --services"]


def test_configuration_without_media_services_fails(tmp_path):
    result, commands = run_recreation(
        tmp_path,
        configured_services="db\nredis",
        running_services="",
    )

    assert result.returncode == 1
    assert "contains no media services" in result.stderr
    assert commands == ["compose:config --services"]


def test_development_recreation_leaves_running_production_profile_container(tmp_path):
    project_name = f"migration-compose-{uuid.uuid4().hex[:12]}"
    image_name = f"ecosignal-migration-production:{uuid.uuid4().hex[:12]}"
    compose_file = tmp_path / "compose.json"
    override_file = tmp_path / "override.json"
    base_service = {
        "image": "python:3.12-alpine",
        "command": ["sleep", "600"],
    }
    compose_file.write_text(
        json.dumps(
            {
                "services": {
                    "backend": {**base_service, "image": image_name},
                    "worker": {**base_service, "image": image_name},
                    "worker-analysis": {
                        **base_service,
                        "image": image_name,
                        "profiles": ["production"],
                    },
                    "frontend": base_service,
                }
            }
        )
    )
    override_file.write_text(
        json.dumps(
            {
                "services": {
                    "backend": base_service,
                    "worker": base_service,
                }
            }
        )
    )
    base_compose = [
        "docker",
        "compose",
        "--project-name",
        project_name,
        "-f",
        str(compose_file),
    ]
    development_compose = [*base_compose, "-f", str(override_file)]

    subprocess.run(
        ["docker", "image", "tag", "python:3.12-alpine", image_name], check=True
    )
    try:
        subprocess.run(
            [*development_compose, "up", "-d", "backend", "worker", "frontend"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [*base_compose, "--profile", "production", "up", "-d", "worker-analysis"],
            check=True,
            capture_output=True,
        )
        analysis_id = subprocess.run(
            [*base_compose, "ps", "-q", "worker-analysis"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["docker", "image", "rm", image_name], check=True, capture_output=True
        )

        compose_array = " ".join(shlex.quote(value) for value in development_compose)
        result = run_bash(
            f"""set -euo pipefail
source {shlex.quote(str(HELPER))}
DOCKER_COMPOSE=({compose_array})
info() {{ :; }}
warn() {{ :; }}
success() {{ :; }}
load_active_media_services
recreate_running_media_services direct-mount
"""
        )

        assert result.returncode == 0, result.stderr
        current_analysis_id = subprocess.run(
            [*base_compose, "ps", "-q", "worker-analysis"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert current_analysis_id == analysis_id
        assert subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Running}}", analysis_id],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip() == "true"
    finally:
        subprocess.run(
            [*base_compose, "--profile", "production", "down", "-v", "--remove-orphans"],
            capture_output=True,
        )
        subprocess.run(["docker", "image", "rm", image_name], capture_output=True)
