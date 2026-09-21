#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
docker build -q -t ecosignal-migration-runtime-tests:local -f scripts/migration/Dockerfile.test scripts/migration
mkdir -p .deploy
docker run --rm \
    -e MIGRATION_RUNTIME_DOCKER_TESTS=1 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$PWD:$PWD:ro" \
    -v "$PWD/.deploy:$PWD/.deploy" \
    -w "$PWD" \
    ecosignal-migration-runtime-tests:local \
    -q --noconftest -c /dev/null \
    backend/tests/deployment/test_migration_runtime.py \
    -o cache_dir=/tmp/pytest-cache
