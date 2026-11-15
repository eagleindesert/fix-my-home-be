#!/usr/bin/env bash
# LiteLLM의 Responses API를 직접 호출해 JSON 출력 경로를 비교한다.
set +x
set -euo pipefail

usage() {
  cat <<'HELP'
사용법: bash scripts/tests/litellm-structured-output.sh [all|schema|tool|prompt]

필수 환경변수:
  export LITELLM_BASE_URL='http://localhost:4000/v1'
  export LITELLM_API_KEY='your-key'

선택 환경변수:
  export LITELLM_MODEL='gpt-6.1-terra'  # 프록시에 등록한 공개 model_name
  export LITELLM_TIMEOUT_SECONDS=90

테스트:
  schema  text.format의 strict JSON Schema 사용
  tool    같은 스키마를 함수 parameters로 전달하고 함수 호출 지정
  prompt  같은 스키마를 instructions에 넣고 JSON 출력 요청
  all     위 세 가지 실행 (기본값)

항목마다 실제 모델을 한 번 호출한다. HTTP 200, completed 상태와 결과 JSON을
모두 검사하며, 하나라도 실패하면 종료 코드 1을 반환한다. 준비 오류는 2이다.
필요 도구: bash, curl, jq. .env나 애플리케이션 DB는 읽지 않는다.
HELP
}

die() {
  printf '[설정 오류] %s\n' "$1" >&2
  exit 2
}

test_selection="${1:-all}"
if [[ "$test_selection" == '--help' || "$test_selection" == '-h' ]]; then
  usage
  exit 0
fi
[[ $# -le 1 ]] || die '테스트 이름은 하나만 지정하세요. --help를 참고하세요.'
case "$test_selection" in
  all) test_cases=(schema tool prompt) ;;
  schema|tool|prompt) test_cases=("$test_selection") ;;
  *) die '지원하는 테스트는 all, schema, tool, prompt입니다.' ;;
esac

for dependency in curl jq; do
  command -v "$dependency" >/dev/null 2>&1 || die "$dependency 명령이 필요합니다."
done
[[ -n "${LITELLM_BASE_URL:-}" ]] || die 'LITELLM_BASE_URL을 export하세요.'
[[ -n "${LITELLM_API_KEY:-}" ]] || die 'LITELLM_API_KEY를 export하세요.'
[[ "$LITELLM_API_KEY" != *$'\n'* && "$LITELLM_API_KEY" != *$'\r'* ]] \
  || die 'API 키에는 줄바꿈을 넣을 수 없습니다.'

