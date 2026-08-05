#!/usr/bin/env bash
# rollback.sh - Restore either legacy ecoSound-web backups or ecoSignal target backups
#
# Usage:
#   ./rollback.sh <backup_name> [options]
#
# Arguments:
#   <backup_name>   Backup directory name, or use 'latest' for the most recent one
#
# Options:
#   --force         Skip confirmation prompt
#   --keep-new      Preserve current ecoSignal volumes when restoring a legacy backup
#   -h, --help      Show this help message
#
# Examples:
#   ./rollback.sh latest
#   ./rollback.sh backup_20260411_133000
#   ./rollback.sh target_backup_20260420_210000 --force

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${PROJECT_ROOT}/.upgrade-backup"

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

BACKUP_NAME=""
FORCE=false
KEEP_NEW=false

usage() {
    grep '^#' "$0" | grep -v '!/usr/bin' | sed 's/^# \?//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help) usage ;;
        --force) FORCE=true; shift ;;
        --keep-new) KEEP_NEW=true; shift ;;
        -*) die "Unknown option: $1" ;;
        *)
            if [[ -z "$BACKUP_NAME" ]]; then
                BACKUP_NAME="$1"
            else
                die "Unexpected argument: $1"
            fi
            shift
            ;;
    esac
done

[[ -n "$BACKUP_NAME" ]] || die "Missing required argument: <backup_name>"
[[ -d "$BACKUP_DIR" ]] || die "Backup directory not found: $BACKUP_DIR"

find_latest_backup() {
    shopt -s nullglob
    local candidates=("${BACKUP_DIR}"/backup_* "${BACKUP_DIR}"/target_backup_*)
    shopt -u nullglob
    if [[ ${#candidates[@]} -eq 0 ]]; then
        return 0
    fi
    ls -1dt "${candidates[@]}" | head -1 | xargs -I{} basename "{}"
}

read_metadata_value() {
    local key="$1"
    local file="$2"
    [[ -f "$file" ]] || return 0
    grep -E "\"${key}\"" "$file" | head -1 | cut -d'"' -f4 || true
}

resolve_old_project_dir() {
    local metadata_file="$1"
    local configured
    configured="$(read_metadata_value old_project_dir "$metadata_file")"
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
    local ini_file="$1"
    local key="$2"
    [[ -f "$ini_file" ]] || return 0
    grep -E "^${key}[[:space:]]*=" "$ini_file" | tail -1 | sed -E "s/^[^=]+= *'?([^']*)'?.*/\1/" || true
}

parse_legacy_compose_port() {
    local compose_file="$1"
    [[ -f "$compose_file" ]] || return 0
    grep -E '^[[:space:]]*-[[:space:]]*[0-9]+:80' "$compose_file" | head -1 | sed -E 's/.*- *([0-9]+):80/\1/' || true
}

parse_legacy_db_port() {
    local compose_file="$1"
    [[ -f "$compose_file" ]] || return 0
    grep -E '^[[:space:]]*-[[:space:]]*[0-9]+:3306' "$compose_file" | head -1 | sed -E 's/.*- *([0-9]+):3306/\1/' || true
}

target_volume_name() {
    local suffix="$1"
    local full_name="${STACK_NAME:-full-stack-ecoSignal}_${suffix}"
    if docker volume inspect "$full_name" >/dev/null 2>&1; then
        printf '%s\n' "$full_name"
        return
    fi
    printf '%s\n' "$suffix"
}

wait_for_pg() {
    local attempts=30
    while (( attempts > 0 )); do
        if docker compose exec -T db pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ecosignal}" >/dev/null 2>&1; then
            return 0
        fi
        attempts=$((attempts - 1))
        sleep 2
    done
    return 1
}

wait_for_legacy_mysql() {
    local container_id="$1"
    local user="$2"
    local password="$3"
    local database="$4"
    local attempts=30
    while (( attempts > 0 )); do
        if docker exec "$container_id" mysql -u"$user" -p"$password" -e "USE \`$database\`;" >/dev/null 2>&1; then
            return 0
        fi
        attempts=$((attempts - 1))
        sleep 2
    done
    return 1
}

confirm_or_exit() {
    [[ "$FORCE" == true ]] && return 0
    echo ""
    read -r -p "Type 'yes' to continue: " REPLY
    [[ "$REPLY" =~ ^[Yy][Ee][Ss]$ ]] || {
        info "Rollback cancelled."
        exit 0
    }
}

restore_target_volume_from_tar() {
    local volume_name="$1"
    local archive_path="$2"
    docker volume create "$volume_name" >/dev/null
    docker run --rm \
        -v "${volume_name}:/data" \
        -v "${archive_path%/*}:/backup:ro" \
        alpine:3 \
        sh -c "rm -rf /data/* /data/.[!.]* /data/..?* 2>/dev/null || true; tar -xzf /backup/$(basename "$archive_path") -C /data"
}

detect_backup_type() {
    if [[ -f "${BACKUP_PATH}/biosounds_db.sql" ]]; then
        printf 'legacy\n'
        return
    fi
    if [[ -f "${BACKUP_PATH}/ecosignal_db.sql" ]]; then
        printf 'target\n'
        return
    fi
    die "Unable to detect backup type for ${BACKUP_PATH}"
}

validate_backup_contents() {
    case "$BACKUP_TYPE" in
        legacy)
            [[ -f "${BACKUP_PATH}/biosounds_db.sql" ]] || die "Legacy backup is missing biosounds_db.sql: ${BACKUP_PATH}"
            ;;
        target)
            [[ -f "${BACKUP_PATH}/ecosignal_db.sql" ]] || die "Target backup is missing ecosignal_db.sql: ${BACKUP_PATH}"
            [[ -f "${BACKUP_PATH}/app-media-data.tar.gz" ]] || die "Target backup is missing app-media-data.tar.gz: ${BACKUP_PATH}"
            ;;
        *)
            die "Unsupported backup type: ${BACKUP_TYPE}"
            ;;
    esac
}

