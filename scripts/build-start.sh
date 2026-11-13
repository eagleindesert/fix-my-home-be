#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/build-common.sh"
(( $# <= 1 )) || { printf '사용법: scripts/build-start.sh [로컬 버전]\n' >&2; exit 2; }
if (( $# == 1 )); then
    valid_tag "$1"
    export LOCAL_IMAGE_TAG="$1"
fi
make_builder
# Compose builds and loads the image using this invocation's temporary builder.
BUILDX_BUILDER="$builder_name" COMPOSE_BAKE=true \
    docker compose -f docker-compose.yaml up -d --build
