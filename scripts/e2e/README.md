# 프론트엔드 관점의 API E2E

`run.sh`는 사용자·기사·다른 사용자 세션을 분리해 `curl`로 API를 호출합니다. 현재 **80개 업무 엔드포인트**의 상태 코드·응답 데이터·상태 전이·접근 권한을 검증합니다. 로컬 모드는 모두의 성공 응답을 확인하며, 외부 서버 모드는 계정 준비 방식과 사전 자료에 따라 생략한 성공 경로를 결과에 표시합니다. `/health/live`, `/health/ready`, `/openapi.json`, `/docs`, `/docs/oauth2-redirect`도 확인합니다.

## 바로 실행

Bash, curl, jq, uv와 프로젝트 의존성, PDF 렌더링용 한글 폰트가 필요합니다.

```bash
uv sync --locked
bash scripts/e2e/run.sh --local
```

로컬 모드는 빈 SQLite DB에 migration을 적용하고, 임의 포트의 `127.0.0.1` HTTP 서버와 실제 worker를 시작합니다. 기존 DB나 계정을 사용하지 않습니다. API 키 없이 동작하도록 **AI 제공자만 고정된 진단 응답으로 대체**하며, 이미지 처리·전달본·PDF·삭제는 실제 구현을 실행합니다. 성공·실패·중단 시 서버와 worker를 종료하고 임시 DB·자료·쿠키를 정리합니다.

`FMH_PDF_FONT=/절대/경로/폰트.ttf`를 지정하면 해당 폰트를 사용합니다. 미지정 시 NanumGothic, DroidSansFallbackFull, NotoSansCJK, AppleSDGothicNeo 순서로 탐색합니다. 로컬 모드는 설치된 프로젝트 환경을 `uv run --no-sync --no-env-file`로 사용하므로 의존성은 먼저 동기화하세요. 실행 위치가 저장소 밖이어도 동작합니다.

```bash
bash scripts/e2e/run.sh --list
bash scripts/e2e/run.sh --help
bash scripts/e2e/run.sh --local --output /tmp/fmh-e2e-results
```

## 개발 PC에서 배포 서버 검증

배포 서버에는 `POST /v1/auth/signup`을 포함한 최신 API와 migration, 실행 중인 worker, PDF 한글 폰트가 필요합니다. 개발 PC에서는 **Bash·curl·jq와 HTTP 접속만** 사용합니다. 서버 DB 접속이나 Python 실행은 필요하지 않습니다.

[remote.example.json](remote.example.json)을 복사하고 실제 서버의 주소·허용 Origin·승인된 기준 자료로 바꾸세요. 예제의 `REPLACE_*` 값은 자리 표시자입니다. `photoPath`에는 승인된 이미지 파일을 지정합니다. 상대 경로는 설정 파일 디렉터리를 기준으로 해석합니다.

```bash
mkdir -p .runtime
cp scripts/e2e/remote.example.json .runtime/e2e-remote.json
# .runtime/e2e-remote.json의 값과 photoPath를 실제 자료에 맞춰 편집합니다.
bash scripts/e2e/run.sh --config .runtime/e2e-remote.json --interactive --skip-health
```

시작 메뉴에서 두 방식 중 하나를 선택합니다.

```text
계정 준비 방식
  1) 랜덤 계정 3개 회원가입
  2) 기존 계정 3개 직접 입력
선택 [1/2]:
```

1번은 사용자 2명과 기사 1명의 ID·비밀번호를 무작위로 생성해 회원가입 API로 등록한 뒤 로그인합니다. 기사 가입에는 설정의 `region.regionId`를 보내 활동 지역과 출발·복귀 대표 위치를 초기화합니다. 서버에 등록된 해당 지역의 대표 위치가 `locationId`와 일치해야 합니다. 생성된 ID는 결과의 `accounts.json`에서 확인할 수 있습니다. 비밀번호는 출력하거나 결과에 저장하지 않으며 실행 후 다시 사용할 수 없습니다. 생성된 계정은 서버에 남습니다.

