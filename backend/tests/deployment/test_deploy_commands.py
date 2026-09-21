import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

# Model only the Docker boundary; execute the real entrypoints and their error handling.
DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open('commands.jsonl', 'a') as log:
    log.write(json.dumps(args) + '\n')
if '--environment' in args:
    print('STACK_NAME=tls-test\nDOMAIN=app.test\nENABLE_HTTPS=' + os.getenv('ENABLE_HTTPS', 'true') + '\nHTTPS_MODE=' + os.getenv('HTTPS_MODE', 'static') + '\nTLS_CERT_FILE=' + os.getcwd() + '/cert.pem\nTLS_KEY_FILE=' + os.getcwd() + '/key.pem')
elif args[0] == 'inspect':
    if '-f' in args:
        template = args[args.index('-f') + 1]
        if 'tls-mode' in template:
            print('static')
        elif 'working_dir' in template:
            print(os.getcwd())
        else:
            print('app.test')
    else:
        print(json.dumps([{"Config":{"Labels":{"ecosignal.tls-mode":"static","ecosignal.domain":"app.test","com.docker.compose.project.working_dir":os.getcwd()}}}]))
elif 'ps' in args and '-q' in args:
    print('frontend-test')
if 'install' in args and os.getenv('FAIL_INSTALL'):
    sys.exit(1)
if 'nginx' in args and '-t' in args and os.getenv('FAIL_NGINX') and not Path('failed').exists():
    Path('failed').touch()
    sys.exit(1)
if 'probe' in args and os.getenv('FAIL_PROBE') and not Path('failed').exists():
    Path('failed').touch()
    sys.exit(1)
'''


@pytest.fixture(params=['bash', 'powershell'] if shutil.which('pwsh') else ['bash'])
def entrypoint(request, tmp_path):
    shutil.copy(ROOT / 'deploy.sh', tmp_path)
    shutil.copy(ROOT / 'deploy.ps1', tmp_path)
    (tmp_path / 'test-entry.ps1').write_text('$env:PATH = "$PSScriptRoot/bin" + [IO.Path]::PathSeparator + $env:PATH\n& "$PSScriptRoot/deploy.ps1" @args\n')
    shutil.copytree(ROOT / 'scripts/tls', tmp_path / 'scripts/tls')
    (tmp_path / 'cert.pem').write_text('source certificate')
    (tmp_path / 'key.pem').write_text('source key')
    (tmp_path / 'bin').mkdir()
    (tmp_path / 'maintenance').mkdir()
    docker = tmp_path / 'bin/docker'
    docker.write_text(DOCKER)
    docker.chmod(0o755)
    def run(action='reload', **extra):
        arguments = {'reload': '--reload-certs', 'dry': '--dry-run', 'maintenance': '--maintenance'} if request.param == 'bash' else {'reload': '-ReloadCerts', 'dry': '-DryRun', 'maintenance': '-Maintenance'}
        command = ['bash', str(tmp_path / 'deploy.sh')] if request.param == 'bash' else ['pwsh', '-NoProfile', '-File', str(tmp_path / 'test-entry.ps1')]
        if action != "deploy":
            command.append(arguments[action])
        if action == 'maintenance':
            command.append('status')
        result = subprocess.run(command, cwd=tmp_path, env={**os.environ, 'PATH': str(tmp_path / 'bin') + ':' + os.environ['PATH'], **extra}, capture_output=True, text=True)
        assert (tmp_path / 'commands.jsonl').exists(), result.stdout + result.stderr
        commands = [json.loads(line) for line in (tmp_path / 'commands.jsonl').read_text().splitlines()]
        return result, commands
    return tmp_path, run


def test_reload_only_touches_certificate_service(entrypoint):
    path, run = entrypoint
    result, commands = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert any('install' in command for command in commands)
    assert any('nginx' in command and 'reload' in command for command in commands)
    assert any('probe' in command for command in commands)
    assert not any('up' in command or 'stop' in command for command in commands)
    assert not (path / '.deploy/deploy.lock').exists()
    assert not (path / 'maintenance/maintenance.flag').exists()


@pytest.mark.parametrize('failure', ['FAIL_NGINX', 'FAIL_PROBE'])
def test_reload_failure_restores_and_returns_nonzero(entrypoint, failure):
    path, run = entrypoint
    result, commands = run(**{failure: 'true'})
    assert result.returncode != 0
    assert any('restore' in command for command in commands)
    assert not (path / '.deploy/deploy.lock').exists()


def test_install_validation_failure_does_not_restore_stale_backup(entrypoint):
    _, run = entrypoint
    result, commands = run(FAIL_INSTALL='true')
    assert result.returncode != 0
    assert not any('restore' in command for command in commands)


def test_reload_cannot_race_an_active_deployment(entrypoint):
    path, run = entrypoint
    (path / '.deploy/deploy.lock').mkdir(parents=True)
    result, commands = run()
    assert result.returncode != 0
    assert not any('install' in command for command in commands)
    assert (path / '.deploy/deploy.lock').exists()


def test_dry_run_does_not_install_or_start_services(entrypoint):
    _, run = entrypoint
    result, commands = run('dry')
    assert result.returncode == 0, result.stdout + result.stderr
    assert any('validate' in command for command in commands)
    assert not any('install' in command or 'up' in command or 'stop' in command for command in commands)


def test_http_dry_run_does_not_build_unused_tls_tool(entrypoint):
    _, run = entrypoint
    result, commands = run('dry', ENABLE_HTTPS='false')
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any('build' in command or 'validate' in command for command in commands)


def test_maintenance_status_does_not_validate_or_update_certificates(entrypoint):
    _, run = entrypoint
    result, commands = run('maintenance')
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any('install' in command or 'validate' in command for command in commands)


@pytest.mark.parametrize('mode', ['http', 'static', 'letsencrypt'])
def test_full_deployment_verifies_before_reporting_success(entrypoint, mode):
    path, run = entrypoint
    result, commands = run('deploy', ENABLE_HTTPS='false' if mode == 'http' else 'true', HTTPS_MODE=mode, EMAIL='admin@app.test')
    assert result.returncode == 0, result.stdout + result.stderr
    probes = [command for command in commands if 'probe' in command]
    assert len(probes) == 2
    assert '--path' not in probes[0] and '--path' in probes[1]
    assert not (path / 'maintenance/maintenance.flag').exists()
    assert 'Deployment succeeded' in result.stdout


def test_failed_full_deployment_retains_maintenance(entrypoint):
    path, run = entrypoint
    result, commands = run('deploy', FAIL_PROBE='true')
    assert result.returncode != 0
    assert (path / 'maintenance/maintenance.flag').exists()
    assert any('restore' in command for command in commands)
    assert 'Deployment succeeded' not in result.stdout
