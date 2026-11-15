#!/usr/bin/env bash
# run.sh에서 source하는 HTTP·검증 공통 함수. 로그인 본문과 쿠키는 출력하지 않는다.

die() {
    printf '\nFAIL: %s\n' "$*" >&2
    exit 1
}

json() { jq -cn "$@"; }
value() { jq -er "$1" "$RESPONSE_FILE"; }
data() { jq -c '.data' "$RESPONSE_FILE"; }
config_value() { jq -er "$1" "$CONFIG"; }

choose_login_mode() {
    [[ $LOGIN_MODE == choose ]] || return 0
    local selection
    printf '\n계정 준비 방식\n  1) 랜덤 계정 3개 회원가입\n  2) 기존 계정 3개 직접 입력\n' >&2
    printf '전체 시나리오는 전용 기사 계정의 프로필과 일정을 변경합니다.\n' >&2
    while :; do
        printf '선택 [1/2]: ' >&2
        IFS= read -r selection || die '계정 선택 입력이 종료되었습니다.'
        case "$selection" in
            1) LOGIN_MODE=random; return ;;
            2) LOGIN_MODE=prompt; return ;;
            *) printf '1 또는 2를 입력하세요.\n' >&2 ;;
        esac
    done
}

prompt_credentials() {
    local actor=$1 label login_id= password=
    case "$actor" in
        user) label=사용자 ;;
        other) label='다른 사용자' ;;
        technician) label=기사 ;;
        *) die '알 수 없는 로그인 계정 종류입니다.' ;;
    esac
    while [[ -z $login_id ]]; do
        printf '%s 로그인 ID: ' "$label" >&2
        IFS= read -r login_id || die '로그인 ID 입력이 종료되었습니다.'
    done
    while [[ -z $password ]]; do
        printf '%s 비밀번호: ' "$label" >&2
        if ! IFS= read -rs password; then
            printf '\n' >&2
            die '비밀번호 입력이 종료되었습니다.'
        fi
        printf '\n' >&2
    done
    # 민감한 값을 jq 인자나 환경변수로 전달하지 않는다.
    printf '%s\0%s' "$login_id" "$password" |
        jq -Rsc 'split("\u0000") | {loginId:.[0],password:.[1]}'
}