2번은 **사용자 → 다른 사용자 → 기사** 순서로 ID·비밀번호를 입력합니다. 비밀번호는 화면에 표시되지 않습니다. 서로 다른 계정 3개가 필요하고, 사용자 두 계정에는 `USER`, 기사 계정에는 `TECHNICIAN` 역할이 있어야 합니다. 로그인 후 필요한 활성 역할로 전환합니다. 기사 계정의 출발·복귀 대표 위치는 사전에 `locationId`로 설정되어 있어야 합니다. 프로필과 일정이 변경되므로 E2E 전용 기사 계정을 사용하세요.

메뉴를 생략하려면 `--interactive` 대신 `--random-accounts` 또는 `--prompt-login`을 지정합니다. 이 모드에서는 설정 파일의 `accounts`가 필요하지 않습니다. `--skip-health`는 외부에서 접근을 막은 상태 확인 API 두 개만 생략합니다. 저장소의 Nginx 예시가 이에 해당하며, OpenAPI·문서·업무 API 검증은 계속 수행합니다. 운영 서버의 Secure 세션 쿠키를 사용하려면 HTTPS 주소로 연결하세요.

**회원가입으로 기준 자료까지 생성되지는 않습니다.** 승인된 지역·대표 위치, 해당 위치 간 이동시간, 수량 1의 60분 작업 자료, 사진 원본 해시와 신규·수정 사례 내용 해시가 승인된 출처가 서버에 있어야 합니다. 해당 자료와 일치하는 이미지·설정 파일을 준비해야 전체 업무 흐름을 실행할 수 있습니다. 기존 계정의 예약·일정과 충돌하면 검증이 실패할 수 있습니다.

랜덤 모드에서는 새 사용자가 소유한 실패한 삭제 작업이 없으므로 삭제 재시도의 성공 경로를 생략합니다. 직접 입력 모드에서는 로그인할 사용자가 소유한 재시도 가능한 `FAILED` 작업을 `failedDeletionJobId`로 지정하면 성공 경로까지 검사합니다. 생략할 경우에도 완료된 작업의 재시도가 거부되는지는 검사합니다.

## DB에 접근 가능한 테스트 환경에서 사전 자료 생성

`fixtures.py`는 검증된 출처·모의 이동 시간·기사 대표 위치처럼 **프론트엔드 API로 생성할 수 없는 사전 자료**와 임의 비밀번호의 전용 계정 3개를 준비합니다. 개발·테스트 환경에서만 사용하는 도구입니다.

API/worker와 **같은 테스트 DB 및 파일 저장소**에 접근할 수 있는 개발 소스 체크아웃에서 실행하세요. `FMH_DATABASE_URL`, `FMH_STORAGE_DIR`, `FMH_PUBLIC_ORIGIN`은 해당 테스트 서버 설정과 맞아야 합니다. `.env`는 자동으로 읽지 않으므로 필요한 설정은 셸 환경변수로 전달합니다. `FMH_ENVIRONMENT=production`에서는 자료 생성을 거부합니다.

```bash
# 테스트 서버와 동일한 FMH_* 설정을 export한 셸에서 실행합니다.
# 출력 디렉터리는 매 실행마다 새 경로를 지정합니다.
uv run --no-env-file python -m scripts.e2e.fixtures \
  --output .runtime/e2e-fixtures-01 \
  --base-url http://localhost:8000/v1

bash scripts/e2e/run.sh --config .runtime/e2e-fixtures-01/config.json
```

설정 생성 이후 `run.sh --config`는 Bash·curl·jq만 사용하며, DB에 직접 접근하지 않습니다. 다른 머신에서 실행하려면 생성된 `config.json`과 `photo.png`를 함께 복사하고 `photoPath`를 `photo.png`로 바꾸세요. 상대 이미지 경로는 설정 파일의 디렉터리를 기준으로 해석합니다. 설정 파일에는 테스트 계정 비밀번호가 들어 있으므로 커밋하지 않습니다.

설정 파일에는 다음 값이 포함됩니다.

