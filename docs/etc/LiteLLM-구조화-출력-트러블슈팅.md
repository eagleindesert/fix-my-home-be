# LiteLLM 최신 정식 릴리스의 JSON 스키마 누락 트러블슈팅

사례 발생일: 2026-11-15 · 릴리스 정보 확인일: 2026-11-16

LiteLLM `v1.109.1`의 `chatgpt/` 경로가 Responses API 요청의 `text.format`을 제거해, AI 작업에서 JSON 파싱이 실패했다. 공식 수정은 이미 `main`과 개발 릴리스에 포함돼 있었지만, 확인 당시 GitHub에서 `Latest`로 지정한 정식 릴리스에는 반영되지 않은 상태였다. 배포 버전의 소스와 실제 curl 응답을 대조한 뒤, 백엔드를 함수 호출 방식으로 전환했다.

이 문서의 버전 정보는 위 확인일 기준이다. 이후 적용할 버전은 해당 태그의 변경 내역과 실제 배포 내용을 다시 확인한다.

## 발생 환경과 증상

| 항목 | 확인한 값 |
| --- | --- |
| 백엔드 클라이언트 | OpenAI Python SDK `openai==1.76.0` |
| 요청 API | `client.responses.create(...)` |
| 중계 서버 | LiteLLM `v1.109.1` |
| 공개 모델명 | `gpt-6.1-terra` |
| LiteLLM `litellm_params.model` | `chatgpt/gpt-6.1-terra` |
| 최초 발생 지점 | 실행 중인 Compose 환경을 검사하는 E2E의 실제 AI `DIAGNOSIS` 작업 |

요청은 백엔드 → OpenAI SDK → LiteLLM → ChatGPT 모델 순서로 전달된다. SDK의 `base_url`은 LiteLLM 주소를 사용한다. 모델명과 중계 서버 버전은 서로 다른 설정이다.

Compose의 DB·API·worker 준비 검사는 통과했지만 AI 작업이 `SUCCEEDED` 대신 `FAILED`로 종료됐다. 당시 worker 로그에서 확인한 핵심 필드는 다음과 같다.

```json
{"message":"job_failed","code":"BAD_REQUEST","errorType":"DomainError"}
```

E2E 최종 출력의 `FAILED | 정리=PASSED`는 테스트가 실패했고 이번 실행의 자료 삭제는 성공했다는 뜻이다. 자료 정리 성공 여부와 AI 작업 성공 여부는 별도로 판단해야 한다.

`BAD_REQUEST`는 이 사례에서 AI가 반환한 텍스트를 공용 JSON 파서로 읽다가 발생했다. HTTP 요청 자체가 400으로 거절됐다는 의미는 아니었다. 실제 진단에서는 LiteLLM이 HTTP 200을 반환했는데도 모델 출력은 JSON이 아니었다.

## 원인: 중계 과정에서 제거된 출력 설정

변경 전 [AI 제공자 코드](../../app/ai_provider.py)는 `text.format`에 `strict: true`와 결과 JSON 스키마를 넣고, 응답의 `output_text`를 JSON으로 파싱했다.

