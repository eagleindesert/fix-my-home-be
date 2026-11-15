# Windows pgAdmin에서 WSL PostgreSQL 연결 지연 트러블슈팅

발생 및 해결일: 2026-11-16

Windows에 설치한 pgAdmin 4 `9.19`에서 WSL의 PostgreSQL 컨테이너에 접속할 때 `Obtaining connection` 단계가 약 5초씩 지연됐다. 접속 주소를 `localhost:5432`에서 `127.0.0.1:5432`로 변경하자 지연이 사라졌고, 사용자가 체감한 속도는 클라우드 배포 환경과 같아졌다.

## 발생 환경과 증상

| 항목 | 확인한 내용 |
| --- | --- |
| 클라이언트 | Windows에 설치한 pgAdmin 4 `9.19` |
| 접속 대상 | 같은 PC의 WSL에서 실행 중인 PostgreSQL 컨테이너 |
| 변경 전 Host name/address | `localhost` |
| Port | `5432` |
| 지연이 표시된 단계 | `Obtaining connection` |
| 지연 시간 | 사용자 관찰 기준 약 5초 |
| 이전 사용 환경 | 같은 WSL의 다른 PostgreSQL 컨테이너에서는 지연을 느끼지 못함 |
| 클라우드 비교 환경 | 클라우드 Ubuntu의 pgAdmin에서 해당 클라우드 DB에 `localhost`로 접속하면 빠름 |

저장소의 [로컬 Compose](../../docker-compose.yaml)는 DB 포트를 `5432:5432`로 공개한다. [배포 Compose](../../docker-compose-deployment.yaml)의 기본 매핑은 `5434:5432`이므로, 다른 실행 환경에 적용할 때는 실제 공개 포트를 확인한다.

클라우드 비교는 다른 DB와 다른 접속 경로를 사용했다. 이번 해결을 판단한 기준은 같은 Windows pgAdmin에서 같은 WSL DB를 대상으로 Host name/address를 변경한 전후 결과다.

## 시도한 조치와 결과

| 순서 | 조치 | 관찰 결과 |
| --- | --- | --- |
| 1 | Parameters에서 `GSS encmode`를 `disable`로 설정 | 연결 지연이 계속됨 |
| 2 | Host name/address를 `localhost`에서 `127.0.0.1`로 변경하고 `5432` 포트로 재연결 | 연결 지연이 사라지고 클라우드 환경과 비슷한 체감 속도로 동작 |

## 적용한 해결 방법

Windows pgAdmin에서 다음 순서로 변경한다.

1. 해당 서버의 Properties 창을 닫는다.
2. 왼쪽 서버 트리에서 서버를 우클릭하고 **Disconnect Server**를 선택한다.
3. 다시 서버를 우클릭해 **Properties → Connection**을 연다.
4. **Host name/address**에 `127.0.0.1`, **Port**에 `5432`를 입력한다.
5. **Save** 후 서버에 재연결한다.
6. 새 Query Tool을 열어 `Obtaining connection` 단계의 지연이 사라졌는지 확인한다.

| 설정 | 변경 전 | 변경 후 |
| --- | --- | --- |
| Host name/address | `localhost` | `127.0.0.1` |
| Port | `5432` | `5432` |

이 주소는 Windows에서 접속하는 pgAdmin에 적용한다. Compose 서비스 사이의 DB 접속 주소는 서비스 이름인 `db:5432`를 사용한다. 컨테이너 내부의 `127.0.0.1`은 그 컨테이너 자신을 가리킨다.

### Parameters의 추가 버튼이 보이지 않을 때

