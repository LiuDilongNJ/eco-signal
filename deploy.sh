#!/usr/bin/env bash
set -euo pipefail

compose_file="docker-compose.yml"
state_dir=".deploy"
lock_dir="${state_dir}/deploy.lock"
pull=false
build_geo_db=false
dry_run=false
force_unlock=false

usage() {
    cat <<'EOF'
Usage: ./deploy.sh [--pull] [--geo-db] [--dry-run] [--force-unlock]

  --pull          Pull newer base images before building.
  --geo-db        Rebuild the geo_db image explicitly.
  --dry-run       Validate configuration without changing Docker state.
  --force-unlock  Remove a verified stale deployment lock before continuing.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --pull) pull=true ;;
        --geo-db) build_geo_db=true ;;
        --dry-run) dry_run=true ;;
        --force-unlock) force_unlock=true ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

environment="$(docker compose -f "$compose_file" config --environment)"
environment_value() {
    awk -F= -v key="$1" '$1 == key { sub("^[^=]*=", ""); print; exit }' <<<"$environment"
}

project_name="${STACK_NAME:-$(environment_value STACK_NAME)}"
project_name="${project_name:-ecosignal}"
original_project_name="$project_name"
project_name="$(printf '%s' "$project_name" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_-]+/-/g; s/^[^a-z0-9]+//; s/[^a-z0-9]+$//')"
project_name="${project_name:-ecosignal}"
if [[ "$project_name" != "$original_project_name" ]]; then
    echo "Normalized STACK_NAME '${original_project_name}' to '${project_name}' for Docker Compose"
fi
domain="${DOMAIN:-$(environment_value DOMAIN)}"
domain="${domain:-localhost}"
https_enabled="${ENABLE_HTTPS:-$(environment_value ENABLE_HTTPS)}"
https_enabled="$(printf '%s' "$https_enabled" | tr '[:upper:]' '[:lower:]')"
email="${EMAIL:-$(environment_value EMAIL)}"

if [[ "$https_enabled" != "true" && "$https_enabled" != "false" ]]; then
    echo "ENABLE_HTTPS must be true or false" >&2
    exit 2
fi
if [[ "$https_enabled" == "true" ]] && { [[ "$domain" == "localhost" ]] || [[ -z "$email" ]]; }; then
    echo "HTTPS requires a public DOMAIN and EMAIL for certificate issuance" >&2
    exit 2
fi

mkdir -p "$state_dir"
if [[ "$force_unlock" == true ]]; then
    rm -rf "$lock_dir"
fi
if ! mkdir "$lock_dir" 2>/dev/null; then
    echo "Another deployment may be running. Inspect ${lock_dir}/owner, then use --force-unlock only for a stale lock." >&2
    exit 1
fi
printf 'pid=%s\nhost=%s\nstarted_at=%s\n' "$$" "$(hostname)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${lock_dir}/owner"
trap 'rm -rf "$lock_dir"' EXIT INT TERM

compose=(docker compose --project-name "$project_name" --profile production -f "$compose_file")
if [[ "$https_enabled" == "true" ]]; then
    compose+=(-f docker-compose.https.yml)
fi

run_compose() {
    STACK_NAME="$project_name" "${compose[@]}" "$@"
}

resolved_config="$(run_compose config)"
if grep -Eq 'ecosignal-backend-dev|uvicorn.*--reload|target: 5173|published: "5173"' <<<"$resolved_config"; then
    echo "Resolved configuration contains development runtime settings" >&2
    exit 2
fi

echo "Deployment mode: $([[ "$https_enabled" == true ]] && echo HTTPS || echo HTTP)"
echo "Resolved production services:"
run_compose config --services

if [[ "$dry_run" == true ]]; then
    echo "Dry run succeeded: project=${project_name} domain=${domain}"
    exit 0
fi

if [[ "$https_enabled" == "true" ]]; then
    docker network inspect traefik-public >/dev/null 2>&1 || docker network create traefik-public
    docker compose --project-name ecosignal-traefik -f docker-compose.traefik.yml up -d
fi

build_services() {
    if [[ "$pull" == true ]]; then
        run_compose build --pull "$@"
    else
        run_compose build "$@"
    fi
}

echo "[1/5] Building application images for ${domain}"
build_services backend frontend

geo_db_image="$(run_compose config --images | awk '/geo_db/ { print; exit }')"
if [[ -z "$geo_db_image" ]] || [[ "$build_geo_db" == true ]] || ! docker image inspect "$geo_db_image" >/dev/null 2>&1; then
    echo "[2/5] Building geo_db image"
    build_services geo_db
else
    echo "[2/5] Reusing existing geo_db image"
fi

echo "[3/5] Starting dependencies"
run_compose up -d --no-build --wait db geo_db redis rabbitmq

echo "[4/5] Applying database setup once"
run_compose run --rm --no-deps -e SKIP_PRESTART=true backend bash /app/scripts/prestart.sh

echo "[5/5] Starting application services"
if ! run_compose up -d --no-build --wait --remove-orphans backend worker worker-analysis frontend; then
    run_compose ps >&2 || true
    run_compose logs --tail=200 backend worker worker-analysis frontend >&2 || true
    exit 1
fi

echo "Deployment succeeded: ${domain}"
run_compose ps
