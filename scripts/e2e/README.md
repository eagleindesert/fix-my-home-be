# Compose E2E

`docker-compose.yaml`로 실행 중인 PostgreSQL 17·API·worker를 대상으로 실제 HTTP 요청을 보냅니다. 마이그레이션 완료, API와 DB의 healthcheck, 애플리케이션 이미지 일치, API와 worker의 공유 파일 볼륨을 먼저 확인합니다. 테스트 실행기는 컨테이너나 볼륨의 생명주기를 변경하지 않습니다.

## 실행

저장소 루트에서 의존성과 로컬 Compose 환경을 준비합니다. 환경변수 설정은 루트 [README](../../README.md)의 빌드와 배포 절차를 따릅니다.

```bash
uv sync --locked
docker compose -f docker-compose.yaml up -d --build
docker compose -f docker-compose.yaml ps -a

# db와 be가 healthy, migrate가 Exited (0), worker가 Up이면 실행합니다.
bash scripts/e2e/run.sh
```

대화형 터미널에서는 `1) 전체 API`, `2) 기획 시나리오` 중 하나를 선택합니다. CI처럼 입력 터미널이 없으면 `api`가 기본입니다. 다음과 같이 명시할 수도 있습니다.

```bash
bash scripts/e2e/run.sh --suite api
bash scripts/e2e/run.sh --suite scenarios

# 프로젝트 이름을 바꿔 띄운 경우
bash scripts/e2e/run.sh --project my-e2e-stack --suite api

# 원격 Docker context 또는 프록시를 통해 접속하는 경우 (/v1은 붙이지 않습니다)
bash scripts/e2e/run.sh --suite scenarios --base-url http://localhost:8000

# 결과 디렉터리는 비어 있어야 합니다.
bash scripts/e2e/run.sh --suite api --output /tmp/fmh-e2e-result
```

기본 접속 주소는 `be` 컨테이너의 공개 포트에서 찾습니다. `--base-url`을 지정하면 선택한 Compose 스택으로 연결되는 주소를 사용해야 합니다. 로그인할 테스트 계정은 해당 스택 안에서 생성합니다. Docker CLI·daemon 접근 권한과 호스트의 uv·프로젝트 의존성이 필요합니다. 실행기가 `.env`나 컨테이너의 전체 환경변수를 출력하지 않습니다.

## 검증 범위

| 모드 | 목적 |
| --- | --- |
| `api` | 회원가입을 포함해 실행 서버의 OpenAPI에 등록된 전체 업무 API를 호출하고 응답·상태 변화를 검증합니다. 호출하지 못한 API가 남으면 실패합니다. |
| `scenarios` | 접수부터 경로 선택, 기사 탐색·상담·견적·예약, 전달본·PDF, 작업 완료·인계 및 중단 흐름을 사용자의 순서로 확인합니다. 실행 결과에 실제 호출 범위를 표시합니다. |

`api`는 8개 흐름으로 전체 API를 확인합니다. `scenarios`는 여기에 긴급 안내·미지원 지역, 자가 해결, 제조사 AS, 외부 직접 연락을 더해 12개 흐름을 실행합니다.

두 모드 모두 실제 로그인 세션·사진 업로드·파일 조회·권한을 사용합니다. PDF와 삭제 등 비동기 작업은 컨테이너의 worker가 처리하고, HTTP polling으로 최종 상태를 확인합니다. SQLite, TestClient, 인프로세스 worker 또는 모의 AI 서버를 E2E 실행에 사용하지 않습니다.

AI는 `DIAGNOSIS` 작업을 검사합니다. 키와 모델이 설정되어 있으면 설정된 실제 제공자를 호출하고 성공을 요구합니다. 이 경우 제공자의 사용 비용이 발생할 수 있습니다. 키나 모델이 없으면 `AI_NOT_CONFIGURED` 실패를 명시적으로 검증합니다. 이 결과를 AI 성공 경로의 통과로 표시하지 않습니다. 다른 AI 작업 종류와 모델 품질 평가는 이 스크립트의 검증 범위에 포함하지 않습니다. 일반 HTTP 제한 시간은 20초, 작업 polling 제한 시간은 180초이며 `--http-timeout`, `--poll-timeout`으로 조절합니다.

AI 결과는 Responses API의 `submit_repair_assistance` 함수 호출 한 건에서 `arguments`를 읽습니다. 결과 스키마는 함수의 `parameters`에 `strict: true`로 전달하며, 기존 결과 계약·참조 검증도 적용합니다. `AI_INVALID_OUTPUT`은 응답 미완료, 함수 호출 누락·중복·이름 불일치, 잘못된 JSON 인자 등에 사용됩니다. 예상하지 못한 AI 실패는 테스트 실패로 처리하며 오류 코드와 상태를 보존합니다. 제공자 연결은 [curl 출력 진단](../tests/README.md)의 `tool` 항목으로 먼저 확인할 수 있습니다.