조사 중 Parameters 탭의 값이 비활성화되고 `+` 버튼도 표시되지 않았다. pgAdmin 4 `9.19`는 서버에 연결된 동안 연결 매개변수를 읽기 전용으로 설정하고 추가·삭제를 제한한다. **Disconnect Server 후 Properties를 다시 열면** 매개변수를 추가할 수 있다. [읽기 전용 처리](https://github.com/pgadmin-org/pgadmin4/blob/REL-9_19/web/pgadmin/browser/server_groups/servers/static/js/server.ui.js#L255-L264), [추가 및 삭제 조건](https://github.com/pgadmin-org/pgadmin4/blob/REL-9_19/web/pgadmin/browser/server_groups/servers/static/js/server.ui.js#L454-L458)

## localhost와 127.0.0.1의 차이

`localhost`는 운영체제가 주소로 해석하는 이름이다. 환경에 따라 IPv4의 `127.0.0.1`과 IPv6의 `::1`이 연결 후보가 될 수 있다. pgAdmin이 사용하는 PostgreSQL 연결 라이브러리인 libpq는 하나의 이름이 여러 주소로 해석되면 성공할 때까지 주소를 순서대로 시도한다. 숫자 IP를 Host에 직접 지정하면 그 주소를 그대로 사용한다. [libpq의 다중 주소 처리와 Host 설정](https://www.postgresql.org/docs/18/libpq-connect.html#LIBPQ-MULTIPLE-HOSTS)

이번 증상에 부합하는 가설은 다음과 같다.

1. Windows에서 `localhost`를 해석한 뒤 IPv6 주소 `::1`로 먼저 연결을 시도한다.
2. 해당 주소에서 WSL의 PostgreSQL까지 연결되지 않아 대기 또는 재시도가 발생한다.
3. 이후 IPv4 주소 `127.0.0.1`로 연결에 성공한다.
4. 처음부터 `127.0.0.1`을 지정하면 앞선 주소 해석과 IPv6 연결 시도를 생략한다.

주소 선택 순서나 패킷을 측정하지 않았으므로, 실제 지연이 이름 해석 자체에서 발생했는지 IPv6 연결 재시도에서 발생했는지는 확정하지 않는다. 확인된 해결 방법은 **같은 Windows 클라이언트에서 IPv4 주소를 직접 지정하는 것**이다.

## 클라우드 Ubuntu에서는 localhost도 빨랐던 이유

`localhost`의 이름은 같아도 운영체제의 주소 선택 순서와 각 주소에서 DB까지 연결되는 경로는 다를 수 있다. Windows에서 WSL 서비스에 접속하는 경로에는 Windows와 WSL 사이의 네트워크 동작도 포함된다. Microsoft는 Windows 앱에서 WSL 서비스를 `localhost`로 이용하는 방식을 지원하지만, 그 사실만으로 모든 환경의 IPv4·IPv6 연결 경로가 같아지는 것은 아니다. [WSL 네트워킹 문서](https://learn.microsoft.com/en-us/windows/wsl/networking#accessing-linux-networking-apps-from-windows-localhost)

| 환경 | 정상 속도 또는 지연을 설명하는 가능한 조건 |
| --- | --- |
| 클라우드 Ubuntu에서 `localhost` 사용 | IPv4 주소를 먼저 선택했거나, IPv6 주소에서도 바로 연결할 수 있었음 |
| Windows에서 WSL DB에 `localhost` 사용 | 먼저 선택한 주소의 연결 시도가 지연됐거나, 이름 해석 자체가 지연됐음 |
| 같은 Windows에서 `127.0.0.1` 사용 | 확인된 IPv4 경로로 바로 연결할 수 있었음 |

클라우드에서 빠르게 연결됐다는 관찰만으로 그 환경의 IPv4·IPv6 선택 순서를 알 수는 없다. 같은 WSL의 이전 DB가 빨랐다는 사실도 현재 포트와 연결 설정에서 동일한 경로를 사용했다는 뜻은 아니다.

## 같은 증상이 다시 발생할 때

1. 지연이 연결 준비 단계인지, 연결 후 SQL 실행 단계인지 구분한다. 새 Query Tool을 여는 시간과 이미 열린 Query Tool에서 `SELECT 1;`을 반복 실행하는 시간을 비교한다.
2. 같은 클라이언트·DB·계정·포트를 사용하고 Host만 `localhost`와 `127.0.0.1`로 바꿔 새 연결을 비교한다.
3. 주소 변경으로 개선되면 이름 해석 시간과 IPv4·IPv6 각각의 TCP 연결 시간을 분리해 확인한다. 주소 목록만으로 특정 주소의 연결 지연을 확정하지 않는다.
4. `127.0.0.1`에서도 느리면 클라이언트와 WSL 사이의 연결, PostgreSQL 인증, pgAdmin의 연결 초기화 작업을 추가로 조사한다.

현재 Windows 개발 환경에서는 pgAdmin의 WSL DB 접속 주소를 `127.0.0.1:5432`로 사용한다.
