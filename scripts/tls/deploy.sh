# Shared deployment helpers; sourced by the Bash entry point.
tls_image="ecosignal-tls-tools:local"
tls_pending=false

prepare_tls_tool() {
    docker build -q -t "$tls_image" scripts/tls >/dev/null
}

tls_source() {
    docker run --rm --network none \
        --mount "type=bind,source=$tls_cert_file,target=/source/cert.pem,readonly" \
        --mount "type=bind,source=$tls_key_file,target=/source/key.pem,readonly" \
        --mount "type=bind,source=$(pwd)/.deploy/tls,target=/state" \
        "$tls_image" "$@" --domain "$domain"
}

tls_restore() {
    docker run --rm --network none --mount "type=bind,source=$(pwd)/.deploy/tls,target=/state" \
        "$tls_image" restore --domain "$domain"
}

frontend_id() { run_compose ps -q frontend; }

verify_endpoint() {
    local phase="$1" target port=443 timeout=30
    local options=()
    if [[ "$https_enabled" == true && "$https_mode" == letsencrypt ]]; then
        target="$(docker compose --project-name ecosignal-traefik -f docker-compose.traefik.yml ps -q traefik)"
        timeout=180
    else
        target="$(frontend_id)"
        if [[ "$https_enabled" == true ]]; then
            options+=(--mount "type=bind,source=$(pwd)/.deploy/tls,target=/state,readonly")
        else
            port=80
        fi
    fi
    [[ -n "$target" ]] || { echo "HTTPS/HTTP entry container is not running" >&2; return 1; }
    local args=(probe --domain "$domain" --port "$port" --timeout "$timeout")
    if [[ "$https_enabled" == false ]]; then args+=(--http); fi
    if [[ "$https_enabled" == true && "$https_mode" == static ]]; then
        args+=(--pin --cert /state/cert.pem)
    fi
    if [[ "$phase" == application ]]; then args+=(--path / --path /api/v1/health); fi
    docker run --rm --network "container:$target" "${options[@]}" "$tls_image" "${args[@]}"
}

rollback_tls() {
    tls_restore || return 1
    if [[ -n "$(frontend_id)" ]]; then
        run_compose exec -T frontend nginx -t && run_compose exec -T frontend nginx -s reload && verify_endpoint tls
    fi
}

reload_tls() {
    local target
    target="$(frontend_id)"
    if [[ -z "$target" ]] || [[ "$(docker inspect -f '{{index .Config.Labels "ecosignal.tls-mode"}}' "$target")" != static ]] || \
       [[ "$(docker inspect -f '{{index .Config.Labels "ecosignal.domain"}}' "$target")" != "$domain" ]]; then
        echo "Certificate reload requires a running static HTTPS frontend for DOMAIN" >&2
        return 1
    fi
    tls_source install
    tls_pending=true
    run_compose exec -T frontend nginx -t
    run_compose exec -T frontend nginx -s reload
    verify_endpoint tls
    tls_pending=false
    echo "TLS certificate reloaded and verified without restarting the frontend"
}

prepare_entrypoint() {
    local target directory frontend
    target="$(docker ps -aq --filter label=com.docker.compose.project=ecosignal-traefik --filter label=com.docker.compose.service=traefik)"
    if [[ -n "$target" ]]; then
        directory="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$target")"
        if [[ "$directory" != "$(pwd)" ]]; then
            echo "Existing Traefik belongs to another deployment; port handoff refused" >&2
            return 1
        fi
    fi
    if [[ "$https_enabled" == true && "$https_mode" == letsencrypt ]]; then
        frontend="$(frontend_id)"
        if [[ -n "$frontend" ]] && docker inspect -f '{{json .HostConfig.PortBindings}}' "$frontend" | grep -Eq '"HostPort":"(80|443)"'; then
            docker stop "$frontend" >/dev/null
        fi
        docker network inspect traefik-public >/dev/null 2>&1 || docker network create traefik-public
        docker compose --project-name ecosignal-traefik -f docker-compose.traefik.yml up -d
    elif [[ -n "$target" ]]; then
        docker stop "$target" >/dev/null
    fi
}
