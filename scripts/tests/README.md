# LiteLLM 출력 진단

`litellm-structured-output.sh`는 `curl`로 실제 LiteLLM Responses API를 호출해 JSON 출력 방식을 비교한다. 필요한 도구는 Bash, curl, jq이다.

```bash
export LITELLM_BASE_URL='http://localhost:4000/v1'
export LITELLM_API_KEY='your-key'
export LITELLM_MODEL='gpt-6.1-terra'

bash scripts/tests/litellm-structured-output.sh
```

URL은 LiteLLM의 API Base URL을 넣는다. `/responses`가 없으면 자동으로 붙인다. 모델은 프록시 설정의 공개 `model_name`이다. `litellm_params.model`이 `chatgpt/gpt-6.1-terra`여도 공개 이름이 `gpt-6.1-terra`라면 후자를 사용한다. 모델 기본값은 `gpt-6.1-terra`, 요청별 제한 시간은 90초이다.

```bash
# 원하는 방식 하나만 호출
bash scripts/tests/litellm-structured-output.sh schema
bash scripts/tests/litellm-structured-output.sh tool
bash scripts/tests/litellm-structured-output.sh prompt

# 응답이 느릴 때 요청별 제한 시간 조정
export LITELLM_TIMEOUT_SECONDS=180
```

| 테스트 | 전달 방식 | 검증 대상 |
| --- | --- | --- |
| `schema` | `text.format`에 strict JSON Schema 지정 | 메시지의 `output_text` |
| `tool` | 같은 스키마를 함수 `parameters`에 지정하고 `tool_choice`로 호출 지정 | `report_capital` 호출 한 건의 `arguments` |
| `prompt` | 같은 스키마를 `instructions`에 넣고 JSON 출력 요청 | 메시지의 `output_text` |

백엔드는 `tool`과 같은 함수 호출 방식으로 `submit_repair_assistance`의 인자를 읽는다. 여기서는 연결 확인용으로 작은 `report_capital` 스키마를 사용한다.

매번 무작위 `testId`를 생성한다. `schema`와 `tool`에서는 질문이나 프롬프트에 이 값을 넣지 않고 스키마로만 전달한다. 응답은 `city`, `country`, `testId`가 기대값과 정확히 일치해야 하며, 코드 블록·설명·중복 키·추가 필드·여러 JSON 값은 실패로 처리한다. 도구 호출은 인자만 검사하고 실제 함수를 실행하지 않는다.

HTTP 상태·소요 시간·모델 출력과 항목별 PASS/FAIL을 터미널에 표시한다. HTTP 200이어도 응답 상태가 `completed`가 아니거나 결과 검증에 실패하면 FAIL이다. 전체 실행에서는 한 항목이 실패해도 다음 항목을 계속 검사한다. 종료 코드는 모두 통과하면 `0`, 호출·검증 실패는 `1`, 설정·도구 준비 오류는 `2`이다.

`schema`가 실패하고 `tool`이나 `prompt`가 통과하면 해당 방식이 우회 후보가 된다. 한 번의 성공이 모든 요청에서 형식 강제를 보장하거나 프록시의 구현을 증명하지는 않는다. 각 항목은 실제 모델을 한 번 호출하므로 제공자의 사용량에 반영된다. 자동 재시도는 하지 않는다.

애플리케이션·DB·Docker는 필요하지 않으며 `.env`를 읽지 않는다. 인증 헤더와 응답의 임시 파일은 종료 시 삭제하고, 알려진 API 키는 출력에서 가린다. 고쳐야집의 전체 결과 계약이나 사진 입력을 검증하는 테스트는 아니며, 서비스 E2E는 별도로 `bash scripts/e2e/run.sh --suite api`를 실행한다.

실제 `schema=FAIL tool=PASS prompt=PASS` 사례와 릴리스별 패치 포함 여부, 백엔드 수정 내용은 [LiteLLM 구조화 출력 트러블슈팅](../../docs/etc/LiteLLM-구조화-출력-트러블슈팅.md)에 정리했다.
