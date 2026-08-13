#!/usr/bin/env bash
# migrate-data.sh - Migrate data and static files from ecoSound-web (biosounds) to ecoSignal.
#
# Usage:
#   ./migrate-data.sh <old-project-dir> [options]
#
# Options:
#   --dry-run        Preview migration without writing data
#   --skip-db        Skip database migration
#   --skip-files     Skip static file migration
#   --copy-files     Copy legacy static files into app-media-data volume (emergency mode)
#   --reset-target   Required after a fresh deploy (Demo Project/collection/site
#                    seed data). Backup current ecoSignal DB/media, clear
#                    business data, then migrate
#   --legacy-app-url Explicit public URL for legacy instances using dynamic APP_URL
#   --repair-network-federation
#                     Repair only federation settings in an already migrated target
#   -h, --help       Show help

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_ROOT="${PROJECT_ROOT}/.upgrade-backup/target_backup_${TIMESTAMP}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$*"; exit 1; }

OLD_PROJECT_DIR=""
DRY_RUN=false
SKIP_DB=false
SKIP_FILES=false
COPY_FILES=false
RESET_TARGET=false
REPAIR_NETWORK_FEDERATION=false
LEGACY_APP_URL_OVERRIDE=""

resolve_environment() {
    local configured="${ENVIRONMENT:-}"
    if [[ -z "$configured" && -f "${PROJECT_ROOT}/.env" ]]; then
        configured=$(grep -E '^ENVIRONMENT=' "${PROJECT_ROOT}/.env" | tail -1 | cut -d= -f2- || true)
    fi
    configured="${configured%\"}"
    configured="${configured#\"}"
    printf '%s\n' "${configured:-local}"
}

resolve_stack_name() {
    local configured="${STACK_NAME:-}"
    if [[ -z "$configured" && -f "${PROJECT_ROOT}/.env" ]]; then
        configured=$(grep -E '^STACK_NAME=' "${PROJECT_ROOT}/.env" | tail -1 | cut -d= -f2- || true)
    fi
    configured="${configured%\"}"
    configured="${configured#\"}"
    printf '%s\n' "${configured:-ecosignal}"
}

# Same normalization as deploy.sh so both scripts target the same compose project.
normalize_project_name() {
    local name
    name="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9_-]+/-/g; s/^[^a-z0-9]+//; s/[^a-z0-9]+$//')"
    printf '%s\n' "${name:-ecosignal}"
}

compose_display_command() {
    printf '%q ' "${DOCKER_COMPOSE[@]}"
}

usage() {
    grep '^#' "$0" | grep -v '!/usr/bin' | sed 's/^# \?//'
    exit 0
}

media_mode() {
    if [[ "$COPY_FILES" == true ]]; then
        printf 'copy-files\n'
    else
        printf 'direct-mount\n'
    fi
}

resolve_old_project_dir() {
    local configured="${LEGACY_PROJECT_DIR:-}"
    if [[ -z "$configured" && -f "${PROJECT_ROOT}/.env" ]]; then
        configured=$(grep -E '^LEGACY_PROJECT_DIR=' "${PROJECT_ROOT}/.env" | tail -1 | cut -d= -f2- || true)
    fi
    configured="${configured:-./ecoSound-web}"
    if [[ "$configured" == /* ]]; then
        printf '%s\n' "$configured"
    else
        printf '%s\n' "$(cd "${PROJECT_ROOT}" && cd "$configured" && pwd)"
    fi
}

parse_legacy_ini() {
    local key="$1"
    local ini_file="${OLD_PROJECT_DIR}/src/config/config.ini"
    if [[ ! -f "$ini_file" ]]; then
        return 0
    fi
    grep -E "^${key}[[:space:]]*=" "$ini_file" | tail -1 | sed -E "s/^[^=]+= *'?([^']*)'?.*/\1/" || true
}

parse_legacy_compose_port() {
    local compose_file="${OLD_PROJECT_DIR}/docker-compose.yml"
    if [[ ! -f "$compose_file" ]]; then
        return 0
    fi
    grep -E '^[[:space:]]*-[[:space:]]*[0-9]+:3306' "$compose_file" | head -1 | sed -E 's/.*- *([0-9]+):3306/\1/' || true
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        --dry-run) DRY_RUN=true; shift ;;
        --skip-db) SKIP_DB=true; shift ;;
        --skip-files) SKIP_FILES=true; shift ;;
        --copy-files) COPY_FILES=true; shift ;;
        --reset-target) RESET_TARGET=true; shift ;;
        --repair-network-federation) REPAIR_NETWORK_FEDERATION=true; shift ;;
        --legacy-app-url)
            [[ $# -ge 2 && -n "$2" ]] || die "--legacy-app-url requires a URL"
            LEGACY_APP_URL_OVERRIDE="$2"
            shift 2
            ;;
        -*) die "Unknown option: $1" ;;
        *)
            if [[ -z "$OLD_PROJECT_DIR" ]]; then
                OLD_PROJECT_DIR="$1"
            else
                die "Unexpected argument: $1"
            fi
            shift
            ;;
    esac