rollback_legacy_backup() {
    local metadata_file="${BACKUP_PATH}/metadata.json"
    local old_project_dir
    local old_compose_file
    local old_ini_file
    local old_db_container
    local mysql_user
    local mysql_password
    local mysql_db
    local legacy_port

    old_project_dir="$(resolve_old_project_dir "$metadata_file")"
    old_compose_file="${old_project_dir}/docker-compose.yml"
    old_ini_file="${old_project_dir}/src/config/config.ini"

    [[ -d "$old_project_dir" ]] || die "Old project directory not found: $old_project_dir"
    [[ -f "$old_compose_file" ]] || die "Missing docker-compose.yml in old project: $old_compose_file"

    mysql_user="$(parse_legacy_ini "$old_ini_file" USER)"
    mysql_password="$(parse_legacy_ini "$old_ini_file" PASSWORD)"
    mysql_db="$(parse_legacy_ini "$old_ini_file" DATABASE)"
    mysql_user="${mysql_user:-biosounds}"
    mysql_password="${mysql_password:-biosounds}"
    mysql_db="${mysql_db:-biosounds}"
    legacy_port="$(parse_legacy_compose_port "$old_compose_file")"
    legacy_port="${legacy_port:-8080}"

    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}  ecoSignal -> ecoSound-web Rollback${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    warn "This will stop the current ecoSignal stack."
    warn "It will restore legacy database and media from: ${BACKUP_NAME}"
    if [[ "$KEEP_NEW" == false ]]; then
        warn "It will delete current ecoSignal app db/media/redis/geo volumes."
    else
        warn "Current ecoSignal volumes will be preserved because --keep-new was passed."
    fi
    confirm_or_exit

    info "Stopping ecoSignal containers..."
    cd "$PROJECT_ROOT"
    docker compose down || warn "Failed to stop some ecoSignal containers"

    if [[ "$KEEP_NEW" == false ]]; then
        warn "Removing ecoSignal data volumes..."
        docker volume rm -f "$(target_volume_name app-db-data)" >/dev/null 2>&1 || true
        docker volume rm -f "$(target_volume_name app-media-data)" >/dev/null 2>&1 || true
        docker volume rm -f "$(target_volume_name geo_db_data)" >/dev/null 2>&1 || true
        docker volume rm -f "$(target_volume_name redis-data)" >/dev/null 2>&1 || true
        success "ecoSignal data volumes removed."
    fi

    info "Restoring legacy ecoSound-web backup..."
    cd "$old_project_dir"
    docker compose up -d database
    sleep 5
    old_db_container="$(docker compose ps -q database)"
    [[ -n "$old_db_container" ]] || die "Failed to start legacy database container"

    info "Recreating legacy MySQL database ${mysql_db}..."
    docker exec "$old_db_container" mysql -uroot -proot -e "DROP DATABASE IF EXISTS \`${mysql_db}\`; CREATE DATABASE \`${mysql_db}\`;" >/dev/null
    docker exec -i "$old_db_container" mysql -uroot -proot "$mysql_db" < "${BACKUP_PATH}/biosounds_db.sql"

    if ! wait_for_legacy_mysql "$old_db_container" "$mysql_user" "$mysql_password" "$mysql_db"; then
        die "Legacy MySQL did not become ready after restore"
    fi
    success "Legacy database restored."

    info "Restoring legacy media archives..."
    for archive in sounds sound_images project_images; do
        if [[ -f "${BACKUP_PATH}/${archive}.tar.gz" ]]; then
            rm -rf "${old_project_dir:?}/${archive}"
            tar -xzf "${BACKUP_PATH}/${archive}.tar.gz" -C "$old_project_dir"
        fi
    done
    success "Legacy media restored."

    if [[ -f "${BACKUP_PATH}/.env" ]]; then
        info "Restoring legacy .env..."
        cp "${BACKUP_PATH}/.env" "${old_project_dir}/.env"
    fi

    if [[ -f "${BACKUP_PATH}/docker-compose.yml" ]]; then
        info "Legacy compose snapshot is available at ${BACKUP_PATH}/docker-compose.yml"
    fi

    info "Starting legacy ecoSound-web services..."
    docker compose up -d
    sleep 10

    if docker exec "$old_db_container" mysql -u"$mysql_user" -p"$mysql_password" "$mysql_db" -e "SELECT COUNT(*) FROM collection;" >/dev/null 2>&1; then
        success "Legacy database verification passed."
    else
        warn "Legacy database verification failed."
    fi

    if curl -fsS "http://localhost:${legacy_port}" >/dev/null 2>&1; then
        success "Legacy web service is responding on port ${legacy_port}."
    else
        warn "Legacy web service did not respond on port ${legacy_port} yet."
    fi

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Legacy rollback complete${NC}"
    echo -e "${GREEN}========================================${NC}"
}

