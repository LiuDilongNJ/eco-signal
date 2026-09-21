"""Isolated tests for migration script staging inside the backend container."""

import json
import os
import shlex
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(
    os.getenv("MIGRATION_RUNTIME_DOCKER_TESTS") != "1",
    reason="requires isolated Docker integration runner",
)


def shell_script(project: Path, compose: list[str], arguments: list[str]) -> str:
    command = " ".join(shlex.quote(part) for part in compose)
    args = " ".join(shlex.quote(part) for part in arguments)
    return f"""set -euo pipefail
PROJECT_ROOT={shlex.quote(str(project))}
DOCKER_COMPOSE=({command})
source {shlex.quote(str(ROOT / 'scripts/migration-runtime.sh'))}
trap cleanup_migration_runtime_on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
run_migration_in_backend -e TEST_VALUE=passed -- {args}
"""


@pytest.fixture(params=["none", "file", "directory"])
def runtime_stack(request):
    name = "migration-runtime-" + uuid.uuid4().hex[:12]
    directory = ROOT / ".deploy" / name
    project = directory / "project"
    scripts = project / "backend" / "scripts"
    mounted = directory / "mounted-scripts"
    scripts.mkdir(parents=True)
    mounted.mkdir(parents=True)
    (scripts / "migration_audit.py").write_text("VALUE = 'imported'\n")
    (scripts / "migrate_from_biosounds.py").write_text(
        "import json, os, sys\n"
        "from migration_audit import VALUE\n"
        "print(json.dumps({'value': VALUE, 'env': os.environ.get('TEST_VALUE'), 'args': sys.argv[1:]}))\n"
        "if '--audit-report' in sys.argv:\n"
        "    path = sys.argv[sys.argv.index('--audit-report') + 1]\n"
        "    open(path, 'w').write('audit')\n"
    )
    (scripts / "setup_insects_model.py").write_text("source marker\n")
    (mounted / "setup_insects_model.py").write_text("mounted marker\n")

    service = {
        "image": "python:3.12-alpine",
        "command": ["sh", "-c", "mkdir -p /app/scripts && exec sleep 600"],
        "working_dir": "/app",
    }
    if request.param == "file":
        service["volumes"] = [
            f"{mounted / 'setup_insects_model.py'}:/app/scripts/setup_insects_model.py:ro"
        ]
    elif request.param == "directory":
        service["volumes"] = [f"{mounted}:/app/scripts:ro"]
    compose_file = directory / "compose.json"
    compose_file.write_text(json.dumps({"services": {"backend": service}}))
    compose = [
        "docker",
        "compose",
        "--project-name",
        name,
        "-f",
        str(compose_file),
    ]
    subprocess.run([*compose, "up", "-d", "--wait"], check=True, capture_output=True)
    yield request.param, project, mounted, compose
    subprocess.run(
        [*compose, "down", "-v", "--remove-orphans"], check=True, capture_output=True
    )
    shutil.rmtree(directory)


