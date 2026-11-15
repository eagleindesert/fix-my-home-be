#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

usage() {
    printf '사용법: scripts/build-push.sh <버전> [--platform linux/arm64|linux/amd64]\n'
}

version=
platform=linux/arm64
platform_selected=false
while (( $# )); do
    case "$1" in
        --platform)
            if (( $# < 2 )) || [[ $platform_selected == true || -z $2 ]]; then
                usage >&2
                exit 2
            fi
            platform=$2
            platform_selected=true
            shift 2
            ;;
        --help|-h) usage; exit 0 ;;
        -*)
            usage >&2
            exit 2
            ;;
        *)
            if [[ -n $version ]]; then
                usage >&2
                exit 2
            fi
            version=$1
            shift
            ;;
    esac
done
if [[ ! $version =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
    usage >&2
    exit 2
fi
case "$platform" in
    linux/arm64|linux/amd64) ;;
    *) usage >&2; exit 2 ;;
esac

image_name=${IMAGE_NAME:-eagleindesert/fix-my-home-be}
builder_name="fmh-${USER:-builder}-$$"
builder_created=false
temporary=

cleanup_builder() {
    if [[ $builder_created == true ]]; then
        docker buildx stop "$builder_name" >/dev/null 2>&1 || true
        docker buildx rm "$builder_name" >/dev/null 2>&1 || true
    fi
    if [[ -n $temporary ]]; then
        rm -f -- "$temporary"
    fi
}
trap cleanup_builder EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# .env와 별개로 이 컴퓨터에서 성공한 마지막 푸시를 이미지·플랫폼별로 기록한다.
history_directory=.runtime/build-push
history_key=$(printf '%s\n%s\n' "$image_name" "$platform" | sha256sum)
history_file="$history_directory/${history_key%% *}.tag"
previous_version='기록 없음'
if [[ -f $history_file ]]; then
    IFS= read -r recorded_version < "$history_file" || true
    if [[ $recorded_version =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
        previous_version=$recorded_version
    fi
fi
mkdir -p -- "$history_directory"
temporary=$(mktemp "$history_directory/.push.XXXXXX")
printf '%s\n' "$version" > "$temporary"

docker buildx create --name "$builder_name" --driver docker-container \
    --driver-opt restart-policy=no >/dev/null
builder_created=true
docker buildx inspect --builder "$builder_name" --bootstrap
docker buildx build --builder "$builder_name" --platform "$platform" \
    --tag "$image_name:$version" --push .

mv -f -- "$temporary" "$history_file"
printf '\n푸시 완료: %s (%s)\n' "$image_name" "$platform"
printf '  이전 푸시 버전 (이 컴퓨터): %s\n' "$previous_version"
printf '  현재 푸시 버전: %s\n' "$version"
