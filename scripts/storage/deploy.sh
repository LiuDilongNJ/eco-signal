#!/usr/bin/env bash

check_build_space() {
    local docker_root capacity total_kib free_kib reserve_kib
    docker_root="$(docker info --format '{{.DockerRootDir}}')"
    if [[ -z "$docker_root" ]]; then
        echo "ERROR: Unable to locate Docker storage" >&2
        return 1
    fi
    capacity="$(docker run --rm --network none --mount "type=bind,source=${docker_root},target=/docker,readonly" alpine:3.22 sh -c 'df -Pk /docker | tail -1')"
    read -r total_kib free_kib <<<"$(awk '{print $2, $4}' <<<"$capacity")"
    if [[ ! "$total_kib" =~ ^[0-9]+$ || ! "$free_kib" =~ ^[0-9]+$ || "$total_kib" -eq 0 ]]; then
        echo "ERROR: Unable to read Docker filesystem capacity" >&2
        return 1
    fi
    reserve_kib=$((total_kib / 10))
    if (( reserve_kib < 5242880 )); then reserve_kib=5242880; fi
    echo "Docker storage: total=${total_kib} KiB free=${free_kib} KiB required=${reserve_kib} KiB"
    if (( free_kib < reserve_kib )); then
        echo "ERROR: Insufficient Docker storage; release space before building" >&2
        return 1
    fi
}

cleanup_deployment_storage() {
    if docker image prune --help 2>&1 | grep -q -- '--filter'; then
        docker image prune --force --filter "label=org.ecosignal.project=${project_name}" || echo "WARNING: Project image cleanup failed" >&2
    else
        echo "WARNING: Filtered image cleanup is unsupported; skipping" >&2
    fi
    if [[ "$prune_build_cache" == true ]]; then
        echo "WARNING: Build cache cleanup affects this Docker builder, including other projects" >&2
        if docker builder prune --help 2>&1 | grep -q -- '--keep-storage'; then
            docker builder prune --force --filter until=168h --keep-storage 20GB || echo "WARNING: Build cache cleanup failed" >&2
        else
            echo "WARNING: Bounded build cache cleanup is unsupported; skipping" >&2
        fi
    fi
    return 0
}
