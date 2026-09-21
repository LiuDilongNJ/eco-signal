#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
compose_file="docker-compose.yml"
state_dir=".deploy"
lock_dir="${state_dir}/deploy.lock"
pull=false
build_geo_db=false
dry_run=false
force_unlock=false
reload_certs=false

usage() {
    cat <<'EOF'
Usage: ./deploy.sh [--pull] [--geo-db] [--dry-run] [--force-unlock] [--maintenance <on|off|status>] [--reload-certs]

  --reload-certs          Validate and hot-reload a running static HTTPS frontend.
  --pull                  Pull newer base images before building.
  --geo-db                Rebuild the geo_db image explicitly.
  --dry-run               Validate configuration without changing running services or installed certificates.
  --force-unlock          Remove a verified stale deployment lock before continuing.
  --maintenance <action>  Control maintenance mode manually: on, off, status.
EOF
}

maintenance_action=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --reload-certs) reload_certs=true ;;
        --pull) pull=true ;;
        --geo-db) build_geo_db=true ;;
        --dry-run) dry_run=true ;;
        --force-unlock) force_unlock=true ;;
        --maintenance)
            shift
            if [[ $# -eq 0 ]]; then
                echo "--maintenance requires an action: on, off, status" >&2
                exit 2
            fi
            maintenance_action="$1"
            if [[ "$maintenance_action" != "on" && "$maintenance_action" != "off" && "$maintenance_action" != "status" ]]; then
                echo "Invalid maintenance action '$maintenance_action'. Must be on, off, or status." >&2
                exit 2
            fi
            ;;
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
https_mode="${HTTPS_MODE:-$(environment_value HTTPS_MODE)}"
https_mode="$(printf '%s' "$https_mode" | tr '[:upper:]' '[:lower:]')"
https_mode="${https_mode:-letsencrypt}"
email="${EMAIL:-$(environment_value EMAIL)}"
tls_cert_file="${TLS_CERT_FILE:-$(environment_value TLS_CERT_FILE)}"
tls_key_file="${TLS_KEY_FILE:-$(environment_value TLS_KEY_FILE)}"
media_storage_mode="${MEDIA_STORAGE_MODE:-$(environment_value MEDIA_STORAGE_MODE)}"
media_storage_mode="${media_storage_mode:-managed}"

if [[ ! "$domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ ]]; then
    echo "DOMAIN must be a hostname without a scheme, port or path" >&2
    exit 2
fi
if [[ "$https_enabled" != "true" && "$https_enabled" != "false" ]]; then
    echo "ENABLE_HTTPS must be true or false" >&2
    exit 2
fi
if [[ "$https_enabled" == "true" ]]; then
    if [[ "$https_mode" != "letsencrypt" && "$https_mode" != "static" ]]; then
        echo "HTTPS_MODE must be 'letsencrypt' or 'static'" >&2
        exit 2
    fi
    if [[ "$domain" == "localhost" ]]; then
        echo "HTTPS requires a valid public DOMAIN (cannot be 'localhost')" >&2
        exit 2
    fi
    if [[ "$https_mode" == "letsencrypt" ]]; then
        if [[ -z "$email" ]]; then
            echo "Let's Encrypt HTTPS requires EMAIL as the ACME account contact" >&2
            exit 2
        fi
    elif [[ "$https_mode" == "static" && -z "$maintenance_action" ]]; then
        if [[ -z "$tls_cert_file" || -z "$tls_key_file" ]]; then
            echo "Static HTTPS mode requires TLS_CERT_FILE and TLS_KEY_FILE in .env" >&2
            exit 2
        fi
        if [[ ! -f "$tls_cert_file" ]]; then
            echo "TLS certificate file not found: $tls_cert_file" >&2
            exit 2
        fi
        if [[ ! -f "$tls_key_file" ]]; then
            echo "TLS private key file not found: $tls_key_file" >&2
            exit 2
        fi
        tls_cert_file="$(cd "$(dirname "$tls_cert_file")" && pwd)/$(basename "$tls_cert_file")"
        tls_key_file="$(cd "$(dirname "$tls_key_file")" && pwd)/$(basename "$tls_key_file")"
    fi
fi
if [[ "$media_storage_mode" != "managed" && "$media_storage_mode" != "direct-mount" ]]; then
    echo "MEDIA_STORAGE_MODE must be managed or direct-mount" >&2
    exit 2
fi

maintenance_dir="maintenance"
maintenance_flag="${maintenance_dir}/maintenance.flag"
maintenance_compose="docker-compose.maintenance.yml"

enable_maintenance() {
    mkdir -p "$maintenance_dir"
    touch "$maintenance_flag"
    if [[ "$https_enabled" == "true" && "$https_mode" == "letsencrypt" ]]; then
        docker network inspect traefik-public >/dev/null 2>&1 || docker network create traefik-public
        STACK_NAME="$project_name" DOMAIN="$domain" docker compose --project-name "$project_name" -f "$maintenance_compose" up -d
    fi
    echo "Maintenance mode is now ACTIVE."
}

disable_maintenance() {
    if [[ "$https_enabled" == "true" && "$https_mode" == "letsencrypt" ]]; then
        STACK_NAME="$project_name" DOMAIN="$domain" docker compose --project-name "$project_name" -f "$maintenance_compose" stop maintenance
        STACK_NAME="$project_name" DOMAIN="$domain" docker compose --project-name "$project_name" -f "$maintenance_compose" rm -f maintenance
    fi
    rm -f "$maintenance_flag"
    echo "Maintenance mode is now DISABLED."
}

check_maintenance_status() {
    local active=false
    if [[ -f "$maintenance_flag" ]]; then
        active=true
    fi
    if [[ "$https_enabled" == "true" && "$https_mode" == "letsencrypt" ]]; then
        if docker compose --project-name "$project_name" -f "$maintenance_compose" ps --services --filter "status=running" 2>/dev/null | grep -q maintenance; then
            active=true
        fi
    fi
    if [[ "$active" == true ]]; then
        echo "Maintenance mode: ACTIVE"
    else
        echo "Maintenance mode: INACTIVE"
    fi
}

mkdir -p "$state_dir"
if [[ "$force_unlock" == true ]]; then
    rm -rf "$lock_dir"
fi
if ! mkdir "$lock_dir" 2>/dev/null; then
    echo "Another deployment may be running. Inspect ${lock_dir}/owner, then use --force-unlock only for a stale lock." >&2
    exit 1
fi
printf 'pid=%s\nhost=%s\nstarted_at=%s\n' "$$" "$(hostname)" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${lock_dir}/owner"

maintenance_started_by_deploy=false
cleanup() {
    if [[ "${tls_pending:-false}" == true ]]; then
        echo "Restoring previous TLS certificate" >&2
        rollback_tls || echo "ERROR: TLS rollback failed; inspect frontend logs" >&2
    fi
    rm -rf "$lock_dir"
    if [[ "$maintenance_started_by_deploy" == true ]]; then
        echo "" >&2
        echo "=================================================================" >&2
        echo "Deployment failed or was interrupted! Maintenance mode remains ACTIVE." >&2
        echo "Inspect the logs, fix the issue, and re-run ./deploy.sh." >&2
        echo "To disable maintenance mode manually, run:" >&2
        echo "  ./deploy.sh --maintenance off" >&2
        echo "=================================================================" >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

compose=(docker compose --project-name "$project_name" --profile production -f "$compose_file")
if [[ "$media_storage_mode" == "direct-mount" ]]; then
    compose+=(-f docker-compose.media-direct.yml)
fi
if [[ "$https_enabled" == "true" ]]; then
    if [[ "$https_mode" == "static" ]]; then
        compose+=(-f docker-compose.https-static.yml)
    else
        compose+=(-f docker-compose.https.yml)
    fi
fi

run_compose() {
    DOMAIN="$domain" STACK_NAME="$project_name" "${compose[@]}" "$@"
}

source scripts/tls/deploy.sh
export DOMAIN="$domain" STACK_NAME="$project_name" EMAIL="$email"
if [[ "$reload_certs" == true && ( "$https_enabled" != true || "$https_mode" != static || -n "$maintenance_action" || "$dry_run" == true || "$pull" == true || "$build_geo_db" == true ) ]]; then
    echo "--reload-certs requires static HTTPS and cannot be combined with deployment actions" >&2
    exit 2
fi
if [[ "$dry_run" == true && -n "$maintenance_action" ]]; then
    echo "--dry-run cannot be combined with --maintenance" >&2
    exit 2
fi
if [[ -n "$maintenance_action" ]]; then
    case "$maintenance_action" in
        on) enable_maintenance ;;
        off) disable_maintenance ;;
        status) check_maintenance_status ;;
    esac
    exit 0
fi

resolved_config="$(run_compose config)"
if grep -Eq 'ecosignal-backend-dev|uvicorn.*--reload|target: 5173|published: "5173"' <<<"$resolved_config"; then
    echo "Resolved configuration contains development runtime settings" >&2
    exit 2
fi

echo "Deployment mode: $([[ "$https_enabled" == true ]] && echo "HTTPS (${https_mode})" || echo HTTP), media=${media_storage_mode}"
echo "Resolved production services:"
run_compose config --services

if [[ "$https_enabled" == true && "$https_mode" == letsencrypt ]]; then
    docker compose --project-name ecosignal-traefik -f docker-compose.traefik.yml config -q
    docker compose --project-name "$project_name" -f "$maintenance_compose" config -q
fi
if [[ "$dry_run" != true || ( "$https_enabled" == true && "$https_mode" == static ) ]]; then
    prepare_tls_tool
fi
if [[ "$https_enabled" == true && "$https_mode" == static ]]; then
    mkdir -p "$state_dir/tls"
    tls_source validate
fi
if [[ "$dry_run" == true ]]; then
    echo "Dry run succeeded: project=${project_name} domain=${domain}"
    exit 0
fi
if [[ "$reload_certs" == true ]]; then
    reload_tls
    exit 0
fi

echo "[0/5] Enabling maintenance mode for ${domain}"
touch "$maintenance_flag"
maintenance_started_by_deploy=true

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

prepare_entrypoint
if [[ "$https_enabled" == true && "$https_mode" == static ]]; then
    tls_source install
    tls_pending=true
fi
enable_maintenance

echo "[3/5] Starting dependencies"
run_compose up -d --no-build --wait db geo_db redis rabbitmq

echo "[4/5] Applying database setup once"
run_compose run --rm --no-deps -e SKIP_PRESTART=true backend bash /app/scripts/prestart.sh

echo "[5/5] Starting application services"
if ! run_compose up -d --no-build --wait backend worker worker-analysis frontend; then
    run_compose ps >&2 || true
    run_compose logs --tail=200 backend worker worker-analysis frontend >&2 || true
    exit 1
fi

run_compose exec -T frontend nginx -t
run_compose exec -T frontend nginx -s reload
if ! verify_endpoint tls; then
    if [[ "$https_mode" == letsencrypt && "$https_enabled" == true ]]; then
        docker compose --project-name ecosignal-traefik -f docker-compose.traefik.yml logs --tail=100 >&2
    fi
    exit 1
fi
tls_pending=false

echo "Disabling maintenance mode for ${domain}"
disable_maintenance
if ! verify_endpoint application; then
    enable_maintenance
    exit 1
fi
maintenance_started_by_deploy=false

echo "Deployment succeeded: ${domain}"
run_compose ps