done

CURRENT_ENVIRONMENT="$(resolve_environment)"
COMPOSE_PROJECT="$(normalize_project_name "$(resolve_stack_name)")"
DOCKER_COMPOSE=(docker compose --project-name "$COMPOSE_PROJECT")
if [[ "$CURRENT_ENVIRONMENT" == "staging" || "$CURRENT_ENVIRONMENT" == "production" ]]; then
    DOCKER_COMPOSE=(docker compose --project-name "$COMPOSE_PROJECT" -f docker-compose.yml)
fi
COMPOSE_DISPLAY="$(compose_display_command)"
COMPOSE_DISPLAY="${COMPOSE_DISPLAY% }"

if [[ -z "$OLD_PROJECT_DIR" ]]; then
    OLD_PROJECT_DIR="$(resolve_old_project_dir)"
else
    [[ -d "$OLD_PROJECT_DIR" ]] || die "Directory not found: $OLD_PROJECT_DIR"
    OLD_PROJECT_DIR="$(cd "$OLD_PROJECT_DIR" && pwd)"
fi

MEDIA_MODE="$(media_mode)"
LEGACY_CONFIG_APP_URL="$(parse_legacy_ini APP_URL)"
LEGACY_CONFIG_HOST_URL="$(parse_legacy_ini HOST_URL)"
LEGACY_APP_URL_VALUE="${LEGACY_APP_URL_OVERRIDE:-$LEGACY_CONFIG_APP_URL}"

info "Selected media migration mode: $MEDIA_MODE"
info "Resolved legacy project directory: $OLD_PROJECT_DIR"
info "Detected environment: $CURRENT_ENVIRONMENT"
info "Docker Compose project name: $COMPOSE_PROJECT"
if [[ "$CURRENT_ENVIRONMENT" == "staging" || "$CURRENT_ENVIRONMENT" == "production" ]]; then
    info "Using Docker Compose files: docker-compose.yml only"
else
    info "Using Docker Compose files: default compose discovery"
fi
[[ -d "$OLD_PROJECT_DIR" ]] || die "Directory not found: $OLD_PROJECT_DIR"
[[ -f "$OLD_PROJECT_DIR/docker-compose.yml" ]] || die "Missing docker-compose.yml in old project"

if [[ "$REPAIR_NETWORK_FEDERATION" == true ]]; then
    [[ "$RESET_TARGET" == false ]] || die "--repair-network-federation cannot be combined with --reset-target"
    [[ "$COPY_FILES" == false ]] || die "--repair-network-federation cannot be combined with --copy-files"
fi

MISSING_DIRS=()
for subdir in sounds sound_images project_images; do
    if [[ ! -d "$OLD_PROJECT_DIR/$subdir" ]]; then
        MISSING_DIRS+=("$subdir")
    fi
