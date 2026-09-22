#!/usr/bin/env bash

# Build the migration Compose command and keep media service selection aligned
# with the services enabled by the active Compose profiles.
MIGRATION_ACTIVE_MEDIA_SERVICES=()

migration_compose_error() {
    printf '[ERROR] %s\n' "$*" >&2
}

configure_migration_compose() {
    local environment="$1" project_name="$2" media_mode="$3"

    DOCKER_COMPOSE=(docker compose --project-name "$project_name")
    if [[ "$environment" == "staging" || "$environment" == "production" ]]; then
        DOCKER_COMPOSE+=(--profile production)
    fi
    DOCKER_COMPOSE+=(-f docker-compose.yml)
    if [[ "$environment" != "staging" && "$environment" != "production" ]]; then
        DOCKER_COMPOSE+=(-f docker-compose.override.yml)
    fi
    if [[ "$media_mode" == "direct-mount" ]]; then
        DOCKER_COMPOSE+=(-f docker-compose.media-direct.yml)
    fi
}

load_active_media_services() {
    local configured_services service

    if ! configured_services=$("${DOCKER_COMPOSE[@]}" config --services); then
        migration_compose_error "Unable to resolve services from the active Docker Compose configuration."
        return 1
    fi

    MIGRATION_ACTIVE_MEDIA_SERVICES=()
    while IFS= read -r service; do
        case "$service" in
            backend|worker|worker-analysis|frontend)
                MIGRATION_ACTIVE_MEDIA_SERVICES+=("$service")
                ;;
        esac
    done <<< "$configured_services"

    if [[ ${#MIGRATION_ACTIVE_MEDIA_SERVICES[@]} -eq 0 ]]; then
        migration_compose_error "The active Docker Compose configuration contains no media services."
        return 1
    fi
}

recreate_running_media_services() {
    local media_mode="$1" service container_id
    local services=()

    for service in "${MIGRATION_ACTIVE_MEDIA_SERVICES[@]}"; do
        container_id=$("${DOCKER_COMPOSE[@]}" ps -q "$service" 2>/dev/null | head -n 1)
        if [[ -n "$container_id" ]] && [[ "$(docker inspect --format '{{.State.Running}}' "$container_id")" == "true" ]]; then
            services+=("$service")
        fi
    done

    if [[ ${#services[@]} -eq 0 ]]; then
        warn "No running media services need recreation. Future starts will use $media_mode mode."
        return 0
    fi

    info "Recreating media services for $media_mode mode: ${services[*]}"
    "${DOCKER_COMPOSE[@]}" up -d --force-recreate "${services[@]}"
    success "Media services recreated for $media_mode mode."
}
