#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

usage() {
    printf '사용법: ./start.sh [버전 [--platform linux/arm64|linux/amd64]]\n'
}

version=
platform=
while (( $# )); do
    case "$1" in
        --platform)
            if (( $# < 2 )) || [[ -n $platform || -z $2 ]]; then
                usage >&2
                exit 2
            fi
            platform=$2
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
            if [[ ! $version =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]]; then
                printf '유효한 Docker 이미지 버전이 필요합니다.\n' >&2
                exit 2
            fi
            shift
            ;;
    esac
done
case "$platform" in
    "") ;;
    linux/arm64|linux/amd64)
        if [[ -z $version ]]; then
            usage >&2
            exit 2
        fi
        export IMAGE_PLATFORM="$platform"
        ;;
    *) usage >&2; exit 2 ;;
esac

if [[ -z $version ]]; then
    docker compose -f docker-compose-deployment.yaml up -d
else
    if [[ ! -f .env || -L .env ]]; then
        printf '.env는 심볼릭 링크가 아닌 일반 파일이어야 합니다.\n' >&2
        exit 2
    fi
    original_stamp=$(stat -c '%d:%i:%s:%y:%z' -- .env)
    temporary=$(mktemp .env.update.XXXXXX)
    trap 'rm -f -- "$temporary"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    chmod 600 "$temporary"

    # 세 파일만 복사한 서버에서도 실행할 수 있도록 Bash와 awk만 사용한다.
    # 따옴표 안의 여러 줄을 하나의 설정으로 읽고, 값은 임시 파일에만 쓴다.
    if ! LC_ALL=C awk -v tag="$version" -v platform="$platform" '
        BEGIN { ending = "\n" }

        function invalid() { failed = 1; exit 2 }

        function close_quote(fragment, i, character, escaped, remainder) {
            for (i = 1; i <= length(fragment); i++) {
                character = substr(fragment, i, 1)
                if (escaped) escaped = 0
                else if (character == "\\") escaped = 1
                else if (character == quote) {
                    remainder = substr(fragment, i + 1)
                    if (remainder !~ /^[ \t]*(#.*)?$/) invalid()
                    comment = remainder
                    if (comment ~ /^#/) comment = " " comment
                    quote = ""
                    return
                }
            }
        }

        function emit_record() {
            if (key == "IMAGE_TAG")
                printf "%sIMAGE_TAG=%s%s%s", bom, tag, comment, ending
            else if (key == "IMAGE_PLATFORM" && platform != "")
                printf "%sIMAGE_PLATFORM=%s%s%s", bom, platform, comment, ending
            else
                printf "%s", record
            record = ""
        }

        {
            line = $0
            sub(/\r$/, "", line)
            if (quote != "") {
                record = record $0 "\n"
                close_quote(line)
                if (quote == "") emit_record()
                next
            }

            bom = ""
            if (NR == 1 && sub(/^\357\273\277/, "", line))
                bom = "\357\273\277"
            ending = ($0 ~ /\r$/ ? "\r\n" : "\n")
            if (line ~ /^[ \t]*(#.*)?$/) {
                printf "%s\n", $0
                next
            }

            value = line
            sub(/^[ \t]*/, "", value)
            sub(/^export[ \t]+/, "", value)
            if (!match(value, /^[A-Za-z_][A-Za-z0-9_]*/)) invalid()
            key = substr(value, 1, RLENGTH)
            value = substr(value, RLENGTH + 1)
            sub(/^[ \t]*/, "", value)
            if (value != "" && substr(value, 1, 1) != "=") invalid()
            if (seen[key]++) invalid()
            sub(/^=[ \t]*/, "", value)
            record = $0 "\n"
            comment = ""
            quote = substr(value, 1, 1)
            if (quote == "\"" || quote == sprintf("%c", 39)) {
                close_quote(substr(value, 2))
            } else {
                quote = ""
                if (value ~ /^#/) comment = " " value
                else if (match(value, /[ \t]+#/)) comment = substr(value, RSTART)
            }
            if (quote == "") emit_record()
        }

        END {
            if (failed || quote != "") exit 2
            if (!seen["IMAGE_TAG"]) printf "IMAGE_TAG=%s%s", tag, ending
            if (platform != "" && !seen["IMAGE_PLATFORM"])
                printf "IMAGE_PLATFORM=%s%s", platform, ending
        }
    ' .env > "$temporary"; then
        printf '.env의 형식·따옴표·중복 키를 확인하세요. 원본은 변경하지 않았습니다.\n' >&2
        exit 2
    fi

    # pull 실패나 처리 중 파일 변경이 있으면 기존 배포 설정을 유지한다.
    IMAGE_TAG="$version" docker compose -f docker-compose-deployment.yaml pull
    if [[ $(stat -c '%d:%i:%s:%y:%z' -- .env) != "$original_stamp" ]]; then
        printf '처리 중 .env가 변경되었습니다. 다시 실행하세요.\n' >&2
        exit 2
    fi
    mv -f -- "$temporary" .env
    IMAGE_TAG="$version" docker compose -f docker-compose-deployment.yaml up -d
fi

address=$(docker compose -f docker-compose-deployment.yaml port be 8000)
printf '\n접속 주소 (현재 호스트):\n'
printf '  Swagger UI: http://%s/api/docs\n' "$address"
printf '  상태 확인: http://%s/health/ready\n' "$address"
