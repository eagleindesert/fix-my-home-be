#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/build-common.sh"
(( $# == 1 )) || { printf '사용법: scripts/build-push.sh <버전>\n' >&2; exit 2; }
valid_tag "$1"
make_builder
docker buildx build --builder "$builder_name" --platform linux/arm64 \
    --tag "$image_name:$1" --push .