new_credentials() {
    local actor=$1 suffix password
    suffix=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
    password=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
    [[ ${#suffix} == 16 && ${#password} == 48 ]] || die '랜덤 계정 정보 생성에 실패했습니다.'
    printf '%s\0%s' "e2e-$suffix-$actor" "$password" |
        jq -Rsc 'split("\u0000") | {loginId:.[0],password:.[1]}'
}

register_account() {
    local actor=$1 credentials=$2 role=USER body
    if [[ $actor == technician ]]; then role=TECHNICIAN; fi
    body=$(printf '%s' "$credentials" | jq -c --arg role "$role" --argjson region "$REGION" '
        . + {role:$role} + if $role == "TECHNICIAN" then {regionId:$region.regionId} else {} end')
    request "$actor" POST /auth/signup 201 "$body"
    assert_json '.data.activeRole == "USER" and (.data.availableRoles | index("USER") != null)' '회원가입 후 사용자 세션'
}

check_signup() {
    local credentials
    credentials=$(new_credentials signup)
    register_account anonymous "$credentials"
}

skip_success_endpoint() {
    local endpoint=$1 reason=$2
    jq --arg endpoint "$endpoint" --arg reason "$reason" \
        '. + [{endpoint:$endpoint,reason:$reason}] | unique_by(.endpoint)' \
        "$RUN_DIR/skipped.json" > "$RUN_DIR/skipped.tmp"
    mv -- "$RUN_DIR/skipped.tmp" "$RUN_DIR/skipped.json"
    printf 'SKIP 성공 경로: %s — %s\n' "$endpoint" "$reason"
}

assert_json() {
    local expression=$1 description=$2
    shift 2
    jq -e "$@" "$expression" "$RESPONSE_FILE" >/dev/null || die "$description"
    ASSERTIONS=$((ASSERTIONS + 1))
}

assert_error() {
    local code=$1
    assert_json '.code == $code and (.message | type == "string")' "오류 코드: $code" --arg code "$code"
}

request() {
    local actor=$1 method=$2 path=$3 expected=$4 body=${5:-}
    shift 4
    if (( $# )); then shift; fi
    local url endpoint status code
    local -a options=()
    CALL_COUNT=$((CALL_COUNT + 1))
    LAST_REQUEST="$method $path"
    case "$path" in
        /health/*|/openapi.json|/docs|/docs/oauth2-redirect)
            url="$APP_URL$path"
            endpoint="$method $path"
            ;;
        *)
            url="$BASE_URL$path"
            endpoint=$(jq -er --arg method "$method" --arg path "${path%%\?*}" '
                [.[] | select(.method == $method)
                    | select((.path | gsub("\\{[^}]+\\}"; "[^/]+")
                        | "^" + . + "$") as $pattern | $path | test($pattern))
                    | .method + " " + .path]
                | if length == 1 then .[0] else error("엔드포인트 매칭 실패") end
            ' "$RUN_DIR/endpoints.json") || die "OpenAPI 경로 확인 실패: $LAST_REQUEST"
            ;;
    esac
    if [[ $actor != anonymous ]]; then
        options+=(--cookie "$COOKIE_DIR/$actor" --cookie-jar "$COOKIE_DIR/$actor")
    fi
    if [[ $method != GET ]]; then
        options+=(--header "Origin: $ORIGIN")
        options+=(--header "Idempotency-Key: \"${IDEMPOTENCY_KEY:-$RUN_ID-$CALL_COUNT}\"")
    fi
    if [[ -n $body ]]; then
        printf '%s' "$body" > "$RUN_DIR/request-body.json"
        options+=(--header 'Content-Type: application/json' --data-binary "@$RUN_DIR/request-body.json")
    fi
    # curlrc·자동 재시도·리다이렉트는 사용하지 않는다. 4xx도 본문과 함께 검증한다.
    if ! status=$(curl -q --silent --show-error --globoff \
        --connect-timeout "$HTTP_TIMEOUT" --max-time "$HTTP_TIMEOUT" \
        --request "$method" --output "$RESPONSE_FILE" --dump-header "$HEADER_FILE" \
        --write-out '%{http_code}' "${options[@]}" "$@" "$url"); then
        rm -f "$RUN_DIR/request-body.json"
        die "HTTP 연결 실패: $LAST_REQUEST"
    fi
    rm -f "$RUN_DIR/request-body.json"
    jq -cn --argjson number "$CALL_COUNT" --arg endpoint "$endpoint" \
        --arg path "$path" --arg expected "$expected" --arg actual "$status" \
        '{number:$number, endpoint:$endpoint, path:$path,
          expected:($expected|tonumber), status:($actual|tonumber), passed:($actual==$expected)}' \
        >> "$RUN_DIR/results.jsonl"
    if [[ $status != "$expected" ]]; then
        code=$(jq -r '.code // "응답 본문 확인 필요"' "$RESPONSE_FILE" 2>/dev/null || true)
        die "$LAST_REQUEST: 예상 HTTP $expected, 실제 $status ($code)"
    fi
    if [[ $status == 204 ]]; then
        [[ ! -s $RESPONSE_FILE ]] || die "204 응답에 본문이 있습니다."
    elif [[ $status -ge 400 ]]; then
        assert_json '(.code | type == "string") and (.retryable | type == "boolean")' '오류 응답 형식'
    elif [[ $path != /health/* && $path != /openapi.json && $path != /docs* \
        && $path != /media/* && $path != /pdf-jobs/*/content ]]; then
        assert_json 'type == "object" and has("data") and .data != null' '성공 응답 data 형식'
    fi
    printf 'PASS %3d  %-5s %-62s %s\n' "$CALL_COUNT" "$method" "$path" "$status"
}

login() {
    local actor=$1 credentials session login_id role=USER
    case "$LOGIN_MODE" in
        prompt) credentials=$(prompt_credentials "$actor") ;;
        random)
            credentials=$(new_credentials "$actor")
            register_account "$actor" "$credentials"
            ;;
        config) credentials=$(config_value ".accounts.$actor | tojson") ;;
        *) die '알 수 없는 로그인 방식입니다.' ;;
    esac
    login_id=$(printf '%s' "$credentials" | jq -r '.loginId')
    request "$actor" POST /auth/login 200 "$credentials"
    unset credentials
    assert_json '.data.accountId | type == "string" and length > 0' '로그인 계정 ID'
    [[ -s $COOKIE_DIR/$actor ]] || die '세션 쿠키가 저장되지 않았습니다.'
    grep -Eiq '^set-cookie:.*; HttpOnly' "$HEADER_FILE" || die '세션 쿠키 HttpOnly 속성 누락'
    grep -Eiq '^set-cookie:.*; SameSite=lax' "$HEADER_FILE" || die '세션 쿠키 SameSite 속성 누락'
    if [[ $actor == technician ]]; then role=TECHNICIAN; fi
    assert_json '.data.availableRoles | index($role) != null' \
        "계정에 필요한 역할이 없습니다: $role" --arg role "$role"
    if [[ $(value '.data.activeRole') != "$role" ]]; then
        request "$actor" PATCH /auth/role 200 "$(json --arg role "$role" '{role:$role}')"
    fi
    session=$(data)
    case "$actor" in
        user) SESSION_USER=$session ;;
        other) SESSION_OTHER=$session ;;
        technician) SESSION_TECHNICIAN=$session ;;
    esac
    jq --arg actor "$actor" --arg login "$login_id" --argjson session "$session" \
        '.[$actor] = {loginId:$login,accountId:$session.accountId,availableRoles:$session.availableRoles}' \
        "$RUN_DIR/accounts.json" > "$RUN_DIR/accounts.tmp"
    mv -- "$RUN_DIR/accounts.tmp" "$RUN_DIR/accounts.json"
}

