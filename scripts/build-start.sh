#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

if (( $# > 1 )); then
    printf '사용법: scripts/build-start.sh [로컬 버전]\n' >&2
    exit 2
fi
if (( $# == 1 )); then
    if [[ ! $1 =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
        printf '유효한 Docker 이미지 버전이 필요합니다.\n' >&2
        exit 2
    fi
    export LOCAL_IMAGE_TAG="$1"
fi

builder_name="fmh-${USER:-builder}-$$"
builder_created=false

cleanup_builder() {
    if [[ $builder_created == true ]]; then
        docker buildx stop "$builder_name" >/dev/null 2>&1 || true
        docker buildx rm "$builder_name" >/dev/null 2>&1 || true
    fi
}
trap cleanup_builder EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker buildx create --name "$builder_name" --driver docker-container \
    --driver-opt restart-policy=no >/dev/null
builder_created=true
docker buildx inspect --builder "$builder_name" --bootstrap

# Compose builds and loads the image using this invocation's temporary builder.
BUILDX_BUILDER="$builder_name" COMPOSE_BAKE=true \
    docker compose -f docker-compose.yaml up -d --build

address=$(docker compose -f docker-compose.yaml port be 8000)
printf '\n접속 주소 (현재 호스트):\n'
printf '  Swagger UI: http://%s/api/docs\n' "$address"
printf '  상태 확인: http://%s/health/ready\n' "$address"