## 터미널과 결과 파일

터미널에는 환경 확인 → 자료 준비 → 시나리오와 단계 → HTTP 메서드·경로·상태 코드 → 검증 결과 → 자료 정리 순서로 출력합니다. 종료 요약에서 실패 단계와 미실행 항목을 확인할 수 있습니다. 요청 본문·비밀번호·쿠키·토큰은 출력하지 않습니다.

출력 형식 예시입니다. 예상한 오류 응답도 계약대로 반환되면 통과로 표시합니다.

```text
[시나리오 1/8] 서비스 상태·API 명세·회원가입·로그인·권한 (...)
  [HTTP PASS] POST /v1/auth/signup -> 201 (expected 201)
  [HTTP PASS] POST /v1/auth/signup -> 409 (expected 409)
  [PASS] POST /v1/auth/signup: expected error code ACCOUNT_EXISTS
```

기본 결과 위치는 `.runtime/e2e/<UTC 시각>-<실행 ID>/`입니다.

| 파일 | 내용 |
| --- | --- |
| `terminal.log` | 터미널에 출력된 진행 상황과 결과 |
| `http-calls.jsonl` | API별 메서드·경로 양식·응답 상태·소속 시나리오; 본문·쿠키 제외 |
| `summary.json` | HTTP 시나리오·API 호출 범위와 `jobs`·`ai`의 기대 상태·실제 상태·오류 코드; HTTP 실행 전 실패하면 생성되지 않음 |
| `run-result.json` | Compose 준비 검사부터 자료 정리까지 포함한 최종 상태·종료 코드 |

HTTP 테스트나 자료 정리 중 하나라도 실패하면 종료 코드가 0이 아닙니다. Docker 접근이나 환경 확인에 실패하면 테스트를 시작하지 않고 실패로 종료합니다.

작업 상태는 `[JOB WAIT]`, `[JOB PASS]`, `[JOB FAIL]`로 표시합니다. 조회 API가 HTTP 200을 반환해도 작업 자체가 실패하면 `[JOB FAIL]`로 표시하고, 정리가 끝난 뒤 `[실패 원인]`을 다시 출력합니다. 테스트 자료를 삭제해도 오류 코드와 상태는 결과 파일에 남으며, AI 응답 원문은 저장하지 않습니다.

## 테스트 자료

준비 도구는 실행 중인 `be` 안에서 동작하며, 무작위 실행 ID에 속한 계정·가상 지역·검증용 기준 자료·합성 사진을 준비합니다. API에 없는 기사 계정 발급·대표 위치 설정과 삭제 재시도의 선행 실패 상태만 사전 구성합니다. 이후 테스트 동작은 HTTP를 사용합니다. 준비·정리는 development/test 환경과 PostgreSQL 17에서만 허용합니다.

성공·실패·일반적인 중단 시 모두 이번 실행 자료만 정리합니다. 컨테이너, 스키마, 볼륨 및 다른 사용자의 자료는 유지합니다. 처리 중인 작업이 남거나 다른 계정 자료가 테스트 자원을 참조하면 정리를 중단하고 실패를 표시합니다. 작업이 끝난 뒤 기록된 실행 ID로 정리를 다시 실행할 수 있습니다.

```bash
# 같은 Compose 프로젝트의 be에서 실행합니다.
docker compose -f docker-compose.yaml exec -T be \
  uv run --no-project --no-sync --no-env-file --python /usr/local/bin/python \
  python - cleanup e2e-여기에기록된32자리실행ID < scripts/e2e/fixtures.py
```

`--keep-data`를 주면 종료 시 남아 있는 계정·기준 자료 등을 보존합니다. 시나리오 자체에서 삭제 API 검증을 마친 자료는 복구하지 않습니다. 임시 계정 비밀번호가 담긴 로컬 파일은 이 옵션과 관계없이 실행 종료 시 삭제합니다. 강제 종료(SIGKILL)처럼 정리 코드가 실행되지 못한 경우에는 결과 디렉터리의 `.credentials.json`도 제거해야 합니다.

`tests/test_e2e_scripts.py`는 실행기의 실패 처리·정리 동작을 검사하는 단위 테스트입니다. 이 테스트 통과만으로 Compose E2E가 통과한 것은 아닙니다.
