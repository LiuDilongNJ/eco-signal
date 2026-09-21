#!/usr/bin/env bash

# Run the migration entry point from an isolated container directory. The backend's
# /app/scripts path may contain read-only bind mounts in local development.
MIGRATION_RUNTIME_DIR=""

migration_runtime_error() {
    printf '[ERROR] %s\n' "$*" >&2
}

migration_runtime_warn() {
    printf '[WARN] %s\n' "$*" >&2
}

cleanup_migration_runtime() {
    local directory="${MIGRATION_RUNTIME_DIR:-}" status=0
    [[ -n "$directory" ]] || return 0

    MIGRATION_RUNTIME_DIR=""
    if [[ ! "$directory" =~ ^/tmp/ecosignal-migration\.[A-Za-z0-9]+$ ]]; then
        migration_runtime_warn "Refusing to clean unexpected migration directory: $directory"
        return 1
    fi
    if "${DOCKER_COMPOSE[@]}" exec -T backend rm -rf -- "$directory"; then
        return 0
    else
        status=$?
        migration_runtime_warn "Unable to remove temporary migration directory: $directory"
        return "$status"
    fi
}

prepare_migration_runtime() {
    local name source destination directory
    local files=(migrate_from_biosounds.py migration_audit.py)

    cleanup_migration_runtime || return 1
    for name in "${files[@]}"; do
        source="${PROJECT_ROOT}/backend/scripts/${name}"
        if [[ ! -f "$source" ]]; then
            migration_runtime_error "Required migration script is missing: $source"
            return 1
        fi
    done

    if ! directory=$("${DOCKER_COMPOSE[@]}" exec -T backend mktemp -d /tmp/ecosignal-migration.XXXXXX); then
        migration_runtime_error "Unable to create a temporary migration directory"
        return 1
    fi
    directory="${directory//$'\r'/}"
    if [[ ! "$directory" =~ ^/tmp/ecosignal-migration\.[A-Za-z0-9]+$ ]]; then
        migration_runtime_error "Backend returned an invalid temporary migration directory: $directory"
        return 1
    fi
    MIGRATION_RUNTIME_DIR="$directory"

    for name in "${files[@]}"; do
        source="${PROJECT_ROOT}/backend/scripts/${name}"
        destination="backend:${MIGRATION_RUNTIME_DIR}/${name}"
        if ! "${DOCKER_COMPOSE[@]}" cp "$source" "$destination"; then
            migration_runtime_error "Unable to copy migration script into the backend container: $name"
            cleanup_migration_runtime || true
            return 1
        fi
    done
}

run_migration_in_backend() {
    local execution_status=0 cleanup_status=0
    local compose_exec_args=()

    while [[ $# -gt 0 && "$1" != "--" ]]; do
        compose_exec_args+=("$1")
        shift
    done
    if [[ $# -eq 0 ]]; then
        migration_runtime_error "Migration command separator is missing"
        return 2
    fi
    shift

    prepare_migration_runtime || return 1
    if "${DOCKER_COMPOSE[@]}" exec -T "${compose_exec_args[@]}" backend \
        python "${MIGRATION_RUNTIME_DIR}/migrate_from_biosounds.py" "$@"; then
        execution_status=0
    else
        execution_status=$?
    fi

    cleanup_migration_runtime || cleanup_status=$?
    if [[ "$execution_status" -ne 0 ]]; then
        return "$execution_status"
    fi
    return "$cleanup_status"
}

cleanup_migration_runtime_on_exit() {
    local status=$? cleanup_status=0
    trap - EXIT
    cleanup_migration_runtime || cleanup_status=$?
    if [[ "$status" -eq 0 && "$cleanup_status" -ne 0 ]]; then
        status=$cleanup_status
    fi
    exit "$status"
}