def test_runtime_executes_all_migration_modes_without_touching_mount(runtime_stack):
    mode, project, mounted, compose = runtime_stack
    before = (mounted / "setup_insects_model.py").read_text()
    report = "/tmp/migration-runtime-audit.csv"
    modes = [[], ["--dry-run"], ["--repair-network-federation"], ["--repair-permissions"]]
    for arguments in modes:
        command_arguments = [*arguments, "--audit-report", report]
        result = subprocess.run(
            ["bash", "-c", shell_script(project, compose, command_arguments)],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout.splitlines()[-1])
        assert payload == {
            "value": "imported",
            "env": "passed",
            "args": command_arguments,
        }
    assert (mounted / "setup_insects_model.py").read_text() == before
    remaining = subprocess.run(
        [*compose, "exec", "-T", "backend", "sh", "-c", "find /tmp -maxdepth 1 -name 'ecosignal-migration.*' -print"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert remaining == ""
    audit = project.parent / "audit.csv"
    subprocess.run(
        [*compose, "cp", f"backend:{report}", str(audit)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert audit.read_text() == "audit"

    old_copy = subprocess.run(
        [*compose, "cp", f"{project}/backend/scripts/.", "backend:/app/scripts/"],
        capture_output=True,
        text=True,
    )
    assert (old_copy.returncode == 0) is (mode == "none")


def run_with_fake_compose(
    tmp_path: Path,
    *,
    copy_failure="",
    execution=0,
    cleanup=0,
    mktemp_status=0,
    mktemp_output="/tmp/ecosignal-migration.test",
):
    project = tmp_path / "project"
    scripts = project / "backend" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "migrate_from_biosounds.py").write_text("entry\n")
    (scripts / "migration_audit.py").write_text("helper\n")
    log = tmp_path / "commands.jsonl"
    fake = tmp_path / "compose"
    fake.write_text(
        "#!/usr/bin/env sh\n"
        "printf '%s\\n' \"$*\" >> \"$COMMAND_LOG\"\n"
        "case \"$*\" in\n"
        "  *'mktemp -d'*) echo \"$MKTEMP_OUTPUT\"; exit \"$MKTEMP_STATUS\" ;;\n"
        "  cp*'migrate_from_biosounds.py'*) [ \"$COPY_FAILURE\" != entry ] ;;\n"
        "  cp*'migration_audit.py'*) [ \"$COPY_FAILURE\" != helper ] ;;\n"
        "  *' python '*) sleep \"${EXEC_SLEEP:-0}\"; exit \"$EXECUTION_STATUS\" ;;\n"
        "  *' rm -rf '*) exit \"$CLEANUP_STATUS\" ;;\n"
        "esac\n"
    )
    fake.chmod(0o755)
    script = shell_script(project, [str(fake)], ["--dry-run"])
    env = {
        **os.environ,
        "COMMAND_LOG": str(log),
        "COPY_FAILURE": copy_failure,
        "EXECUTION_STATUS": str(execution),
        "CLEANUP_STATUS": str(cleanup),
        "MKTEMP_STATUS": str(mktemp_status),
        "MKTEMP_OUTPUT": mktemp_output,
    }
    return script, env, log


def test_missing_source_fails_before_container_changes(tmp_path):
    script, env, log = run_with_fake_compose(tmp_path)
    (tmp_path / "project/backend/scripts/migration_audit.py").unlink()
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True)
    assert result.returncode != 0
    assert not log.exists()


@pytest.mark.parametrize("failed_file", ["entry", "helper"])
def test_copy_failure_cleans_runtime_before_execution(tmp_path, failed_file):
    script, env, log = run_with_fake_compose(tmp_path, copy_failure=failed_file)
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True)
    assert result.returncode != 0
    commands = log.read_text().splitlines()
    expected_name = (
        "migration_audit.py" if failed_file == "helper" else "migrate_from_biosounds.py"
    )
    assert any(expected_name in command for command in commands)
    assert any("rm -rf" in command for command in commands)
    assert not any(" python " in command for command in commands)


def test_execution_status_wins_when_cleanup_also_fails(tmp_path):
    script, env, log = run_with_fake_compose(tmp_path, execution=7, cleanup=9)
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True)
    assert result.returncode == 7
    assert b"Unable to remove temporary migration directory" in result.stderr


def test_cleanup_failure_fails_successful_execution(tmp_path):
    script, env, _ = run_with_fake_compose(tmp_path, cleanup=9)
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True)
    assert result.returncode == 9


@pytest.mark.parametrize(
    ("status", "output"),
    [(6, "/tmp/ecosignal-migration.test"), (0, "/tmp/unexpected")],
)
def test_invalid_temporary_directory_creation_stops_before_copy(tmp_path, status, output):
    script, env, log = run_with_fake_compose(
        tmp_path, mktemp_status=status, mktemp_output=output
    )
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True)
    assert result.returncode != 0
    commands = log.read_text().splitlines()
    assert len(commands) == 1
    assert "mktemp -d" in commands[0]


def test_separator_and_cleanup_path_guards_fail_without_docker_mutation(tmp_path):
    script, env, log = run_with_fake_compose(tmp_path)
    prefix = script.split("run_migration_in_backend", 1)[0]
    guarded = (
        prefix
        + "MIGRATION_RUNTIME_DIR=/tmp/unexpected\n"
        + "cleanup_migration_runtime || cleanup_status=$?\n"
        + "run_migration_in_backend || separator_status=$?\n"
        + "test \"$cleanup_status\" -eq 1\n"
        + "test \"$separator_status\" -eq 2\n"
    )
    result = subprocess.run(["bash", "-c", guarded], env=env, capture_output=True)
    assert result.returncode == 0
    assert not log.exists()


def test_term_signal_preserves_signal_status_and_cleans(tmp_path):
    script, env, log = run_with_fake_compose(tmp_path)
    env["EXEC_SLEEP"] = "30"
    process = subprocess.Popen(
        ["bash", "-c", script],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if log.exists() and " python " in log.read_text():
            break
        time.sleep(0.05)
    else:
        process.kill()
        pytest.fail("migration command did not start")
    os.killpg(process.pid, signal.SIGTERM)
    process.communicate(timeout=5)
    assert process.returncode == 143
    assert any("rm -rf" in command for command in log.read_text().splitlines())