| 키 | 용도 |
| --- | --- |
| `baseUrl` | `/v1`까지 포함한 API 주소 |
| `origin` | 서버의 `FMH_PUBLIC_ORIGIN`과 일치하는 출처 |
| `accounts.user`, `accounts.technician`, `accounts.other` | 기본 `--config` 모드의 `loginId`, `password`. 메뉴·랜덤·직접 입력 모드에는 불필요 |
| `region`, `locationId`, `workType` | 검증된 가상 동·대표 위치·60분 작업 자료 |
| `photoPath`, `source` | 합성 이미지와 SHA-256으로 승인된 출처 |
| `case`, `updatedCase` | 각각 내용 해시가 승인된 신규·수정 사례 |
| `failedDeletionJobId` | 선택 사항. 로그인할 사용자가 소유한 재시도 가능한 실패 작업. 랜덤 모드에서는 무시 |
| `ai.expectedStatus`, `ai.expectedErrorCode` | 기대하는 AI 최종 상태와 실패 코드 |

삭제 재시도용 자료는 사전 준비 과정에서 별도 가상 요청의 삭제 작업을 `FAILED`로 만들어 둡니다. 실제 실행에서는 HTTP로 재시도를 요청하고 worker의 파일·참조 정리 완료를 확인합니다. 실행 도중 상태를 DB로 조작하지 않습니다.

전용 계정은 다른 사용처와 공유하지 마세요. 스크립트가 기사 프로필과 해당 날짜의 일정을 편집하며 테스트 프로필·사진·사례가 공개됩니다. 성공하면 이번 시나리오에서 만든 요청들과 지정된 재시도용 요청을 삭제합니다. 기존 계정의 다른 요청은 삭제하지 않습니다. 계정·기사 프로필·사례·포트폴리오·기준 자료·작업 이력은 삭제 API가 없으므로 서버에 남습니다. 실패 시에는 생성한 업무 자료도 남을 수 있습니다. fixture를 다시 준비할 때는 새 출력 디렉터리를 지정하세요.

## AI와 시간 설정

외부 서버 모드의 기본 기대값은 `SUCCEEDED`입니다. 실제 모델 호출 실패를 성공으로 간주하지 않습니다. AI를 설정하지 않은 서버의 실패 처리를 검사하려면 생성된 설정의 `ai`를 명시적으로 변경하세요.

```json
{
  "expectedStatus": "FAILED",
  "expectedErrorCode": "AI_NOT_CONFIGURED"
}
```

이 경우에도 worker는 필요하며, 실제 최종 상태와 오류 코드가 모두 일치해야 통과합니다. 고정 AI 또는 미설정 실패 모드의 통과는 실제 모델 품질 검증을 의미하지 않습니다. 이번 시나리오에서 AI 실행 유형은 `DIAGNOSIS`, 문답 동작은 `FINISH`입니다. 각 API의 모든 입력 조합·분기·동시성까지 전수 검사하지는 않습니다.

계획 시각은 실행 시점 기준 약 2시간 뒤로 잡고 15분 단위를 사용합니다. 작업 수행은 조기 시작 동의 API를 거쳐 즉시 검증하며, 서버 시간을 변경하거나 예약 시각까지 기다리지 않습니다. 실행 머신과 서버의 시계가 일치해야 합니다.

| 환경변수 | 기본값 | 설명 |
| --- | --- | --- |
| `E2E_BASE_URL` | 설정의 `baseUrl` | 외부 서버 주소 재정의. 예: `https://example.test/fixmyhome/api/v1` |
| `E2E_ORIGIN` | 설정의 `origin` | 경로 없는 허용 출처. 예: `https://example.test` |
| `E2E_HTTP_TIMEOUT` | `15` | 개별 HTTP 연결/응답 제한, 초 |
| `E2E_POLL_TIMEOUT` | `90` | 작업별 polling 제한, 초 |

`--local`은 주소를 직접 정하므로 `E2E_BASE_URL`과 `E2E_ORIGIN`을 설정하지 않습니다. HTTP 오류를 자동 재시도하거나 다른 주소로 리다이렉트하지 않으며, 멱등 재전송은 시나리오에서 명시적으로 수행합니다.