LiteLLM `v1.109.1`의 `ChatGPTResponsesAPIConfig.transform_responses_api_request()`는 `allowed_keys`에 포함된 요청 필드만 다음 서버로 전달한다. 이 목록에는 `tools`와 `tool_choice`가 있지만 `text`가 없다. 따라서 스키마가 들어 있는 `text.format`도 함께 제거된다. [v1.109.1의 해당 소스](https://github.com/BerriAI/litellm/blob/v1.109.1/litellm/llms/chatgpt/responses/transformation.py#L127-L140)

이 구현과 관찰된 응답을 대조하면 실패 과정은 다음과 같이 설명된다.

1. 백엔드가 JSON 스키마를 포함한 Responses API 요청을 보낸다.
2. LiteLLM의 `chatgpt/` 변환 과정에서 `text` 필드가 제거된다.
3. 모델에는 질문이 전달되지만 지정한 JSON 스키마는 전달되지 않는다.
4. 모델이 일반 문장으로 답하고 API는 HTTP 200을 반환한다.
5. 백엔드의 JSON 파싱이 실패하면서 worker 작업과 E2E가 실패한다.

API 응답 전체가 JSON이라는 사실과, 그 안의 모델 출력 문자열이 애플리케이션의 JSON 계약을 지킨다는 사실은 다르다. HTTP 200만 검사하면 이 문제를 발견할 수 없다.

## 최신 정식 버전에도 패치가 없었던 이유

아래 날짜는 GitHub에 표시된 릴리스·병합 날짜다.

| 시점 | 확인한 상태 | 근거 |
| --- | --- | --- |
| 2026-11-06 | `text`와 `max_output_tokens` 전달을 보완한 수정이 `main`에 병합됨 | [PR #38086](https://github.com/BerriAI/litellm/pull/38086) |
| 2026-11-07 | `v1.110.0-dev.1` 변경 내역에 #38086이 포함됨. 개발 릴리스임 | [v1.110.0-dev.1](https://github.com/BerriAI/litellm/releases/tag/v1.110.0-dev.1) |
| 2026-11-12 | `v1.109.1`이 정식 릴리스됨. 변경 내역은 `stable/1.109.x` 보안 백포트와 버전 갱신이며, 해당 태그 소스에는 `text` 누락이 남아 있음 | [v1.109.1](https://github.com/BerriAI/litellm/releases/tag/v1.109.1) |
| 2026-11-16 확인 | GitHub의 `Latest` 대상은 여전히 `v1.109.1` | [당시 Latest 릴리스](https://github.com/BerriAI/litellm/releases/tag/v1.109.1) |

정식 릴리스가 나중에 발행됐어도 다른 개발 브랜치의 모든 수정이 포함되는 것은 아니다. 이 사례에서는 `main` 병합 여부, 개발 릴리스 포함 여부, 실제 사용 중인 정식 태그 포함 여부를 각각 확인해야 했다. 단순히 “최신 버전을 사용 중”이라는 정보만으로 수정 적용 여부를 판단할 수 없었다.

`v1.110.0-dev.1`은 수정 포함을 확인한 개발 버전이다. 이 문서는 이를 정식 릴리스로 표기하거나, 모든 후속 배포 이미지의 수정 포함을 보장하지 않는다.

## curl로 재현하고 우회 경로 비교

저장소 루트에서 [진단 스크립트](../../scripts/tests/litellm-structured-output.sh)를 실행한다. Bash, curl, jq가 필요하며, 각 항목은 실제 모델을 한 번 호출한다.

```bash
export LITELLM_BASE_URL='https://litellm.example.com/v1'
export LITELLM_API_KEY='your-key'
export LITELLM_MODEL='gpt-6.1-terra'

bash scripts/tests/litellm-structured-output.sh
```

모델에는 프록시의 공개 `model_name`을 넣는다. URL에 `/responses`가 없으면 스크립트가 자동으로 붙인다. 키와 실제 서버 주소를 저장소 파일에 넣지 않고 실행 환경에서 지정한다. 옵션과 종료 코드는 [진단 도구 안내](../../scripts/tests/README.md)를 참고한다.

동일한 URL·키·모델로 요청한 실제 실행 결과는 다음과 같았다.

| 항목 | 스키마 전달 방식 | HTTP 상태 | 관찰한 결과 | 판정 |
| --- | --- | --- | --- | --- |
| `schema` | `text.format` | 200 | `The capital of South Korea is Seoul.`이라는 일반 문장 반환 | FAIL |
| `tool` | 함수 `parameters`와 `tool_choice` | 200 | 필수 필드와 실행별 `testId`가 일치하는 함수 인자 반환 | PASS |
| `prompt` | `instructions` 안에 스키마와 JSON 출력 지시 | 200 | 필수 필드와 실행별 `testId`가 일치하는 텍스트 JSON 반환 | PASS |

```text
[기대 결과] {"city":"Seoul","country":"South Korea","testId":"probe-3766-18558"}
[최종 결과] schema=FAIL tool=PASS prompt=PASS
```

`schema`와 `tool`의 무작위 `testId`는 질문에 넣지 않고 스키마로만 전달한다. 일반 상식으로 답을 맞히는 것과 스키마에 포함된 값을 돌려주는 것을 구분하기 위한 장치다. SDK를 거치지 않는 curl 호출에서도 문제가 재현됐으므로, SDK 호출 코드 외부에서도 같은 현상이 발생함을 확인했다.

한 번의 PASS는 해당 요청에서 형식이 일치했다는 근거다. 모든 모델 출력의 형식 강제나 복잡한 업무 스키마의 성공을 보장하지 않는다. 프롬프트 방식도 이번에는 성공했지만, 이 프로젝트에서는 스키마를 함수 인자로 전달하는 방식을 선택했다.

## 적용한 수정

OpenAI SDK와 Responses API는 계속 사용한다. [AI 제공자 코드](../../app/ai_provider.py)의 스키마 전달 위치와 결과 추출 경로를 변경했다.

| 항목 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 스키마 전달 | `text.format.schema` | `tools[].parameters`, `strict: true` |
| 결과 형식 지정 | `text.format` | `tool_choice`로 `submit_repair_assistance` 지정 |
| 결과 추출 | `result.output_text` | 해당 `function_call.arguments` |
| 잘못된 JSON 분류 | 공용 파서의 `BAD_REQUEST`가 작업 오류로 전달됨 | AI 출력 오류인 `AI_INVALID_OUTPUT`으로 변환 |

해당 버전의 LiteLLM이 전달하는 `tools`·`tool_choice`를 이용해 누락 경로를 우회한다. 함수 호출은 결과 제출 형식으로만 사용하고 별도의 함수를 실행하지 않는다. 기존 결과 스키마를 재사용하며, 파싱 후의 업무 계약·사진 및 자료 참조 검증도 유지한다.

응답 완료 여부, 결과 함수명, 호출이 정확히 한 건인지, 인자가 비어 있지 않은 문자열인지 확인한다. `parallel_tool_calls=False`도 요청에 포함하지만, 중계 서버가 옵션을 그대로 전달한다고 가정하지 않고 반환된 호출 수를 직접 검증한다. JSON 코드 블록·중복 키·잘못된 JSON을 임의로 보정하거나 일반 텍스트를 성공 결과로 대신 사용하지 않는다.

E2E에는 HTTP 상태와 worker 작업 상태를 구분하는 `[JOB WAIT]`·`[JOB PASS]`·`[JOB FAIL]` 출력을 추가했다. 자료 정리 후에도 작업 상태와 오류 코드를 `summary.json`에 남기고, 최종 출력에서 실패 이유를 다시 보여준다. 상세한 결과 파일 구성은 [Compose E2E 안내](../../scripts/e2e/README.md)를 참고한다.

같은 `chatgpt/` 설정에서 Chat Completions의 `response_format`으로만 바꾸는 방식도 영향을 받는다. 공식 수정 설명에 해당 변환 경로의 문제도 기록돼 있으므로, URL이나 SDK 메서드만 변경하는 것을 해결로 판단하지 않는다. [공식 수정의 재현·검증 내용](https://github.com/BerriAI/litellm/pull/38086)

## 검증 상태와 재실행

함수 호출 전환 후 코드 테스트는 `370 passed, 3 skipped`였다. 건너뛴 3개는 `FMH_TEST_POSTGRES_URL`이 필요한 실제 PostgreSQL 테스트다. SDK 요청의 함수 스키마·사진 입력 보존과 함수 호출 누락·중복·잘못된 이름·미완료 응답·잘못된 JSON 거부를 확인했다.

실제 LiteLLM 진단에서 확인된 것은 위의 작은 스키마에 대한 `tool`과 `prompt` 성공이다. 변경된 백엔드의 전체 결과 계약과 사진 입력을 사용하는 Compose E2E 통과는 아직 별도 확인이 필요한 상태다. 백엔드 변경을 이미지에 반영한 뒤 다음 순서로 검사한다.

```bash
./scripts/build-start.sh
bash scripts/e2e/run.sh --suite api
```

실행 후 AI 작업의 `SUCCEEDED`, 시나리오별 결과, 자료 정리 상태를 함께 확인한다. 백엔드 재빌드는 이 프로젝트의 우회 코드를 반영하며, 별도로 실행 중인 LiteLLM 서버의 버전을 갱신하는 명령은 아니다.

## 이후 버전 선택 시 확인할 사항

1. 실제 실행 중인 패키지 버전과 이미지 태그·digest를 기록한다. `Latest` 표시는 조사 시점의 정보로 남긴다.
2. 수정 PR의 병합 대상과 적용하려는 릴리스의 변경 내역을 대조한다. 필요한 경우 해당 태그의 소스에서 수정 구문을 직접 확인한다.
3. 동일한 URL·키·공개 모델명으로 진단 스크립트를 실행해 HTTP 상태와 실제 출력 계약을 함께 검증한다.
4. 작은 진단 스키마가 통과한 뒤, 실제 업무 스키마·사진·worker를 포함한 E2E로 확인한다.

이 사례의 재발 방지 기준은 “최신 버전 사용” 자체가 아니라, 사용 중인 배포물에 필요한 수정이 포함돼 있고 실제 요청에서도 그 동작이 확인되는지다.
