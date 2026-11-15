#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd -- "$SCRIPT_DIR/../.." && pwd)
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

usage() {
    cat <<'USAGE'
사용법:
  scripts/e2e/run.sh --local [--suite api|scenarios] [--output 디렉터리]
  scripts/e2e/run.sh --config 설정.json [--suite api|scenarios] [--output 디렉터리]
  scripts/e2e/run.sh --list

--local   임시 DB·계정·HTTP 서버·worker를 시작한다. AI는 고정 응답이다.
--config  준비된 테스트 서버를 실제 HTTP로 검증한다. 데이터가 생성·변경·삭제된다.
--suite   api: 전체 업무 API 검증 (기본값).
          scenarios: 기획서의 선택 경로·AI·경과 분석·인계·정상 완료까지 검증.
--output  결과를 보관할 상위 디렉터리 (기본: .runtime/e2e).
--list    현재 80개 업무 API 목록을 출력한다.

환경변수: E2E_BASE_URL (/v1 포함), E2E_ORIGIN, E2E_HTTP_TIMEOUT (기본 15초),
          E2E_POLL_TIMEOUT (기본 90초), FMH_PDF_FONT (로컬 PDF 한글 폰트).
사전 준비와 테스트 범위는 scripts/e2e/README.md를 참고하세요.
USAGE
}

LOCAL=false
CONFIG=
SUITE=api
OUTPUT="$PROJECT_DIR/.runtime/e2e"
while (( $# )); do
    case "$1" in
        --local) LOCAL=true; shift ;;
        --config|--output|--suite)
            (( $# >= 2 )) && [[ -n $2 && $2 != --* ]] || die "$1 값이 필요합니다."
            case "$1" in
                --config) CONFIG=$2 ;;
                --output) OUTPUT=$2 ;;
                --suite) SUITE=$2 ;;
            esac
            shift 2
            ;;
        --list) cat "$SCRIPT_DIR/endpoints.txt"; exit 0 ;;
        --help|-h) usage; exit 0 ;;
        *) usage >&2; die "알 수 없는 옵션: $1" ;;
    esac
done
[[ $SUITE == api || $SUITE == scenarios ]] || die '--suite는 api 또는 scenarios여야 합니다.'
if [[ $LOCAL == true && -n $CONFIG ]] || [[ $LOCAL == false && -z $CONFIG ]]; then
    die '--local 또는 --config 중 하나를 지정하세요.'
fi
for dependency in curl jq; do
    command -v "$dependency" >/dev/null || die "필수 명령이 없습니다: $dependency"
done
HTTP_TIMEOUT=${E2E_HTTP_TIMEOUT:-15}
POLL_TIMEOUT=${E2E_POLL_TIMEOUT:-90}
[[ $HTTP_TIMEOUT =~ ^[1-9][0-9]*$ && $POLL_TIMEOUT =~ ^[1-9][0-9]*$ ]] || die 'timeout은 양의 정수 초 단위입니다.'
mkdir -p -- "$OUTPUT"
OUTPUT=$(cd -- "$OUTPUT" && pwd)
RUN_DIR=$(mktemp -d "${OUTPUT%/}/run.XXXXXX")
RUN_DIR=$(cd -- "$RUN_DIR" && pwd)
RUN_ID="e2e-$(date -u +%Y%m%dT%H%M%S)-$$"
COOKIE_DIR="$RUN_DIR/cookies"
RESPONSE_FILE="$RUN_DIR/last-response"
HEADER_FILE="$RUN_DIR/response-headers"
mkdir -- "$COOKIE_DIR"
: > "$RUN_DIR/results.jsonl"
: > "$RUN_DIR/scenarios.jsonl"
CALL_COUNT=0 ASSERTIONS=0 LOCAL_PID= LAST_REQUEST=initialization
ACTIVE_SCENARIO=
CREATED_REQUEST_IDS=()
trap finish EXIT
trap 'printf "E2E 스크립트 오류 (줄 %s)\n" "$LINENO" >&2' ERR
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ $LOCAL == true ]]; then
    command -v uv >/dev/null || die '로컬 모드에는 uv가 필요합니다. uv가 설치되어 있지 않습니다.'
    [[ -z ${E2E_BASE_URL:-} && -z ${E2E_ORIGIN:-} ]] || die '로컬 모드에서는 E2E_BASE_URL/E2E_ORIGIN을 해제하세요.'
    (
        cd -- "$PROJECT_DIR"
        # app.main의 모듈 초기화도 임시 저장소만 사용하도록 자식 환경을 격리한다.
        for variable in "${!FMH_@}"; do
            if [[ $variable != FMH_PDF_FONT ]]; then unset "$variable"; fi
        done
        export FMH_ENVIRONMENT=test
        export FMH_DATABASE_URL="sqlite:///$RUN_DIR/local/e2e.db"
        export FMH_STORAGE_DIR="$RUN_DIR/local/media"
        export FMH_LOG_DIR="$RUN_DIR/local/logs"
        exec uv run --no-sync --no-env-file python -m scripts.e2e.local --directory "$RUN_DIR/local"
    ) > "$RUN_DIR/server.log" 2>&1 &
    LOCAL_PID=$!
    CONFIG="$RUN_DIR/local/config.json"
    deadline=$((SECONDS + 30))
    until [[ -s $CONFIG ]]; do
        kill -0 "$LOCAL_PID" 2>/dev/null || die "로컬 서버 시작 실패: $RUN_DIR/server.log"
        (( SECONDS < deadline )) || die '로컬 서버 준비 시간 초과'
        sleep 1
    done