find_page_item() {
    local actor=$1 path=$2 predicate=$3 description=$4
    shift 4
    local page_path=$path cursor separator='?' seen='|'
    if [[ $path == *\?* ]]; then separator='&'; fi
    while :; do
        request "$actor" GET "$page_path" 200
        if jq -e "$@" "any(.data.items[]; $predicate)" "$RESPONSE_FILE" >/dev/null; then
            ASSERTIONS=$((ASSERTIONS + 1))
            return
        fi
        cursor=$(jq -r '.data.nextCursor // empty' "$RESPONSE_FILE")
        [[ -n $cursor ]] || die "$description: 목록에서 해당 자료를 찾을 수 없습니다."
        [[ $seen != *"|$cursor|"* ]] || die "$description: 커서가 반복되었습니다."
        seen="$seen$cursor|"
        cursor=$(jq -rn --arg cursor "$cursor" '$cursor | @uri')
        page_path="$path${separator}cursor=$cursor"
    done
}

poll_job() {
    local path=$1 wanted=$2 deadline=$((SECONDS + POLL_TIMEOUT)) status
    while :; do
        request user GET "$path" 200
        status=$(value '.data.status')
        if [[ $status == "$wanted" ]]; then return; fi
        case "$status" in
            QUEUED|RUNNING|PROCESSING) ;;
            *) die "$path: 예상 종료 상태 $wanted, 실제 $status" ;;
        esac
        (( SECONDS < deadline )) || die "$path: ${POLL_TIMEOUT}초 동안 worker 완료를 확인하지 못했습니다."
        sleep 1
    done
}

refresh_request() {
    request user GET "/requests/$REQUEST_ID" 200
    ROOT=$(data)
    ITEM=$(jq -ce --arg id "$ITEM_ID" '.workItems[] | select(.workItemId == $id)' <<< "$ROOT")
}

confirm_item() {
    refresh_request
    request user PUT "/work-items/$ITEM_ID/confirmation" 200 "$(json \
        --argjson item "$ITEM" '{expectedRevision:$item.revision,
        sourceRevision:$item.sourceRevision, fields:["PLUMBING"], confirmed:true,
        summary:{text:"E2E 누수 관찰. 원인은 현장 확인 필요", facts:[], unknowns:["원인"],
                 riskSignals:[], limitations:[], onsiteInspectionNeeded:true}}')"
    ITEM=$(data)
    assert_json '.data.reviewStatus == "CONFIRMED"' '요약 확인 상태'
}

