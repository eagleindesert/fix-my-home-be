#!/usr/bin/env bash
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Support both the repository layout and a standalone deployment directory.
if [[ -f "$script_dir/docker-compose-deployment.yaml" ]]; then
    cd -- "$script_dir"
else
    cd -- "$script_dir/../.."
fi

if (( $# == 0 )); then
    docker compose -f docker-compose-deployment.yaml up -d
else
    if (( $# != 1 )) || [[ ! $1 =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
        printf '사용법: %s [이미지 버전]\n' "$0" >&2
        exit 2
    fi
    [[ -f .env ]] || { printf '.env 파일이 필요합니다.\n' >&2; exit 2; }
    version=$1
    # A failed pull must leave the previously selected deployment version intact.
    IMAGE_TAG="$version" IMAGE_PLATFORM=linux/arm64 \
        docker compose -f docker-compose-deployment.yaml pull
    temporary=$(mktemp .env.update.XXXXXX)
    trap 'rm -f -- "$temporary"' EXIT
    chmod 600 "$temporary"
    awk -v tag="$version" '
        !/^[[:space:]]*(export[[:space:]]+)?(IMAGE_TAG|IMAGE_PLATFORM)[[:space:]]*=/ { print }
        END { print "IMAGE_TAG=" tag; print "IMAGE_PLATFORM=linux/arm64" }
    ' .env > "$temporary"
    mv -f -- "$temporary" .env
    # Persisted values also apply to a subsequent direct docker compose invocation.
    IMAGE_TAG="$version" IMAGE_PLATFORM=linux/arm64 \
        docker compose -f docker-compose-deployment.yaml up -d
fi

address=$(docker compose -f docker-compose-deployment.yaml port be 8000)
printf '\n접속 주소 (현재 호스트):\n'
printf '  Swagger UI: http://%s/api/docs\n' "$address"
printf '  상태 확인: http://%s/health/ready\n' "$address"
