#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/build-common.sh"
(( $# <= 1 )) || { printf '사용법: scripts/build-start.sh [로컬 버전]\n' >&2; exit 2; }
version=${1:-local}
valid_tag "$version"
make_builder
docker buildx build --builder "$builder_name" --platform linux/amd64 \
    --tag "$image_name:$version" --load .
IMAGE_NAME="$image_name" IMAGE_TAG="$version" IMAGE_PLATFORM=linux/amd64 \
    FMH_ENVIRONMENT=development FMH_COOKIE_SECURE=false \
    FMH_PUBLIC_ORIGIN="${FMH_LOCAL_ORIGIN:-http://localhost:8000}" \
    docker compose -f docker-compose-deployment.yaml up -d
