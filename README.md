# 고쳐야집 Backend

FastAPI · SQLAlchemy · PostgreSQL · Alembic 기반 API와 DB 작업 큐입니다. 요구사항 v1.7, FE·BE 분업 v1.4, API v1.1의 80개 메서드·경로를 내부 `/v1`에 연결했습니다. API 문서는 `/docs`, OpenAPI JSON은 `/openapi.json`입니다. 공개 접두사 `/fixmyhome/api`는 호스트 Nginx에서 지정합니다.

실제 서비스 자료와 검증 자료는 저장소에 포함하지 않습니다. 빈 DB에서도 회원가입·로그인과 사진·증상 접수는 가능하며, 기사 예약에는 운영자가 검증한 지역·일정·이동 자료가 필요합니다. AI는 선택 기능이고 키·모델이 없으면 해당 작업만 실패합니다.

## 개발 환경

Python 실행과 의존성 관리는 uv를 사용합니다. 배포 기준은 CPython 3.13이며 3.12에서도 기능 테스트를 실행할 수 있습니다.

```bash
uv sync --locked
export FMH_DATABASE_URL='postgresql+psycopg2://admin:admin@localhost:5432/fmh'
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

Windows pgAdmin에서 WSL의 로컬 PostgreSQL 컨테이너를 조회할 때는 `127.0.0.1:5432`를 사용합니다. `localhost` 접속 시 `Obtaining connection` 단계가 약 5초 지연됐고, IPv4 주소를 직접 지정해 해결한 과정은 [pgAdmin WSL 연결 지연 트러블슈팅](docs/etc/pgAdmin-WSL-연결-지연-트러블슈팅.md)에 정리했습니다.

### 초기 시연 데이터

마이그레이션이 끝난 개발·테스트 DB에 [초기 적재 스크립트](scripts/seed_initial.py)를 실행합니다. 서울 6개 동의 지역·모의 이동시간표·작업 소요시간(`미닫이문 수리`, `벽지 물자국 점검` 포함)과 함께 5개 분야의 기사 32명, 방문 가능 일정, 합성 이미지가 있는 모의 사례 7건, 그리고 [대표 시연 시나리오](docs/시연-시나리오.md) 3종에 필요한 사전 일정·비교용 합정동 요청·서연의 벽지 물자국 경과 및 확정 예약 데이터를 함께 준비합니다.

```bash
# 백엔드 디렉터리에서 직접 실행할 때는 API와 동일한 DB 및 미디어 저장 경로를 사용합니다.
uv run --no-env-file python -m scripts.seed_initial

# 상위 작업 디렉터리에서 실행하는 경우
uv run --no-env-file fix-my-home-be/scripts/seed_initial.py

# 실행 중인 로컬 Compose에서는 be 컨테이너의 DB 및 공유 미디어 볼륨을 사용합니다.
docker compose -f docker-compose.yaml exec -T be \
  uv run --no-project --no-sync --no-env-file --python /usr/local/bin/python \
  python - < scripts/seed_initial.py