## 검증 흐름과 결과

1. 공개 정보, 선택한 모드의 회원가입·로그인·역할 전환·쿠키 유지, 비인증·권한·Origin 오류
2. 기사 프로필·포트폴리오 사진·사례·일정
3. 요청·항목·사진 교체·기록·외부 조치 결과·타임라인·사진 묶음
4. AI 접수·조회·polling·문답 종료, 사용자 요약 확인, 해결 경로·후보·관심 표시
5. 보고서 편집·확인, 마스킹 전달본·PDF 생성·파일 다운로드·타인 접근 거부
6. 상담 수락, 견적 거절·재발행, 예약 검사·확정·멱등 재전송
7. 합의 변경, 오래된 버전 거부, 조기 시작 동의·실제 시작·종료 예상 변경·중단·위치 정정
8. 별도 예약 취소, 관계 종료 후 방문 정보 비공개, 커서 페이지 이동
9. 요청 종료·삭제·실패한 삭제 재시도·로그아웃

`endpoints.txt`와 서버 OpenAPI의 메서드·경로를 비교하므로 API가 추가되거나 제거되면 실패합니다. 사전에 명시한 생략 항목 외에는 모든 엔드포인트에서 최소 한 번 기대한 2xx 응답을 받아야 통과합니다. 의도한 4xx 검증은 성공 경로 수에 포함하지 않습니다.

| 실행 방식 | 성공 경로 검증 범위 |
| --- | --- |
| `--local` | 80/80 |
| 외부 서버의 랜덤 계정 | 79/80, 실패한 삭제 재시도의 성공 경로 생략 |
| 외부 서버의 기존 계정 + 실패 삭제 작업 | 79/80, 신규 회원가입 생략 |
| 외부 서버의 기존 계정 + 실패 삭제 작업 없음 | 78/80, 위 두 경로 생략 |

`coverage.json`의 `missing`은 성공 응답 미검증 목록, `skipped`는 사유를 명시한 생략 목록, `uncovered`는 생략하지 않았는데 성공 응답을 검증하지 못한 목록입니다. `uncovered`가 있으면 실패합니다. 기존 계정 모드는 신규 계정을 추가하지 않습니다.

실행 결과는 기본적으로 `.runtime/e2e/run.XXXXXX/`에 저장합니다.

| 파일 | 내용 |
| --- | --- |
| `summary.json` | 선택한 시나리오 통과 여부, 로그인 모드, 종료 코드, 호출/검증 횟수, 마지막 요청 |
| `coverage.json` | 업무 API 총수·성공 응답 확인 수·누락/생략/미검증 목록·의도한 오류 검사 |
| `accounts.json` | 사용한 계정의 로그인 ID·계정 ID·보유 역할. 비밀번호 제외 |
| `results.jsonl` | 호출별 경로·기대/실제 HTTP 상태·상태 일치 여부 |
| `last-response` | 실패했을 때 마지막 응답. 성공하면 제거 |
| `server.log` | 로컬 모드의 서버 시작/실행 로그 |

검증 하나라도 실패하면 즉시 0이 아닌 종료 코드로 끝납니다. 선택한 시나리오의 성공 여부는 `summary.json`의 `passed`, 실제 성공 경로 수와 생략 사유는 `coverage.json`으로 확인하세요. 결과 디렉터리는 기본 권한 `0700`, 파일은 `0600`으로 만들며, 쿠키·Set-Cookie 헤더·임시 요청 본문은 종료 시 삭제합니다.

```bash
uv run --no-env-file pytest -q tests/test_e2e_scripts.py tests/test_e2e_login.py tests/test_signup.py
```

회귀 테스트는 TCP가 제한된 환경에서도 Bash 전체를 실행하도록 curl 전송부만 FIFO/TestClient로 바꿉니다. 상태나 응답을 미리 만들어 주지 않고 실제 FastAPI·DB·worker·파일 처리를 실행합니다. 네트워크·TLS·브라우저 쿠키 정책·CORS 검증은 별도로 실제 서버 또는 브라우저에서 수행해야 합니다.
