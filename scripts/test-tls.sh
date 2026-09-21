#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == --powershell ]]; then
    docker build --platform linux/amd64 -q -t ecosignal-tls-powershell-tests:local -f scripts/tls/Dockerfile.powershell-test scripts/tls
    docker run --rm --platform linux/amd64 -v "$PWD:$PWD:ro" -w "$PWD" ecosignal-tls-powershell-tests:local \
        -q --confcutdir=backend/tests/deployment -c /dev/null backend/tests/deployment/test_deploy_commands.py -o cache_dir=/tmp/pytest-cache
    exit 0
fi
if [[ -n "${1:-}" && "$1" != --integration ]]; then
    echo "Usage: $0 [--integration|--powershell]" >&2
    exit 2
fi
docker build -q -t ecosignal-tls-tools:local scripts/tls
docker build -q -t ecosignal-tls-tests:local -f scripts/tls/Dockerfile.test scripts/tls
# Docker fixtures bind the same absolute checkout path; no application containers are reused.
args=(--rm -e COVERAGE_FILE=/tmp/tls.coverage -v "$PWD:$PWD:ro" -w "$PWD")
if [[ "${1:-}" == --integration ]]; then
    docker build -q -t ecosignal-tls-frontend-test:local -f frontend/Dockerfile frontend
    mkdir -p .deploy
    args+=(-e TLS_DOCKER_TESTS=1 -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD/.deploy:$PWD/.deploy")
fi
docker run "${args[@]}" ecosignal-tls-tests:local -q --confcutdir=backend/tests/deployment -c /dev/null \
    backend/tests/deployment --cov=scripts/tls --cov-report=term-missing --cov-fail-under=90 -o cache_dir=/tmp/pytest-cache