```

파일 경로로 실행하면 미디어 저장 경로 등 상대 경로는 백엔드 디렉터리를 기준으로 해석합니다.

시나리오별 로그인 계정과 상세 흐름은 [시연 시나리오](docs/시연-시나리오.md)를 참고하세요. 첫 적재 시 시연 계정들에 공통 적용되는 자동 발급 비밀번호가 표시되며, 실행 환경에 `FMH_SEED_PASSWORD`를 지정하면 해당 값을 사용합니다.

- **기본·시나리오 2 (동선 할인 예약)**: 기사 `demo-tech-01`(연남동·서교동·합정동, 목요일 `13:00~13:45` 연남동 / `16:00~16:45` 서교동 기존 방문), 비교용 합정동 요청 `demo-user-hapjeong`
- **시나리오 1 (사례 기반 기사 추천)**: 연남동 문·창호 기사 A `demo-tech-door-a`(하부 롤러 모의 사례), 기사 B `demo-tech-02`(창문 잠금장치 모의 사례), 기사 C `demo-tech-door-c`(하단 레일 모의 사례, 토요일 `14:00~17:00` 기존 작업)
- **시나리오 3 (경과 분석·기사 인계)**: 임차인 서연 `demo-user-seoyeon`(벽지 물자국 3시점 사진·기록·묶음 및 확정 예약), 담당 기사 `demo-tech-03`

방문 가능 일정은 실행일을 포함해 한국 시간 기준 14일치입니다. 재실행 시 초기 적재 이후 변경되지 않은 일정에 새 날짜와 반복 시연 외부 일정을 이어 붙입니다.

## Swagger UI와 API 명세

서버 실행 후 Swagger UI에서 API를 확인하고 호출할 수 있습니다. Python 직접 실행과 로컬 Compose는 [localhost:8000/docs](http://localhost:8000/docs), 배포 Compose는 배포 호스트의 [localhost:8002/docs](http://localhost:8002/docs)를 사용합니다. FastAPI 내부 경로에는 `/api`를 붙이지 않습니다.

Nginx에서 `/fixmyhome/api/`를 `http://127.0.0.1:8002/`로 전달하면 공개 Swagger 주소는 `/fixmyhome/api/docs`, 명세 파일은 `/fixmyhome/api/openapi.json`, API Base URL은 `/fixmyhome/api/v1`입니다. `proxy_pass` 끝의 `/`가 공개 접두사를 제거합니다. 앱에는 [FastAPI의 `root_path`](https://fastapi.tiangolo.com/advanced/behind-a-proxy/)로 외부 접두사를 알려 Swagger의 명세 조회와 **Try it out**이 올바른 공개 주소를 사용하게 합니다.

VM의 `.env`는 사용자가 다음과 같이 설정합니다. `FMH_PUBLIC_ORIGIN`에는 경로를 포함하지 않습니다.

```dotenv
FMH_PUBLIC_ORIGIN=https://your-domain.example
FMH_ROOT_PATH=/fixmyhome/api
```

앱 코드와 배포 Compose를 반영한 새 이미지를 빌드·푸시한 뒤 새 버전으로 배포해야 합니다. 기존 이미지에는 환경변수만 추가해도 이 변경이 적용되지 않습니다. [Nginx 예시](deploy/nginx.conf.example)의 경로 전달 방식도 함께 맞춥니다. 접두사가 없는 배포에서는 `FMH_ROOT_PATH`를 비우고, 로컬 Compose는 항상 빈 값으로 덮어씁니다.

80개 API를 12개 업무 분류로 묶고 검색 필터를 제공합니다. 각 API에는 용도·권한·선행 조건, 종류별 처리 조건, 요청 필드와 DTO, Enum의 의미, 성공 응답·파일 형식, 상태 코드별 오류 설명이 표시됩니다. `Idempotency-Key`의 큰따옴표 포함 예시와 multipart `metadata`의 JSON 문자열 예시도 확인할 수 있습니다.

계정이 없으면 `POST /v1/auth/signup`으로 회원가입한 뒤 `POST /v1/auth/login`의 **Try it out**을 실행합니다. 공개 접두사는 Swagger의 서버 URL에서 자동 적용합니다. 브라우저가 받은 HttpOnly 쿠키로 이후 요청을 인증하므로 Authorize에 쿠키를 직접 입력하지 않습니다. 기사 API를 호출하려면 기사 권한이 있는 계정으로 로그인하고 `PATCH /v1/auth/role`로 전환합니다. Swagger UI의 접속 출처와 `FMH_PUBLIC_ORIGIN`을 일치시키고 운영에서는 HTTPS를 사용합니다. 로컬 Compose의 허용 출처는 `http://localhost:8000`으로 지정되어 있습니다.