done
if [[ ${#MISSING_DIRS[@]} -gt 0 ]]; then
    warn "Some legacy static directories are missing and will be skipped: ${MISSING_DIRS[*]}"
fi

require_full_legacy_media_tree() {
    local missing=("$@")
    if [[ ${#missing[@]} -eq 0 || ( ${#missing[@]} -eq 1 && -z "${missing[0]}" ) ]]; then
        return 0
    fi
    die "Direct-mount mode requires legacy media directories before migration. Missing: ${missing[*]}"
}

command -v docker >/dev/null 2>&1 || die "docker is not installed"
cd "$PROJECT_ROOT"

BACKEND_RUNNING=$("${DOCKER_COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -c "^backend$" || true)
DB_RUNNING=$("${DOCKER_COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -c "^db$" || true)
[[ "$BACKEND_RUNNING" -gt 0 ]] || die "The backend container is not running."
[[ "$DB_RUNNING" -gt 0 ]] || die "The db container is not running."
success "ecoSignal backend and db are running."

if [[ "$REPAIR_NETWORK_FEDERATION" == true ]]; then
    info "Repairing migrated federation settings only..."
    REPAIR_ARGS=(--repair-network-federation)
    [[ "$DRY_RUN" == true ]] && REPAIR_ARGS+=(--dry-run)
    "${DOCKER_COMPOSE[@]}" exec -T \
        -e LEGACY_APP_URL="$LEGACY_APP_URL_VALUE" \
        -e LEGACY_HOST_URL="$LEGACY_CONFIG_HOST_URL" \
        backend \
        python scripts/migrate_from_biosounds.py "${REPAIR_ARGS[@]}"
    success "Federation repair finished."
    exit 0
fi

recreate_media_mount_services() {
    info "Recreating backend and worker so legacy media bind mounts use the current LEGACY_PROJECT_DIR..."
    "${DOCKER_COMPOSE[@]}" up -d --force-recreate backend worker
    success "Backend and worker recreated for legacy media mounts."
}

MYSQL_HOST="${MYSQL_HOST:-127.0.0.1}"
MYSQL_PORT="${MYSQL_PORT:-$(parse_legacy_compose_port)}"
MYSQL_PORT="${MYSQL_PORT:-13306}"
MYSQL_USER="${MYSQL_USER:-$(parse_legacy_ini USER)}"
MYSQL_USER="${MYSQL_USER:-root}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-$(parse_legacy_ini PASSWORD)}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-root}"
MYSQL_DB="${MYSQL_DB:-$(parse_legacy_ini DATABASE)}"
MYSQL_DB="${MYSQL_DB:-biosounds}"

if [[ "$SKIP_DB" == false ]]; then
    info "Checking legacy MySQL connectivity at ${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DB}"
    if ! nc -z -w5 "$MYSQL_HOST" "$MYSQL_PORT" 2>/dev/null; then
        die "Cannot reach MySQL at ${MYSQL_HOST}:${MYSQL_PORT}"
    fi
    success "Legacy MySQL is reachable."
fi

backup_target_state() {
    mkdir -p "$BACKUP_ROOT"
    info "Backing up current ecoSignal target state into $BACKUP_ROOT"
    "${DOCKER_COMPOSE[@]}" exec -T db pg_dump -U "${POSTGRES_USER:-postgres}" "${POSTGRES_DB:-ecosignal}" > "${BACKUP_ROOT}/ecosignal_db.sql"

    local full_volume
    full_volume="${COMPOSE_PROJECT}_app-media-data"
    docker volume inspect "$full_volume" >/dev/null 2>&1 || die "Docker volume ${full_volume} not found."
    docker run --rm \
        -v "${full_volume}:/data" \
        -v "${BACKUP_ROOT}:/backup" \
        alpine:3 \
        sh -c "tar -czf /backup/app-media-data.tar.gz -C /data ."
    success "Current ecoSignal DB and media backup completed."
}

if [[ "$DRY_RUN" == false && "$RESET_TARGET" == true ]]; then
    backup_target_state
fi

copy_to_volume() {
    local src_dir="$1"
    local dest_subdir="$2"
    local full_volume="$3"

    if [[ ! -d "$src_dir" ]]; then
        warn "Source directory not found, skipping: $src_dir"
        return
    fi

    local src_count
    src_count=$(find "$src_dir" -type f | wc -l | tr -d ' ')
    info "Syncing $src_count files: $src_dir -> <volume>/$dest_subdir/"

    docker run --rm \
        -v "$full_volume:/data" \
        -v "$src_dir:/src:ro" \
        alpine:3 \
        sh -c "mkdir -p /data/${dest_subdir} && find /data/${dest_subdir} -mindepth 1 -maxdepth 1 -exec rm -rf {} + && cp -a /src/. /data/${dest_subdir}/"
}

verify_direct_mount_access() {
    info "Verifying direct-mount media paths in backend container..."
    "${DOCKER_COMPOSE[@]}" exec -T backend sh -lc '
set -eu
for d in /app/sounds/sounds /app/sounds/images /app/sounds/projects; do
  if [ ! -d "$d" ]; then
    echo "MISSING_DIR $d"
    exit 1
  fi
  if [ ! -r "$d" ]; then
    echo "UNREADABLE_DIR $d"
    exit 1
  fi
done

total_files=0
sample_checked=0
for d in /app/sounds/sounds /app/sounds/images /app/sounds/projects; do
  count=$(find "$d" -type f | wc -l | tr -d " ")
  total_files=$((total_files + count))
  sample=$(find "$d" -type f | head -n 3 || true)
  if [ -n "$sample" ]; then
    while IFS= read -r f; do
      [ -r "$f" ] || { echo "UNREADABLE_FILE $f"; exit 1; }
      sample_checked=$((sample_checked + 1))
    done <<EOF
$sample
EOF
  fi
done
echo "DIRECT_MOUNT_OK total_files=$total_files sample_checked=$sample_checked"
'
}

prepare_media_access() {
    info "Preparing media access strategy: $MEDIA_MODE"

    if [[ "$MEDIA_MODE" == "copy-files" ]]; then
        warn "COPY mode enabled (--copy-files). Legacy media will be copied into app-media-data."
        return 0
    fi

    if [[ "$SKIP_FILES" == true ]]; then
        warn "Direct-mount mode selected but static file handling is skipped (--skip-files). Legacy media access will not be pre-verified."
        return 0
    fi

    require_full_legacy_media_tree "${MISSING_DIRS[@]-}"
    recreate_media_mount_services
    verify_direct_mount_access
    success "Direct-mount media verification completed."
}

prepare_media_access

TARGET_IS_NON_EMPTY=0
if [[ "$SKIP_DB" == false ]]; then
    TARGET_IS_NON_EMPTY=$("${DOCKER_COMPOSE[@]}" exec -T db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ecosignal}" -Atc "
        SELECT CASE WHEN EXISTS (
            SELECT 1 FROM (
                SELECT COUNT(*) AS c FROM project
                UNION ALL SELECT COUNT(*) FROM collection
                UNION ALL SELECT COUNT(*) FROM site
                UNION ALL SELECT COUNT(*) FROM media
                UNION ALL SELECT COUNT(*) FROM annotation
                UNION ALL SELECT COUNT(*) FROM preview
                UNION ALL SELECT COUNT(*) FROM user_permission
            ) t WHERE c > 0
        ) THEN 1 ELSE 0 END;
    " | tr -d '\r')
    if [[ "$TARGET_IS_NON_EMPTY" == "1" && "$RESET_TARGET" == false ]]; then
        if [[ "$DRY_RUN" == true ]]; then
            warn "Target PostgreSQL already contains business data (fresh deploys include Demo Project/collection/site). Continuing because this is a dry-run."
        else
            die "Target PostgreSQL already contains business data (fresh deploys include Demo Project/collection/site). Re-run with --reset-target to back up, clear, and migrate."
        fi
    fi
fi

if [[ "$SKIP_DB" == false ]]; then
    info "Ensuring MySQL migration dependencies are available in the backend container..."
    if ! "${DOCKER_COMPOSE[@]}" exec -T backend python -c "import pymysql, cryptography" >/dev/null 2>&1; then
        "${DOCKER_COMPOSE[@]}" exec -T backend sh -c '
            VENV_SITE_PACKAGES=$(python - <<'"'"'PY'"'"'
import sysconfig
print(sysconfig.get_path("purelib"))
PY
)
            pip install --quiet --target "$VENV_SITE_PACKAGES" pymysql cryptography
        '
    fi
    success "MySQL migration dependencies are available."
fi

if [[ "$SKIP_DB" == true ]]; then
    warn "Skipping database migration (--skip-db)."
else
    info "Starting database migration..."
    MYSQL_HOST_IN_CONTAINER="host.docker.internal"
    AUDIT_REPORT_DIR="${PROJECT_ROOT}/migration-reports"
    AUDIT_REPORT_NAME="migration-audit_${TIMESTAMP}.csv"
    AUDIT_REPORT_CONTAINER_PATH="/tmp/${AUDIT_REPORT_NAME}"
    mkdir -p "$AUDIT_REPORT_DIR"

    DB_MIGRATE_ARGS=()
    if [[ "$DRY_RUN" == true && "$TARGET_IS_NON_EMPTY" == "1" && "$RESET_TARGET" == false ]]; then
        info "Passing --reset-target to in-container dry-run so migration can preview against a non-empty target without mutating it."
        DB_MIGRATE_ARGS+=(--reset-target)
    fi
    [[ "$DRY_RUN" == true ]] && DB_MIGRATE_ARGS+=(--dry-run)
    [[ "$RESET_TARGET" == true ]] && DB_MIGRATE_ARGS+=(--reset-target)

    MIGRATION_EXIT=0
    if "${DOCKER_COMPOSE[@]}" exec -T \
        -e MYSQL_HOST="$MYSQL_HOST_IN_CONTAINER" \
        -e MYSQL_PORT="$MYSQL_PORT" \
        -e MYSQL_USER="$MYSQL_USER" \
        -e MYSQL_PASSWORD="$MYSQL_PASSWORD" \
        -e MYSQL_DB="$MYSQL_DB" \
        -e LEGACY_APP_URL="$LEGACY_APP_URL_VALUE" \
        -e LEGACY_HOST_URL="$LEGACY_CONFIG_HOST_URL" \
        backend \
        python scripts/migrate_from_biosounds.py "${DB_MIGRATE_ARGS[@]}" --audit-report "$AUDIT_REPORT_CONTAINER_PATH"; then
        :
    else
        MIGRATION_EXIT=$?
    fi

    if "${DOCKER_COMPOSE[@]}" cp "backend:${AUDIT_REPORT_CONTAINER_PATH}" "${AUDIT_REPORT_DIR}/${AUDIT_REPORT_NAME}"; then
        success "Migration audit report saved at: ${AUDIT_REPORT_DIR}/${AUDIT_REPORT_NAME}"
    else
        warn "No migration audit report was created (no row-level issues or migration stopped before auditing)."
    fi

    if [[ "$MIGRATION_EXIT" -ne 0 ]]; then
        exit "$MIGRATION_EXIT"
    fi

    if [[ "$DRY_RUN" == false ]]; then
        success "Database migration completed."
    else
        success "Dry-run finished. No database changes were made."
    fi
fi

if [[ "$SKIP_FILES" == true ]]; then
    warn "Skipping static file migration (--skip-files)."
elif [[ "$DRY_RUN" == true ]]; then
    if [[ "$COPY_FILES" == true ]]; then
        warn "DRY-RUN: static files will NOT be copied."
        info "Would sync ${OLD_PROJECT_DIR}/sounds -> <volume>/sounds"
        info "Would sync ${OLD_PROJECT_DIR}/sound_images -> <volume>/images"
        info "Would sync ${OLD_PROJECT_DIR}/project_images -> <volume>/projects"
    else
        warn "DRY-RUN: direct-mount media access was pre-verified before database migration."
    fi
elif [[ "$COPY_FILES" == true ]]; then
    info "Starting static file migration..."
    FULL_VOLUME="${COMPOSE_PROJECT}_app-media-data"
    docker volume inspect "$FULL_VOLUME" >/dev/null 2>&1 || die "Docker volume ${FULL_VOLUME} not found."

    copy_to_volume "${OLD_PROJECT_DIR}/sounds" "sounds" "$FULL_VOLUME"
    copy_to_volume "${OLD_PROJECT_DIR}/sound_images" "images" "$FULL_VOLUME"
    copy_to_volume "${OLD_PROJECT_DIR}/project_images" "projects" "$FULL_VOLUME"
    success "Static file migration completed."
else
    info "Direct-mount mode enabled (default): no file copy is required because legacy media access was pre-verified before migration."
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Migration finished!${NC}"
echo -e "${GREEN}========================================${NC}"

if [[ "$DRY_RUN" == true ]]; then
    warn "This was a DRY-RUN. No data was modified."
else
    info "Run verification with: $COMPOSE_DISPLAY exec backend python scripts/migrate_from_biosounds.py --verify"
    if [[ "$RESET_TARGET" == true ]]; then
        info "Target backup saved at: $BACKUP_ROOT"
    fi
    if [[ "$MEDIA_MODE" == "direct-mount" ]]; then
        info "Legacy media access depends on recreated backend/worker bind mounts, not a plain docker compose restart."
    fi
fi