rollback_target_backup() {
    local db_volume
    local media_volume

    db_volume="$(target_volume_name app-db-data)"
    media_volume="$(target_volume_name app-media-data)"

    echo -e "${YELLOW}========================================${NC}"
    echo -e "${YELLOW}  ecoSignal Target Rollback${NC}"
    echo -e "${YELLOW}========================================${NC}"
    echo ""
    warn "This will overwrite the current ecoSignal PostgreSQL data and media volume"
    warn "using backup: ${BACKUP_NAME}"
    confirm_or_exit

    cd "$PROJECT_ROOT"
    info "Stopping ecoSignal containers..."
    docker compose down || warn "Failed to stop some ecoSignal containers"

    info "Recreating ecoSignal data volumes..."
    docker volume rm -f "$db_volume" >/dev/null 2>&1 || true
    docker volume rm -f "$media_volume" >/dev/null 2>&1 || true
    docker volume create "$db_volume" >/dev/null
    restore_target_volume_from_tar "$media_volume" "${BACKUP_PATH}/app-media-data.tar.gz"
    success "Target media volume restored."

    info "Starting PostgreSQL service..."
    docker compose up -d db
    if ! wait_for_pg; then
        die "PostgreSQL did not become ready in time"
    fi

    info "Restoring PostgreSQL backup..."
    docker compose exec -T db sh -c "psql -U \"${POSTGRES_USER:-postgres}\" -d postgres -c 'DROP DATABASE IF EXISTS \"${POSTGRES_DB:-ecosignal}\";' >/dev/null && psql -U \"${POSTGRES_USER:-postgres}\" -d postgres -c 'CREATE DATABASE \"${POSTGRES_DB:-ecosignal}\";' >/dev/null"
    docker compose exec -T db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ecosignal}" < "${BACKUP_PATH}/ecosignal_db.sql"
    success "Target PostgreSQL restored."

    info "Starting ecoSignal stack..."
    docker compose up -d
    sleep 10

    if docker compose exec -T db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-ecosignal}" -Atc "SELECT COUNT(*) FROM project;" >/dev/null 2>&1; then
        success "Target database verification passed."
    else
        warn "Target database verification failed."
    fi

    if curl -fsS http://localhost:8000/api/v1/health >/dev/null 2>&1; then
        success "ecoSignal backend health-check passed."
    else
        warn "ecoSignal backend health-check did not pass yet."
    fi

    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}  Target rollback complete${NC}"
    echo -e "${GREEN}========================================${NC}"
}

if [[ "$BACKUP_NAME" == "latest" ]]; then
    BACKUP_NAME="$(find_latest_backup)"
    [[ -n "$BACKUP_NAME" ]] || die "No backups found in $BACKUP_DIR"
    info "Using latest backup: $BACKUP_NAME"
fi

BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"
[[ -d "$BACKUP_PATH" ]] || die "Backup not found: $BACKUP_PATH"

BACKUP_TYPE="$(detect_backup_type)"
info "Detected backup type: ${BACKUP_TYPE}"
validate_backup_contents

case "$BACKUP_TYPE" in
    legacy) rollback_legacy_backup ;;
    target) rollback_target_backup ;;
    *) die "Unsupported backup type: ${BACKUP_TYPE}" ;;
esac
