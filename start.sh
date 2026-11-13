#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if (( $# == 0 )); then
    exec docker compose -f docker-compose-deployment.yaml up -d
fi
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
