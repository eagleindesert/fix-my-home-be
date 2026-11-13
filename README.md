# 고쳐야집 Backend

FastAPI · SQLAlchemy · PostgreSQL · Alembic 기반 API와 DB 작업 큐입니다. 요구사항 v1.7, FE·BE 분업 v1.4, API v0.1의 79개 메서드·경로를 `/api/v1`에 연결했습니다. API 문서는 `/api/docs`, OpenAPI JSON은 `/api/openapi.json`입니다.

실제 서비스 자료와 검증 자료는 저장소에 포함하지 않습니다. 빈 DB에서도 로그인 계정 발급과 사진·증상 접수는 가능하며, 기사 예약에는 운영자가 검증한 지역·일정·이동 자료가 필요합니다. AI는 선택 기능이고 키·모델이 없으면 해당 작업만 실패합니다.

## 개발 환경

Python 실행과 의존성 관리는 uv를 사용합니다. 배포 기준은 CPython 3.13이며 3.12에서도 기능 테스트를 실행할 수 있습니다.

```bash
uv sync --locked
export FMH_DATABASE_URL='postgresql+psycopg2://fmh:password@localhost:5432/fmh'
uv run python -m app.migrate
uv run python -m app.admin create-account user-one --roles USER
uv run python -m app.admin create-account technician-one --roles USER TECHNICIAN
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

별도 터미널에서 작업 큐를 실행합니다.

```bash
uv run python -m app.worker
uv run pytest -q
```

애플리케이션은 `.env`를 직접 읽지 않습니다. 로컬 Python 실행에는 환경변수를 전달하고, 컨테이너 실행에는 Compose가 `.env`를 읽습니다. `FMH_TEST_POSTGRES_URL`을 테스트 전용 PostgreSQL에 지정하면 실제 DB 경합·부분 유일 인덱스 테스트도 실행합니다. 이 테스트는 임시 스키마를 생성한 뒤 제거합니다.

## 빌드와 배포

로컬 개발자는 `.env.example`을 참고해 `.env`를 준비합니다. 비밀번호와 세션 비밀값은 실제 값으로 교체하고 DB URL의 비밀번호는 URL 인코딩합니다. 서버 환경 파일은 저장소에 커밋하지 않습니다.

```bash
# x86 로컬 이미지를 만들고 로컬 Compose를 실행합니다. push하지 않습니다.
./scripts/build-start.sh local

# 로그인한 Docker Hub 계정으로 ARM64 이미지를 배포합니다. 컨테이너를 실행하지 않습니다.
./scripts/build-push.sh v0.1.0
```

기본 이미지는 `eagleindesert/fix-my-home-be`입니다. `IMAGE_NAME` 환경변수로 변경할 수 있습니다. 두 빌드 스크립트는 각 실행 전용 Buildx builder를 `restart-policy=no`로 만들고 종료 시 정지·제거합니다. 다른 builder 설정은 수정하지 않습니다.

`Dockerfile`의 모든 `RUN` 단계는 `$BUILDPLATFORM`에서 실행합니다. 대상 CPU wheel을 `uv sync --python-platform … --no-build`로 설치하고 ELF 아키텍처를 검사합니다. 프로젝트 코드는 같은 CPython 3.13 빌드 이미지에서 `.pyc`로 컴파일합니다. 최종 ARM 이미지에는 해당 wheel, `.pyc`, 설정과 한글 글꼴만 복사하며 ARM 명령을 실행하지 않습니다. 애플리케이션·worker·migration의 `.py` 소스는 최종 이미지 레이어에 포함하지 않습니다. 표준 라이브러리와 외부 패키지 소스는 제거 대상이 아닙니다. Python 바이트코드는 원본 소스 배포를 피하는 방식이며 강한 역공학 방지를 보장하지 않습니다.

Ubuntu 24.04 ARM64 VM에는 Docker Compose와 호스트 Nginx가 준비되어 있어야 합니다. 다음 세 파일만 같은 디렉토리에 복사합니다.

```text
docker-compose-deployment.yaml
.env
start.sh
```

```bash
# 인자가 없으면 아래 Compose 명령과 동일합니다.
./start.sh
docker compose -f docker-compose-deployment.yaml up -d