request_url="${LITELLM_BASE_URL%/}"
[[ "$request_url" =~ ^https?://[^/?#[:space:]]+(/[^?#[:space:]]*)?$ ]] \
  || die 'URL은 http(s) 주소여야 하며 공백·query·fragment를 포함할 수 없습니다.'
authority="${request_url#*://}"
[[ "${authority%%/*}" != *@* ]] || die '인증 정보는 URL 대신 LITELLM_API_KEY에 넣으세요.'
[[ "$request_url" == */responses ]] || request_url+='/responses'

model="${LITELLM_MODEL:-gpt-6.1-terra}"
timeout_seconds="${LITELLM_TIMEOUT_SECONDS:-90}"
[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || die '제한 시간은 양의 정수(초)여야 합니다.'

umask 077
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/fmh-litellm-test.XXXXXX")"
trap 'rm -rf -- "$work_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# 키를 curl 프로세스의 명령행 인자에 노출하지 않는다.
printf 'Authorization: Bearer %s\nContent-Type: application/json\n' "$LITELLM_API_KEY" \
  > "$work_dir/headers"

probe_id="probe-${RANDOM}-${RANDOM}"
jq -n --arg probe "$probe_id" '{
  city: "Seoul", country: "South Korea", testId: $probe
}' > "$work_dir/expected.json"

# 제공자가 오류 메시지에 키를 반사하는 경우에도 출력에서 가린다.
# JSON 문자열로 표시해 줄바꿈과 터미널 제어 문자도 이스케이프한다.
show_output() {
  jq -Rrs '
    split(env.LITELLM_API_KEY) | join("[REDACTED]")
    | if length > 1500 then .[:1500] + " ... (생략)" else . end
    | @json
  ' "$1"
}

build_request() {
  jq -n --arg model "$model" --arg mode "$1" --arg probe "$probe_id" '
    {
      type: "object", additionalProperties: false,
      properties: {
        city: {type: "string", enum: ["Seoul"]},
        country: {type: "string", enum: ["South Korea"]},
        testId: {type: "string", enum: [$probe]}
      },
      required: ["city", "country", "testId"]
    } as $schema
    | {
        model: $model, store: false, stream: false,
        instructions: "Answer the question in English.",
        input: [{role: "user", content: [{
          type: "input_text", text: "What is the capital of South Korea?"
        }]}]
      }
    | if $mode == "schema" then
        .text = {format: {
          type: "json_schema", name: "capital_probe", strict: true, schema: $schema
        }}
      elif $mode == "tool" then
        .tools = [{
          type: "function", name: "report_capital",
          description: "Submit the answer using the required fields.",
          strict: true, parameters: $schema
        }]
        | .tool_choice = {type: "function", name: "report_capital"}
      else
        .instructions += (" Return only one JSON object matching this schema. "
          + "Do not use Markdown fences or explanatory text. Schema: " + ($schema | tojson))
      end
  ' > "$work_dir/$1.request.json"
}

run_case() {
  local test_case="$1" response_file="$work_dir/$1.response" curl_report http_status seconds
  local output_file="$work_dir/$1.output" curl_exit
  printf '\n[실행] %s | POST %s\n' "$test_case" "$request_url"
  # --disable은 사용자 .curlrc의 verbose/redirect 설정이 섞이지 않게 한다.
  if curl_report="$(curl --disable --silent --show-error \
    --connect-timeout 10 --max-time "$timeout_seconds" \
    --header "@$work_dir/headers" \
    --data-binary "@$work_dir/$test_case.request.json" \
    --output "$response_file" --write-out '%{http_code} %{time_total}' \
    "$request_url" 2> "$work_dir/curl-error")"; then
    read -r http_status seconds <<< "$curl_report"
  else
    curl_exit=$?
    printf '[FAIL] %s | curl 오류=%s (연결·TLS·제한 시간 확인)\n' "$test_case" "$curl_exit"
    show_output "$work_dir/curl-error"
    return 1
  fi
  printf '[HTTP] %s | 상태=%s | 소요=%ss\n' "$test_case" "$http_status" "$seconds"
  if [[ "$http_status" != '200' ]]; then
    printf '[FAIL] %s | HTTP 200이 아닙니다. 제공자 응답:\n' "$test_case"
    show_output "$response_file"
    return 1
  fi
  if ! jq -e -s 'length == 1 and (.[0] | type == "object")' "$response_file" >/dev/null 2>&1; then
    printf '[FAIL] %s | API 응답이 단일 JSON 객체가 아닙니다:\n' "$test_case"
    show_output "$response_file"
    return 1
  fi
  if ! jq -e '.status == "completed" and (.output | type == "array")' "$response_file" >/dev/null; then
    printf '[FAIL] %s | 응답이 completed 상태가 아니거나 output 배열이 없습니다:\n' "$test_case"
    show_output "$response_file"
    return 1
  fi

  if [[ "$test_case" == 'tool' ]]; then
    if ! jq -er '
      [.output[] | select(.type == "function_call")] as $calls
      | if ($calls | length) == 1 and $calls[0].name == "report_capital"
           and ($calls[0].arguments | type) == "string"
        then $calls[0].arguments else error("Expected one report_capital call") end
    ' "$response_file" > "$output_file" 2>/dev/null; then
      printf '[FAIL] tool | report_capital 함수 호출 한 건과 arguments 문자열이 필요합니다:\n'
      show_output "$response_file"
      return 1
    fi
  else
    if ! jq -er '
      [.output[] | select(.type == "message") | .content[]?
       | select(.type == "output_text") | .text] | join("") | select(length > 0)
    ' "$response_file" > "$output_file" 2>/dev/null; then
      printf '[FAIL] %s | output_text가 없습니다:\n' "$test_case"
      show_output "$response_file"
      return 1
    fi
  fi
  printf '[모델 출력] '
  show_output "$output_file"
  # 예상 객체와 정확히 비교한다. jq가 합쳐 버리는 중복 키는 원본 스트림에서도
  # 검사한다. 이 스키마는 문자열 필드 3개이므로 값이 정확히 3번 나와야 한다.
  if ! jq -e -s --slurpfile expected "$work_dir/expected.json" \
    'length == 1 and .[0] == $expected[0]' "$output_file" >/dev/null 2>&1 \
    || ! jq --stream -e -s '[.[] | select(length == 2)] | length == 3' \
      "$output_file" >/dev/null 2>&1; then
    printf '[FAIL] %s | JSON 문법·중복 키 또는 필수 필드·값·testId가 일치하지 않습니다.\n' "$test_case"
    return 1
  fi
  printf '[PASS] %s | JSON 형식·필드·값·testId 일치\n' "$test_case"
}

printf 'LiteLLM 출력 진단 | model=%s | timeout=%ss\n' "$model" "$timeout_seconds"
printf '[기대 결과] '
jq -c . "$work_dir/expected.json"
printf '[비교] schema=text.format | tool=함수 인자 | prompt=프롬프트 JSON 지시\n'
printf '[호출] 항목당 실제 모델 1회 호출; 자동 재시도 없음\n'

failed=0
results=()
for test_case in "${test_cases[@]}"; do
  build_request "$test_case"
  if run_case "$test_case"; then
    results+=("$test_case=PASS")
  else
    results+=("$test_case=FAIL")
    failed=$((failed + 1))
  fi
done
printf '\n[최종 결과]'
printf ' %s' "${results[@]}"
printf '\nPASS는 이번 응답의 일치 여부이며, 모델의 모든 출력 형식을 보장하지는 않습니다.\n'
if ((failed > 0)); then
  exit 1
fi
