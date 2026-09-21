import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="requires the deployment test image")

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def deployment(tmp_path):
    for path in ROOT.glob('docker-compose*.yml'):
        shutil.copy(path, tmp_path / path.name)
    shutil.copy(ROOT / '.env.example', tmp_path / '.env')
    return tmp_path


def config(deployment, *files):
    command = ['docker', 'compose', '--project-name', 'tls-test', '--profile', 'production']
    for file in files:
        command.extend(['-f', file])
    command.extend(['config', '--format', 'json'])
    result = subprocess.run(command, cwd=deployment, env={**os.environ, 'DOMAIN': 'app.test'}, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('mode,ports', [('http', ['80']), ('static', ['80', '443']), ('letsencrypt', [])])
def test_modes_resolve_single_domain_and_expected_ports(deployment, mode, ports):
    files = ['docker-compose.yml']
    if mode != 'http':
        files.append('docker-compose.https-static.yml' if mode == 'static' else 'docker-compose.https.yml')
    data = config(deployment, *files)
    frontend = data['services']['frontend']
    assert 'VITE_API_BASE_URL' not in frontend['build']['args']
    assert 'NODE_ENV' not in frontend['build']['args']
    assert [port['published'] for port in frontend.get('ports', [])] == ports
    if mode != 'http':
        assert not data['services']['backend'].get('ports')
        for service in ('backend', 'worker', 'worker-analysis'):
            assert data['services'][service]['environment']['ENABLE_HTTPS'] == 'true'
            assert data['services'][service]['environment']['FRONTEND_PORT'] == '443'
    if mode == 'letsencrypt':
        rules = [value for key, value in frontend['labels'].items() if key.endswith('.rule')]
        assert rules == ['Host(`app.test`)', 'Host(`app.test`)']
    if mode == 'static':
        assert frontend['environment']['NGINX_ENVSUBST_FILTER'].replace('$$', '$') == '^DOMAIN$'
        assert any(mount['target'] == '/etc/nginx/tls' and mount['read_only'] for mount in frontend['volumes'])


def test_automatic_entrypoint_has_no_public_dashboard(deployment):
    data = config(deployment, 'docker-compose.traefik.yml')
    traefik = data['services']['traefik']
    assert '--api' not in traefik['command']
    assert 'api@internal' not in str(traefik)
    assert [port['published'] for port in traefik['ports']] == ['80', '443']
    assert '--entrypoints.http.http.redirections.entrypoint.to=https' in traefik['command']


def test_maintenance_routes_use_same_domain(deployment):
    data = config(deployment, 'docker-compose.maintenance.yml')
    labels = data['services']['maintenance']['labels']
    assert all(value == 'Host(`app.test`)' for key, value in labels.items() if key.endswith('.rule'))