엔드포인트는 [app/routers](app/routers)의 12개 업무별 파일에서 `@router.get(...)`, `@router.post(...)`, `@router.put(...)`, `@router.patch(...)`로 직접 선언합니다. 각 데코레이터에 경로·요약·상세 설명·상태 코드를 두고, 바로 아래 함수에서 해당 업무 처리를 정의합니다. 예를 들어 회원가입·로그인은 [auth.py](app/routers/auth.py), 요청 접수·조회는 [requests.py](app/routers/requests.py)에 있습니다. 새 업무 라우터는 [app/routers/__init__.py](app/routers/__init__.py)에 등록합니다. 기존 클라이언트 호환을 위해 `operation_id`는 유지합니다.

인증·입력 검증·트랜잭션·멱등성·파일 정리는 [app/http.py](app/http.py)의 `run_endpoint()`가 공통 적용합니다. 라우터 내부의 `operation()`은 이 트랜잭션 안에서 동기 서비스 함수를 호출하며, DB·파일 작업은 스레드풀에서 실행합니다. 엔드포인트 선택은 FastAPI 라우터가 담당합니다.

요청·응답 필드, 인증·멱등성 요구사항 등 전송 계약은 [API 명세서](docs/API명세서.md)에서 생성한 `app/contract_data.py`로 검증합니다. API를 추가하거나 계약을 바꿀 때는 라우터와 명세서를 함께 수정하고 다음 명령으로 계약 데이터를 갱신합니다. 이 명령은 라우터 파일을 생성하거나 수정하지 않습니다. Swagger의 엔드포인트 요약·설명은 라우터 데코레이터가 기준이며, 공통 사용 안내·표시 옵션과 입출력 스키마 보완은 `app/openapi.py`에서 관리합니다. 실행 서버에는 Markdown 원본이 필요하지 않습니다.

```bash
uv run python -m scripts.etc.generate_contract
```

## 빌드와 배포

루트의 `start.sh`는 배포 이미지를 실행합니다. `scripts/`에는 빌드 도구인 `build-push.sh`, `build-start.sh`와 환경 양식 동기화 도구인 `sync_env.py`를 둡니다. 보조 Python 도구는 `scripts/etc/`에 모읍니다. `build-push.sh`는 태그 조회 도구를 uv로 실행하며, 이 도구에는 추가 Python 의존성이 없습니다. 배포 서버의 `start.sh`에는 uv나 별도 Python 파일이 필요하지 않습니다.

로컬 개발자는 `.env.example`을 양식으로 다음 명령을 실행해 `.env`를 준비합니다.

```bash
uv run scripts/sync_env.py
```

`.env`가 없으면 양식 전체를 복사합니다. 있으면 구역 제목·주석·구분선·키 순서를 `.env.example`에 맞추고, 기존 설정값을 해당 위치에 옮깁니다. 누락 항목은 양식의 예시 값으로 추가하므로, 새 키가 없어도 주석이나 순서가 바뀌면 반영됩니다.

빈 값·따옴표·여러 줄 값·설정 줄의 인라인 주석은 보존합니다. 양식에 없는 키는 주석과 함께 파일 끝의 추가 설정 구역에 남기므로, 양식에서 항목을 삭제해도 기존 설정값은 사라지지 않습니다. 형식 오류나 중복 키가 있으면 파일을 변경하지 않습니다. 재실행 시 내용이 같으면 다시 쓰지 않으며, 새 파일과 갱신 파일의 권한은 `0600`입니다.

기존 추가 설정이 있는 상태에서 양식의 키를 삭제해도 추가 설정 구역은 하나로 유지됩니다. 이전 실행에서 중복된 구역 제목이 생겼다면 다음 동기화에서 제목을 정리하고 각 키의 주석과 값은 보존합니다.