create_delivery() {
    local purpose=$1 include_report=$2
    refresh_request
    request user POST "/work-items/$ITEM_ID/deliveries" 202 "$(json \
        --argjson item "$ITEM" --arg purpose "$purpose" --arg tech "$TECH_ID" \
        --arg photo "$PHOTO_ID" --argjson report "$include_report" '
        {sourceRevision:$item.sourceRevision,
         scope:({purpose:$purpose, photoIds:[$photo], recordIds:[], questionIds:[],
                 includeSummary:true, includeReport:$report,
                 includeQuoteContext:($purpose == "CONSULTATION")}
                + if $purpose == "CONSULTATION" then {recipientTechnicianId:$tech} else {} end),
         redactions:[{targetType:"PHOTO", resourceId:$photo, exclude:false, boxes:[[0,0,0.5,0.5]]}]}')"
    DELIVERY_ID=$(value '.data.deliveryId')
    poll_job "/deliveries/$DELIVERY_ID" READY
    assert_json '.data.metadataRemoved == true and .data.content.photos[0].media.mediaId != null' '전달본 이미지와 메타정보 제거'
    request user PUT "/deliveries/$DELIVERY_ID/confirmation" 200 "$(jq -c \
        '{expectedRevision:.data.revision, sourceRevision:.data.sourceRevision, confirmed:true}' "$RESPONSE_FILE")"
    DELIVERY=$(data)
    assert_json '.data.reviewStatus == "CONFIRMED"' '전달본 확인 상태'
}

coverage() {
    jq -n --slurpfile endpoints "$RUN_DIR/endpoints.json" \
        --slurpfile results "$RUN_DIR/results.jsonl" --slurpfile skipped "$RUN_DIR/skipped.json" '
        ($endpoints[0] | map(.method + " " + .path) | sort) as $expected |
        ([$results[] | select(.passed and .status >= 200 and .status < 300) | .endpoint] | unique) as $successful |
        ($expected - $successful) as $missing |
        {total:($expected|length), successful:($expected - $missing | length),
         missing:$missing, skipped:[$skipped[0][] | select(.endpoint as $endpoint | $missing | index($endpoint))],
         uncovered:($missing - [$skipped[0][].endpoint]),
         expectedErrors:[$results[] | select(.passed and .status >= 400) | {endpoint,status}]}
    ' > "$RUN_DIR/coverage.json"
}

finish() {
    local status=$?
    trap - EXIT ERR INT TERM
    if [[ -n ${LOCAL_PID:-} ]]; then
        kill "$LOCAL_PID" 2>/dev/null || true
        wait "$LOCAL_PID" 2>/dev/null || true
    fi
    rm -rf -- "$COOKIE_DIR" "$RUN_DIR/local"
    rm -f -- "$RUN_DIR/request-body.json" "$HEADER_FILE"
    if [[ -f $RUN_DIR/endpoints.json ]]; then coverage || status=1; fi
    jq -n --argjson status "$status" --argjson requests "$CALL_COUNT" \
        --argjson assertions "$ASSERTIONS" --arg lastRequest "$LAST_REQUEST" --arg loginMode "$LOGIN_MODE" \
        '{passed:($status==0), exitCode:$status, requests:$requests,
          assertions:$assertions, lastRequest:$lastRequest, loginMode:$loginMode}' > "$RUN_DIR/summary.json"
    if (( status == 0 )); then
        rm -f -- "$RESPONSE_FILE"
        printf '\nE2E 시나리오 성공: %s회 HTTP 호출, %s회 검증\n' "$CALL_COUNT" "$ASSERTIONS"
    else
        printf '\nE2E 실패. 마지막 요청: %s\n' "$LAST_REQUEST" >&2
    fi
    printf '실행 결과: %s\n' "$RUN_DIR"
    exit "$status"
}