fi
[[ -f $CONFIG ]] || die '설정 JSON 파일을 찾을 수 없습니다.'
jq -e '
    [.accounts.user, .accounts.other, .accounts.technician]
    | all(.[]; (.loginId | type == "string" and length > 0)
        and (.password | type == "string" and length > 0))
' "$CONFIG" >/dev/null || die '세 계정의 loginId/password 설정이 필요합니다.'
BASE_URL=${E2E_BASE_URL:-$(config_value '.baseUrl')}
BASE_URL=${BASE_URL%/}
ORIGIN=${E2E_ORIGIN:-$(config_value '.origin')}
[[ $BASE_URL =~ ^https?://[^/?#]+(/[^?#]*)?/v1$ && $BASE_URL != *@* ]] || die 'baseUrl은 인증 정보 없는 http(s) 주소이며 /v1로 끝나야 합니다.'
[[ $ORIGIN =~ ^https?://[^/?#]+$ && $ORIGIN != *@* ]] || die 'origin은 경로 없는 http(s) 출처여야 합니다.'
APP_URL=${BASE_URL%/v1}
PHOTO_PATH=$(config_value '.photoPath')
if [[ $PHOTO_PATH != /* ]]; then PHOTO_PATH="$(dirname -- "$CONFIG")/$PHOTO_PATH"; fi
[[ -r $PHOTO_PATH ]] || die 'photoPath의 업로드 이미지를 읽을 수 없습니다.'
REGION=$(config_value '.region | tojson')
LOCATION_ID=$(config_value '.locationId')
WORK_TYPE=$(config_value '.workType')
FAILED_DELETION_ID=$(config_value '.failedDeletionJobId')
AI_STATUS=$(config_value '.ai.expectedStatus')
[[ $AI_STATUS == SUCCEEDED || $AI_STATUS == FAILED ]] || die 'ai.expectedStatus는 SUCCEEDED 또는 FAILED여야 합니다.'
if [[ $AI_STATUS == FAILED ]]; then config_value '.ai.expectedErrorCode | select(length > 0)' >/dev/null; fi

if [[ $SUITE == scenarios ]]; then
    jq -e '[.accounts.noCaseTechnician.loginId, .accounts.noCaseTechnician.password,
        .wallPhotos.before, .wallPhotos.after, .wallPhotos.unchanged, .wallPhotos.incomparable,
        .guidance.guideId, .guidance.manufacturer, .guidance.officialUrl, .guidance.emergencyUrl,
        .emptyRegionId, .neighborLocations.before, .neighborLocations.after]
        | all(.[]; type == "string" and length > 0)' "$CONFIG" >/dev/null \
        || die '기획서 시나리오 설정이 부족합니다. 최신 fixtures.py로 새 설정을 준비하세요.'
    for variant in before after unchanged incomparable; do
        wall_path=$(config_value ".wallPhotos.$variant")
        if [[ $wall_path != /* ]]; then wall_path="$(dirname -- "$CONFIG")/$wall_path"; fi
        [[ -r $wall_path ]] || die "wallPhotos.$variant 이미지를 읽을 수 없습니다."
    done
fi

if [[ $LOCAL == true ]]; then
    deadline=$((SECONDS + 30))
    until curl -q --silent --fail --max-time 2 "$APP_URL/health/ready" >/dev/null; do
        kill -0 "$LOCAL_PID" 2>/dev/null || die '로컬 서버가 종료되었습니다.'
        (( SECONDS < deadline )) || die '로컬 서버 health 준비 시간 초과'
        sleep 1
    done
fi

# OpenAPI가 제공하는 현재 서버의 경로와 저장소의 계약을 먼저 비교한다.
request anonymous GET /openapi.json 200
jq -e '.paths | type == "object"' "$RESPONSE_FILE" >/dev/null
jq '[.paths | to_entries[] | .key as $path | .value | keys[]
    | select(. == "get" or . == "post" or . == "put" or . == "patch" or . == "delete")
    | {method:ascii_upcase, path:($path | sub("^/v1"; ""))}]' \
    "$RESPONSE_FILE" > "$RUN_DIR/endpoints.json"
jq -r '.[] | .method + " " + .path' "$RUN_DIR/endpoints.json" | LC_ALL=C sort > "$RUN_DIR/server-endpoints.txt"
LC_ALL=C sort "$SCRIPT_DIR/endpoints.txt" > "$RUN_DIR/expected-endpoints.txt"
diff -u "$RUN_DIR/expected-endpoints.txt" "$RUN_DIR/server-endpoints.txt" || die '현재 서버와 스크립트의 API 목록이 다릅니다.'

# shellcheck source=scenarios.sh
source "$SCRIPT_DIR/scenarios.sh"
if [[ $SUITE == scenarios ]]; then
    source "$SCRIPT_DIR/choice-scenarios.sh"
    source "$SCRIPT_DIR/ai-scenarios.sh"
    source "$SCRIPT_DIR/completion-scenarios.sh"
    run_plan_scenarios
else
    run_scenarios
fi
coverage
jq -e '.missing | length == 0' "$RUN_DIR/coverage.json" >/dev/null || die '성공 응답을 검증하지 못한 엔드포인트가 있습니다. coverage.json을 확인하세요.'
printf '\n업무 API 성공 경로: %s/%s\n' \
    "$(jq -r '.successful' "$RUN_DIR/coverage.json")" "$(jq -r '.total' "$RUN_DIR/coverage.json")"