기존 파일은 스크립트 실행 중 내부에서만 읽고 값이나 파일 내용은 출력하지 않습니다. DB 접속은 사용자 `admin`, 암호 `admin`, DB 이름 `fmh`를 기준으로 합니다. Compose의 DB 호스트는 `db`, Python 직접 실행의 기본 호스트는 `localhost`입니다. DB에는 이메일 설정이 없습니다. 서버 환경 파일은 저장소에 커밋하지 않습니다. 동기화는 기존 값을 보존하므로, 이미 존재하는 `.env`의 `POSTGRES_USER`·`POSTGRES_PASSWORD`·`FMH_DATABASE_URL`을 이 계정으로 맞추려면 사용자가 직접 변경해야 합니다.

이미 다른 계정으로 초기화한 `postgres-data` 볼륨에서는 환경변수만 바꿔도 DB 계정이 변경되지 않습니다. 이 경우 기존 DB의 계정과 암호도 별도로 맞춰야 합니다. [PostgreSQL 이미지의 초기화 규칙](https://github.com/docker-library/docs/blob/master/postgres/README.md#environment-variables)을 참고하세요.

운영 `FMH_SESSION_SECRET`은 DB 비밀번호와 다른 32자 이상의 무작위 값이어야 합니다. `development-`·`replace_`로 시작하는 값은 길이가 충분해도 예시값으로 판단해 거부합니다. 환경 양식 동기화는 비밀값을 자동 생성하지 않으므로 사용자가 VM의 `.env`에서 변경해야 합니다. 이 검사는 DB 연결 전 마이그레이션 진입점에서도 실행합니다. `migrate` 로그에 해당 설정 오류가 나오면 값을 수정하고 `./start.sh <배포한 버전>`으로 다시 실행합니다. 설정값 수정만으로 같은 이미지를 다시 사용할 수 있습니다.

스크립트는 작업 디렉터리와 관계없이 저장소 루트를 기준으로 동작합니다. 다른 배포 디렉터리에 있는 양식을 반영할 때는 `--directory /path/to/deployment`를 지정합니다. 추가 의존성은 없으며, 프로젝트 의존성 동기화와 uv의 환경 파일 로딩을 생략하려면 `uv run --no-project --no-env-file scripts/sync_env.py`로 실행합니다.

```bash
# docker-compose.yaml을 기준으로 로컬 이미지를 빌드하고 실행합니다.
./scripts/build-start.sh

# 루트에서 직접 실행해도 같은 로컬 서비스 설정을 사용합니다.
docker compose -f docker-compose.yaml up -d --build

# 이번 실행의 로컬 이미지 태그를 지정할 수도 있습니다.
./scripts/build-start.sh local-v0.1.0

# 로컬 실행 대상 CPU를 지정합니다. 에뮬레이션 없이 실행하려면 호스트 CPU와 맞춥니다.
./scripts/build-start.sh local-v0.1.0 --platform linux/amd64

# Docker Hub 태그 목록을 확인하고, 프롬프트에서 버전을 입력한 뒤 ARM64 이미지를 푸시합니다.
./scripts/build-push.sh

# 빌드·푸시 대상 CPU를 변경할 때도 조회 후 버전을 입력합니다.
./scripts/build-push.sh --platform linux/amd64
```

`docker-compose.yaml`은 배포 Compose의 DB·마이그레이션·API·worker 설정을 상속하고 로컬 빌드와 개발 환경 설정을 적용합니다. `build-start.sh`는 이 파일을 대상으로 `docker compose up -d --build`를 실행합니다. 루트에서는 `docker compose up -d --build`만으로도 파일을 자동 선택합니다. `LOCAL_IMAGE_TAG` 기본값은 `local`, `LOCAL_IMAGE_PLATFORM` 기본값은 `linux/amd64`이며 ARM 개발 호스트에서는 `linux/arm64`로 지정할 수 있습니다. 로컬 HTTP 쿠키를 사용하고 공개 포트와 허용 출처는 이 Compose 파일에서 각각 `8000`, `http://localhost:8000`으로 지정합니다. 이 값들은 배포용 `IMAGE_TAG`·`IMAGE_PLATFORM`·운영 쿠키 설정과 구분됩니다.

로컬의 `ports: !override`는 상속한 배포 포트 목록을 교체하므로 로컬에서 배포용 `8002`가 함께 열리지 않습니다. [포트 목록 교체 문법](https://docs.docker.com/reference/compose-file/merge/#replace-value)은 Docker Compose 2.24.4 이상에서 지원합니다.

기본 이미지는 `eagleindesert/fix-my-home-be`입니다. `IMAGE_NAME`으로 변경할 수 있습니다. 두 빌드 스크립트는 각 실행 전용 Buildx builder를 `restart-policy=no`로 만들고 성공·실패 후 정지·제거합니다. `build-start.sh`는 `BUILDX_BUILDER`와 `COMPOSE_BAKE=true`로 해당 builder에 [Compose 빌드를 위임](https://docs.docker.com/compose/how-tos/dependent-images/#build-with-bake)하므로 Bake 위임을 지원하는 Docker Compose와 Buildx가 필요합니다. CLI에서 직접 실행할 때는 현재 Docker builder 설정을 사용합니다.

`build-push.sh`는 [Registry V2 태그 API](https://distribution.github.io/distribution/spec/api/#listing-image-tags)의 모든 페이지를 조회하고 이름순으로 태그를 표시한 뒤 `푸시할 버전:` 프롬프트에서 버전을 입력받습니다. 이 API는 푸시 시각을 제공하지 않습니다. 버전은 이 단계에서만 입력하며, 선택한 태그로 빌드·푸시합니다. 이미 존재하는 태그를 입력하면 해당 태그를 갱신합니다. 태그 목록이 비었거나 첫 태그 조회가 404를 반환하면 `등록된 이미지가 없습니다`를 표시하고 첫 버전 입력으로 이어집니다.

조회와 푸시는 같은 사용자의 [Docker CLI 로그인 정보](https://docs.docker.com/reference/cli/docker/login/)를 사용합니다. 먼저 `docker login`을 실행하면 별도의 조회용 토큰 없이 비공개 저장소도 조회할 수 있습니다. 조회 도구는 `DOCKER_CONFIG/config.json` 또는 기본 `~/.docker/config.json`에서 Hub 전용 `credHelpers`, 공통 `credsStore`, 파일의 `auths` 순으로 자격 증명을 선택합니다. 비밀번호·PAT 및 브라우저 로그인으로 저장한 자격 증명을 지원하고, 저장된 identity token도 refresh token 방식으로 교환합니다. 로그인 정보가 없으면 공개 저장소를 익명 조회합니다. `.env`를 읽지 않고 자격 증명 파일을 변경하지 않으며 비밀번호·토큰·응답 본문·credential helper 출력은 화면이나 로그에 남기지 않습니다.

인증·권한·네트워크 오류 등 조회 실패 시에는 입력·빌드를 시작하지 않고 대상 이미지 이름과 오류 원인을 표시합니다. 인증 실패는 스크립트를 실행하는 사용자로 `docker login`을 다시 실행하고, 접근 거부는 해당 계정의 저장소 읽기 권한을 확인합니다. 인증 요청이나 두 번째 이후 태그 페이지의 404는 조회 실패로 처리합니다.

빈 입력이나 잘못된 태그는 다시 입력받고, EOF 또는 Ctrl+C로 취소할 수 있습니다. 태그를 확인하고 유효한 버전을 입력하기 전에는 builder와 푸시 기록을 만들지 않습니다. 지원 이미지는 Docker Hub의 `namespace/repository`이며 `docker.io/`·`index.docker.io/` 접두사도 사용할 수 있습니다. 이미지 이름은 `IMAGE_NAME=사용자/이미지 ./scripts/build-push.sh`처럼 지정합니다.

푸시 성공 후에는 이전·현재 푸시 버전과 대상 플랫폼을 출력합니다. 이전 버전은 이 컴퓨터의 같은 이미지·플랫폼에 대한 마지막 성공 기록이며, `.runtime/build-push/`에 저장합니다. 첫 실행은 `기록 없음`으로 표시하고 실패한 푸시는 기록을 바꾸지 않습니다. 이는 조회한 Docker Hub 태그 목록과 별개인 로컬 기록입니다.

`Dockerfile`의 모든 `RUN` 단계는 `$BUILDPLATFORM`에서 실행합니다. 대상 CPU wheel을 `uv sync --python-platform … --no-build`로 설치하고 ELF 아키텍처를 검사합니다. 프로젝트 코드는 같은 CPython 3.13 빌드 이미지에서 `.pyc`로 컴파일합니다. 최종 ARM 이미지에는 해당 wheel, `.pyc`, 설정과 한글 글꼴만 복사하며 ARM 명령을 실행하지 않습니다. 애플리케이션·worker·migration의 `.py` 소스는 최종 이미지 레이어에 포함하지 않습니다. 표준 라이브러리와 외부 패키지 소스는 제거 대상이 아닙니다. Python 바이트코드는 원본 소스 배포를 피하는 방식이며 강한 역공학 방지를 보장하지 않습니다.

Ubuntu 24.04 ARM64 VM에는 Docker Compose와 호스트 Nginx가 준비되어 있어야 합니다. 저장소 루트의 다음 세 파일만 같은 디렉토리에 복사합니다. `start.sh`의 실행 권한을 유지하거나 `bash start.sh`로 실행합니다. 작업 디렉터리와 관계없이 `start.sh`가 있는 디렉토리의 Compose 설정을 사용합니다.

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

# 플랫폼도 변경하려면 명시합니다. 이후 직접 실행하는 Compose에도 적용됩니다.
./start.sh v0.1.0 --platform linux/arm64
```

버전 없는 실행은 강제 pull·재생성을 추가하지 않습니다. 버전만 지정하면 기존 플랫폼을 유지하고, `--platform`을 함께 지정하면 `IMAGE_PLATFORM`도 저장합니다. 플랫폼 기본값은 배포 Compose의 `linux/arm64`입니다. `start.sh`와 `build-start.sh`는 실행 후 현재 호스트에서 사용할 Swagger UI·상태 확인 주소를 출력합니다.

`start.sh`는 API 공통 경로 `/v1`을 포함한 현재 호스트의 Base URL을 출력합니다. 주소는 실행 중인 컨테이너의 Compose 포트 매핑에서 가져오며, 기본 배포 설정에서는 `http://127.0.0.1:8002/v1`입니다. 명세서의 상대 경로를 이어 붙여 호출합니다. 예를 들어 로그인 주소는 `http://127.0.0.1:8002/v1/auth/login`입니다. VM 외부에서는 Nginx의 도메인과 공개 접두사를 사용합니다. `/fixmyhome/api`로 배포했다면 외부 로그인 경로는 `/fixmyhome/api/v1/auth/login`입니다.

버전 변경은 여러 줄 값·빈 값·주석을 보존하며 이미지 선택 설정만 수정합니다. 형식 오류나 중복 키가 있으면 값 없이 오류를 알리고 중단합니다. pull 실패 또는 pull 도중 환경파일이 변경되면 기존 파일을 덮어쓰지 않습니다. 성공 시 `0600` 임시 파일을 원자적으로 교체하므로 이후 직접 실행하는 Compose 명령에도 저장한 버전과 플랫폼이 적용됩니다. 별도로 export한 `IMAGE_TAG`·`IMAGE_PLATFORM`은 Compose의 환경변수 우선순위에 따라 `.env`보다 우선합니다.

PostgreSQL 정상 기동 → migration 성공 → API·worker 순서로 시작합니다. DB·사진·로그는 named volume에 보관합니다. API 공개 포트는 환경별 Compose의 `ports`에서 직접 설정합니다. 로컬 `docker-compose.yaml`은 `127.0.0.1:8000:8000`, 배포 `docker-compose-deployment.yaml`은 `127.0.0.1:8002:8000`을 사용합니다. 호스트 Nginx는 배포용 `127.0.0.1:8002`로 포워딩하고 Docker는 컨테이너 내부의 `8000` 포트로 연결합니다. 기존 `.env`나 셸에 남아 있는 `BE_PORT`·`FMH_LOCAL_ORIGIN`은 사용하지 않습니다. 포트를 바꿀 때는 해당 Compose의 매핑과 로컬 허용 출처 또는 운영 Nginx 설정을 함께 맞춥니다. [Nginx 예시](deploy/nginx.conf.example)를 기존 호스트 설정에 맞춰 적용합니다. 기본 Docker 네트워크는 `172.30.0.0/24`이며 다른 네트워크와 충돌하면 `.env`의 subnet·gateway·trusted proxy 값을 함께 바꿉니다.

## 운영 자료와 계정

일반 사용자는 별도 이메일·휴대전화 인증 없이 `POST /v1/auth/signup`으로 가입합니다.

```json
{
  "loginId": "member01",
  "password": "example-password"
}
```

로그인 ID는 앞뒤 공백 없는 1~128자, 비밀번호는 기존 계정 정책에 따라 12자 이상입니다. ID가 중복되면 `409 ACCOUNT_EXISTS`, 가입에 성공하면 계정 ID·로그인 ID·`availableRoles: ["USER"]`를 `201`로 반환합니다. 가입 시 로그인 쿠키는 발급하지 않으므로 같은 정보로 `POST /v1/auth/login`을 호출합니다. 회원가입 요청에는 역할을 지정하지 않습니다.

기본 비밀번호가 설정된 운영 계정을 자동 생성하지 않습니다. 기사 권한이 필요한 계정은 배포된 컨테이너에서 다음과 같이 발급합니다.

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

E2E는 `docker-compose.yaml`로 DB·마이그레이션·API·worker를 실행한 상태에서 `bash scripts/e2e/run.sh`로 시작합니다. 터미널에서 전체 API 검사(`api`)와 기획 흐름 검사(`scenarios`)를 선택할 수 있고, `--suite api` 또는 `--suite scenarios`로 바로 실행할 수도 있습니다. 호스트에서 컨테이너 API에 실제 HTTP 요청을 보내며 PostgreSQL과 별도 worker의 작업 완료를 확인합니다. API 메서드·경로·응답 상태와 시나리오별 검증 결과를 실시간으로 출력합니다. 실행기는 컨테이너를 시작·종료하거나 볼륨을 삭제하지 않습니다. 준비 방법, 검증 범위, 결과 파일과 테스트 자료 정리는 [Compose E2E 안내](scripts/e2e/README.md)를 참고하세요.

테스트는 계약 경로, 권한, 업로드 원자성, 재전송, 비AI 예약 흐름, 작업 상태, 버전 경합, 삭제, AI 실패·deadline, 마스킹·PDF, 스키마 차이와 배포 스크립트를 다룹니다. CI에는 PostgreSQL 테스트와 QEMU 없는 ARM 이미지 빌드를 추가했습니다.

조사 당시 LiteLLM의 최신 정식 릴리스에 JSON 출력 패치가 빠져 발생한 AI 작업 실패와 함수 호출 방식으로 우회한 과정은 [LiteLLM 구조화 출력 트러블슈팅](docs/etc/LiteLLM-구조화-출력-트러블슈팅.md)에 정리했습니다. 재현용 curl 명령과 확인한 릴리스별 차이도 포함합니다.

실제 ARM VM 기동, Docker Hub pull, 호스트 Nginx 연동, 실제 모델 평가와 FE의 AC 63개 통합 검수는 해당 환경·자료가 필요합니다. 코드 테스트 통과를 이 검수들의 합격으로 간주하지 않습니다. 평가 실행 방법은 [AI 평가 안내](docs/AI-평가-실행.md)를 참고하세요.