# 먼저 지정 버전을 pull하고, 성공한 경우 .env에 버전을 저장한 뒤 up합니다.
./start.sh v0.1.0
```

버전 없는 실행은 강제 pull·재생성을 추가하지 않습니다. 버전 지정 pull 실패 시 기존 `.env` 버전을 유지합니다. 버전은 `.env`에 저장되므로 이후 직접 실행하는 Compose 명령에도 적용됩니다. 별도로 export한 `IMAGE_TAG`·`IMAGE_PLATFORM`은 Compose의 환경변수 우선순위에 따라 `.env`보다 우선합니다.

PostgreSQL 정상 기동 → migration 성공 → API·worker 순서로 시작합니다. DB·사진·로그는 named volume에 보관합니다. API 포트는 `127.0.0.1:8000`에만 공개하고 호스트 Nginx가 포워딩합니다. [Nginx 예시](deploy/nginx.conf.example)를 기존 호스트 설정에 맞춰 적용합니다. 기본 Docker 네트워크는 `172.30.0.0/24`이며 다른 네트워크와 충돌하면 `.env`의 subnet·gateway·trusted proxy 값을 함께 바꿉니다.

## 운영 자료와 계정

기본 비밀번호가 설정된 운영 계정을 자동 생성하지 않습니다. 배포된 컨테이너에서 다음과 같이 발급합니다.

```bash
docker compose -f docker-compose-deployment.yaml exec be uv run --no-project --no-sync --python /usr/local/bin/python python -m app.admin create-account technician-one --roles USER TECHNICIAN
```

검증한 기준 자료는 JSON 번들을 표준 입력으로 전달할 수 있으므로 배포 디렉토리에 추가 파일을 둘 필요가 없습니다.

```bash
docker compose -f docker-compose-deployment.yaml exec -T be uv run --no-project --no-sync --python /usr/local/bin/python python -m app.admin import-references - < verified-reference-bundle.json
```

번들은 `version`, `reviewedBy`, `reviewedAt`, `entries`를 포함합니다. 각 entry는 `id`, `kind`, `verified: true`, `source`, `data`를 가집니다. 자료 종류는 `REGION`, `TRAVEL`, `DURATION`, `SOURCE`, `GUIDANCE`, `EMERGENCY_TRIGGER`입니다. 모의 이동·작업 시간은 양수 15분 배수로 등록하며 같은 동의 이동도 명시적으로 등록해야 합니다. 서울 전체 동 목록·검증된 공식 안내·사용 가능한 사례 사진은 운영 데이터로 준비해야 합니다. 단위 테스트의 `테스트구/테스트동`은 테스트 DB 전용 가상 자료입니다.

공개 포트폴리오용 `SOURCE.data`에는 `identifiersRemoved: true`, 검토한 사진 원본 바이트의 `assetSha256` 목록과 사례 내용의 `caseSha256` 목록을 등록합니다. 사례 해시는 `source`를 제외한 CaseContentDTO를 UTF-8 JSON으로 직렬화하여 계산합니다(`ensure_ascii=False`, 키 정렬, 공백 없는 구분자). 검토하지 않은 사진 재업로드나 사례 정정을 출처 이름만으로 공개하지 않도록 내용 해시도 검사합니다.

기사 출발·복귀 대표 위치는 다음 명령으로 설정합니다. 웹의 일정 편집 API에는 해당 입력 필드가 정의되어 있지 않아 운영 명령으로 분리했습니다.

```bash
uv run python -m app.admin set-technician-locations technician-one departure-location return-location
```

## 데이터 정합성과 접근 제어

세션 토큰은 DB에 SHA-256 해시만 저장합니다. 비밀번호는 scrypt로 검증합니다. 운영 쿠키는 Secure·HttpOnly·SameSite=Lax이며 상태 변경 요청의 Origin도 검사합니다. 소유자·활성 역할·관계별 권한은 API, 파일 조회, 재전송에서 다시 확인합니다.

요청·작업·관계 본문은 `resources`의 유형별 JSONB로, 소유자·연결 ID·상태·버전은 FK와 인덱스가 있는 열로 저장합니다. 활성 예약과 실제 진행 작업에는 부분 유일 인덱스가 있습니다. 초기 구현은 PostgreSQL advisory transaction lock으로 쓰기를 직렬화합니다. 이 방식은 교차 요청 일정 경합을 막지만 쓰기 처리량 확장에는 잠금 범위 분리가 필요합니다. 외부 AI 호출과 PDF 렌더링은 해당 잠금 밖에서 수행합니다.

자료 수정은 sourceRevision을 갱신하고 관련 AI·보고서·전달본·PDF를 재확인 대상으로 만듭니다. 삭제는 접근을 먼저 차단하고 worker가 파일과 파생 참조를 정리합니다. 완료 전에는 사진 저장 슬롯을 복구하지 않습니다. 종료된 관계에서는 상세 방문 정보와 연락처를 숨기며, 기사에게 남는 인계서는 확인된 마스킹 전달본의 종료 시점 사본입니다. 사진 속 비공개 정보는 전달 전에 사용자가 가림 영역을 지정하고 결과를 확인해야 합니다.

`/health/live`는 프로세스 생존, `/health/ready`는 DB 연결·Alembic revision·ORM 차이를 검사합니다. 운영 자동 `create_all`과 자동 downgrade는 사용하지 않습니다. 스키마 변경은 새 Alembic migration으로 반영하고 변경 전 DB 백업을 준비합니다.

HTTP 접근 로그에는 메서드, URI 경로, 상태 코드, 신뢰한 Nginx 전달 IP, userId, elapsedMs, requestId를 기록합니다. query·본문·쿠키·인증 토큰은 기록하지 않습니다. 파일은 20,000,000 Byte에서 gzip으로 회전하며 기본 10개를 보관합니다. API와 worker는 서로 다른 파일을 쓰고 각 프로세스를 하나씩 실행합니다. 컨테이너 stdout 로그도 20MB × 3개로 제한합니다.

## 검증 범위

테스트는 계약 경로, 권한, 업로드 원자성, 재전송, 비AI 예약 흐름, 작업 상태, 버전 경합, 삭제, AI 실패·deadline, 마스킹·PDF, 스키마 차이와 배포 스크립트를 다룹니다. CI에는 PostgreSQL 테스트와 QEMU 없는 ARM 이미지 빌드를 추가했습니다.

실제 ARM VM 기동, Docker Hub pull, 호스트 Nginx 연동, 실제 모델 평가와 FE의 AC 63개 통합 검수는 해당 환경·자료가 필요합니다. 코드 테스트 통과를 이 검수들의 합격으로 간주하지 않습니다. 평가 실행 방법은 [AI 평가 안내](docs/AI-평가-실행.md)를 참고하세요.
