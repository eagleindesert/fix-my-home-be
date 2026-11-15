# 고쳐야집 Backend API Specification (v1.0)

> Base URL: `/v1` (백엔드 내부 경로). Nginx 공개 접두사가 `/fixmyhome/api`이면 외부 Base URL은 `/fixmyhome/api/v1`이다.
>
> 인증 방식: 브라우저 쿠키 기반 세션 인증. 회원가입 또는 기존 계정 로그인에 성공하면 서버가 세션을 생성하고 세션 식별자를 쿠키로 발급한다. 이후 요청의 세션 쿠키로 인증하고 활성 역할·관계별 권한을 검사한다.
>
> Last Updated: 2026-11-15

---

## 문서 범위와 공통 전송 규격

본 문서는 **API를 통해 주고받는 파일과 데이터의 입출력 규격**에 집중한다. 각 API의 경로·HTTP 메서드·헤더·요청 및 응답 본문·파일 형식·필드명·타입·필수 여부·DTO·Enum·상태 코드를 명세한다.

기능·업무 정책과 처리 흐름은 [FE·BE 분업 작업 명세 v1.4](FE-BE-분업작업.md), [요구사항명세서 v1.7](요구사항명세서(기능들).md)를 기준으로 하며, 이 문서에서 새로 결정하거나 변경하지 않는다. 해당 문서는 API에 필요한 입력·출력 데이터를 확인하는 근거로 참조한다.

본 문서는 API `v1.0`의 연동 규격이다. 경로·필드명·DTO·Enum·상태 코드·응답 구조를 정의하며, 미정인 전송 규격은 해당 항목에 표시한다.

- **경로·인증 헤더**: 상대 경로에는 Base URL을 붙인다. 인증이 필요한 요청은 세션 식별자를 `Cookie` 헤더로 전송하며, 쿠키 발급·만료는 `Set-Cookie` 응답 헤더로 전달한다. 쿠키 이름·속성은 미정이다.
- **JSON 본문**: JSON 요청은 `application/json`이다. 성공 JSON은 `data`로 감싸고 오류는 공통 에러 구조를 루트에 반환한다. `204 No Content`는 응답 본문이 없다.
- **파일 업로드**: `multipart/form-data`를 사용한다. `files`는 같은 이름의 파일 파트를 파일마다 반복하고, `file`은 단일 파일 파트이다. 브라우저 `FormData` 사용 시 `Content-Type`과 boundary는 브라우저가 설정한다.
- **공통 사진 제한**: 사용자 요청 사진은 JPEG·PNG, 파일당 `10,000,000` Byte 이하, 한 번의 업로드에 `1~5`장, 요청 전체에 최대 `30`장이다. 기사 포트폴리오의 파일 규격은 해당 API를 따른다.
- **파일 메타데이터**: multipart의 `metadata`·`source`는 각 API에 지정한 DTO를 JSON 직렬화한 UTF-8 문자열 Form 필드로 전송한다. JSON Blob·파일 파트로 보내지 않는다. 사진별 메타정보 배열은 `files`의 개수·순서에 맞춘다.
- **파일 응답**: 이미지 조회는 해당 이미지 MIME 타입과 바이트를, PDF 다운로드는 `application/pdf`와 PDF 바이트를 반환한다. 파일 바이트는 JSON의 `data`로 감싸지 않는다. 파일명과 다운로드 헤더는 개별 API의 응답 규격을 따른다.
- **필드 표기**: 필수·선택 여부는 요청 표와 공통 DTO 설명을 따른다. `T?`는 `null` 허용, `T[]`는 배열이며 배열은 별도 표기가 없으면 `null` 대신 빈 배열을 사용한다. `PATCH`에서 생략한 필드는 유지하고 `null`은 nullable 필드만 해제한다. 필수 문자열은 공백만 허용하지 않는다.
- **날짜·시각**: 날짜는 `YYYY-MM-DD`, 시각은 시간대를 포함한 ISO 8601을 사용한다. 기준 시간대는 `Asia/Seoul`이다.
- **공통 멱등 키 규칙**: 개별 **Headers** 표에 필수로 표시된 API에 `Idempotency-Key`를 전송한다. 값은 큰따옴표로 감싼 비어 있지 않은 ASCII 문자열 하나이다. 예: `Idempotency-Key: "550e8400-e29b-41d4-a716-446655440000"`. 같은 요청의 네트워크 재전송에는 같은 키를, 요청 내용 변경·별도 요청에는 새 키를 사용한다.
- **공통 재응답 규칙**: 같은 계정·HTTP 메서드·경로에서 같은 키·내용을 재전송하면 현재 조회가 허용된 기존 처리 결과를 반환한다. 이미 접수된 비동기 작업은 기존 작업 ID를 반환한다. 처리 중·키 재사용 오류의 상태 코드와 본문은 공통 에러 응답을 따른다.

### 멱등 키·재전송 계약

키의 범위는 계정·HTTP 메서드·실제 경로이다. 요청 내용에는 업무 쿼리와 기대 버전도 포함한다. 현재 권한·삭제 조건을 만족하는 결과만 재응답한다.

| 입력·상황 | 입출력 계약 |
| --- | --- |
| JSON 동일성 | 객체 키 순서·형식상 공백은 무시한다. 배열 순서·문자열 값·생략과 `null`·기본값의 명시 여부는 구분한다. 중복 객체 키는 `400 BAD_REQUEST`이다. |
| multipart 동일성 | 파일 파트 이름·파일 순서·원래 파일명·검증된 파일 형식·바이트와 Form 값으로 비교한다. boundary·파트 헤더 순서 차이는 무시하고 `metadata`·`source`는 JSON 규칙을 적용한다. |
| 같은 키·다른 내용 | `409 IDEMPOTENCY_KEY_REUSED`; 내용·기대 버전 변경에는 새 키 사용 |
| 같은 키·같은 내용, 성공·비동기 접수 완료 | 기존 리소스·작업 ID와 현재 조회 허용 결과; 이미 반영한 요청의 과거 기대 버전만으로 `VERSION_CONFLICT`를 반환하지 않음 |
| 같은 키·같은 내용, 처리·반영 여부 확인 중 | `409 IDEMPOTENCY_IN_PROGRESS`, `retryable=true`; 같은 키로 재전송 |
| 같은 키·같은 내용, 업무 조건으로 확정 거절 | 기존 `409`·`422` 거절; 보완·재확인 후 새 요청에는 새 키 사용 |
| 미반영이 확인된 일시적 실패 | `500`·`503`, `retryable=true`이면 같은 키로 재시도 가능; 반영 여부 미확인은 처리 중 응답 |
| 인증·구문·전송 형식 오류 | 키가 접수되지 않은 오류; 내용 수정 시 새 키 사용 |
| 접수 후 실패한 비동기 작업 | 같은 키는 기존 작업 반환; AI는 새 키·`retryOfJobId`, 전달본·PDF는 새 생성 요청, 삭제는 전용 재시도 API 사용 |

### 확인 API·목록·필드 공통 규격

| 항목 | 계약 |
| --- | --- |
| 확인 API | 요약·전달본·보고서·방문 중복 확인은 `PUT`과 `Idempotency-Key`를 사용한다. 버전 필드는 각 요청 표를 따르며 같은 키 재전송에는 위 규칙을 적용한다. |
| 기대 버전만 사용하는 확인 입력 | `PUT /requests/{requestId}/visit-details`와 `PUT /work-items/{workItemId}/route-exploration`은 `confirmed` 필드가 있어도 `Idempotency-Key`를 사용하지 않는다. 두 API는 `expectedRevision`으로 검사하며 성공 후 이전 기대값의 재전송은 `409 VERSION_CONFLICT`; 해당 상세 조회로 반영 여부를 확인한다. |
| 요청 본문 없음 | GET은 요청 본문을 사용하지 않는다. 나머지 메서드는 개별 Request Body 표를 따르며 본문이 없는 호출은 설명에 표시한다. |
| 페이지 목록 | `data: PageDTO<T>`, `cursor` 선택, `limit` 기본 `20`·최대 `100`·최소 `1`인 연동안. 범위 위반·잘못된 커서는 `422 VALIDATION_ERROR`; 커서는 동일 경로·필터·정렬에서만 재사용한다. |
| 전체 배열 목록 | `data: T[]`는 페이지 분할 없이 정의된 범위 전체를 반환하며 조용히 잘라내지 않는다. 결과 없음은 `[]`; 개별 정렬·범위는 해당 응답 표를 따른다. |
| 입력 필드 | 필수 여부와 `null` 허용은 별개이다. 필수 nullable 필드는 생략할 수 없고 값이 없으면 `null`을 보낸다. 조건부 필수·전송 금지 필드는 개별 표를 따른다. |
| 응답 필드 | 명시적인 생략 규칙이 없으면 표의 필드를 모두 반환한다. 값 없음은 nullable 필드의 `null`, 배열 결과 없음은 `[]`로 표현한다. 공용 DTO의 `✅`·`-`는 입력 필수 여부에만 적용한다. |
| 권한별 반환 | 숨길 필드·배열의 `null`·`[]` 또는 응답 거절은 해당 DTO·예외 표를 따른다. 권한 없는 본문을 상태 조회나 재전송으로 제공하지 않는다. |

### 목록 정렬·커서 계약

각 페이지 목록의 **정렬** 또는 응답 표에 나열된 키를 왼쪽부터 적용한다. 문자열 ID는 대소문자를 구분한 Unicode 코드 포인트순으로 비교하고 숫자로 변환하지 않는다. 시각은 시간대 표기와 무관한 실제 시점으로 비교한다.

| 조건 | 응답·재조회 규칙 |
| --- | --- |
| 첫 페이지 | `cursor`를 생략한다. 지정한 필터와 정렬의 현재 결과를 반환한다. |
| 다음 페이지 | 같은 경로·필터·정렬로 `nextCursor`를 제출한다. 커서에 연결된 마지막 정렬 키와 동률 ID 다음부터 조회하며 클라이언트는 커서를 해석·수정하지 않는다. |
| 조회 중 추가·수정·삭제·권한 변경 | 각 페이지는 현재 자료·권한을 적용한다. 추가·정렬 키 이동으로 페이지 간 중복·누락이 생길 수 있으며 첫 페이지 시점의 전체 목록 고정을 보장하지 않는다. 최신 전체 목록이 필요하면 커서 없이 다시 조회한다. |
| 커서 대상 항목 삭제 | 그 항목의 과거 본문을 반환하지 않으며 커서에 연결된 정렬 키 다음을 조회한다. |
| 같은 커서 재전송 | 데이터·권한·조회 조건·검사 결과가 같으면 같은 순서의 결과를 반환한다. 시각 경과에 따른 재검사 결과도 현재 값을 적용하며 과거 상태를 복원하지 않는다. |
| 잘못된 커서·조회 조건 불일치 | `422 VALIDATION_ERROR`, `fieldErrors[].field=cursor`; `requiredActions`에 커서 없이 다시 조회할 안내를 제공한다. |
| 더 조회할 결과 없음 | `nextCursor=null`; 현재 페이지에 결과도 없으면 `items=[]`이다. |

### 확정이 필요한 전송 규격

아래 항목은 구현·배포 전 FE·BE가 결정할 사항이다. 미정 값을 다른 기능의 제한에서 추정하지 않는다. 나머지 경로·필드·공통 페이지 값은 이 문서의 v1.0 규격을 사용한다.

| 항목 | 현재 정의 | 결정할 값·관련 위치 |
| --- | --- | --- |
| Base URL·세션 쿠키 | 내부 `/v1`, Nginx 공개 접두사 별도 적용, `Cookie`·`Set-Cookie` 사용 | 배포 경로, 쿠키 이름·Domain·Path·Secure·HttpOnly·SameSite·유효기간 및 만료 헤더; 인증 API |
| 포트폴리오 사진 | multipart의 반복 `files`와 JSON 문자열 `source` | MIME 허용 목록·파일당 최대 Byte·최대 파트 수; `POST /technicians/me/portfolio-photos` |
| 일정 날짜 범위 | `date`, `from ≤ to` | 최대 조회·교체 일수와 경계 날짜 포함 여부·경계를 걸친 일정 반환/교체 범위; 일정 GET·PUT |
| 멱등 키 보존 | 같은 요청의 재전송에 같은 키 사용 | 보존 기간·만료 후 재사용 응답; 이 값이 정해지기 전 만료 후 중복 실행을 가정하지 않음 |
| 식별자·문자열·수량 | 불투명 `string`, 자유 문자열, 양수 수량 | ID 형식·최대 길이, 문자열 길이, 수량 단위·정밀도, 연락수단 형식별 검증 |
| 지원 범위 밖 상담의 지역 | 일반 접수는 RegionValueDTO, 지원 지역 조회는 ServiceRegionDTO | 상담 허용 정책 결정 후 견적 전제의 지역 타입·오류 매핑 확정 |

---

## 📋 API 엔드포인트 총괄표

| # | 분류 | Method | Endpoint | 인증 | 선행 조건 | 설명 | 업데이트 날짜 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Authentication | POST | `/auth/login` | ❌ | 가입 또는 사전 발급 계정 | 로그인 | 2026-11-15 |
| 2 | Authentication | POST | `/auth/logout` | ✅ | 계정 본인 | 로그아웃 | 2026-11-13 |
| 3 | Authentication | GET | `/auth/me` | ✅ | 계정 본인 | 현재 계정·역할 조회 | 2026-11-13 |
| 4 | Authentication | PATCH | `/auth/role` | ✅ | 계정 본인 | 활성 역할 전환 | 2026-11-13 |
| 5 | Public | GET | `/public/service-info` | ❌ | 없음 | 소개·지원 범위 조회 | 2026-11-13 |
| 6 | Public | GET | `/public/technicians` | ❌ | 없음 | 공개 기사 연락 목록 | 2026-11-13 |
| 7 | Public | GET | `/public/technicians/{technicianId}` | ❌ | 없음 | 공개 기사 프로필 조회 | 2026-11-13 |
| 8 | Public | GET | `/public/guidance` | ❌ | 없음 | 긴급·공식 안내 조회 | 2026-11-13 |
| 9 | Requests | POST | `/requests` | ✅ | 본인 | 사진·증상 최초 접수 | 2026-11-13 |
| 10 | Requests | GET | `/requests` | ✅ | 본인 | 본인 요청 목록 | 2026-11-13 |
| 11 | Requests | GET | `/requests/{requestId}` | ✅ | 본인 | 요청 상세·이력 조회 | 2026-11-13 |
| 12 | Requests | PATCH | `/requests/{requestId}` | ✅ | 본인 | 공통 증상·지역 정정 | 2026-11-13 |
| 13 | Requests | PUT | `/requests/{requestId}/visit-details` | ✅ | 본인 | 상세 방문 정보 확인 | 2026-11-13 |
| 14 | Requests | POST | `/requests/{requestId}/closure` | ✅ | 본인 | 요청 전체 종료 | 2026-11-13 |
| 15 | Requests | POST | `/requests/{requestId}/work-items` | ✅ | 본인 | 독립 작업 항목 추가 | 2026-11-13 |
| 16 | Requests | PATCH | `/work-items/{workItemId}` | ✅ | 본인 | 작업 사실·해결 경로 변경 | 2026-11-13 |
| 17 | Requests | PUT | `/work-items/{workItemId}/confirmation` | ✅ | 본인 | 요약·분야 사용자 확인 | 2026-11-13 |
| 18 | Requests | GET | `/work-items/{workItemId}/solutions` | ✅ | 본인 | 항목별 해결 안내 | 2026-11-13 |
| 19 | Requests | POST | `/work-items/{workItemId}/outcomes` | ✅ | 본인 | 자가 조치·외부 해결 결과 기록 | 2026-11-13 |
| 20 | History | POST | `/requests/{requestId}/photos` | ✅ | 본인 | 추가 사진 업로드 | 2026-11-13 |
| 21 | History | PUT | `/photos/{photoId}` | ✅ | 본인 | 사진·촬영일·설명 정정 | 2026-11-13 |
| 22 | History | GET | `/media/{mediaId}` | ✅ | 자료 종류·관계 권한 | 권한 있는 이미지 조회 | 2026-11-13 |
| 23 | History | POST | `/requests/{requestId}/records` | ✅ | 본인 | 경과·보완 기록 추가 | 2026-11-13 |
| 24 | History | PATCH | `/records/{recordId}` | ✅ | 본인 | 본인 경과 기록 정정 | 2026-11-13 |
| 25 | History | GET | `/requests/{requestId}/timeline` | ✅ | 본인 | 날짜별 경과·비교쌍 조회 | 2026-11-13 |
| 26 | History | PUT | `/requests/{requestId}/photo-groups` | ✅ | 본인 | 동일 부위 묶음·비교쌍 설정 | 2026-11-13 |
| 27 | AI | POST | `/requests/{requestId}/ai-jobs` | ✅ | 본인 | AI 작업 명시적 실행·재시도 | 2026-11-13 |
| 28 | AI | GET | `/requests/{requestId}/ai-jobs` | ✅ | 본인 | 요청별 AI 작업·결과 이력 조회 | 2026-11-13 |
| 29 | AI | GET | `/ai-jobs/{jobId}` | ✅ | 본인 | AI 상태·결과·오류 조회 | 2026-11-13 |
| 30 | AI | PUT | `/requests/{requestId}/ai-dialogue` | ✅ | 본인 | 답변·건너뛰기·문답 종료 | 2026-11-13 |
| 31 | Technicians | GET | `/technicians/me` | ✅ | 기사 본인 | 본인 기사 자원 조회 | 2026-11-13 |
| 32 | Technicians | PUT | `/technicians/me/profile` | ✅ | 기사 본인 | 프로필 등록·수정 | 2026-11-13 |
| 33 | Technicians | POST | `/technicians/me/portfolio-photos` | ✅ | 기사 본인 | 본인 포트폴리오 사진 업로드 | 2026-11-13 |
| 34 | Technicians | GET | `/technicians/{technicianId}/portfolio` | ✅ | 로그인; 공개 검증 자료 | 포트폴리오·사례 목록 조회 | 2026-11-13 |
| 35 | Technicians | POST | `/technicians/me/cases` | ✅ | 기사 본인 | 준비된 시공 사례 등록 | 2026-11-13 |
| 36 | Technicians | PATCH | `/technicians/me/cases/{caseId}` | ✅ | 기사 본인 | 본인 사례 정정 | 2026-11-13 |
| 37 | Technicians | GET | `/cases/{caseId}` | ✅ | 로그인; 공개 검증 자료 | 사례 상세 조회 | 2026-11-13 |
| 38 | Technicians | GET | `/technicians/me/schedule` | ✅ | 기사 본인 | 본인 일정표 조회 | 2026-11-13 |
| 39 | Technicians | PUT | `/technicians/me/schedule` | ✅ | 기사 본인 | 가능 시간·외부 일정 변경 | 2026-11-13 |
| 40 | Matching | GET | `/work-items/{workItemId}/case-recommendations` | ✅ | 본인 | 사례 기반 기사 추천 조회 | 2026-11-13 |
| 41 | Matching | GET | `/work-items/{workItemId}/general-candidates` | ✅ | 본인 | 일반 기사 후보 조회 | 2026-11-13 |
| 42 | Matching | PUT | `/work-items/{workItemId}/route-exploration` | ✅ | 본인 | 동선 탐색 공개·중단 | 2026-11-13 |
| 43 | Matching | GET | `/technicians/me/route-candidates` | ✅ | 기사 본인 | 기사 동선 추천 작업 조회 | 2026-11-13 |
| 44 | Matching | POST | `/route-candidates/{candidateId}/interests` | ✅ | 기사 본인; 탐색 공개 중 | 상담 참여 의사 표시 | 2026-11-13 |
| 45 | Matching | GET | `/work-items/{workItemId}/interests` | ✅ | 본인 | 참여 기사 조회 | 2026-11-13 |
| 46 | Consultations | POST | `/work-items/{workItemId}/consultations` | ✅ | 소유자; 지역·방문 조건·요약 확인 | 기사 선택·상담 요청 | 2026-11-13 |
| 47 | Consultations | GET | `/consultations` | ✅ | 현재 역할의 당사자 | 참여 상담 목록 | 2026-11-13 |
| 48 | Consultations | GET | `/consultations/{consultationId}` | ✅ | 관계 당사자 | 상담 상세·전달 이력 조회 | 2026-11-13 |
| 49 | Consultations | PATCH | `/consultations/{consultationId}` | ✅ | 관계 당사자; 액션별 권한 | 상담 수락·거절·종료·해제 | 2026-11-13 |
| 50 | Consultations | POST | `/consultations/{consultationId}/quotes` | ✅ | 수락된 활성 상담의 기사 | 견적 신규 발행·수정본 발행 | 2026-11-13 |
| 51 | Consultations | PATCH | `/quotes/{quoteId}` | ✅ | 발행 기사 또는 요청 소유자 | 견적 철회·거절 | 2026-11-13 |
| 52 | Consultations | GET | `/work-items/{workItemId}/quotes` | ✅ | 본인 | 항목별 견적 비교 | 2026-11-13 |
| 53 | Reservations | POST | `/reservation-checks` | ✅ | 소유자 또는 관련 기사 | 예약·변경·시작 조건 사전 검사 | 2026-11-13 |
| 54 | Reservations | PUT | `/reservation-checks/{checkId}/confirmation` | ✅ | 해당 요청 소유자 | 다른 기사 방문 중복 확인 | 2026-11-13 |
| 55 | Reservations | POST | `/work-items/{workItemId}/reservations` | ✅ | 소유자; 최신 견적·방문 정보 확인 | 견적 선택·예약 확정 | 2026-11-13 |
| 56 | Reservations | GET | `/reservations` | ✅ | 현재 역할의 당사자 | 당사자 예약 목록 | 2026-11-13 |
| 57 | Reservations | GET | `/reservations/{reservationId}` | ✅ | 예약 당사자 | 예약·작업·인계 상세 | 2026-11-13 |
| 58 | Reservations | POST | `/reservations/{reservationId}/cancellation` | ✅ | 예약 당사자; 실제 시작 전 | 시작 전 예약 취소 | 2026-11-13 |
| 59 | Reservations | POST | `/reservations/{reservationId}/changes` | ✅ | 예약 당사자 | 시작 전·진행 중 변경안 제안 | 2026-11-13 |
| 60 | Reservations | PATCH | `/reservation-changes/{changeId}` | ✅ | 예약 당사자; 동일 변경 버전 | 변경안 수락·거절·철회 | 2026-11-13 |
| 61 | Work | PUT | `/reservations/{reservationId}/early-start-consent` | ✅ | 요청 소유자; 시작 전 | 조기 시작 동의·철회 | 2026-11-13 |
| 62 | Work | POST | `/reservations/{reservationId}/work-events` | ✅ | 액션별 사용자 또는 담당 기사 | 시작·중단 요청·중단·완료·종료 예상 갱신 | 2026-11-13 |
| 63 | Work | PUT | `/reservations/{reservationId}/end-location` | ✅ | 해당 완료·중단 예약 담당 기사 | 종료 위치 보완·정정 | 2026-11-13 |
| 64 | Work | PUT | `/reservations/{reservationId}/preparation-notes` | ✅ | 해당 활성 예약 담당 기사 | 방문 준비사항 등록·수정 | 2026-11-13 |
| 65 | Handover | POST | `/work-items/{workItemId}/deliveries` | ✅ | 본인 | 가림·공개 범위 전달본 준비 | 2026-11-13 |
| 66 | Handover | GET | `/work-items/{workItemId}/deliveries` | ✅ | 본인 | 전달본·준비본 목록 복구 | 2026-11-13 |
| 67 | Handover | GET | `/deliveries/{deliveryId}` | ✅ | 소유자 또는 허용 수신자 | 전달본 처리 상태·미리보기·열람 | 2026-11-13 |
| 68 | Handover | PUT | `/deliveries/{deliveryId}/confirmation` | ✅ | 본인 | 처리 결과·공개 범위 확인 | 2026-11-13 |
| 69 | Handover | PUT | `/work-items/{workItemId}/report` | ✅ | 본인 | 보고서 직접 작성·수정 초안 | 2026-11-13 |
| 70 | Handover | GET | `/work-items/{workItemId}/report` | ✅ | 본인 | 본인 보고서·초안 조회 | 2026-11-13 |
| 71 | Handover | PUT | `/work-items/{workItemId}/report/confirmation` | ✅ | 본인 | 최신 보고서 본문 확인 | 2026-11-13 |
| 72 | Handover | POST | `/deliveries/{deliveryId}/pdf-jobs` | ✅ | 본인 | 사진 포함 PDF 생성 | 2026-11-13 |
| 73 | Handover | GET | `/deliveries/{deliveryId}/pdf-jobs` | ✅ | 본인 | PDF 작업 목록 복구 | 2026-11-13 |
| 74 | Handover | GET | `/pdf-jobs/{jobId}` | ✅ | 본인 | PDF 생성 상태 조회 | 2026-11-13 |
| 75 | Handover | GET | `/pdf-jobs/{jobId}/content` | ✅ | 본인 | 확인된 PDF 다운로드 | 2026-11-13 |
| 76 | Deletion | POST | `/deletion-jobs` | ✅ | 본인 | 사진·일반 기록·요청 전체 삭제 | 2026-11-13 |
| 77 | Deletion | GET | `/deletion-jobs` | ✅ | 본인 | 삭제 작업 목록·재시도 대상 복구 | 2026-11-13 |
| 78 | Deletion | GET | `/deletion-jobs/{jobId}` | ✅ | 본인 | 삭제 처리 상태 조회 | 2026-11-13 |
| 79 | Deletion | POST | `/deletion-jobs/{jobId}/retry` | ✅ | 본인 | 삭제 미완료 정리 재시도 | 2026-11-13 |
| 80 | Authentication | POST | `/auth/signup` | ❌ | 없음 | 회원가입 및 자동 로그인 | 2026-11-15 |

범례: `✅` 세션 쿠키 인증 필요, `❌` 인증 불필요. `계정 본인`은 활성 역할·요청 소유와 무관한 본인 계정이고, `본인`은 사용자 역할로 자신의 요청·자료를 다루는 조건이다. 기사·관계 당사자는 별도 표기한다. 인증이 필요한 API에는 공통 `401`·`403`, 식별자 조회에는 `404`, 멱등 키 필수 API에는 관련 `400`·`409`가 적용된다.

---

## 1. 인증·역할 (Authentication)

> 정책 참조: `W01` · `FR-ACT-01~03` · [요구사항 §4.15](요구사항명세서(기능들).md#415-테스트-계정과-역할-권한) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### POST `/auth/login` — 로그인

- **인증 요구사항**: ❌
- **선행 조건**: 가입 또는 사전 발급 계정
- **설명**: 기존 계정으로 로그인하고 세션 쿠키와 계정·역할 정보를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `loginId` | string | ✅ | 가입 또는 발급 계정 | 로그인 식별값 |
| `password` | string | ✅ | 계정 자격증명 | 로그·응답에 포함하지 않음 |

**Response Headers**

| 헤더 | 값 |
| --- | --- |
| `Set-Cookie` | 세션 쿠키; 이름·속성은 공통 미정 항목 참조 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | SessionDTO | 처리 결과 |

**예외 응답**

- **401 Unauthorized**: 계정 인증 실패 (`INVALID_CREDENTIALS`)

---

### POST `/auth/logout` — 로그아웃

- **인증 요구사항**: ✅
- **선행 조건**: 계정 본인
- **설명**: 현재 세션을 종료하고 로그인 쿠키를 만료시킨다. 요청 본문은 없다.

**Response Headers**

| 헤더 | 값 |
| --- | --- |
| `Set-Cookie` | 로그인 쿠키와 동일한 이름·범위의 만료 쿠키; 세부 값 미정 |

**Response 204 No Content**

응답 본문 없음.

---

### GET `/auth/me` — 현재 계정·역할 조회

- **인증 요구사항**: ✅
- **선행 조건**: 계정 본인
- **설명**: 현재 계정·활성 역할·연결 기사 식별자를 반환한다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | SessionDTO | 처리 결과 |

---

### PATCH `/auth/role` — 활성 역할 전환

- **인증 요구사항**: ✅
- **선행 조건**: 계정 본인
- **설명**: 허용 역할 중 선택한 활성 역할과 계정 정보를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `role` | Role | ✅ | 해당 계정의 허용 역할 | 전환할 역할 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | SessionDTO | 처리 결과 |

**예외 응답**

- **403 Forbidden**: 허용되지 않은 역할 또는 액션 (`ROLE_FORBIDDEN`)

---

### POST `/auth/signup` — 회원가입 및 자동 로그인

- **인증 요구사항**: ❌
- **선행 조건**: 없음
- **설명**: 사용자 또는 기사 계정을 생성하고 즉시 로그인한다. 계정·기사 프로필·초기 일정·세션은 하나의 트랜잭션으로 저장한다. 이미 로그인한 브라우저에서 가입하면 기존 세션을 폐기하고 새 계정 세션으로 교체한다.
- **역할 규칙**: `USER` 가입의 허용 역할은 `[USER]`, `TECHNICIAN` 가입은 `[USER, TECHNICIAN]`이다. 초기 활성 역할은 모두 `USER`이며 기사 기능은 `/auth/role`에서 전환한다. 임의 역할이나 추가 권한은 지정할 수 없다.
- **기사 초기 지역**: 기사 가입에서 `regionId`를 제공하면 검증된 지원 지역을 초기 활동 지역으로 설정하고, 해당 지역의 대표 위치를 일정의 출발·복귀 위치로 사용한다. 초기 가능 시간과 외부 일정은 빈 배열이다. 생략하면 활동 지역·대표 위치를 설정하지 않는다. 기존 기사의 대표 위치는 이 API로 변경하지 않는다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `loginId` | string | ✅ | 3~128자, 영문·숫자·`.`·`_`·`-` | 대소문자를 구분하는 고유 로그인 ID. 앞뒤 공백을 제거하지 않는다. |
| `password` | string | ✅ | 12~128자, 공백만 입력 불가 | 해시로 저장하며 로그·응답에 포함하지 않는다. |
| `role` | Role | ✅ | `USER` 또는 `TECHNICIAN` | 가입 유형. 기사도 사용자 역할을 함께 가진다. |
| `regionId` | string | ❌ | `TECHNICIAN`에서만 허용, 검증된 지원 지역 ID | `/public/service-info`의 지원 지역 중 기사 초기 활동 지역. 생략 가능하며 null은 허용하지 않는다. |

**Response Headers**

| 헤더 | 값 |
| --- | --- |
| `Set-Cookie` | 로그인과 동일한 세션 쿠키; HttpOnly, SameSite=Lax, Path=/, 운영 HTTPS에서 Secure |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | SessionDTO | 새 계정과 USER 활성 역할. 기사 가입은 technicianId를 포함한다. |

**예외 응답**

- **409 Conflict**: 이미 사용 중인 로그인 ID (`ACCOUNT_EXISTS`)
- **422 Unprocessable Entity**: 로그인 ID·비밀번호 형식, 가입 역할 또는 일반 사용자의 지역 지정 오류 (`VALIDATION_ERROR`)
- **422 Unprocessable Entity**: 등록되지 않았거나 검증되지 않은 지원 지역 (`INVALID_REFERENCE`)

---

## 2. 공개 정보·직접 연락 (Public)

> 정책 참조: `W02`, `W04`, `W22` · `FR-ACT-01`, `FR-CON-05~06`, `FR-SOL-05` · [요구사항 §4.3](요구사항명세서(기능들).md#43-해결-경로-안내) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### GET `/public/service-info` — 소개·지원 범위 조회

- **인증 요구사항**: ❌
- **설명**: 소개·지원 분야·지원 지역·기준 자료 버전·재촬영 안내를 반환한다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ServiceInfoDTO | 처리 결과 |

---

### GET `/public/technicians` — 공개 기사 연락 목록

- **인증 요구사항**: ❌
- **설명**: 공개 연락수단이 있는 기사의 공개 프로필을 페이지로 반환한다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `field` | ServiceField | - | 없음 | 전문 분야 |
| `regionId` | string | - | 없음 | 활동 지역 식별자 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**정렬**

`technicianId` 오름차순. 기사 ID는 목록에서 유일하며 표시명 변경으로 순서를 바꾸지 않는다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<PublicTechnicianDTO> | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 전문 분야·지역 필터 또는 cursor·limit 형식·범위 오류 (`VALIDATION_ERROR`)

---

### GET `/public/technicians/{technicianId}` — 공개 기사 프로필 조회

- **인증 요구사항**: ❌
- **설명**: 표시명·분야·지역·공개 중인 업무 연락수단을 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `technicianId` | string | 기사 자원 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PublicTechnicianDTO | 처리 결과 |

**예외 응답**

- **404 Not Found**: 대상 없음·삭제됨; 권한 밖 존재 여부 노출도 차단 (`RESOURCE_NOT_FOUND`)

---

### GET `/public/guidance` — 긴급·공식 안내 조회

- **인증 요구사항**: ❌
- **설명**: 검증 가이드와 공식 경로를 각각 상태·보완 입력·사유와 함께 반환한다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `type` | GuidanceType | ✅ | 없음 | 긴급 또는 제조사 AS |
| `triggerId` | string | - | 없음 | 버전 관리된 긴급 입력 식별자 |
| `productType` | string | - | 없음 | 제품 종류 |
| `manufacturer` | string | - | 없음 | 제조사 |
| `modelName` | string | - | 없음 | 모델명 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | GuidanceDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: type 누락·미지원 코드 또는 triggerId·제품 정보 쿼리 형식 오류; 정상 정보 부족은 안내 결과의 INFORMATION_REQUIRED로 구분 (`VALIDATION_ERROR`)

---

## 3. 요청·작업 항목·해결 경로 (Requests)

> 정책 참조: `W03~07` · `FR-REQ-01~11`, `FR-AI-04`, `FR-SOL-01~04` · [요구사항 §6.1](요구사항명세서(기능들).md#61-요청작업항목-처리-단계) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### POST `/requests` — 사진·증상 최초 접수

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 사진·증상으로 요청과 기본 작업 항목 하나를 생성하여 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `multipart/form-data` | ✅ |

**Request Body (`multipart/form-data`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `files` | binary[] | ✅ | 1~5장; 공통 사진 제한 | 반복 파일 파트 |
| `metadata` | string | ✅ | `RequestInputDTO`의 JSON 문자열; 사진 순서 일치 | 일반 Form 필드; 증상·사진 설명·선택 입력 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RequestDTO | 처리 결과 |

**예외 응답**

- **413 Content Too Large**: 사용자 요청 사진 파일당 10,000,000 Byte 초과 (`FILE_TOO_LARGE`)
- **415 Unsupported Media Type**: 실제 파일 형식 또는 Content-Type 미지원 (`UNSUPPORTED_MEDIA_TYPE`)
- **422 Unprocessable Content**: 묶음 내 손상 이미지·메타정보 불일치·파일별 오류; 전부 미저장 (`UPLOAD_BATCH_REJECTED`)

---

### GET `/requests` — 본인 요청 목록

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 본인 요청과 항목별 상태의 요약 목록을 반환한다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `status` | RequestStatus | - | 전체 | 전체 요청 종료 여부 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**정렬**

`updatedAt` 내림차순 → 동률 `requestId` 내림차순.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<RequestListItemDTO> | 처리 결과 |

---

### GET `/requests/{requestId}` — 요청 상세·이력 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 공통 자료·작업 항목·연결 이력을 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RequestDTO | 처리 결과 |

---

### PATCH `/requests/{requestId}` — 공통 증상·지역 정정

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 공통 증상·지역을 수정하고 현재 요청을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `symptom` | string | - | 공백 불가 | 공통 증상 |
| `context` | SymptomContextDTO | - | DTO 조건 | 발생 조건·발견일 |
| `region` | RegionValueDTO | - | 실제 지역 | 서울 밖도 저장 허용 |
| `urgent` | boolean | - | 사용자 표시 | AI와 독립적인 긴급 안내 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RequestDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **409 Conflict**: 전체 종료 또는 삭제 중인 요청에 새 관계·자료 생성 시도 (`RESOURCE_CLOSED`)

---

### PUT `/requests/{requestId}/visit-details` — 상세 방문 정보 확인

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 확인한 상세 방문 정보와 확인 버전을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 `RequestDTO.revision`과 일치 | 리소스 버전 검사값; `Idempotency-Key` 미사용, `visitDetailsRevision`과 구분 |
| `visitDetails` | VisitDetailsDTO | ✅ | 주소·연락처·지역 일치 | 본인이 확인한 방문 정보 |
| `confirmed` | boolean | ✅ | `true` | 입력값 사용자 확인 |

**재전송 응답**

성공 후 이전 `expectedRevision`으로 재전송하면 `409 VERSION_CONFLICT`이다. `GET /requests/{requestId}`로 현재 방문 정보·버전을 확인한다. 기대값만 바꾼 자동 재제출은 하지 않는다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RequestDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 상세 주소와 입력 작업 지역 불일치 (`ADDRESS_REGION_MISMATCH`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)

---

### POST `/requests/{requestId}/closure` — 요청 전체 종료

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 항목별 종료 선택을 입력받아 요청의 종료 결과를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `items` | ItemClosureDTO[] | ✅ | 모든 항목을 중복 없이 포함 | 해결 또는 진행하지 않음 확인 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RequestDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 일반 기록·전체 삭제 또는 전체 종료를 막는 활성 관계 (`ACTIVE_RELATION_EXISTS`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)

---

### POST `/requests/{requestId}/work-items` — 독립 작업 항목 추가

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 확인한 작업 사실로 독립 작업 항목을 추가한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `facts` | WorkItemFactsDTO | ✅ | 사용자 확인한 작업 단위 | 부위·종류·수량·분야·제품·방문 조건 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | WorkItemDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 전체 종료 또는 삭제 중인 요청에 새 관계·자료 생성 시도 (`RESOURCE_CLOSED`)
- **422 Unprocessable Content**: 작업 사실의 필드 타입·수량·분야·방문 조건 오류 (`VALIDATION_ERROR`)

---

### PATCH `/work-items/{workItemId}` — 작업 사실·해결 경로 변경

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 작업 사실·방문 조건·해결 경로를 부분 수정한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `facts` | WorkItemFactsPatchDTO | - | 하위 필드 부분 수정; 단계별 필수 조건 유지 | 변경한 사실만 전송 |
| `resolutionPath` | ResolutionPath | - | 경로 적용 조건 검사 | 선택한 해결 경로 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | WorkItemDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **409 Conflict**: 전체 종료 또는 삭제 중인 요청에 새 관계·자료 생성 시도 (`RESOURCE_CLOSED`)
- **422 Unprocessable Content**: 적용 조건을 충족하지 않은 가이드 실행 경로 선택 (`GUIDE_NOT_APPLICABLE`)

---

### PUT `/work-items/{workItemId}/confirmation` — 요약·분야 사용자 확인

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 요약·분야·근거 버전의 사용자 확인 결과를 저장한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `sourceRevision` | string | ✅ | 최신 자료와 일치 | 사용자에게 표시한 근거 자료 식별값 |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `summary` | SummaryDTO | ✅ | 삭제 근거 인용 금지 | 직접 정정 가능 |
| `fields` | ServiceField[] | ✅ | 중복 불가; 빈 배열이면 `otherField` 필수 | 확인 분야 |
| `otherField` | string | - | 지원 분야 외 설명 | 지원 범위 밖 기록 |
| `confirmed` | boolean | ✅ | `true` | 사용자 최종 확인 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | WorkItemDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 확인 대상 버전 불일치 (`VERSION_CONFLICT`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **422 Unprocessable Content**: 요약·분야·기타 분야 설명 또는 confirmed 값 오류 (`VALIDATION_ERROR`)

---

### GET `/work-items/{workItemId}/solutions` — 항목별 해결 안내

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 자가 해결과 공식 AS 각각의 상태·안내·보완 입력 및 선택 경로를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | SolutionsDTO | 처리 결과 |

---

### POST `/work-items/{workItemId}/outcomes` — 자가 조치·외부 해결 결과 기록

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 자가 조치·외부 해결 결과를 사용자 기록으로 저장한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `outcome` | OutcomeContentDTO | ✅ | DTO 조건 | 조치와 해결·미해결 결과 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RecordDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 전체 종료 또는 삭제 중인 요청에 새 결과 기록 생성 시도 (`RESOURCE_CLOSED`)
- **422 Unprocessable Content**: 해결 경로·결과 코드·조치 설명·발생일 등 결과 기록 입력 오류 (`VALIDATION_ERROR`)

---

## 4. 사진·경과 기록 (History)

> 정책 참조: `W03`, `W16~17` · `FR-REQ-03`, `FR-REQ-09`, `FR-HIS-01~10` · [요구사항 §6.6](요구사항명세서(기능들).md#66-경과-비교정정파생-결과의-유효성) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### POST `/requests/{requestId}/photos` — 추가 사진 업로드

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 파일과 촬영일·설명·항목 연결을 입력받아 추가 사진을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `multipart/form-data` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Request Body (`multipart/form-data`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `files` | binary[] | ✅ | 1~5장; 저장 합계 ≤30 | 오류 시 묶음 전체 미저장 |
| `metadata` | string | ✅ | `PhotoInputDTO[]`의 JSON 문자열; 파일 수·순서 일치 | 일반 Form 필드; 촬영일 확인·항목 연결 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PhotoCollectionDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 전체 종료 또는 삭제 중인 요청에 새 사진 생성 시도 (`RESOURCE_CLOSED`)
- **413 Content Too Large**: 사용자 요청 사진 파일당 10,000,000 Byte 초과 (`FILE_TOO_LARGE`)
- **415 Unsupported Media Type**: 실제 파일 형식 또는 Content-Type 미지원 (`UNSUPPORTED_MEDIA_TYPE`)
- **422 Unprocessable Content**: 묶음 내 손상 이미지·메타정보 불일치·파일별 오류; 전부 미저장 (`UPLOAD_BATCH_REJECTED`)
- **409 Conflict**: 동시 업로드를 포함한 요청 저장 사진 30장 초과 (`PHOTO_LIMIT_EXCEEDED`)

---

### PUT `/photos/{photoId}` — 사진·촬영일·설명 정정

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 선택한 파일 교체와 현재 사진 메타정보를 저장한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `multipart/form-data` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `photoId` | string | 사용자 요청 사진 식별자; 실제 형식 미정 |

**Request Body (`multipart/form-data`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `file` | binary | - | JPEG·PNG; ≤10,000,000 Byte | 생략하면 기존 파일 유지; 전송하면 교체 |
| `metadata` | string | ✅ | `PhotoUpdateInputDTO`의 JSON 문자열; 하위 필드 모두 필수 | 메타정보 전체를 교체; 파일 교체 여부와 독립 |
| `expectedRevision` | string | ✅ | 최신 사진 값 일치 | 경합 검사 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PhotoDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **413 Content Too Large**: 사용자 요청 사진 파일당 10,000,000 Byte 초과 (`FILE_TOO_LARGE`)
- **415 Unsupported Media Type**: 실제 파일 형식 또는 Content-Type 미지원 (`UNSUPPORTED_MEDIA_TYPE`)
- **422 Unprocessable Content**: 교체 이미지 손상·파일과 메타정보 불일치; 전부 미저장 (`UPLOAD_BATCH_REJECTED`)
- **422 Unprocessable Content**: 수정 메타정보 필드 누락·잘못된 타입·촬영일 확인값 불일치 (`VALIDATION_ERROR`)
- **422 Unprocessable Content**: 다른 요청 소속 또는 삭제된 작업 항목 참조 (`INVALID_REFERENCE`)

---

### GET `/media/{mediaId}` — 권한 있는 이미지 조회

- **인증 요구사항**: ✅
- **선행 조건**: 자료 종류·관계 권한
- **설명**: 현재 권한으로 조회 가능한 원본·전달본·포트폴리오 이미지 바이트를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `mediaId` | string | 이미지 자원 식별자; 실제 형식 미정 |

**Response 200 OK**

| 항목 | 값 |
| --- | --- |
| Content-Type | 요청 사진은 `image/jpeg` 또는 `image/png`; 포트폴리오 허용 형식은 미정 |
| Body | 권한을 검사한 이미지 바이트 |
| 방향·가림 | 분석 좌표와 같은 표시 방향; 전달본에는 가림 전 원본·메타데이터 없음 |

**예외 응답**

- **403 Forbidden**: 소유·관계·자료 범위 권한 없음; 비공개 최신 상태는 제공하지 않음 (`ACCESS_DENIED`)
- **404 Not Found**: 대상 없음·삭제됨; 권한 밖 존재 여부 노출도 차단 (`RESOURCE_NOT_FOUND`)
- **409 Conflict**: 처리 중·실패·갱신 필요·삭제 근거로 파생 자료 제공 불가 (`DERIVED_CONTENT_UNAVAILABLE`)

---

### POST `/requests/{requestId}/records` — 경과·보완 기록 추가

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 경과·조치·보완 설명을 날짜·사진·작업 항목과 연결하여 저장한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `record` | RecordContentDTO | ✅ | 본인 요청의 참조 자료 | 날짜·설명·관련 항목 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RecordDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 전체 종료 또는 삭제 중인 요청에 새 기록 생성 시도 (`RESOURCE_CLOSED`)
- **422 Unprocessable Content**: 타 요청·타 항목·타 기사·삭제 자료 참조 (`INVALID_REFERENCE`)

---

### PATCH `/records/{recordId}` — 본인 경과 기록 정정

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 기존 기록 종류에 맞는 `record` 또는 `outcome`을 입력받아 현재 기록을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `recordId` | string | 사용자 기록 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `record` | RecordContentDTO | - | 일반 경과 기록 정정이면 필수; `outcome`과 동시 제출 불가 | 수정할 현재 내용 |
| `outcome` | OutcomeContentDTO | - | 자가·외부 결과 기록 정정이면 필수; `record`와 동시 제출 불가 | 조치·결과·경로·날짜·사진의 현재 값 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RecordDTO | 처리 결과 |

**예외 응답**

- **403 Forbidden**: 소유·관계·자료 범위 권한 없음; 비공개 최신 상태는 제공하지 않음 (`ACCESS_DENIED`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 저장된 기록 종류와 입력 불일치 또는 `record`·`outcome` 동시 제출·모두 누락 (`VALIDATION_ERROR`)

---

### GET `/requests/{requestId}/timeline` — 날짜별 경과·비교쌍 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 촬영일별 사진·날짜 미확인 사진·기록·동일 부위 묶음을 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | TimelineDTO | 처리 결과 |

---

### PUT `/requests/{requestId}/photo-groups` — 동일 부위 묶음·비교쌍 설정

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 사진 묶음 전체 구성과 기본·수동 비교쌍 선택을 저장한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `sourceRevision` | string | ✅ | 최신 `TimelineDTO.sourceRevision`과 일치 | 묶음 구성 전체의 편집 경합 검사값; 개별 비교 분석 버전과 구분 |
| `groups` | PhotoGroupInputDTO[] | ✅ | 해당 요청 사진만 참조 | 현재 묶음 구성 전체; 빈 배열은 해제 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | TimelineDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 다른 부위·같은 사진·유효하지 않은 비교쌍 (`INVALID_COMPARISON_PAIR`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)

---

## 5. AI 작업·문답 (AI)

> 정책 참조: `W06`, `W10`, `W17`, `W19`, `W21` · `FR-AI-01~06`, `FR-ERR-01~02` · [요구사항 §6.8](요구사항명세서(기능들).md#68-ai-작업실패-복귀검증된-안내) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### POST `/requests/{requestId}/ai-jobs` — AI 작업 명시적 실행·재시도

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 종류·대상·근거 버전으로 AI 작업을 접수하여 작업 ID를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `type` | AiJobType | ✅ | 종류별 선행 조건 | 실행할 AI 기능 |
| `sourceRevision` | string | ✅ | 종류별 기준 DTO의 최신 값과 일치 | 실행에 사용할 근거 자료 식별값 |
| `workItemId` | string | - | 아래 종류별 조건 적용; 지정 시 해당 요청 소속 | 항목 단위 AI의 대상; 기본 항목도 ID를 명시 |
| `photoGroupId` | string | - | `PHOTO_COMPARISON`에서 필수, 그 외 전송 금지 | 해당 요청의 사진 묶음과 현재 비교쌍 |
| `guideId` | string | - | `GUIDE_EXPLANATION`에서 필수, 그 외 전송 금지 | 해당 항목에 적용 가능한 검증 가이드 |
| `retryOfJobId` | string | - | 같은 요청·종류·대상의 본인 실패·시간 초과 작업 | 기존 작업은 유지하고 새 작업으로 연결; 대상 변경은 재시도 없이 신규 실행 |

**종류별 대상·근거 버전**

| `AiJobType` | 처리 단위 | `workItemId` | `photoGroupId` | `guideId` | `sourceRevision` 기준 |
| --- | --- | --- | --- | --- | --- |
| `DIAGNOSIS` | 작업 항목 | ✅ 필수 | 전송 금지 | 전송 금지 | 대상 `WorkItemDTO.sourceRevision` |
| `QUESTION` | 요청 전체 | 전송 금지 | 전송 금지 | 전송 금지 | `RequestDTO.sourceRevision` |
| `GUIDE_EXPLANATION` | 작업 항목·가이드 | ✅ 필수 | 전송 금지 | ✅ 필수 | 대상 `WorkItemDTO.sourceRevision`; 가이드 출처·버전도 서버가 함께 검사 |
| `CASE_MATCHING` | 작업 항목 | ✅ 필수 | 전송 금지 | 전송 금지 | 대상 `WorkItemDTO.sourceRevision` |
| `PHOTO_COMPARISON` | 요청의 사진 묶음 | 전송 금지 | ✅ 필수 | 전송 금지 | 대상 `PhotoGroupDTO.sourceRevision`; 해당 묶음의 비교 근거만 검사 |
| `REPORT_DRAFT` | 작업 항목 | ✅ 필수 | 전송 금지 | 전송 금지 | 대상 `WorkItemDTO.sourceRevision` |

**Response 202 Accepted**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | AiJobDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **409 Conflict**: 새 `QUESTION` 접수 시 요청 전체 질문 5개가 이미 발행됨 (`QUESTION_LIMIT_REACHED`)
- **409 Conflict**: 한도 도달 전 문답이 종료됨, 생성 중·답변 대기 질문이 있음, 또는 수동 재시도 대상이 실패·시간 초과 작업이 아님 (`INVALID_STATE`)
- **409 Conflict**: 전체 종료 또는 삭제 중인 요청에 새 AI 작업 접수 시도 (`RESOURCE_CLOSED`)
- **409 Conflict**: `CASE_MATCHING`에 필요한 기준 자료 누락으로 해당 평가 자체를 수행할 수 없음; 사례 없음·시간 적합성 미확인만으로 적용하지 않음 (`REFERENCE_DATA_MISSING`)
- **422 Unprocessable Content**: 종류별 필수·금지 필드 또는 대상 소속 조건 위반 (`VALIDATION_ERROR`)
- **422 Unprocessable Content**: `CASE_MATCHING`의 조건 충족 추천 대상이 서울 밖 또는 미지원 분야임 (`SERVICE_UNSUPPORTED`)
- **422 Unprocessable Content**: 벽지 물자국 외 사진 변화 분석 (`ANALYSIS_NOT_SUPPORTED`)
- **422 Unprocessable Content**: 해당 기능의 필수 정보·사진 근거 부족; 지원 대상의 유효한 사진 묶음에서 비교쌍을 구성할 사진이 부족한 정상 미수행에는 적용하지 않음 (`INSUFFICIENT_INPUT`)

---

### GET `/requests/{requestId}/ai-jobs` — 요청별 AI 작업·결과 이력 조회

- **인증 요구사항**: ✅
- **선행 조건**: 요청 소유자
- **설명**: 종류·대상별 작업 ID·상태·결과·실패 및 재시도 이력을 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 본인 요청 식별자 |

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `type` | AiJobType | - | 전체 | AI 종류 필터 |
| `workItemId` | string | - | 전체 | 해당 요청의 항목 작업만 조회 |
| `photoGroupId` | string | - | 전체 | 해당 요청의 사진 묶음 비교 작업만 조회 |
| `guideId` | string | - | 전체 | 해당 검증 가이드의 맞춤 설명 작업만 조회 |
| `cursor` | string | - | 없음 | 동일 필터의 이전 응답 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<AiJobDTO> | 현재 권한의 작업 이력; `receivedAt` 내림차순·동률 `jobId` 내림차순; 실패·시간 초과 포함 |
| `data.items` | AiJobDTO[] | AI 미실행 또는 필터 일치 작업이 없으면 빈 배열; 실패는 작업 항목의 `error`로 구분 |

**예외 응답**

- **422 Unprocessable Content**: 종류와 양립할 수 없는 대상 필터 또는 잘못된 페이지 입력 (`VALIDATION_ERROR`)

---

### GET `/ai-jobs/{jobId}` — AI 상태·결과·오류 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 저장된 AI 작업의 상태·종류별 결과·오류를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | 해당 종류의 비동기 작업 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | AiJobDTO | 처리 결과 |

---

### PUT `/requests/{requestId}/ai-dialogue` — 답변·건너뛰기·문답 종료

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 현재 질문의 답변·건너뛰기 또는 문답 종료 결과를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | `DialogueDTO.revision`과 일치 | 이미 반영한 동일 질문·액션·답변의 재전송은 아래 규칙 적용 |
| `action` | DialogueAction | ✅ | `ANSWER`, `SKIP`, `FINISH` | 문답 처리 |
| `questionId` | string | - | `ANSWER`·`SKIP`이면 필수; `FINISH`이면 생략 | 현재 요청의 발행된 질문 |
| `answer` | string | - | `ANSWER`이면 `answer` 또는 `optionId` 필수; 그 외 생략 | 사용자 답변 |
| `optionId` | string | - | `ANSWER`에서 구조화 질문의 유효 선택지; 그 외 생략 | 긴급 분기에도 사용 |

**동일 입력 재전송 응답**

| 입력 | 응답 |
| --- | --- |
| 이미 저장한 같은 질문·액션·답변 또는 종료된 문답의 `FINISH` | 현재 DialogueDTO, `200`; 해당 처리에 소비된 과거 기대값만으로 충돌 처리하지 않음 |
| 처리한 질문에 다른 답변·액션 | `409 INVALID_STATE` |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DialogueDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 현재 답변 대기 질문이 아님, 종료된 문답에 새 답변 제출, 또는 이미 처리한 질문의 답변·처리를 변경하려 함 (`INVALID_STATE`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 액션별 필수·금지 필드 또는 질문 선택지 조건 위반 (`VALIDATION_ERROR`)

---

## 6. 기사 프로필·사례·일정 (Technicians)

> 정책 참조: `W08~09`, `W22` · `FR-PRO-01~05` · [요구사항 §4.4](요구사항명세서(기능들).md#44-기사-프로필일정수리-사례-관리) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### GET `/technicians/me` — 본인 기사 자원 조회

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 본인 프로필·공개 설정·포트폴리오를 반환한다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | TechnicianDTO | 처리 결과 |

---

### PUT `/technicians/me/profile` — 프로필 등록·수정

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 기대 버전과 프로필 전체 내용을 입력받아 현재 프로필을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 `TechnicianDTO.profileRevision` 일치 | 프로필 내용·공개 설정의 경합 검사 |
| `profile` | TechnicianProfileContentDTO | ✅ | 본인 자원 | 공개 정보·공개 설정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | TechnicianDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 다른 프로필 변경이 먼저 반영됨 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 표시명·전문 분야·활동 지역·연락수단·대표 사진 등 프로필 입력 오류 (`VALIDATION_ERROR`)

---

### POST `/technicians/me/portfolio-photos` — 본인 포트폴리오 사진 업로드

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 포트폴리오 사진과 출처 정보를 입력받아 미디어 목록을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `multipart/form-data` | ✅ |

**Request Body (`multipart/form-data`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `files` | binary[] | ✅ | 형식·용량·개수 미정 | 프로필용 사진 |
| `source` | string | ✅ | `SourceDTO`의 JSON 문자열; 출처·사용 가능 여부 확인 | 일반 Form 필드; 실제 접수자료 전환 금지 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | MediaDTO[] | 처리 결과 |

**예외 응답**

- **413 Content Too Large**: 파일당 최대 Byte 초과; 상한은 공통 미정 항목 참조 (`FILE_TOO_LARGE`)
- **415 Unsupported Media Type**: 허용 MIME 외 형식; 허용 목록은 공통 미정 항목 참조 (`UNSUPPORTED_MEDIA_TYPE`)
- **422 Unprocessable Content**: 허용 파일 파트 수 초과·누락; 상한은 공통 미정 항목 참조 (`VALIDATION_ERROR`)
- **422 Unprocessable Content**: 준비 자료 출처·사용 가능 여부·비식별 검증 실패 (`SOURCE_NOT_VERIFIED`)

---

### GET `/technicians/{technicianId}/portfolio` — 포트폴리오·사례 목록 조회

- **인증 요구사항**: ✅
- **선행 조건**: 로그인; 공개 검증 자료
- **설명**: 본인 자료 또는 타인에게 공개 가능한 사진·사례 목록을 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `technicianId` | string | 기사 자원 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PortfolioDTO | 처리 결과 |

---

### POST `/technicians/me/cases` — 준비된 시공 사례 등록

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 본인 자료에 연결한 시공 사례를 생성한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `case` | CaseContentDTO | ✅ | 본인 프로필 사진·검증 자료 | 사례 내용 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | CaseDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 준비 자료 출처·사용 가능 여부·비식별 검증 실패 (`SOURCE_NOT_VERIFIED`)
- **422 Unprocessable Content**: 타 요청·타 항목·타 기사·삭제 자료 참조 (`INVALID_REFERENCE`)

---

### PATCH `/technicians/me/cases/{caseId}` — 본인 사례 정정

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 기대 버전과 사례 내용을 입력받아 수정한 사례를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `caseId` | string | 시공 사례 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `case` | CaseContentDTO | ✅ | 본인 사례 | 수정한 현재 내용 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | CaseDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 준비 자료 출처·사용 가능 여부·비식별 검증 실패 (`SOURCE_NOT_VERIFIED`)

---

### GET `/cases/{caseId}` — 사례 상세 조회

- **인증 요구사항**: ✅
- **선행 조건**: 로그인; 공개 검증 자료
- **설명**: 현재 권한으로 조회 가능한 사례 내용·출처·전후 사진을 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `caseId` | string | 시공 사례 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | CaseDTO | 처리 결과 |

**예외 응답**

- **404 Not Found**: 대상 없음·삭제됨; 권한 밖 존재 여부 노출도 차단 (`RESOURCE_NOT_FOUND`)

---

### GET `/technicians/me/schedule` — 본인 일정표 조회

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 날짜 범위의 가능 시간·외부 일정·예약·이동 구간·검사 결과를 반환한다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `from` | date | ✅ | 없음 | 조회 시작일 |
| `to` | date | ✅ | 없음 | 조회 종료일; 허용 조회 길이 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ScheduleDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: from·to 누락·날짜 형식·범위 오류; from은 to 이후일 수 없음 (`VALIDATION_ERROR`)

---

### PUT `/technicians/me/schedule` — 가능 시간·외부 일정 변경

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 지정 날짜 범위의 편집 가능한 일정 전체를 입력받아 일정표를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `from` | date | ✅ | `from ≤ to` | 적용 시작일 |
| `to` | date | ✅ | 범위 확인 | 적용 종료일 |
| `availability` | TimeRangeDTO[] | ✅ | 15분 단위 | 방문 가능 구간 |
| `externalVisits` | ExternalVisitDTO[] | ✅ | 15분 단위; 위치 필수 | 외부 일정; 예약은 입력 불가 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ScheduleDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 일정 변경이 예약·작업·이동과 충돌; `checks[].reservationIds`에 권한 있는 충돌 예약을 반환 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **409 Conflict**: 서울 동·이동·작업 기준 자료 부족으로 필요한 검사 불가 (`REFERENCE_DATA_MISSING`)

---

## 7. 사례 매칭·동선 탐색 (Matching)

> 정책 참조: `W10~11` · `FR-MAT-01~06`, `FR-FLX-01~05` · [요구사항 §6.4~6.5](요구사항명세서(기능들).md#65-사례-점수와-기사-후보-구성) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### GET `/work-items/{workItemId}/case-recommendations` — 사례 기반 기사 추천 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 사례 평가 상태·추천 기사·점수·근거·미완료 사유를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | CaseRecommendationsDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 해당 기능의 필수 정보·사진 근거 부족 (`INSUFFICIENT_INPUT`)
- **422 Unprocessable Content**: 서울 밖 또는 확인 분야가 모두 미지원인 항목의 조건 충족 추천 요청 (`SERVICE_UNSUPPORTED`)

---

### GET `/work-items/{workItemId}/general-candidates` — 일반 기사 후보 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 분야·지역·시간 적합성과 미확인 사유를 포함한 일반 기사 후보를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**정렬**

`technician.technicianId` 오름차순. 사례 점수나 시간 적합성으로 순서를 바꾸지 않는다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<CandidateDTO> | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 후보 분야·지역을 판별할 사용자 확인 정보 부족; 사진쌍·사례·추정 소요 시간 부재만으로는 거절하지 않음 (`INSUFFICIENT_INPUT`)
- **422 Unprocessable Content**: 서울 밖 또는 확인 분야가 모두 미지원인 항목의 조건 충족 후보 요청 (`SERVICE_UNSUPPORTED`)

---

### PUT `/work-items/{workItemId}/route-exploration` — 동선 탐색 공개·중단

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 최소 공개 확인과 동선 탐색 활성 여부를 저장한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 `WorkItemDTO.revision`과 일치 | 리소스 버전 검사값; `Idempotency-Key` 미사용 |
| `enabled` | boolean | ✅ | 활성화 시 필수 정보 확인 | 탐색 시작·중단 |
| `confirmed` | boolean | - | `enabled=true`이면 필수·`true`; 중단이면 생략 가능 | 분야·동·시간·추정 시간 공개 확인 |

**재전송 응답**

성공 후 이전 `expectedRevision`으로 재전송하면 `409 VERSION_CONFLICT`이다. 상위 `GET /requests/{requestId}`의 `workItems`에서 해당 항목의 활성 여부·버전을 확인한다. 기대값만 바꾼 자동 재제출은 하지 않는다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | WorkItemDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: `enabled=true`인데 확인 분야·지역·방문 조건 또는 최소 공개 확인 부족; 추정 시간 미확인만으로는 거절하지 않음 (`INSUFFICIENT_INPUT`)
- **422 Unprocessable Content**: `enabled=true`인데 서울 밖 또는 확인 분야가 모두 미지원 (`SERVICE_UNSUPPORTED`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)

---

### GET `/technicians/me/route-candidates` — 기사 동선 추천 작업 조회

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 공개 확인된 최소 작업 정보·시간 적합성·동선 계산 근거를 반환한다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `date` | date | ✅ | 없음 | `Asia/Seoul` 기준 작업 시작일; 시작 후보는 `[00:00, 다음 날 00:00)`, 작업 전체는 사용자 가능 구간 안에 포함 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**정렬**

아래 그룹 순서로 반환하며, 각 그룹 안에서 명시한 키를 왼쪽부터 적용한다. 조회한 `date`에서 삽입 가능한 구간이 여러 개이면 추가 이동 시간이 가장 작은 구간의 `route.additionalMinutes`를 사용한다.

| 순서 | 응답 조건 | 그룹 내 정렬 |
| --- | --- | --- |
| 1 | `timeFit=MATCHED`, `route != null` | `route.additionalMinutes` 오름차순 → 요청 접수 시각 오름차순 → `candidateId` 오름차순 |
| 2 | `timeFit=MATCHED`, `route=null`; 효율만 미산정 | 요청 접수 시각 오름차순 → `candidateId` 오름차순 |
| 3 | `timeFit=UNKNOWN`; 작업·이동 검사 보완 필요 | 요청 접수 시각 오름차순 → `candidateId` 오름차순 |

`NOT_MATCHED` 항목은 목록에서 제외한다. 미산정은 0분으로 취급하지 않으며, 요청 접수 시각은 서버 정렬용 값으로 응답에 추가하지 않는다. 정렬 근거는 [요구사항 §6.4](요구사항명세서(기능들).md#64-동선-추천의-비교-기준)를 따른다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<RouteCandidateDTO> | 처리 결과 |

---

### POST `/route-candidates/{candidateId}/interests` — 상담 참여 의사 표시

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인; 탐색 공개 중
- **설명**: 추천 작업에 대한 본인의 참여 의사를 저장한다. 요청 본문은 없다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `candidateId` | string | 동선 추천용 식별자; 실제 형식 미정 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | InterestDTO | 처리 결과 |

**예외 응답**

- **403 Forbidden**: 자기 계정 요청의 기사 참여 시도 (`SELF_PARTICIPATION_FORBIDDEN`)
- **409 Conflict**: 동선 탐색 중단·최소 공개 철회 (`EXPLORATION_CLOSED`)

---

### GET `/work-items/{workItemId}/interests` — 참여 기사 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 항목에 참여 의사를 표시한 기사의 공개 정보를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | InterestDTO[] | 항목의 현재 조회 가능한 참여 의사 전체; `createdAt` 내림차순·동률 `interestId` 내림차순; 페이지 분할·개수 절단 없음 |

---

## 8. 상담 관계·견적 (Consultations)

> 정책 참조: `W12~13` · `FR-CON-01~04`, `FR-QTE-01~05` · [요구사항 §6.3](요구사항명세서(기능들).md#63-정보-전달-단계) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### POST `/work-items/{workItemId}/consultations` — 기사 선택·상담 요청

- **인증 요구사항**: ✅
- **선행 조건**: 소유자; 지역·방문 조건·요약 확인
- **설명**: 선택 기사와 확인 전달본을 입력받아 상담 관계를 생성한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `technicianId` | string | ✅ | 자기 기사 제외 | 선택 기사 |
| `deliveryId` | string | ✅ | 동일 항목·수신 기사; `CONSULTATION` 목적·최신 자료·가림·공개 확인 완료 | 요약·견적 전제(`includeQuoteContext=true`)를 포함한 상담용 전달본 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ConsultationDTO | 처리 결과 |

**예외 응답**

- **403 Forbidden**: 자기 계정 요청의 기사 참여 시도 (`SELF_PARTICIPATION_FORBIDDEN`)
- **409 Conflict**: 목적·수신자에 맞는 최신 전달 확인 없음 (`DELIVERY_NOT_CONFIRMED`)
- **409 Conflict**: 전달본의 공통·항목 전제 또는 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **422 Unprocessable Content**: 상담에 필요한 확인 분야·작업 지역·방문 조건·요약 또는 견적 전제 공개 누락 (`INSUFFICIENT_INPUT`)
- **409 Conflict**: 전체 종료 또는 삭제 중인 요청에 새 관계·자료 생성 시도 (`RESOURCE_CLOSED`)

---

### GET `/consultations` — 참여 상담 목록

- **인증 요구사항**: ✅
- **선행 조건**: 현재 역할의 당사자
- **설명**: 현재 역할로 참여한 상담과 허용된 자료를 페이지로 반환한다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `status` | ConsultationStatus | - | 전체 | 관계 상태 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**정렬**

`createdAt` 내림차순 → 동률 `consultationId` 내림차순.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<ConsultationDTO> | 처리 결과 |

---

### GET `/consultations/{consultationId}` — 상담 상세·전달 이력 조회

- **인증 요구사항**: ✅
- **선행 조건**: 관계 당사자
- **설명**: 해당 상담의 이벤트·견적·전달본 ID·공개 확인 견적 전제를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `consultationId` | string | 상담 관계 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ConsultationDTO | 처리 결과 |

---

### PATCH `/consultations/{consultationId}` — 상담 수락·거절·종료·해제

- **인증 요구사항**: ✅
- **선행 조건**: 관계 당사자; 액션별 권한
- **설명**: 역할별 상담 액션과 기대 버전을 입력받아 현재 상담 상태를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `consultationId` | string | 상담 관계 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `action` | ConsultationAction | ✅ | 현재 상태에서 유효한 전이 | 처리 액션 |
| `reason` | string | - | 자유 문자열 | 종료 사유 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ConsultationDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 항목에 활성 예약 존재 또는 상담 종료로 예약 취소 시도 (`ACTIVE_RESERVATION_EXISTS`)
- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)

---

### POST `/consultations/{consultationId}/quotes` — 견적 신규 발행·수정본 발행

- **인증 요구사항**: ✅
- **선행 조건**: 수락된 활성 상담의 기사
- **설명**: 공개 확인 전제와 기사 제안 조건으로 새 견적 버전을 발행한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `consultationId` | string | 상담 관계 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `contextDeliveryId` | string | ✅ | 본 상담·수신 기사·항목의 현재 유효한 견적 전제 확인본 | 조회한 `quoteContext.deliveryId`; `ConsultationQuoteContextDTO` 규칙 적용; 현재 항목의 `sourceRevision`과 단순 동등 비교 금지 |
| `terms` | QuoteTermsDTO | ✅ | 비용·시간·전제 검증 | 확정 비용·미확정 조건·방문 제안 |
| `replacesQuoteId` | string | - | 본 상담의 최신 미확정 견적 | 수정 발행 시 지정 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | QuoteDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 수락된 활성 상담·사용자 선택이 없음 (`CONSULTATION_NOT_ACTIVE`)
- **409 Conflict**: 항목에 활성 예약 존재 또는 상담 종료로 예약 취소 시도 (`ACTIVE_RESERVATION_EXISTS`)
- **409 Conflict**: 제안 구간의 기사 작업·이동 충돌; 다른 시간대 작업의 진행 사실만으로 견적 발행을 거절하지 않음 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: 공통·항목 사실 버전 또는 수정 대상 제안 버전 불일치; 무관한 참고 자료 추가만으로 적용하지 않음 (`VERSION_CONFLICT`)
- **409 Conflict**: 해당 견적 전제의 수신자·공개 범위·가림·사용자 확인이 미완료 또는 무효화됨 (`DELIVERY_NOT_CONFIRMED`)
- **409 Conflict**: 해당 전제가 실제 포함·참조한 근거 내용의 정정·삭제로 재확인 필요; 무관한 참고 자료 추가나 요약의 갱신 필요 표시만으로 적용하지 않음 (`STALE_SOURCE`)
- **409 Conflict**: 해당 제안의 작업·이동 검사를 완료하는 데 필요한 서울 대표 위치·이동 기준 자료가 없음; 공통 작업시간표 부재만으로는 거절하지 않음 (`REFERENCE_DATA_MISSING`)
- **409 Conflict**: 해당 제안 구간의 작업·이동 검사가 실제 종료 불명·재검사 미완료로 불가능함; 다른 구간의 초과 사실만으로 일괄 거절하지 않음 (`SCHEDULE_RECHECK_REQUIRED`)
- **422 Unprocessable Content**: 15분 단위·양수 소요 시간·사용자 방문 조건·`expiresAt ≤ startAt` 등 견적 입력 조건 위반 (`VALIDATION_ERROR`)
- **422 Unprocessable Content**: 다른 상담·항목·수신자의 견적 전제 전달본 참조 (`INVALID_REFERENCE`)
- **422 Unprocessable Content**: 음수·소수 원 금액·최소 비용 미확인·동일 조건 할인 위반 (`INVALID_COST`)

---

### PATCH `/quotes/{quoteId}` — 견적 철회·거절

- **인증 요구사항**: ✅
- **선행 조건**: 발행 기사 또는 요청 소유자
- **설명**: 발행 기사의 철회 또는 사용자의 거절 결과를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `quoteId` | string | 견적 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `action` | QuoteAction | ✅ | `WITHDRAW` 또는 `REJECT` | 선택 불가 처리 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | QuoteDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)

---

### GET `/work-items/{workItemId}/quotes` — 항목별 견적 비교

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 항목의 견적·선택 가능 여부·확정 및 미확정 비용을 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | QuoteDTO[] | 항목의 현재 조회 가능한 견적 전체; 선택 불가·대체된 견적도 상태와 함께 포함; `issuedAt` 내림차순·동률 `quoteId` 내림차순; 페이지 분할·개수 절단 없음 |

---

## 9. 예약·변경 합의 (Reservations)

> 정책 참조: `W14~15`, `W21` · `FR-RES-01~06`, `FR-WRK-08` · [요구사항 §6.2](요구사항명세서(기능들).md#62-예약견적-일관성-규칙) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### POST `/reservation-checks` — 예약·변경·시작 조건 사전 검사

- **인증 요구사항**: ✅
- **선행 조건**: 소유자 또는 관련 기사
- **설명**: 처리 종류별 사전 검사 결과·확인 식별값·허용 중복 정보를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `operation` | ReservationOperation | ✅ | 처리 종류 | 적용할 검사 규칙 |
| `quoteId` | string | - | 신규 확정이면 필수 | 선택할 견적 |
| `reservationId` | string | - | 신규 확정 외 필수 | 대상 예약 |
| `changeId` | string | - | 변경 검사이면 필수 | 최신 변경안 |
| `proposedStartAt` | dateTime | - | `START_WORK`의 조기 시작 동의 전 검사이면 필수; 현재 예약 `agreement.terms.startAt`보다 이른 시각; 다른 `operation`에는 전송 불가 | 사전 검사할 예상 시작 시각; 생략한 `START_WORK`는 조회 시점 서버 시각으로 검사 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationCheckDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 처리 종류별 필수 식별자·예상 시각 형식·범위 등 조건부 입력 오류 (`VALIDATION_ERROR`)

---

### PUT `/reservation-checks/{checkId}/confirmation` — 다른 기사 방문 중복 확인

- **인증 요구사항**: ✅
- **선행 조건**: 해당 요청 소유자
- **설명**: 표시한 방문 중복에 대한 사용자 확인을 저장한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `checkId` | string | 조건 검사 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `confirmed` | boolean | ✅ | `true` | 표시된 중복 전체 확인 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationCheckDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 중복 검사 대상·구간·조건이 변경됨 (`STALE_CHECK`)
- **409 Conflict**: 해당 처리의 기사 작업·이동 충돌; 실제 시작 검사에서는 같은 기사의 다른 실제 작업 진행 중도 포함 (`TECHNICIAN_CONFLICT`)

---

### POST `/work-items/{workItemId}/reservations` — 견적 선택·예약 확정

- **인증 요구사항**: ✅
- **선행 조건**: 소유자; 최신 견적·방문 정보 확인
- **설명**: 견적·방문 정보·전제 버전·중복 확인을 입력받아 확정 예약을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `quoteId` | string | ✅ | 최신 선택 가능 견적 | 해당 항목의 견적 |
| `versions` | QuoteVersionsDTO | ✅ | 최신 전제와 일치 | 공통·항목·제안 버전 |
| `visitDetailsRevision` | string | ✅ | 최신 사용자 확인 정보 | 주소·연락처 확인값 |
| `overlapConfirmation` | OverlapConfirmationDTO | - | 다른 기사 방문 중복 시 최신 확인 필수 | 본 API 또는 별도 확인 API의 사용자 확인 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 만료·철회·거절·대체·전제 변경·관계 종료로 선택 불가 (`QUOTE_UNAVAILABLE`)
- **409 Conflict**: 항목에 활성 예약 존재 또는 상담 종료로 예약 취소 시도 (`ACTIVE_RESERVATION_EXISTS`)
- **409 Conflict**: 반영 직전 방문 시작이 미래가 아니거나 30분 미만 (`INSUFFICIENT_LEAD_TIME`)
- **409 Conflict**: 확정할 구간의 기사 작업·이동 충돌; 다른 시간대 작업의 진행 사실만으로 미래 예약을 거절하지 않음 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 (`OVERLAP_CONFIRMATION_REQUIRED`)
- **409 Conflict**: 서울 동·이동·작업 기준 자료 부족으로 필요한 검사 불가 (`REFERENCE_DATA_MISSING`)
- **409 Conflict**: 초과 미갱신·종료 불명·일정 재검사 미완료로 확정 불가 (`SCHEDULE_RECHECK_REQUIRED`)
- **422 Unprocessable Content**: 서울 밖 또는 미지원 분야의 조건 충족 추천·예약 시도 (`SERVICE_UNSUPPORTED`)

---

### GET `/reservations` — 당사자 예약 목록

- **인증 요구사항**: ✅
- **선행 조건**: 현재 역할의 당사자
- **설명**: 현재 역할의 예약·실제 작업 상태를 페이지로 반환한다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `status` | ReservationStatus | - | 전체 | 예약 상태 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**정렬**

현재 `agreement.terms.startAt` 오름차순 → 동률 `reservationId` 오름차순. 상태 필터를 적용한 뒤 같은 순서로 반환한다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<ReservationDTO> | 처리 결과 |

---

### GET `/reservations/{reservationId}` — 예약·작업·인계 상세

- **인증 요구사항**: ✅
- **선행 조건**: 예약 당사자
- **설명**: 당사자에게 허용된 합의·변경안·실제 작업·인계 정보를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 예약 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationDTO | 처리 결과 |

---

### POST `/reservations/{reservationId}/cancellation` — 시작 전 예약 취소

- **인증 요구사항**: ✅
- **선행 조건**: 예약 당사자; 실제 시작 전
- **설명**: 합의 버전과 취소 사유를 입력받아 취소 결과를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 예약 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `agreementVersion` | string | ✅ | 현재 합의 | 경합 검사 |
| `reason` | string | - | 기사 취소 시 필수 | 취소 사유 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 실제 시작 후 일반 취소·시작 전 변경 시도 (`WORK_ALREADY_STARTED`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)

---

### POST `/reservations/{reservationId}/changes` — 시작 전·진행 중 변경안 제안

- **인증 요구사항**: ✅
- **선행 조건**: 예약 당사자
- **설명**: 변경 조건과 기준 합의 버전으로 새 변경안을 생성한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 예약 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `type` | ChangeType | ✅ | 실제 시작 여부에 맞게 지정 | 시작 전 또는 진행 중 |
| `agreementVersion` | string | ✅ | 최신 합의 | 기준 버전 |
| `terms` | ReservationChangeTermsInputDTO | ✅ | 유형별 변경 허용 범위와 방문 정보 참조 권한 | 새 범위·비용·종료·방문 조건; 상세 주소·연락처 직접 입력 없음 |
| `replacesChangeId` | string | - | 기존 미반영 변경안 | 재수정 대상 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationChangeDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 변경 유형별 필수·금지 필드·수량·비용·시간 단위·방문 정보 참조 조건 오류 (`VALIDATION_ERROR`)

---

### PATCH `/reservation-changes/{changeId}` — 변경안 수락·거절·철회

- **인증 요구사항**: ✅
- **선행 조건**: 예약 당사자; 동일 변경 버전
- **설명**: 동일 변경안 버전에 대한 수락·거절·철회 결과를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `changeId` | string | 예약 변경안 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `action` | ChangeAction | ✅ | 수락·거절은 상대; 철회는 제안자 | 제안자 제출 확인과 합산 |
| `overlapConfirmation` | OverlapConfirmationDTO | - | 사용자 수락 시 중복이 있고 유효한 저장 확인이 없으면 필수 | 사용자만 제출; 기사 수락은 생략하고 서버가 저장된 사용자 확인 검사 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationChangeDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **409 Conflict**: 변경 후 작업 구간과 기사 일정·이동의 충돌; 진행 중 변경 대상 작업 자체는 다른 작업과의 충돌로 취급하지 않음 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 (`OVERLAP_CONFIRMATION_REQUIRED`)
- **409 Conflict**: 시작 전 변경의 반영 직전 방문 시작이 미래가 아니거나 30분 미만; 진행 중 변경에는 적용하지 않음 (`INSUFFICIENT_LEAD_TIME`)

---

## 10. 실제 작업·방문 준비 (Work)

> 정책 참조: `W15`, `W19` · `FR-WRK-01~08`, `FR-HND-05` · [요구사항 §6.2](요구사항명세서(기능들).md#62-예약견적-일관성-규칙) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### PUT `/reservations/{reservationId}/early-start-consent` — 조기 시작 동의·철회

- **인증 요구사항**: ✅
- **선행 조건**: 요청 소유자; 시작 전
- **설명**: 현재 예약의 조기 시작 동의·철회와 동의 변경 식별값을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 예약 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `agreementVersion` | string | ✅ | 현재 예약 합의 | 동의 대상 |
| `expectedConsentRevision` | string? | ✅ | 조회한 `earlyStartConsent.revision`과 일치; `earlyStartConsent=null`일 때만 명시적 `null` | 동의 상태의 변경 식별값; 생략 불가; 예약 합의 버전과 별개 |
| `action` | ConsentAction | ✅ | 부여 또는 철회 | 사용자 확인 |
| `proposedStartAt` | dateTime | - | `GRANT`이면 필수; 현재 예약 `agreement.terms.startAt`보다 이르고 사전 검사·중복 확인의 예상 시각과 일치 | 사용자에게 제시한 검사·확인용 예상 시작 시각; 실제 시작 가능 시각을 제한하거나 실제 시작 시각을 대체하지 않음 |
| `overlapConfirmation` | OverlapConfirmationDTO | - | 새 중복이 있고 유효한 저장 확인이 없으면 `GRANT`에 필수 | 사용자 확인; `REVOKE`에는 불필요 |

**동의 버전·재전송 응답**

| 입력·조회 조건 | 응답 |
| --- | --- |
| 동의 기록 없음 | `earlyStartConsent=null`; 최초 변경의 기대값은 명시적 `null` |
| 최초 `REVOKE(null)` | `active=false`인 동의 객체와 새 `revision`; 이후 기대값은 이 값 사용 |
| 비활성 기록에 최신 기대값으로 `REVOKE` | 변경 없이 `200`; 같은 `revision` 유지 |
| 변경 성공 후 이전 기대값 재전송 | `409 VERSION_CONFLICT`; 현재 예약을 재조회 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 현재 예약 합의 또는 동의 변경 식별값이 요청의 기대값과 다름 (`VERSION_CONFLICT`)
- **409 Conflict**: 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 (`OVERLAP_CONFIRMATION_REQUIRED`)
- **422 Unprocessable Content**: `expectedConsentRevision` 생략, `GRANT`의 예상 시각 누락·잘못된 형식 또는 예약 시작 이상인 예상 시각 등 조건부 입력 오류 (`VALIDATION_ERROR`)

---

### POST `/reservations/{reservationId}/work-events` — 시작·중단 요청·중단·완료·종료 예상 갱신

- **인증 요구사항**: ✅
- **선행 조건**: 액션별 사용자 또는 담당 기사
- **설명**: 작업 이벤트와 조건부 입력을 저장하고 현재 예약·수행·검사 결과를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 예약 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `event` | WorkEventType | ✅ | Enum별 상태·권한 | 실제 작업 처리 |
| `agreementVersion` | string | ✅ | 최신 합의 | 경합 검사 |
| `reason` | string | - | 중단 요청·직접 중단이면 필수 | 사용자 요청 확인 중단은 기존 사유 연결 |
| `performance` | PerformanceDTO | - | 완료·중단이면 필수 | 원인·수행·미수행·부품·종료 위치 |
| `expectedEndAt` | dateTime | - | 예상 갱신이면 필수; 현재 이후·15분 단위 | 운영상 종료 예상 |
| `expectedEndEstimateRevision` | string | - | `UPDATE_EXPECTED_END`이면 필수, 그 외 전송 금지; 최신 값 일치 | 조회한 `ReservationDTO.endEstimateRevision`; 합의 버전과 별도로 종료 예상 경합 검사 |

**이벤트별 출력**

| 이벤트 | ReservationDTO의 출력 |
| --- | --- |
| `START` | `actualStartedAt`은 처리 서버 시각; `proposedStartAt`을 복사하거나 15분 단위로 반올림하지 않음 |
| `COMPLETE`, `STOP` | `actualEndedAt`은 처리 서버 시각; 종료 위치가 `null`이어도 종료 결과 반환, 위치·이동 미확인은 `checks`에 표시 |
| `UPDATE_EXPECTED_END` | 갱신된 종료 예상·출처·변경 식별값; 충돌은 `checks`로 반환, 오래된 기대값은 `409 VERSION_CONFLICT`; 최신 기대값의 동일 값·출처는 변경 없이 `200` |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 예약 시각 전 `START`에 필요한 현재 조건의 유효한 조기 시작 동의가 없음 (`EARLY_START_CONSENT_REQUIRED`)
- **409 Conflict**: `START`의 기사 작업·이동 충돌 또는 다른 실제 작업 진행 중 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: `START`로 생기는 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 (`OVERLAP_CONFIRMATION_REQUIRED`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 이벤트별 필수·금지 필드 또는 expectedEndAt의 미래 시각·15분 단위 조건 오류 (`VALIDATION_ERROR`)

---

### PUT `/reservations/{reservationId}/end-location` — 완료·중단 후 종료 위치 보완·정정

- **인증 요구사항**: ✅
- **선행 조건**: 해당 완료·중단 예약의 담당 기사
- **설명**: 종료 위치를 보완·정정하고 기존 종료 시각·상태를 유지한 예약을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 본인이 담당한 종료 예약 식별자 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedEndLocationRevision` | string | ✅ | 최신 `ReservationDTO.endLocationRevision` 일치 | 종료 위치 정정 경합 검사 |
| `endLocationId` | string? | ✅ | 확인한 동 대표 위치; 알 수 없으면 명시적 `null` | `performance.endLocationId`를 교체; 작업 지역으로 임의 대체 금지 |

**저장·재전송 응답**

| 조건 | 응답 |
| --- | --- |
| 최신 기대값·같은 위치 | 변경 없이 `200` |
| 이전 기대값 | `409 VERSION_CONFLICT`; 예약 상세로 반영 여부 확인 |
| 위치 저장 후 이동 검사 미완료 | `200`, 종료 상태·시각 유지, `checks[].status=RECHECK_REQUIRED` |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationDTO | 종료 기사에게 허용된 수행 정보·현재 검사 결과; 종료 관계의 공개 제한 유지 |

**예외 응답**

- **409 Conflict**: 완료·중단 상태가 아닌 예약 (`INVALID_STATE`)
- **409 Conflict**: 다른 종료 위치 정정이 먼저 반영됨 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 존재하지 않는 위치 식별자 (`INVALID_REFERENCE`)
- **422 Unprocessable Content**: 필수 필드 누락·입력 형식 오류 (`VALIDATION_ERROR`)

---

### PUT `/reservations/{reservationId}/preparation-notes` — 방문 준비사항 등록·수정

- **인증 요구사항**: ✅
- **선행 조건**: 해당 활성 예약 담당 기사
- **설명**: 장비·부품·현장 점검 준비사항을 저장한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 예약 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `preparation` | PreparationDTO | ✅ | 본인 활성 예약 | 준비사항 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PreparationDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)

---

## 11. 전달본·보고서·PDF (Handover)

> 정책 참조: `W18~19` · `FR-HND-01~05`, `FR-INF-01~02`, `FR-INF-05` · [요구사항 §6.3·§6.6](요구사항명세서(기능들).md#63-정보-전달-단계) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### POST `/work-items/{workItemId}/deliveries` — 가림·공개 범위 전달본 준비

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 근거·공개 범위·가림 입력으로 전달본 준비 작업을 접수한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `sourceRevision` | string | ✅ | 최신 자료와 일치 | 사용자에게 표시한 근거 자료 식별값 |
| `scope` | DeliveryScopeDTO | ✅ | 목적·수신자·자료 범위 검사 | 사용자 선택 공개 범위 |
| `redactions` | RedactionDTO[] | ✅ | 원본 참조 검증 | 수동 가림; 필요한 가림이 없으면 빈 배열 |
| `replacesDeliveryId` | string | - | 동일 항목·목적의 기존본 | 재작성 대상; 가림 자동 상속 없음, 편집한 `redactions` 전체를 필수 전송 |

**Response 202 Accepted**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DeliveryDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 목적별 필수 필드·대상별 가림 경로·문자열 가림 외 구조화 값 변경 등 입력 규칙 위반 (`VALIDATION_ERROR`)
- **409 Conflict**: 종료된 상담·취소 예약에 새 전달 시도 또는 목적·관계에 허용되지 않은 전달본 생성 (`INVALID_STATE`)
- **422 Unprocessable Content**: 종료 기사에게 종료 이후 자료 선택 또는 종료 당시 허용 범위 밖 자료 선택 (`INVALID_REFERENCE`)
- **422 Unprocessable Content**: 타 요청·타 항목·타 기사·삭제 자료 참조 (`INVALID_REFERENCE`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)

---

### GET `/work-items/{workItemId}/deliveries` — 본인 전달본·준비본 목록 복구

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 상담 전 준비본·외부 PDF용을 포함한 현존 본인 전달본을 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 본인 작업 항목 식별자 |

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `purpose` | DeliveryPurpose | - | 전체 | 상담·인계·외부 PDF 목적 필터 |
| `status` | ProcessingStatus | - | 전체 | 처리 상태 필터; 실패·갱신 필요도 조회 가능 |
| `cursor` | string | - | 없음 | 동일 필터의 이전 응답 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<DeliveryDTO> | 현존 본인 전달본·준비본 전체 상태; `createdAt` 내림차순·동률 `deliveryId` 내림차순; 결과 없음은 빈 `items`; 필드 공개는 상세와 동일 |

**예외 응답**

- **404 Not Found**: 대상 없음·삭제됨·권한 밖 존재 여부 차단 (`RESOURCE_NOT_FOUND`)
- **422 Unprocessable Content**: 잘못된 필터·페이지 입력 (`VALIDATION_ERROR`)

---

### GET `/deliveries/{deliveryId}` — 전달본 처리 상태·미리보기·열람

- **인증 요구사항**: ✅
- **선행 조건**: 소유자 또는 허용 수신자
- **설명**: 소유자의 처리 상태·허용 미리보기 또는 수신자의 최신 확인본을 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `deliveryId` | string | 전달본 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DeliveryDTO | 소유자의 처리 상태·허용 미리보기 또는 수신자의 최신 확인본 |

**예외 응답**

- **403 Forbidden**: 본인 소유 또는 현재 목적·수신자·관계의 열람 권한 없음 (`ACCESS_DENIED`); 존재 여부를 숨겨야 하는 대상은 `404`
- **404 Not Found**: 전달본 또는 상위 요청이 삭제되었거나 대상 없음·권한 밖 존재 여부 차단 (`RESOURCE_NOT_FOUND`)
- **409 Conflict**: 열람 권한이 있는 수신자에게도 처리 중·실패·갱신 필요·삭제 근거로 본문 제공 불가 (`DERIVED_CONTENT_UNAVAILABLE`); 소유자의 상태 조회에는 적용하지 않음
- **409 Conflict**: 수신자에게 제공할 `READY` 전달본의 최신 사용자 공개 확인이 없음 (`DELIVERY_NOT_CONFIRMED`)

---

### PUT `/deliveries/{deliveryId}/confirmation` — 처리 결과·공개 범위 확인

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 전달본 버전·근거·공개 범위의 사용자 확인을 저장한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `deliveryId` | string | 전달본 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `sourceRevision` | string | ✅ | 최신 자료와 일치 | 사용자에게 표시한 근거 자료 식별값 |
| `confirmed` | boolean | ✅ | `true`; 처리 성공 | 결과·공개 범위 확인 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DeliveryDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 확인 대상 버전 불일치 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 상담용 견적 전제의 필수 분야·지역·방문 조건 누락 또는 전체 제외 (`INSUFFICIENT_INPUT`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **409 Conflict**: 가림·메타데이터 제거 실패 또는 미완료 (`REDACTION_INCOMPLETE`)

---

### PUT `/work-items/{workItemId}/report` — 보고서 직접 작성·수정 초안

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 보고서·근거 버전과 본문을 입력받아 현재 초안을 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string? | ✅ | 편집 시작·AI 생성 요청 때 조회한 `ReportDTO.revision`과 일치; 보고서가 아직 없을 때만 명시적 `null` | 최초 생성 경합도 검사하며 생략 불가; 충돌 후에는 최신 본문을 확인하고 다시 편집 |
| `sourceRevision` | string | ✅ | 최신 자료와 일치 | 직접 편집은 조회한 근거, AI 초안 적용은 해당 AiJobDTO.sourceRevision; 이전 결과에 최신 값만 붙여 보내지 않음 |
| `report` | ReportBodyDTO | ✅ | 현존 근거 참조 | 직접 편집 또는 선택한 AI 초안의 사진과 Markdown 본문 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReportDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 보고서 생성·초안 수정·확인이 먼저 반영되어 기대 버전과 다름 (`VERSION_CONFLICT`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **422 Unprocessable Content**: 타 요청·타 항목·타 기사·삭제 자료 참조 (`INVALID_REFERENCE`)

---

### GET `/work-items/{workItemId}/report` — 본인 보고서·초안 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 본인 보고서의 초안·현재본·확인 상태를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReportDTO | 처리 결과 |

**예외 응답**

- **404 Not Found**: 대상 없음·삭제됨; 권한 밖 존재 여부 노출도 차단 (`RESOURCE_NOT_FOUND`)

---

### PUT `/work-items/{workItemId}/report/confirmation` — 최신 보고서 본문 확인

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 보고서 버전·근거에 대한 확인 결과와 현재 보고서를 반환한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `expectedRevision` | string | ✅ | 최신 값 일치 | 조회한 대상 리소스의 변경 식별값 |
| `sourceRevision` | string | ✅ | 최신 자료와 일치 | 사용자에게 표시한 근거 자료 식별값 |
| `confirmed` | boolean | ✅ | `true` | 본문·사진·촬영일 확인 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReportDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 확인 대상 버전 불일치 (`VERSION_CONFLICT`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **409 Conflict**: 처리 중·실패·갱신 필요·삭제 근거로 파생 자료 제공 불가 (`DERIVED_CONTENT_UNAVAILABLE`)

---

### POST `/deliveries/{deliveryId}/pdf-jobs` — 사진 포함 PDF 생성

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 확인 전달본 버전으로 PDF 생성 작업을 접수한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `deliveryId` | string | 전달본 식별자; 실제 형식 미정 |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `deliveryRevision` | string | ✅ | 최신 확인 완료 | 공유 범위·근거 고정 |

**Response 202 Accepted**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PdfJobDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 목적·수신자에 맞는 최신 전달 확인 없음 (`DELIVERY_NOT_CONFIRMED`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **409 Conflict**: 가림·메타데이터 제거 실패 또는 미완료 (`REDACTION_INCOMPLETE`)

---

### GET `/deliveries/{deliveryId}/pdf-jobs` — 본인 PDF 작업 목록 복구

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 전달본별 현존 PDF 작업의 ID·처리 상태·오류를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `deliveryId` | string | 본인 전달본 식별자 |

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `status` | ProcessingStatus | - | 전체 | 처리 상태 필터 |
| `cursor` | string | - | 없음 | 동일 필터의 이전 응답 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<PdfJobDTO> | 현존 본인 작업 전체 상태; `createdAt` 내림차순·동률 `jobId` 내림차순; 결과 없음은 빈 `items`; 상위 전달본의 `STALE`만으로 조회 차단하지 않음 |

**예외 응답**

- **404 Not Found**: 대상 없음·삭제됨·권한 밖 존재 여부 차단 (`RESOURCE_NOT_FOUND`)
- **422 Unprocessable Content**: 잘못된 필터·페이지 입력 (`VALIDATION_ERROR`)

---

### GET `/pdf-jobs/{jobId}` — PDF 생성 상태 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: PDF 작업 상태·오류·현재 다운로드 가능 여부를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | 해당 종류의 비동기 작업 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PdfJobDTO | 처리 결과 |

---

### GET `/pdf-jobs/{jobId}/content` — 확인된 PDF 다운로드

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 권한과 최신성이 유효한 PDF 바이트를 첨부 파일로 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | 해당 종류의 비동기 작업 식별자; 실제 형식 미정 |

**Response 200 OK**

| 항목 | 값 |
| --- | --- |
| Content-Type | `application/pdf` |
| Content-Disposition | `attachment; filename="report.pdf"`; 개인정보 없는 고정 ASCII 파일명인 연동안 |
| Body | 사진·그림과 렌더링한 Markdown 본문을 포함한 PDF |
| 제외 정보 | 상담·견적·상세 주소·연락처·원본 URL·가림 전 원본·금지 메타데이터 |

**예외 응답**

- **409 Conflict**: 처리 중·실패·갱신 필요·삭제 근거로 파생 자료 제공 불가 (`DERIVED_CONTENT_UNAVAILABLE`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)

---

## 12. 본인 자료 삭제 (Deletion)

> 정책 참조: `W20~21` · `FR-INF-06~07` · [요구사항 §6.7](요구사항명세서(기능들).md#67-보관과-개별-삭제) · [FE·BE 작업 명세](FE-BE-분업작업.md)

### POST `/deletion-jobs` — 사진·일반 기록·요청 전체 삭제

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 삭제 대상·참조 정리 확인을 입력받아 삭제 작업을 접수한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `targetType` | DeletionTarget | ✅ | `PHOTO`, `RECORD`, `REQUEST` | 사용자 소유 대상만 |
| `targetId` | string | ✅ | 대상 유형과 일치 | 삭제 식별자 |
| `includeAllReferences` | boolean | ✅ | `true` | 공유 참조·파생 결과 정리 확인 |

**Response 202 Accepted**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DeletionJobDTO | 처리 결과 |

**예외 응답**

- **403 Forbidden**: 소유 권한 없음; 작업 생성 없이 거절 (`ACCESS_DENIED`)
- **404 Not Found**: 대상 없음·삭제됨 또는 존재 여부 비공개; 작업 생성 없이 거절 (`RESOURCE_NOT_FOUND`)
- **409 Conflict**: 본인 일반 기록·전체 삭제를 막는 활성 관계; 생성한 `REJECTED` 작업을 `currentState`로 연결 (`ACTIVE_RELATION_EXISTS`)

---

### GET `/deletion-jobs` — 삭제 작업 목록·재시도 대상 복구

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 원래 요청의 삭제 여부와 관계없이 본인 삭제 작업 ID·상태를 반환한다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `status` | DeletionStatus | - | 전체 | 처리 상태 필터; 실패 작업 복구에 사용 |
| `targetType` | DeletionTarget | - | 전체 | 삭제 대상 종류 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 | 1~100; 공통 페이지 규격 |

**정렬**

`createdAt` 내림차순 → 동률 `jobId` 내림차순. 재시도는 최초 작업 생성 시각을 바꾸지 않는다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<DeletionJobDTO> | 본인 삭제 작업의 식별자·상태·필요 조치; 없으면 빈 목록 |

---

### GET `/deletion-jobs/{jobId}` — 삭제 처리 상태 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 삭제 작업 상태·영향 범위·접근 차단·회복 사진 수를 반환한다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | 해당 종류의 비동기 작업 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DeletionJobDTO | 처리 결과 |

---

### POST `/deletion-jobs/{jobId}/retry` — 삭제 미완료 정리 재시도

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 실패한 삭제 작업을 기존 작업 ID로 재접수한다. 요청 본문은 없다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | 해당 종류의 비동기 작업 식별자; 실제 형식 미정 |

**Response 202 Accepted**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DeletionJobDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)

---

## 입출력 예시

식별자는 설명용이다. 필수 인증·헤더는 각 API 표를 따른다. 업무 흐름과 인수 조건은 [요구사항 §7](요구사항명세서(기능들).md#7-기능-확인-시나리오)을 참조한다.

### 해결 안내 응답

`GET /work-items/{workItemId}/solutions`의 `200` JSON이다. 두 경로의 상태·보완 입력을 독립적으로 표현한다.

```json
{
  "data": {
    "availablePaths": [
      "MANUFACTURER_AS"
    ],
    "selfHelp": {
      "status": "NOT_APPLICABLE",
      "guides": [],
      "missingFields": [],
      "message": "현재 조건에 적용 가능한 자가 해결 안내가 없습니다."
    },
    "officialService": {
      "status": "INFORMATION_REQUIRED",
      "routes": [],
      "missingFields": [
        "facts.product.manufacturer"
      ],
      "message": "공식 경로 안내를 위해 제조사를 입력해 주세요."
    },
    "selectedPath": null
  }
}
```

### 보고서 확인 요청

`PUT /work-items/{workItemId}/report/confirmation`, `Idempotency-Key: "report-confirm-example"`, `Content-Type: application/json`의 본문이다.

```json
{
  "expectedRevision": "report_v2",
  "sourceRevision": "source_v3",
  "confirmed": true
}
```

### AI 작업 요청과 정상 미수행 결과

`POST /requests/{requestId}/ai-jobs`의 요청 본문이다. Idempotency-Key를 함께 전송한다.

```json
{
  "type": "PHOTO_COMPARISON",
  "sourceRevision": "photo_group_v2",
  "photoGroupId": "group_example"
}
```

접수는 `202 AiJobDTO`이다. 비교쌍이 부족한 작업의 완료 후 `GET /ai-jobs/{jobId}`는 `200`이며, 아래는 `data`의 일부 필드만 발췌한 예시이다.

```json
{
  "status": "SUCCEEDED",
  "attempts": [],
  "error": null,
  "result": {
    "comparison": {
      "groupId": "group_example",
      "photoIds": [],
      "status": "NOT_PERFORMED",
      "chronologyKnown": false,
      "regions": [],
      "observations": [],
      "causeUnknown": true,
      "reason": "비교할 사진이 부족합니다.",
      "retakeGuide": [
        "같은 부위 사진과 촬영일을 보완해 주세요."
      ]
    }
  }
}
```

---

## 공통 에러 응답

### 공통 에러 응답 구조

> `W21`의 원인 코드·대상 필드·재시도·최신 상태·권한 여부·필요 조치를 반영한 `ErrorResponseDTO` 제안이다. 구현 코드가 없어 실제 응답 래퍼·필드·HTTP 매핑은 확인 필요이다. 아래 필드를 루트에 반환하며 `data`로 감싸지 않는다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `code` | string | 원인 코드 |
| `message` | string | 사용자에게 표시할 사유 |
| `fieldErrors` | FieldErrorDTO[] | 필드·파일별 사유; 없으면 빈 배열 |
| `retryable` | boolean | 요청 내용 보완 없이 재시도 가능한지; 실행 방법은 `requiredActions`와 공통 멱등 규칙 적용; 접수된 실패 작업을 같은 키로 새 작업으로 만드는 의미가 아님 |
| `permissionDenied` | boolean | 인증·인가 문제 여부 |
| `currentState` | ResourceStateDTO? | 권한 범위 내 최신 상태; 없거나 공개 불가이면 `null`; 삭제 작업의 거절·실패 연결은 `resourceType=DELETION_JOB`과 해당 작업 ID 사용 |
| `checks` | ScheduleCheckDTO[] | 일정·작업·이동 검사별 사유와 조치; 권한 있는 관련 예약 ID만 포함; 해당 없으면 빈 배열 |
| `requiredActions` | string[] | 재조회·입력 보완·관계 정리·수동 복귀 등 필요한 조치 |

중첩 경로는 `fieldErrors.0.field`처럼 표기한다. 일정 충돌 예약 ID는 `checks`에만 제공한다. 삭제 요청의 `403`·`404`에는 `currentState=null`을 반환한다.

### HTTP 상태 코드별 예외 조건

| HTTP Status | 에러 코드 | 예시 메시지 / 추가 정보 |
| --- | --- | --- |
| 400 Bad Request | `BAD_REQUEST` | 본문 구문·파트 형식·중복 JSON 객체 키 또는 multipart의 `metadata`·`source` JSON 문자열 구문이 올바르지 않음; 업로드 미저장 |
| 400 Bad Request | `IDEMPOTENCY_KEY_REQUIRED` | 필수 `Idempotency-Key` 요청 헤더 누락 |
| 400 Bad Request | `INVALID_IDEMPOTENCY_KEY` | 키가 빈 값이거나 큰따옴표로 감싼 ASCII 문자열 하나가 아님 |
| 401 Unauthorized | `AUTHENTICATION_REQUIRED` | 세션 쿠키 없음 또는 유효하지 않은·만료된·로그아웃된 세션 |
| 401 Unauthorized | `INVALID_CREDENTIALS` | 테스트 계정 인증 실패 |
| 403 Forbidden | `ACCESS_DENIED` | 소유·관계·자료 범위 권한 없음; 비공개 최신 상태는 제공하지 않음 |
| 403 Forbidden | `ROLE_FORBIDDEN` | 허용되지 않은 역할 또는 액션 |
| 403 Forbidden | `SELF_PARTICIPATION_FORBIDDEN` | 자기 계정 요청의 기사 참여 시도 |
| 404 Not Found | `RESOURCE_NOT_FOUND` | 대상 없음·삭제됨; 권한 밖 존재 여부 노출도 차단 |
| 409 Conflict | `IDEMPOTENCY_KEY_REUSED` | 같은 계정·Method·실제 경로·키로 다른 요청 내용 전송; `retryable=false` |
| 409 Conflict | `IDEMPOTENCY_IN_PROGRESS` | 같은 키의 최초 접수·상태 반영 처리 중; `retryable=true`이며 같은 키·내용으로 재전송 |
| 409 Conflict | `VERSION_CONFLICT` | 조회한 리소스·전제·합의 버전과 현재 값이 다름 |
| 409 Conflict | `STALE_SOURCE` | 근거 자료가 변경·삭제됨 |
| 409 Conflict | `STALE_CHECK` | 중복 검사 대상·구간·조건이 변경됨 |
| 409 Conflict | `RESOURCE_CLOSED` | 전체 종료 또는 삭제 중인 요청에 새 관계·자료 생성 시도 |
| 409 Conflict | `INVALID_STATE` | 허용되지 않은 상태 전이·처리 순서 |
| 409 Conflict | `PHOTO_LIMIT_EXCEEDED` | 동시 업로드를 포함한 요청 저장 사진 30장 초과 |
| 409 Conflict | `QUESTION_LIMIT_REACHED` | 새 `QUESTION` 발행 시 요청 전체 5개 한도 도달; 기존 다섯 번째 질문 답변·건너뛰기에는 미적용 |
| 409 Conflict | `EXPLORATION_CLOSED` | 동선 탐색 중단·최소 공개 철회 |
| 409 Conflict | `ACTIVE_RELATION_EXISTS` | 일반 기록·전체 삭제 또는 전체 종료를 막는 활성 관계 |
| 409 Conflict | `ACTIVE_RESERVATION_EXISTS` | 항목에 활성 예약 존재 또는 상담 종료로 예약 취소 시도 |
| 409 Conflict | `CONSULTATION_NOT_ACTIVE` | 수락된 활성 상담·사용자 선택이 없음 |
| 409 Conflict | `QUOTE_UNAVAILABLE` | 만료·철회·거절·대체·전제 변경·관계 종료로 선택 불가 |
| 409 Conflict | `INSUFFICIENT_LEAD_TIME` | 반영 직전 방문 시작이 미래가 아니거나 30분 미만 |
| 409 Conflict | `TECHNICIAN_CONFLICT` | 요청한 처리의 기사 작업·이동 충돌; `checks`에 원인·조치·권한 있는 관련 예약 ID 반환. 처리별 적용 조건은 개별 API 참조 |
| 409 Conflict | `OVERLAP_CONFIRMATION_REQUIRED` | 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 |
| 409 Conflict | `EARLY_START_CONSENT_REQUIRED` | 예약 시각 전 실제 시작에 필요한 현재 조건의 유효한 사용자 동의 없음 |
| 409 Conflict | `WORK_ALREADY_STARTED` | 실제 시작 후 일반 취소·시작 전 변경 시도 |
| 409 Conflict | `SCHEDULE_RECHECK_REQUIRED` | 요청한 구간의 일정 검사·반영 불가; `checks`에 종료 불명·재검사 미완료 사유와 필요한 조치 반환 |
| 409 Conflict | `REFERENCE_DATA_MISSING` | 요청 처리에 필수인 기준 자료 누락; `message`·`requiredActions`와 해당되는 `checks`에 누락 사유·보완 조치 반환 |
| 409 Conflict | `DELIVERY_NOT_CONFIRMED` | 목적·수신자에 맞는 최신 전달 확인 없음 |
| 409 Conflict | `REDACTION_INCOMPLETE` | 가림·메타데이터 제거 실패 또는 미완료 |
| 409 Conflict | `DERIVED_CONTENT_UNAVAILABLE` | 처리 중·실패·갱신 필요·삭제 근거로 파생 자료 제공 불가 |
| 413 Content Too Large | `FILE_TOO_LARGE` | 사용자 요청 사진 파일당 10,000,000 Byte 초과 |
| 415 Unsupported Media Type | `UNSUPPORTED_MEDIA_TYPE` | 실제 파일 형식 또는 Content-Type 미지원 |
| 422 Unprocessable Content | `VALIDATION_ERROR` | 해당 API의 필수·타입·범위·조건부 입력 오류; 대상 필드와 사유는 `fieldErrors`로 반환 |
| 422 Unprocessable Content | `UPLOAD_BATCH_REJECTED` | 묶음 내 손상 이미지·메타정보 불일치·파일별 오류; 전부 미저장 |
| 422 Unprocessable Content | `INVALID_REFERENCE` | 타 요청·타 항목·타 기사·삭제 자료 참조 |
| 422 Unprocessable Content | `ADDRESS_REGION_MISMATCH` | 상세 주소와 입력 작업 지역 불일치 |
| 422 Unprocessable Content | `SERVICE_UNSUPPORTED` | 서울 밖 또는 지원 분야 없음으로 판정된 항목의 조건 충족 추천·예약 시도; 상담 생성에 대한 적용 여부는 확인 필요. 지역·분야 미확인과 기준 자료 부족은 구분 |
| 422 Unprocessable Content | `ANALYSIS_NOT_SUPPORTED` | 벽지 물자국 외 사진 변화 분석 |
| 422 Unprocessable Content | `INSUFFICIENT_INPUT` | 해당 기능의 필수 정보·사진 근거 부족; 유효한 사진 묶음에서 비교쌍을 구성할 사진 부족은 정상 `NOT_PERFORMED` 결과로 구분 |
| 422 Unprocessable Content | `INVALID_COMPARISON_PAIR` | 다른 부위·같은 사진·유효하지 않은 비교쌍 |
| 422 Unprocessable Content | `GUIDE_NOT_APPLICABLE` | 적용 조건을 충족하지 않은 가이드 실행 경로 선택 |
| 422 Unprocessable Content | `INVALID_COST` | 음수·소수 원 금액·최소 비용 미확인·동일 조건 할인 위반 |
| 422 Unprocessable Content | `SOURCE_NOT_VERIFIED` | 준비 자료 출처·사용 가능 여부·비식별 검증 실패 |
| 500 Internal Server Error | `INTERNAL_ERROR` | 저장·내부 처리 실패; 상세 내부 정보는 미노출 |
| 503 Service Unavailable | `SERVICE_UNAVAILABLE` | 일시적 처리 불가; 재시도 가능 여부를 함께 반환 |

AI 처리 오류 코드는 `AI_TIMEOUT`, `AI_PROVIDER_ERROR`, `AI_OUTPUT_INVALID`이며 AiJobDTO.error로 반환한다. AI·PDF·삭제 작업의 처리 실패는 조회 HTTP 오류와 구분하여 `200`의 `status`·`error`로 제공한다. 전달본의 소유자 상태 조회와 수신자 열람 응답은 해당 API의 예외 표를 따른다.

---

## 식별자 / 자유 문자열 (Enum 아님)

| 필드 | 예시 | 비고 |
| --- | --- | --- |
| `Idempotency-Key` 요청 헤더 | `"550e8400-e29b-41d4-a716-446655440000"` | 클라이언트가 처리 한 번에 발급하는 고유 키; 같은 작업의 재전송에 재사용 |
| 계정·요청·항목·상담·견적·예약 ID | `req_example`, `item_example` | 설명용 예시; UUID·숫자 등 실제 형식 미정 |
| `candidateId`, `checkId` | `candidate_example`, `check_example` | 추천·확인용 불투명 ID; 비공개 요청 접근 권한 아님 |
| `regionId`, `locationId`, `referenceId` | `region_example`, `location_example` | 버전 관리 기준 자료 ID; 공인 행정코드 형식 미정 |
| `revision`, `sourceRevision`, 각 합의·전제 버전 | `rev_example` | 비교용 불투명 식별값; 본문 복원 이력 아님 |
| `manufacturer`, `modelName`, `productType` | `제조사 입력값`, `모델 입력값` | 자유 문자열·각각 모름 가능; Enum으로 제한하지 않음 |
| `part`, `workType`, `scope`, `reason`, `description` | `주방 싱크대 하부` | 사용자·기사 자유 입력; 길이 제한 미정 |
| `guideId`, `triggerId`, `questionId`, `optionId` | `guide_example` | 사전 등록 자료 또는 질문의 식별자 |
| `markdown`, `contact`, `SourceDTO.reference` | `보고서 본문`, `등록 연락수단` | 목적별 가림·검증 적용; 임의 URL·연락처 생성 금지 |

---

## 공통 DTO

> 타입은 `string`, `integer`, `number`, `boolean`, `date`, `dateTime`, `binary`, `T[]`, `T?`를 사용한다. `T?`는 `null` 가능, 배열은 별도 표기가 없으면 `null` 대신 빈 배열이다. `date`는 날짜, `dateTime`은 시간대 포함 시각이다. 입력 DTO 설명의 `✅`는 필수, `-`는 선택이다. 서버 계산·검증 필드는 입력으로 확정할 수 없다. 공통 DTO와 Enum 코드명은 모두 연동안이며 확인 필요이다.

### PageDTO<T>

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `items` | T[] | 빈 배열은 현재 조건의 결과 없음; 오류·평가 미완료와 구분 |
| `nextCursor` | string? | 다음 페이지 식별자; 마지막이면 `null` |

### SessionDTO

세션 식별자는 JSON에 넣지 않고 `Set-Cookie`로 반환한다. 만료 정보의 본문 제공 여부는 미정이다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `accountId` | string | 역할과 무관하게 유지되는 계정 ID |
| `activeRole` | Role | 현재 세션의 활성 역할 |
| `availableRoles` | Role[] | 전환 가능한 역할 |
| `technicianId` | string? | 연결된 기사 자원; 없으면 `null` |

### ServiceInfoDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `introduction` | string | 서비스 소개와 웹 이용 안내 |
| `fields` | ServiceField[] | 서울 전역 지원 5개 분야 |
| `regions` | ServiceRegionDTO[] | 서울 전역 지원 동; 행정/법정동 체계·코드는 확인 필요 |
| `referenceVersions` | ReferenceVersionsDTO | 지역·이동·작업시간표 버전·가정 |
| `emergencyTriggers` | TriggerDTO[] | 사전 정의 긴급 입력; 빈 배열은 등록 없음 |
| `retakeGuide` | string[] | 동일 부위·유사 구도·거리 촬영 안내 |

### TriggerDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `triggerId` | string | 구조화 긴급 입력 ID |
| `label` | string | 표시 문구 |
| `version` | string | 사전 정의 규칙 버전 |

### RegionValueDTO

입력·응답 공용 지역 값이다. 서울 밖 또는 기준 자료에 매핑되지 않은 지역도 표현하며, 응답의 `regionId`는 미매핑이면 `null`이다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `city` | string | ✅ 시·도; 서울 밖도 접수 가능 |
| `district` | string | ✅ 시·군·구 |
| `neighborhood` | string | ✅ 읍·면·동 |
| `regionId` | string? | - 기준 자료 ID; 미매핑이면 `null` |

### ServiceRegionDTO

지원 동 기준 자료의 조회용 타입이다. 일반 지역 값과 달리 `regionId`·`version`이 필수이며, 미매핑 지역을 이 타입으로 반환하지 않는다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `regionId` | string | 지원 동 기준 자료 식별자 |
| `city` | string | 시·도 |
| `district` | string | 시·군·구 |
| `neighborhood` | string | 읍·면·동 |
| `representativeLocationId` | string? | 동 대표 위치; 누락은 자료 보완 대상 |
| `version` | string | 지원 목록 버전 |

### SupportDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `status` | SupportStatus | 지원 여부와 정보·기준 자료 부족 구분 |
| `reasons` | string[] | 판정 근거; 시연 사례 부재를 지원 제외로 넣지 않음 |
| `missingFields` | string[] | 필요한 입력 경로; 없으면 빈 배열 |
| `demoDataAvailable` | boolean | 시연 자료 유무; 예약 지원 여부와 독립 |

### PublicTechnicianDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `technicianId` | string | 기사 자원 ID |
| `displayName` | string | 공개 표시명 |
| `fields` | ServiceField[] | 등록 전문 분야 |
| `regions` | ServiceRegionDTO[] | 활동 지역 |
| `contacts` | ContactDTO[] | 공개 중인 업무 연락수단만; 비공개 값은 제외 |
| `directContactAvailable` | boolean | 공개 연락수단 존재 여부 |
| `visitAvailability` | `"UNKNOWN"` | 고정 문자열 리터럴; 실제 방문 가능 여부는 이 응답에서 제공하지 않음 |

### ContactDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `label` | string | ✅ 전화·외부 연락수단 표시명 |
| `value` | string | ✅ 기사가 등록·확인한 공개 연락값; 형식별 검증 세부는 미정 |

### SourceDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `title` | string | ✅ 자료명·제공자 |
| `reference` | string | ✅ 원자료 위치 또는 출처 식별값; 비공개 저장소 URL 미노출 |
| `version` | string | ✅ 원자료 버전 |
| `verifiedAt` | date? | - 확인일; 미확인이면 `null` |
| `usageBasis` | string? | - 준비 자료 사용 가능 근거; 없으면 공개·평가 불가 |
| `verified` | boolean | 입력에서는 전송 금지; 출력에서는 필수인 서버 검증 결과 |

### GuidanceDTO

공개 안내·긴급 안내의 응답이다. 가이드와 공식 경로의 상태를 각각 반환한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `guide` | GuideResultDTO | 조회 종류에 해당하는 검증 가이드; 긴급 안내이면 긴급 대응 가이드 |
| `officialService` | OfficialServiceResultDTO | 공식 AS·지원·대안 경로 |

| 사용 위치·조회 종류 | `guide` | `officialService` |
| --- | --- | --- |
| `GET /public/guidance?type=EMERGENCY`, 요청·문답의 `emergencyGuidance` | 긴급 대응 가이드 결과 | 공식 지원·대안 경로 결과 |
| `GET /public/guidance?type=MANUFACTURER_AS` | `status=NOT_APPLICABLE`, `guides=[]`, `missingFields=[]`; `message`에 이 조회에서 가이드를 제공하지 않음을 표시 | 제조사 공식 AS 조회 결과 |

제조사 AS 조회의 빈 `guide`는 안내 자료 미등록을 뜻하지 않는다. 두 필드는 항상 반환하며 한쪽 상태로 다른 쪽 상태를 대체하지 않는다. `SolutionsDTO.selfHelp`는 아래 `GuideResultDTO`를 자가 해결 안내에 사용한다.

### GuideResultDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `status` | GuidanceStatus | 허용값: `AVAILABLE`, `INFORMATION_REQUIRED`, `NOT_REGISTERED`, `NOT_APPLICABLE`, `VALIDATION_FAILED`; 공식 경로 상태와 독립 |
| `guides` | GuideDTO[] | 제공 가능한 검증 가이드; 해당 결과가 없으면 빈 배열 |
| `missingFields` | string[] | 이 안내에 필요한 보완 입력 경로; 없으면 빈 배열 |
| `message` | string | 이 안내의 제공·보완·미등록·적용 불가·검증 실패 사유 |

| `status` | `guides` | `missingFields` |
| --- | --- | --- |
| `AVAILABLE` | 적용 가능한 검증 가이드가 1개 이상; `applicable=false`인 항목은 `steps=[]` | `[]` |
| `INFORMATION_REQUIRED` | `[]` | 보완할 입력 경로 1개 이상 |
| `NOT_REGISTERED` | `[]` | `[]` |
| `NOT_APPLICABLE` | `[]` 또는 적용 불가 조건·주의를 보여 주는 검증 가이드; 반환한 항목은 모두 `applicable=false`, `steps=[]` | `[]` |
| `VALIDATION_FAILED` | `[]`; 검증 실패한 내용을 반환하지 않음 | `[]` |

`type=MANUFACTURER_AS`의 `NOT_APPLICABLE`은 위 `GuidanceDTO`의 고정 빈 배열 규칙을 적용한다.

### OfficialServiceResultDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `status` | GuidanceStatus | 허용값: `AVAILABLE`, `INFORMATION_REQUIRED`, `NOT_REGISTERED`, `VALIDATION_FAILED`; `NOT_APPLICABLE`은 사용하지 않음 |
| `routes` | OfficialRouteDTO[] | 사전 확인된 공식 경로; 해당 결과가 없으면 빈 배열 |
| `missingFields` | string[] | 공식 경로 안내에 필요한 제품 등 입력 경로; 없으면 빈 배열 |
| `message` | string | 공식 경로의 제공·보완·미등록·검증 실패 사유 |

| `status` | `routes` | `missingFields` |
| --- | --- | --- |
| `AVAILABLE` | 검증된 공식 경로 1개 이상 | `[]` |
| `INFORMATION_REQUIRED` | `[]` 또는 제품별 정보 보완 전에도 확인 가능한 일반 공식 경로만; 각 항목은 `productSpecific=false` | 보완할 입력 경로 1개 이상 |
| `NOT_REGISTERED` | `[]`; 필요한 입력은 갖췄으나 등록 경로가 없음 | `[]` |
| `VALIDATION_FAILED` | `[]`; 경로 검증에 실패하여 제공 가능한 경로가 없음 | `[]` |

`INFORMATION_REQUIRED`는 정상 조회 결과이며 `422 VALIDATION_ERROR`와 구분한다. `missingFields`는 공개 조회에서는 `manufacturer` 등 쿼리 필드명, 항목별 조회에서는 `facts.product.manufacturer` 등 해당 입력 경로를 사용한다.

### GuideDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `guideId` | string | 등록 가이드 ID |
| `source` | SourceDTO | 출처·확인일·버전 |
| `applicable` | boolean | 현재 입력에 적용 가능한지 |
| `conditions` | string[] | 고정 적용 조건 |
| `steps` | string[] | 고정 순서·허용 절차; 적용 불가·검증 실패이면 빈 배열 |
| `supplies` | string[] | 필요 용품 |
| `warnings` | string[] | 필수 주의 |
| `prohibitions` | string[] | 금지 사항 |
| `stopConditions` | string[] | 필수 중단 기준; AI는 의미를 바꿀 수 없음 |

### OfficialRouteDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `label` | string | 등록된 공식 지원·예약 경로명 |
| `contact` | string | 검증된 URL 또는 연락처 |
| `productSpecific` | boolean | 제품별 경로인지 일반 공식 경로인지 |
| `source` | SourceDTO | 검증 출처·버전 |

### SolutionsDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `availablePaths` | ResolutionPath[] | 항목별 적용 가능한 경로 |
| `selfHelp` | GuideResultDTO | 자가 해결 가이드·상태·보완 입력 |
| `officialService` | OfficialServiceResultDTO | 공식 AS 경로·상태·보완 입력 |
| `selectedPath` | ResolutionPath? | 미선택이면 `null` |

### ProductDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `productType` | string? | - 제품 종류; 모름은 `null` |
| `manufacturer` | string? | - 제조사; 다른 필드와 독립적으로 모름 허용 |
| `modelName` | string? | - 모델명; 모름은 `null` |

### SymptomContextDTO

최초 요청 생성 시 `context`를 생략하거나 `null`로 보내면 아래 nullable 필드는 모두 `null`, `attemptedActions`는 `[]`인 객체를 저장·반환한다. 일부 하위 필드만 입력해도 나머지는 같은 기본값을 적용한다. `PATCH`에서는 생략한 하위 필드를 기존 값으로 유지한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `locationDescription` | string? | - 고장 부위; 상세 방문 주소와 별개 |
| `discoveredOn` | date? | - 최초 발견일; 업로드·수정일과 구분 |
| `conditions` | string? | - 발생 조건 |
| `recurring` | boolean? | - 반복 여부; 모르면 `null` |
| `attemptedActions` | string[] | - 시도한 조치; 미입력은 빈 배열 |

### RequestInputDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `symptom` | string | ✅ 증상 텍스트; 공백 불가 |
| `photos` | PhotoInputDTO[] | ✅ `files`와 수·순서 일치; 최초에는 항목 ID 생략 가능 |
| `context` | SymptomContextDTO? | - 증상 보충 정보; 생략·`null`이면 SymptomContextDTO의 최초 입력 기본값 적용 |
| `product` | ProductDTO? | - 기본 항목의 `facts.product`로 반환; 생략·`null`이면 제품 하위 필드는 모두 `null` |
| `region` | RegionValueDTO? | - 작업 지역; 추천·상담 전 보완 |
| `urgent` | boolean | - 사용자 긴급 표시; 생략 시 `false`라는 연동안 |

### RequestListItemDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 ID |
| `symptom` | string | 공통 증상 |
| `status` | RequestStatus | 전체 종료 상태 |
| `workItems` | WorkItemDTO[] | 항목별 독립 상태 |
| `updatedAt` | dateTime | 서버 최종 수정 시각 |

### RequestDTO

AI 작업 ID·결과 이력은 `GET /requests/{requestId}/ai-jobs`에서 조회한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `requestId` | string | 요청 ID |
| `revision` | string | 공통 편집 경합 검사값 |
| `commonVersion` | string | 장소 등 공통 사실 버전 |
| `sourceRevision` | string | 요청 공통 근거 식별값; 항목 처리에는 해당 항목의 값을 사용 |
| `status` | RequestStatus | 요청 전체 상태 |
| `symptom` | string | 공통 증상 |
| `urgent` | boolean | 사용자 긴급 표시 |
| `emergencyGuidance` | GuidanceDTO? | 긴급 표시·사전 정의 입력이면 검증된 안내; AI 완료와 독립 |
| `context` | SymptomContextDTO | 항상 객체를 반환; 최초 미입력 nullable 필드는 `null`, `attemptedActions`는 `[]` |
| `region` | RegionValueDTO? | 미입력이면 `null` |
| `support` | SupportDTO | 서비스 지원과 자료 유무 구분 |
| `visitDetails` | VisitDetailsDTO? | 본인 상세 방문 정보; 미입력 `null` |
| `visitDetailsRevision` | string? | 최신 확인값; 미확인 `null` |
| `photos` | PhotoCollectionDTO | 확인·미확인 촬영일 분리 |
| `workItems` | WorkItemDTO[] | 기본 항목과 사용자 추가 항목 |
| `dialogue` | DialogueDTO | 사용자와 AI 문답만 |
| `history` | HistoryEntryDTO[] | 항목별 상담·견적·예약·외부 결과·합의·수행 연결 |
| `closures` | ItemClosureDTO[] | 전체 종료 전에는 빈 배열 |
| `updatedAt` | dateTime | 서버 최종 수정 시각 |

### HistoryEntryDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string? | 공통 기록이면 `null` |
| `resourceType` | ResourceType | 이력 연결에는 `RECORD`, `CONSULTATION`, `QUOTE`, `RESERVATION`, `RESERVATION_CHANGE`만 사용; 외부 해결 결과는 `RECORD`, 합의·수행은 `RESERVATION`에 연결 |
| `resourceId` | string | 권한을 유지한 이력 자원 ID |
| `occurredAt` | dateTime | 이력 발생 시각 |
| `description` | string | 사용자 진술·기사 수행·합의 구분; 외부 대화 내용 없음 |

### VisitDetailsDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `address` | string | ✅ 상세 방문 주소; 요청 지역과 일치 검증 |
| `contact` | string | ✅ 방문 연락처; 검증 형식 미정 |

### ItemClosureDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | ✅ 해당 요청 항목 ID |
| `resolved` | boolean | ✅ `true` 해결, `false` 더 진행하지 않음 |
| `reason` | string? | - 미해결 종료이면 사유 필수 |

### TimeRangeDTO

실제 시작·종료와 그에 따른 중복 구간은 서버의 초 단위 시각을 유지한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `startAt` | dateTime | ✅ 시작 포함; 계획 방문 입력만 15분 단위 |
| `endAt` | dateTime | ✅ 종료 제외; 시작 이후; 계획 입력만 15분 단위 |

### VisitPreferenceDTO

유연 구간에는 작업 전체가 포함되어야 하며 이동시간은 별도 검사한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `mode` | VisitMode | ✅ 특정 시각 또는 유연 구간 |
| `fixedStartAt` | dateTime? | 특정 시각이면 필수; 15분 단위 |
| `ranges` | TimeRangeDTO[] | 유연 구간이면 1개 이상; 특정 시각이면 빈 배열 |

### WorkItemFactsDTO

독립 항목 생성·현재 사실 조회의 공용 구조이다. 부분 수정은 WorkItemFactsPatchDTO를 사용한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `part` | string? | ✅ 사용자 확인한 부위; 독립 항목 생성 시 확인 필수; 미확인 조회값은 `null` |
| `workType` | string? | ✅ 작업 종류; 독립 항목 생성 시 확인 필수; 미확인 조회값은 `null` |
| `quantity` | number? | ✅ 확인 시 양수; 미확인은 `null`; 단위는 확인 필요 |
| `fields` | ServiceField[] | ✅ 확인한 지원 분야 집합; 분야 미확인 또는 `otherField`로 기록한 미지원 분야이면 빈 배열; 지원 여부는 별도 판정 |
| `otherField` | string? | - 미지원 분야 설명; 기록 허용 |
| `product` | ProductDTO | ✅ 각 필드 독립적으로 모름 허용 |
| `visitPreference` | VisitPreferenceDTO? | - 최초 접수에서 미입력 가능; 상담 전 보완 |

### WorkItemFactsPatchDTO

모든 필드는 선택이다. 생략한 하위 필드는 유지하고 전송한 배열은 전체 교체한다. `null`은 nullable 필드를 미확인으로 정정한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `part` | string? | - 부위; 값이 있으면 공백 불가; `null`은 미확인으로 정정 |
| `workType` | string? | - 작업 종류; 값이 있으면 공백 불가; `null`은 미확인으로 정정 |
| `quantity` | number? | - 확인 시 양수; `null`은 미확인으로 정정 |
| `fields` | ServiceField[] | - 확인한 지원 분야 집합; 빈 배열은 분야 미확인 또는 `otherField`로 설명한 미지원 분야이며 두 상태를 구분 |
| `otherField` | string? | - 미지원 분야 설명; `null`이면 설명 해제 |
| `product` | ProductPatchDTO | - 보완할 제품 하위 필드만 전송; 객체 자체의 `null` 불가 |
| `visitPreference` | VisitPreferenceDTO? | - 전송 시 방문 조건 전체를 교체; `null`이면 미입력 상태로 해제하며 확정 예약 합의는 별도 유지 |

### ProductPatchDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `productType` | string? | - 생략 유지; `null`은 제품 종류 모름 |
| `manufacturer` | string? | - 생략 유지; `null`은 제조사 모름 |
| `modelName` | string? | - 생략 유지; `null`은 모델명 모름 |

### WorkItemDTO

미확정 AI 분야·요약은 해당 항목의 `DIAGNOSIS` 작업에서 `result.fieldCandidates`·`result.summary`로 조회한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 ID |
| `requestId` | string | 상위 요청 |
| `revision` | string | 항목 편집 경합 검사값 |
| `itemVersion` | string | 해당 항목 사실 버전 |
| `sourceRevision` | string | 해당 항목이 참조한 현재 자료 식별값 |
| `facts` | WorkItemFactsDTO | 현재 작업 사실; 미확인 기본 항목은 관련 단계 전 보완 |
| `status` | WorkItemStatus | 다른 항목·전체 종료와 독립 |
| `summary` | SummaryDTO? | 아직 작성·확인하지 않았으면 `null` |
| `reviewStatus` | ReviewStatus | 초안·확인 완료·갱신 필요 |
| `aiUseStatus` | AiUseStatus | AI 미선택·미완료·완료; 사용자 확인과 독립 |
| `resolutionPath` | ResolutionPath? | 선택 경로 |
| `support` | SupportDTO | 지원·정보 부족 판정 |
| `activeReservationId` | string? | 항목별 최대 1개 |
| `routeExplorationEnabled` | boolean | 최소 공개 확인된 동선 탐색 여부 |

### SummaryDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `text` | string | ✅ 증상 요약; 사진만으로 원인·안전·최종 비용 단정 금지 |
| `facts` | FactDTO[] | ✅ 관찰·사용자 진술·AI 추정·미확인 구분 |
| `unknowns` | string[] | ✅ 미확인 항목; 없으면 빈 배열 |
| `riskSignals` | string[] | - 참고용 위험 신호; 미입력·없음은 빈 배열 |
| `limitations` | string[] | - 사진 판단 한계; 없으면 빈 배열 |
| `onsiteInspectionNeeded` | boolean? | - 현장 확인 필요 여부; 판단 불가이면 `null` |

### FactDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `text` | string | ✅ 근거에 연결한 설명 |
| `sourceType` | FactSource | ✅ 정보 성격; 현장 확인은 연결된 기사 수행 근거가 있을 때만 |
| `photoIds` | string[] | ✅ 현존 근거 사진; 사진 근거 없으면 빈 배열 |
| `recordIds` | string[] | ✅ 현존 사용자 기록 근거; 없으면 빈 배열; 기사 수행 기록 ID로 사용하지 않음 |
| `performanceReservationIds` | string[] | ✅ 같은 항목의 `COMPLETED`·`STOPPED` 예약 중 수행 기록이 있는 ID; 입력 `FIELD_CONFIRMED`이면 1개 이상, 잘못된 참조는 `422 INVALID_REFERENCE`; 본인 조회는 ID, 기사 전달본·외부 PDF는 `[]` |

### PhotoInputDTO

최초 접수·사진 추가 업로드의 메타정보이다. 기존 사진의 `PUT` 수정에는 필수 필드가 구분된 `PhotoUpdateInputDTO`를 사용한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `capturedOn` | date? | - 사용자가 확인한 촬영일; 모름은 `null` |
| `dateConfirmed` | boolean | ✅ `true`일 때 촬영일 필수; `false`이면 `capturedOn=null` |
| `description` | string? | - 사진 설명 |
| `workItemIds` | string[] | - 이 사진을 참조할 같은 요청 항목; 최초는 기본 항목에 연결 |

### PhotoUpdateInputDTO

`PUT /photos/{photoId}`의 `metadata`에 사용하는 전체 교체 입력이다. 아래 네 필드를 모두 보내야 하며 하나라도 생략하면 `422 VALIDATION_ERROR`이다. `null`·빈 배열은 기존 값 유지가 아닌 명시적 해제이다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `capturedOn` | date? | ✅ 확인한 촬영일; `dateConfirmed=true`이면 날짜, `false`이면 명시적 `null` |
| `dateConfirmed` | boolean | ✅ 촬영일 확인 여부; `capturedOn`과 일치해야 함 |
| `description` | string? | ✅ 사진 설명; `null`이면 기존 설명 해제 |
| `workItemIds` | string[] | ✅ 같은 요청의 유효한 항목 ID, 중복 불가; `[]`이면 항목별 참조를 모두 해제하고 요청 공통 사진으로 유지 |

사진 파일은 별도 `file` 파트를 생략하면 유지한다. 항목 참조 해제는 사진 삭제가 아니며 사진 삭제 API를 대신하지 않는다.

### PhotoDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `photoId` | string | 요청 사진 ID; 공유 참조도 1장으로 계산 |
| `revision` | string | 사진 수정 식별값 |
| `media` | MediaDTO | 소유자에게만 원본 조회 허용 |
| `capturedOn` | date? | 사용자가 확인한 실제 촬영일; 경과 정렬·비교 기준; 미확인 `null` |
| `suggestedCapturedOn` | date? | EXIF 촬영일 후보; 자동 확정하지 않음 |
| `dateConfirmed` | boolean | 사용자 날짜 확인 여부 |
| `description` | string? | 현재 사진 설명 |
| `workItemIds` | string[] | 공유 참조 항목; `[]`이면 항목별 참조가 없는 요청 공통 사진 |
| `uploadedAt` | dateTime | 서버 최초 업로드 시각; 과거 사진도 현재 접수 시각을 기록하며 정정·파일 교체 후에도 유지 |
| `updatedAt` | dateTime | 서버 최종 수정 시각; 촬영일·파일·설명 정정 시 갱신; 촬영 선후 판정에 사용하지 않음 |

### MediaDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `mediaId` | string | 보호된 이미지 자원 ID; 원본 저장소 URL 아님 |
| `contentType` | string | 검증된 미디어 형식 |
| `sizeBytes` | integer | Byte 단위 크기 |
| `width` | integer | 표시 방향 정규화 후 가로 px |
| `height` | integer | 표시 방향 정규화 후 세로 px |

### PhotoCollectionDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `confirmedDatePhotos` | PhotoDTO[] | 촬영일·사진 ID 순; 없으면 빈 배열 |
| `unknownDatePhotos` | PhotoDTO[] | 날짜 미확인 별도 묶음 |
| `storedCount` | integer | 삭제 완료 전까지 포함한 요청 저장 사진 수 |
| `remainingCount` | integer | `30 - storedCount` |

### RecordContentDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `occurredOn` | date? | - 실제 경과 날짜; 모름 허용 |
| `description` | string | ✅ 증상·조치·결과·보완 사실 |
| `photoIds` | string[] | ✅ 같은 요청 사진; 없으면 빈 배열 |
| `workItemIds` | string[] | ✅ 관련 항목; 요청 공통이면 빈 배열 |

### OutcomeContentDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `path` | ResolutionPath | ✅ 자가 해결·공식 AS·직접 연락만 허용 |
| `result` | OutcomeResult | ✅ 해결·미해결·이용 불가 |
| `action` | string | ✅ 사용자가 시도한 조치 |
| `description` | string | ✅ 사용자 진술의 결과 |
| `occurredOn` | date? | - 조치 날짜 |
| `photoIds` | string[] | ✅ 본인 요청 사진; 없으면 빈 배열 |

### RecordDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `recordId` | string | 사용자 기록 ID |
| `revision` | string | 수정 식별값 |
| `record` | RecordContentDTO | 현재 기록; 외부·자가 결과의 날짜·설명·사진은 outcome과 동일하게 반환 |
| `outcome` | OutcomeContentDTO? | 외부·자가 결과이면 반환 |
| `sourceType` | FactSource | 사용자 작성은 `USER_STATEMENT` |
| `updatedAt` | dateTime | 서버 수정 시각 |

### PhotoGroupInputDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `groupId` | string? | - 신규는 `null`; 기존 묶음 변경은 ID 지정 |
| `label` | string | ✅ 같은 부위 설명 |
| `photoIds` | string[] | ✅ 같은 요청·동일 부위 사진 |
| `selectedPhotoIds` | string[] | ✅ 기본 선택은 빈 배열; 수동이면 서로 다른 2장 |

### PhotoGroupDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `groupId` | string | 부위 묶음 ID |
| `sourceRevision` | string | 묶음의 현재 비교 근거 버전; AI 접수·결과에 사용하며 요청 전체 버전과 구분 |
| `label` | string | 동일 부위 설명 |
| `photoIds` | string[] | 포함 사진 |
| `selectedPhotoIds` | string[] | 저장한 선택 방식; 기본은 `[]`, 수동은 서로 다른 두 ID; 수동 선택 사진이 삭제·이탈하면 `[]`와 `reason` 반환 |
| `comparisonPhotoIds` | string[] | 기본·수동 선택된 서로 다른 두 ID; 기본은 확인 촬영일 최초·최신, 동률 ID순; 부족하면 `[]` |
| `chronologyKnown` | boolean | 미확인 날짜·동일 날짜이면 `false` |
| `reason` | string? | 기본쌍 제외·자료 부족 사유 |

### TimelineDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `sourceRevision` | string | 요청 공통 근거 식별값; `RequestDTO.sourceRevision`과 동일하며 사진 묶음·비교쌍·촬영일 변경을 포함; 묶음 구성 편집에 사용하고 비교 분석에는 `groups[].sourceRevision` 사용 |
| `photos` | PhotoCollectionDTO | 날짜 확인 여부별 사진 |
| `records` | RecordDTO[] | 실제 경과 날짜 기준; 날짜 미확인은 별도 표시 |
| `groups` | PhotoGroupDTO[] | 묶음·비교쌍 |
| `retakeGuide` | string[] | 재촬영 안내 |

### DialogueDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `revision` | string | 문답 변경 식별값 |
| `completedRounds` | integer | 요청 전체 누적 답변·건너뛰기 횟수; `0~5`; 같은 질문을 다시 전송해도 증가하지 않음 |
| `finished` | boolean | 정보 충분으로 추가 질문 없이 정상 종료, 사용자 `FINISH` 또는 다섯 번째 답변·건너뛰기 완료 시 `true`; 새 질문 발행 불가 |
| `questions` | QuestionDTO[] | 발행된 질문을 발행 순서로 반환; 미발행이면 빈 배열; 생성 실패는 질문으로 추가하지 않음 |
| `emergencyGuidance` | GuidanceDTO? | 긴급 입력에 해당하면 AI와 독립적으로 반환 |

### QuestionDTO

`answer=null`, `optionId=null`, `skipped=false`이면 미응답이다. 답변 가능 여부에는 `DialogueDTO.finished`도 확인한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `questionId` | string | 요청 내 고유 질문 ID; 답변·건너뛰기 및 재전송 대상 식별값 |
| `text` | string | 질문 하나 |
| `options` | QuestionOptionDTO[] | 구조화 선택지; 자유 답변이면 빈 배열 |
| `answer` | string? | 자유 답변 전·건너뛰기·선택지만 제출했으면 `null` |
| `optionId` | string? | 선택지 답변이면 해당 ID; 자유 답변·건너뛰기·미응답이면 `null` |
| `skipped` | boolean | 건너뛰기 여부; 동일 질문 재전송으로 횟수 증가 금지 |

### QuestionOptionDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `optionId` | string | 선택지 ID |
| `label` | string | 표시 내용 |
| `triggerId` | string? | 사전 정의 긴급 규칙 연결; 없으면 `null` |

### AiJobDTO

작업 조회는 실패·시간 초과에도 `200`이며 처리 오류는 `error`로 반환한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | AI 작업 식별자 |
| `type` | AiJobType | 처리 종류 |
| `requestId` | string | 소유 요청 |
| `workItemId` | string? | 항목 단위 작업의 대상; `QUESTION`·`PHOTO_COMPARISON`이면 `null` |
| `photoGroupId` | string? | `PHOTO_COMPARISON`의 대상 사진 묶음; 그 외 `null` |
| `guideId` | string? | `GUIDE_EXPLANATION`의 대상 가이드; 그 외 `null` |
| `sourceRevision` | string | 실행 당시 입력의 근거 식별값; 종류별 기준은 AI 접수 API 표 참조 |
| `status` | AiJobStatus | 대기·처리·성공·실패·시간 초과 |
| `receivedAt` | dateTime | 서버 접수 시각 |
| `startedAt` | dateTime? | 시작 전 `null` |
| `finishedAt` | dateTime? | 미종결이면 `null` |
| `deadlineAt` | dateTime | 접수 시각 +60초; 자동 재시도에도 유지 |
| `attempts` | AiAttemptDTO[] | 외부 AI 최초·자동 재시도 기록; 최대 2회 시도; 대기 중 또는 사진 부족으로 호출 없이 정상 미수행이면 빈 배열 |
| `retryOfJobId` | string? | 수동 재시도의 원래 실패·시간 초과 작업; 신규 실행이면 `null` |
| `stale` | boolean | 관련 근거·비교쌍·가이드 버전 변경 또는 삭제로 현재 결과에 사용 불가; 작업 성공 여부와 별개 |
| `result` | AiResultDTO? | 성공한 결과; 미완료·실패·시간 초과·삭제 근거 차단 시 `null`; 성공해도 사용자 확인 전에는 미확정 |
| `error` | ErrorResponseDTO? | 실패·시간 초과 원인; 정상 비교 불가는 오류가 아님 |

| 조회·사용 조건 | 반환·선택 기준 |
| --- | --- |
| 현재 결과 (`QUESTION` 제외) | 같은 종류·대상·현재 근거의 `SUCCEEDED`, `stale=false`, `result != null` 중 `receivedAt` 내림차순·동률 `jobId` 내림차순 첫 결과 |
| 근거 버전 변경 | `stale=true`; 삭제 근거가 없는 과거 결과는 본인에게 과거 결과로 조회 가능 |
| 삭제 근거 포함 | `result=null`; 상위 요청 삭제는 작업 조회도 `404` |
| 현재 질문 | 답변 가능 여부·종료 상태는 RequestDTO.dialogue 기준 |

### AiAttemptDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `number` | integer | 시도 번호 `1~2` |
| `startedAt` | dateTime | 시도 시각 |
| `finishedAt` | dateTime? | 종료 전 `null` |
| `errorCode` | string? | 오류 식별자; 상세 AI 제공자 오류는 비공개 |

### AiResultDTO

해당 종류의 결과 필드만 채우고 나머지는 `null` 또는 빈 배열로 반환한다. 대상·최신성은 상위 AiJobDTO의 필드로 구분한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `summary` | SummaryDTO? | `DIAGNOSIS`의 대상 작업 항목 요약 초안; 사용자 확인 전에는 확정 요약이 아님 |
| `fieldCandidates` | ServiceField[] | `DIAGNOSIS`의 미확정 분야 후보; 후보 없음·다른 종류이면 빈 배열; 확인 전 `WorkItemDTO.facts.fields`에 자동 반영하지 않음 |
| `question` | QuestionDTO? | `QUESTION`; 정보 충분으로 정상 종료하면 `null`, 작업은 `SUCCEEDED`, `dialogue.finished=true`, 완료 횟수 유지 |
| `guideExplanation` | string? | `GUIDE_EXPLANATION`; 상위 `guideId`의 고정 가이드 의미 검증을 통과한 설명; 미실행·사용 불가이면 고정 가이드만 제공 |
| `caseRecommendations` | CaseRecommendationsDTO? | `CASE_MATCHING`; 사례 없음은 성공 결과의 빈 추천과 사유 |
| `comparison` | PhotoComparisonDTO? | `PHOTO_COMPARISON` 결과; 상위 `photoGroupId`와 동일한 묶음; 타임라인의 사진 묶음에 연결해 표시 |
| `reportDraft` | ReportBodyDTO? | `REPORT_DRAFT` 초안; 보고서 저장 시 생성 요청 때 조회한 보고서 버전과 이 작업의 sourceRevision을 사용 |

### PhotoComparisonDTO

상위 작업의 처리 상태와 아래 비교 결과 상태는 별개이다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `groupId` | string | 동일 부위 묶음 |
| `photoIds` | string[] | 선택한 서로 다른 두 사진; 부족하면 빈 배열 |
| `status` | ComparisonStatus | 변화 있음·없음·비교 불가·자료 부족 미수행 |
| `chronologyKnown` | boolean | 날짜 미확인·동일 날짜이면 `false`; 악화·호전 선후 단정 금지 |
| `regions` | EvidenceRegionDTO[] | 변화 없음은 빈 배열; 비교 불가에는 단정 영역 없음 |
| `observations` | FactDTO[] | 외형 관찰과 근거; 내부 원인·위험·실제 면적 확정 금지 |
| `causeUnknown` | boolean | 변화 판정과 독립적인 원인 미확인 |
| `reason` | string? | 비교 불가·미수행 사유 |
| `retakeGuide` | string[] | 필요할 때 재촬영 안내 |

| 비교 결과 | 필드 값 |
| --- | --- |
| 유효 묶음의 비교쌍 부족 | 작업 `SUCCEEDED`, `attempts=[]`, `error=null`; 비교 `NOT_PERFORMED`, `photoIds=[]`, `chronologyKnown=false`, `regions=[]`, `observations=[]`, `causeUnknown=true`, 사유·보완 안내 반환 |
| 유효한 두 사진의 시각적 비교 불가 | 작업 `SUCCEEDED`, 비교 `INCOMPARABLE`, 사유·재촬영 안내 반환 |
| AI 처리 실패·시간 초과 | 작업 `FAILED`·`TIMED_OUT`, `result=null`, 작업의 `error` 반환 |

### EvidenceRegionDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `photoId` | string | 근거 사진 |
| `width` | integer | 표시 방향 정규화 후 가로 px |
| `height` | integer | 표시 방향 정규화 후 세로 px |
| `box` | BoundingBoxDTO | 해당 사진 좌표 |
| `description` | string | 영역의 관찰 설명 |

### BoundingBoxDTO

길이 4인 JSON 배열 `[x_min, y_min, x_max, y_max]`이다. 표의 필드는 배열 인덱스이며 웹·PDF에서 같은 정규화 이미지 방향을 사용한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `0` | number | ✅ `x_min`; 좌상단 원점; `0 ≤ x_min < x_max ≤ 1` |
| `1` | number | ✅ `y_min`; `0 ≤ y_min < y_max ≤ 1` |
| `2` | number | ✅ `x_max`; 우측 경계 |
| `3` | number | ✅ `y_max`; 하단 경계 |

### TechnicianProfileContentDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `displayName` | string | ✅ 공개 표시명 |
| `fields` | ServiceField[] | ✅ 전문 분야 |
| `regionIds` | string[] | ✅ 활동 지역 |
| `contacts` | ContactSettingDTO[] | ✅ 본인 연락수단; 빈 배열이면 공개 연락 불가 |
| `representativeMediaIds` | string[] | ✅ 본인 포트폴리오의 대표 자료; 없으면 빈 배열 |

### ContactSettingDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `contact` | ContactDTO | ✅ 기사가 등록한 업무 연락수단 |
| `isPublic` | boolean | ✅ 공개 여부; 중단 시 공개 응답에서 값 제거 |

### TechnicianDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `technicianId` | string | 계정에 연결된 본인 기사 자원 |
| `profileRevision` | string | 연결된 기사 자원 생성 시 발급; 프로필 내용·공개 설정 변경 시 갱신; 프로필 최초 등록도 현재 값으로 검사 |
| `profile` | TechnicianProfileContentDTO | 비공개 설정 포함; 본인 전용 |
| `portfolio` | PortfolioDTO | 본인 프로필 사진·사례 |

### PortfolioDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `representativePhotos` | MediaDTO[] | 공개 가능한 대표 사진만 프로필 설정 순서로 반환; 미지정이면 빈 배열; 아래 전체 사진과 중복 포함 가능 |
| `technicianId` | string | 소유 기사 |
| `photos` | MediaDTO[] | 공개 검증 범위 또는 본인 자료 |
| `cases` | CaseDTO[] | 별도 준비된 사례; 없는 경우 빈 배열 |

### CaseContentDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `title` | string | ✅ 사례 제목 |
| `fields` | ServiceField[] | ✅ 해당 분야 |
| `initialSymptom` | string | ✅ 최초 증상 |
| `confirmedCause` | string? | ✅ 원인 미확인이면 `null`; AI 추정과 구분 |
| `workDescription` | string | ✅ 작업 내용 |
| `parts` | string[] | ✅ 부품; 없으면 빈 배열 |
| `beforeMediaIds` | string[] | ✅ 본인 프로필의 전 사진 |
| `afterMediaIds` | string[] | ✅ 본인 프로필의 후 사진 |
| `dataType` | CaseDataType | ✅ 이번 시연은 모의·재현만 허용 |
| `source` | SourceDTO | ✅ 별도 준비 출처·사용 가능 근거 |

### CaseDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `caseId` | string | 사례 식별자 |
| `technicianId` | string | 담당 기사 |
| `revision` | string | 정정·추천 최신성 검사값 |
| `content` | CaseContentDTO | 원문·출처·모의 구분 |
| `beforePhotos` | MediaDTO[] | 검증된 전 사진 |
| `afterPhotos` | MediaDTO[] | 검증된 후 사진 |

### ExternalVisitDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `externalVisitId` | string? | - 기존 외부 일정이면 ID; 신규는 `null` |
| `range` | TimeRangeDTO | ✅ 작업 시간 |
| `locationId` | string | ✅ 동 대표 위치 |
| `description` | string? | - 기사 본인에게만 보이는 설명 |

### ScheduleDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `revision` | string | 편집 경합 검사값 |
| `availability` | TimeRangeDTO[] | 가능한 구간 |
| `externalVisits` | ExternalVisitDTO[] | 본인 외부 일정 |
| `reservations` | ReservationDTO[] | 서버 관리 예약; 일정 편집으로 덮어쓰기 불가 |
| `travelSegments` | TravelSegmentDTO[] | 현재 일정 순서의 이동 계산 결과; 작업 구간과 구분하여 표시하고 누락 자료·충돌도 항목별 반환 |
| `departureLocationId` | string? | 기준 출발 위치; 누락은 미확인 |
| `returnLocationId` | string? | 기준 복귀 위치 |
| `checks` | ScheduleCheckDTO[] | 이동·충돌·재검사 결과; 종료 위치·이동 자료 누락 또는 재검사 미완료 구간은 `RECHECK_REQUIRED` |
| `openRanges` | TimeRangeDTO[] | 재검사 완료 후 개방한 잔여 구간만 포함; 자료 누락·미완료 구간은 제외하며 개방할 구간이 없으면 빈 배열 |
| `referenceVersions` | ReferenceVersionsDTO | 같은 동 내부 이동도 기준표 적용 |

### TravelSegmentDTO

기사 본인 일정표의 조회용 계산 결과이다. 작업 구간과 구분하며 시각은 서버의 초 단위를 유지한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `from` | TravelEndpointDTO | 직전 작업 또는 기준 출발 위치 |
| `to` | TravelEndpointDTO | 다음 작업 또는 기준 복귀 위치 |
| `departureAt` | dateTime? | 서버 계산 출발 시각; 종료 불명·위치 미확인으로 기준을 정할 수 없으면 `null` |
| `arrivalAt` | dateTime? | `departureAt + minutes`; 필요한 값이 없으면 `null`과 `checks` 사유 반환 |
| `minutes` | number? | 고정 모의 이동표의 음수가 아닌 분; 같은 동도 등록값 사용, 자료가 없으면 `null` |
| `checks` | ScheduleCheckDTO[] | 해당 이동의 충족·충돌·충돌 가능·재검사 필요와 사유 |
| `referenceVersions` | ReferenceVersionsDTO | 이 구간 계산에 사용한 위치·이동 자료 버전과 가정 |

### TravelEndpointDTO

본인 일정 식별자·대표 위치만 반환하며 고객 이름·연락처·상세 주소는 포함하지 않는다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `type` | TravelEndpointType | 기준 출발·예약·외부 일정·기준 복귀 |
| `resourceId` | string? | 예약이면 본인 담당 `reservationId`, 외부 일정이면 본인 `externalVisitId`; 기준 출발·복귀이면 `null` |
| `locationId` | string? | 해당 계산의 동 대표 위치; `from`이 완료·중단 예약이면 확인된 실제 종료 위치, `to`가 예약이면 해당 합의 작업 장소, 외부 일정은 등록 위치; 미확인이면 `null` |

### ReferenceVersionsDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `regionVersion` | string? | 지원 동·대표 위치 자료 버전 |
| `travelVersion` | string? | 동 내부·동 간 고정 모의 이동표 버전 |
| `durationVersion` | string? | 공통 작업시간표 버전 |
| `assumptions` | string[] | 실제 도로 이동·도착을 보장하지 않는 모의 계산 가정 |

### DurationEstimateDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `minutes` | integer? | 추천 추정 시간; 기준표에 없으면 `null` |
| `referenceId` | string? | 작업 종류·수량별 기준표 항목 |
| `version` | string? | 기준표 버전 |
| `technicianConfirmed` | boolean | 추정은 `false`; 견적은 기사 확인 시간 별도 사용 |

### CandidateDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `technician` | PublicTechnicianDTO | 공개 프로필 |
| `matchedFields` | ServiceField[] | 일치 분야 |
| `unsupportedFields` | ServiceField[] | 이 기사가 지원하지 않는 확인 분야 |
| `timeFit` | FeasibilityStatus | 적합·부적합·미확인; 미확인은 예약 가능이 아님 |
| `durationEstimate` | DurationEstimateDTO | 출처 있는 추정 또는 미확인 |
| `checks` | ScheduleCheckDTO[] | 확인한 조건과 부족한 조건 |

### ScoredCaseDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `case` | CaseDTO | 관련 원문·담당 기사 연결 |
| `score` | integer | `1~5`; 채택·평균 대상은 3 이상 |
| `evidence` | string[] | 최초 증상·확인 원인·작업·부품의 원문 근거 |

### CaseRecommendationDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `candidate` | CandidateDTO | 분야·지역·시간 검사 통과 기사 |
| `cases` | ScoredCaseDTO[] | 점수 내림차순 상위 최대 3개; 동점은 사례 ID순 |
| `averageScore` | number | 반올림 전 평균으로 순위 결정; 1~2개는 해당 평균 |
| `rank` | integer | 평균 내림차순; 동률 기사 ID순; 최대 5 |

### CaseRecommendationsDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `evaluationStatus` | EvaluationStatus | 미실행·처리 중·완료·미완료 구분 |
| `sourceRevision` | string | 평가 근거 식별값 |
| `stale` | boolean | 관련 입력·사례 변경으로 갱신 필요 |
| `recommendations` | CaseRecommendationDTO[] | 중복 없는 적합 상위 최대 5명 |
| `reason` | string? | 연관 사례 없음·적합 기사 없음·평가 미완료 등을 구분 |

### RouteCandidateDTO

요청·계정 ID, 자유 증상, 사진, 문답, 상세 주소·연락처는 반환하지 않는다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `candidateId` | string | 비공개 요청 접근에 사용할 수 없는 추천용 ID |
| `fields` | ServiceField[] | 최소 공개 확인 분야 |
| `region` | ServiceRegionDTO | 시·군·구·동까지만 공개 |
| `visitPreference` | VisitPreferenceDTO | 최소 공개 확인 방문 조건 |
| `durationEstimate` | DurationEstimateDTO | 기사 확인 전 추정·미확인 구분 |
| `timeFit` | FeasibilityStatus | 작업·이동 검사 불가이면 `UNKNOWN` |
| `route` | RouteCalculationDTO? | 조회한 `date`와 사용자 가능 구간의 교집합 안에서 최소 추가 이동 근거; 미산정 `null` |
| `reason` | string? | 미산정·보완 사유 |

### RouteCalculationDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `insertionRange` | TimeRangeDTO | 조회한 한국 날짜에 시작하고 사용자 가능 구간 안에 작업 전체가 들어가는 삽입 구간; 다일 가능 조건 전체의 최적 구간을 뜻하지 않음 |
| `beforeLocationId` | string | 앞 일정의 동 대표 위치; 없으면 고정 출발 위치 |
| `requestLocationId` | string | 후보 동 대표 위치 |
| `afterLocationId` | string | 뒤 일정의 동 대표 위치; 없으면 고정 복귀 위치 |
| `beforeToRequestMinutes` | number | `이동(A,R)`; 실제 상세 주소·타 고객 정보 없음 |
| `requestToAfterMinutes` | number | `이동(R,B)` |
| `beforeToAfterMinutes` | number | `이동(A,B)` |
| `additionalMinutes` | number | `이동(A,R)+이동(R,B)-이동(A,B)`; 임의 0 보정 금지 |
| `referenceVersions` | ReferenceVersionsDTO | 이동·작업시간 자료 버전·가정 |

### InterestDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `interestId` | string | 참여 의사 ID |
| `candidateId` | string | 최소 공개 추천용 ID |
| `technician` | PublicTechnicianDTO | 참여 기사 |
| `createdAt` | dateTime | 서버 등록 시각 |

### ConsultationDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `consultationId` | string | 항목·기사별 독립 관계 |
| `workItemId` | string | 해당 항목만 접근 가능 |
| `technicianId` | string | 선택된 기사 |
| `revision` | string | 관계 변경 식별값 |
| `status` | ConsultationStatus | 대기·수락·거절·종료 |
| `createdAt` | dateTime | 서버 최초 상담 생성 시각; 수락·상태 변경 후에도 유지하며 목록 정렬에 사용 |
| `deliveryIds` | string[] | 현재 권한·최신성 검사 통과 자료만; 종료 유형에 따라 빈 배열 |
| `quoteContext` | ConsultationQuoteContextDTO? | 현재 유효한 공개 확인 전제; 미확인·무효·종료이면 `null`; 근거와 무관한 자료 추가만으로는 `null`로 바꾸지 않음 |
| `quoteContextUnavailableReason` | string? | 전제 재확인 등 필요한 조치; 전제 제공 시 `null`; 권한 밖 사실·개인정보는 포함하지 않음 |
| `quotes` | QuoteDTO[] | 해당 관계의 견적만 |
| `events` | RelationEventDTO[] | 선택·수락·거절·종료 이력; 대화 없음 |

### ConsultationQuoteContextDTO

가림 처리된 공개 확인 전제이다. 상세 주소·연락처·원본 접근 주소·다른 항목 및 기사 관계 정보는 포함하지 않는다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `deliveryId` | string | 이 전제를 확인한 상담용 전달본; 견적의 `contextDeliveryId`에 사용; 전달본 전체의 열람 권한을 보장하지 않음 |
| `commonVersion` | string | 전달본에 연결된 요청 공통 사실 버전; 견적 `terms.versions.commonVersion`에 사용 |
| `itemVersion` | string | 전달본에 연결된 항목 사실 버전; 견적 `terms.versions.itemVersion`에 사용 |
| `sourceRevision` | string | 전제 생성 당시 항목 근거의 추적값; 현재 전체 항목 값과 같을 필요는 없으며 전제 제공 여부는 아래 응답 조건 적용 |
| `region` | ServiceRegionDTO | 지원 범위 내 상담의 사용자 확인 작업 지역; 시·군·구·동 및 기준 위치 정보까지만 제공. 지원 범위 밖 상담 정책·지역 타입은 확인 필요 |
| `facts` | ConsultationWorkItemFactsDTO | 사용자 확인·공개 범위·가림을 적용한 해당 항목의 작업 전제 |
| `durationEstimate` | DurationEstimateDTO | 기준표의 출처·버전이 연결된 추정; 미등록이면 `minutes=null`, 견적에서 기사 확인 시간으로 보완 |

| 전제 조건 | 조회 값·새 견적 발행 응답 |
| --- | --- |
| 전제·참조 근거·공개 확인은 그대로, 무관한 자료만 추가 | 기존 quoteContext·deliveryId 유지; 전체 항목 sourceRevision 차이만으로 거절하지 않음 |
| 공통·항목 사실 버전 변경 | quoteContext는 `null`; 발행은 `409 VERSION_CONFLICT` |
| 실제 참조 근거 정정·삭제 | quoteContext는 `null`; 발행은 `409 STALE_SOURCE` |
| 공개 범위·가림·사용자 확인 무효 | quoteContext는 `null`; 발행은 `409 DELIVERY_NOT_CONFIRMED` |
| 상담 종료·선택 해제 | quoteContext는 `null`; 발행은 `409 CONSULTATION_NOT_ACTIVE` |

### ConsultationWorkItemFactsDTO

조회 전용이며 사용자가 공개 확인한 가림 결과만 반환한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `part` | string? | 해당 작업 부위; 미확인 또는 식별정보 가림·제외 후 공개 가능한 내용이 없으면 `null` |
| `workType` | string? | 작업 종류; 미확인 또는 식별정보 가림·제외 후 공개 가능한 내용이 없으면 `null` |
| `quantity` | number? | 확인된 양수 수량; 미확인 값은 `null`, 견적 발행 시 기사 확인 필요 |
| `fields` | ServiceField[] | 지원 범위 내 상담에서 사용자가 확인하고 공개한 분야는 1개 이상이며 가림으로 제거하지 않음; 미지원 분야 상담 허용 여부·표현은 확인 필요 |
| `otherField` | string? | 가림 처리한 미지원 분야 설명; 없으면 `null` |
| `product` | ProductDTO | 공개 가능한 제품 정보; 각 필드의 모름·가림으로 인한 제외는 `null` |
| `visitPreference` | VisitPreferenceDTO | 상담 전에 사용자가 확인한 방문 조건; 특정 시각·유연 구간 구분, 가림으로 제거하지 않음 |

### RelationEventDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `status` | ConsultationStatus | 전이한 관계 상태 |
| `occurredAt` | dateTime | 서버 시각 |
| `reason` | string? | 종료·거절 사유; 비공개 식별 정보 제거 |

### QuoteVersionsDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `commonVersion` | string | ✅ 요청 공통 사실 버전 |
| `itemVersion` | string | ✅ 해당 항목 사실 버전 |
| `proposalVersion` | string? | 신규 발행 입력은 `null`; 수정·선택은 최신 값 필수; 서버 발행 결과는 값 존재 |

### CostLineDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `category` | CostCategory | ✅ 공임·출장·진단·부품·추가 작업 |
| `description` | string | ✅ 비용 항목과 동일 비교 범위 |
| `confirmed` | boolean | ✅ 비용 확정 여부 |
| `beforeAmount` | integer? | 확정이면 필수; 할인 전 원 단위·음수 금지 |
| `afterAmount` | integer? | 확정이면 필수; 할인 후 원 단위·음수 금지; 할인 여부·상한은 동일 조건의 확정 항목 합계로 검사 |
| `condition` | string? | 미확정이면 발생 조건 필수; 미확정 금액은 양쪽 `null` |

### CostDTO

최소 비용의 생략·`null`은 `0`과 다르며 `INVALID_COST`이다. 명시적으로 없음이 확인된 경우 `0`을 입력한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `minimumVisitFee` | integer | ✅ 최소 발생 출장비; 없음 확인은 0원·미입력 금지 |
| `minimumDiagnosticFee` | integer | ✅ 최소 발생 진단비; 없음 확인은 0원·미입력 금지 |
| `lines` | CostLineDTO[] | ✅ 확정·미확정 항목; 최소 비용과 중복 합산하지 않음 |
| `discountCondition` | string? | - 기사 자율 할인 적용 시간·조건; 할인 시 필수 |

### PriceSummaryDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `beforeTotal` | integer | 확정 항목 할인 전 합계 B; 원 |
| `afterTotal` | integer | 확정 항목 할인 후 합계 A; 원 |
| `discountAmount` | integer | `B-A`; 음수 불가 |
| `discountRate` | number? | `(B-A)/B×100`; 소수 첫째 자리; B=0이면 `null`(해당 없음) |
| `minimumTotal` | integer | 최소 발생 출장비+진단비; 확정 합계에 다시 더하지 않음 |

### QuoteTermsDTO

응답의 QuoteDTO.endAt은 `startAt + durationMinutes`이다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `versions` | QuoteVersionsDTO | ✅ 공통·항목·제안 전제 |
| `fields` | ServiceField[] | ✅ 기사 확인 분야 |
| `scope` | string | ✅ 작업 범위 |
| `quantity` | number | ✅ 양수; 수량 단위 세부 규격은 확인 필요 |
| `durationMinutes` | integer | ✅ 기사 확인한 양수 15분 배수 |
| `startAt` | dateTime | ✅ 사용자 특정 시각 일치 또는 유연 구간 내 시작 |
| `expiresAt` | dateTime | ✅ 방문 시작 이하; 서버 시각 도달 시 만료 |
| `cost` | CostDTO | ✅ 비용·미확정 조건·할인 |

### QuoteDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `quoteId` | string | 견적 버전별 식별자 |
| `consultationId` | string | 수락된 상담 관계 |
| `workItemId` | string | 작업 항목 하나 |
| `technicianId` | string | 발행 기사 |
| `revision` | string | 철회·거절 등 경합 검사값 |
| `issuedAt` | dateTime | 서버 발행 시각; 수정본은 별도 견적 ID와 발행 시각 |
| `status` | QuoteStatus | 유효성 상태 |
| `terms` | QuoteTermsDTO | 제안 조건과 전제 버전 |
| `endAt` | dateTime | 기사 확인 시간으로 산출한 예상 종료 |
| `price` | PriceSummaryDTO | 서버 계산값 |
| `durationEstimate` | DurationEstimateDTO | 추천 시 추정; 기사 확인 시간과 구분 |
| `selectable` | boolean | 조회 시점 선택 가능 여부; 확정 직전 재검사 |
| `reasons` | string[] | 선택 불가 사유; 없으면 빈 배열 |
| `checks` | ScheduleCheckDTO[] | 작업·이동 검사 결과 |

### ScheduleCheckDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `status` | ScheduleCheckStatus | 충족·충돌·충돌 가능·재검사 필요 |
| `code` | string | 공통 에러 코드 또는 검사 규칙 식별값 |
| `reason` | string | 부족 조건·해소 방법; 타 고객 정보 미노출 |
| `reservationIds` | string[] | 열람 권한 있는 관련 예약만; 없으면 빈 배열 |

### ReservationCheckDTO

`checkId`는 처리 종류·대상·당시 조건을 묶는 불투명 식별값이며 예약 보장이 아니다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `checkId` | string | 현재 처리·대상·조건을 묶는 검사 식별값 |
| `operation` | ReservationOperation | 신규 확정·시작 전 변경·시작·진행 중 변경 |
| `reservationId` | string? | 검사 대상 예약; 신규 확정 검사이면 `null` |
| `agreementVersion` | string? | 검사한 예약의 기존 합의 버전; 신규 확정 검사이면 `null` |
| `changeId` | string? | 변경 검사 대상; 변경 검사가 아니면 `null` |
| `changeRevision` | string? | 검사한 변경안의 `revision`; 변경 검사가 아니면 `null` |
| `proposedStartAt` | dateTime? | 조기 시작 동의 전 검사에 제출한 예상 시작 시각; 현재 예약 시작보다 이른 값; 제출하지 않았거나 다른 처리이면 `null`; 실제 시작 가능 시각을 제한하지 않음 |
| `allowed` | boolean | 조회 시점 조건 충족 여부; 조건 불충족도 `200`과 `false`; 조기 시작 동의 전에도 checkId·합의 버전·권한별 중복 결과 반환 |
| `checks` | ScheduleCheckDTO[] | 부족 조건과 필요한 조치 |
| `overlaps` | VisitOverlapDTO[]? | 요청 소유자에게만 같은 요청의 다른 기사 방문 중복 상세 반환; 중복이 없으면 빈 배열; 기사에게는 `null`. 조기 시작은 검사 대상 시각부터 현재 유효 종료 예상까지 검사하며 종료 예상을 자동으로 당기지 않음 |
| `overlapConfirmationRequired` | boolean | 현재 검사에 사용자 중복 확인이 추가로 필요한지; 기사는 이 상태와 본인에게 허용된 검사 결과로 확인 필요 여부 조회 |
| `overlapConfirmed` | boolean | 표시된 대상·구간·조건에 대한 사용자 확인 |
| `checkedAt` | dateTime | 서버 검사 시각 |

### VisitOverlapDTO

요청 소유자 전용이다. 기사 응답의 overlaps는 `null`이며 상대 예약·항목·기사·시간을 별도 필드로 제공하지 않는다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 중복 상대 예약; 동일 요청만 |
| `workItemId` | string | 상대 작업 항목 |
| `technicianId` | string | 다른 기사 |
| `agreementVersion` | string | 상대 예약 현재 합의 |
| `range` | TimeRangeDTO | 실제 확인할 겹침 구간 |

### OverlapConfirmationDTO

사용자 입력 전용이며 기사는 전송하지 않는다. 유효한 저장 확인이 있거나 중복이 없으면 입력을 생략할 수 있다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `checkId` | string | ✅ 최신 검사 대상·구간·조건 식별값 |
| `confirmed` | boolean | ✅ `true`; 사용자만 제출 가능 |

| 입력·확인 조건 | 계약 |
| --- | --- |
| 변경안 확인 | 검사한 changeId·변경 버전에 연결된 checkId 사용; 다른 변경안 버전에는 재사용 불가 |
| 일반 시작·일반 START_WORK 확인 저장 | 시간 경과로 중복 구간만 줄고 상대 예약·합의·조건·종료 예상이 유지되면 저장한 확인 사용 가능 |
| 실제 조기 시작 | 같은 예약·현재 동의에 연결된 확인이며 현재 중복이 확인 범위 안이면 사용 가능; 실제 시각은 proposedStartAt보다 이를 수 있음 |
| 새로운 중복·확인 범위 확대·조건 변경 | 새 검사·확인 필요; 반영은 `409 OVERLAP_CONFIRMATION_REQUIRED`, 낡은 검사 확인 저장은 `409 STALE_CHECK` |
| 조기 시작 동의 전 확인 저장 | 아직 부여하지 않은 동의는 필수 입력이 아님; 동의 자체는 별도 API 사용 |

### ReservationChangeTermsInputDTO

주소·연락처·region은 직접 받지 않는다. `visitDetailsRevision` 생략 시 기존 방문 정보를 유지한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `fields` | ServiceField[] | ✅ 해당 항목의 변경 후 분야; 다른 항목을 합치지 않음 |
| `scope` | string | ✅ 변경 후 작업 범위 |
| `quantity` | number | ✅ 변경 후 양수 수량 |
| `cost` | CostDTO | ✅ 변경 후 확정·미확정 비용 조건 |
| `startAt` | dateTime | - `BEFORE_START`이면 필수·15분 단위; `IN_PROGRESS`이면 전송 불가하며 기존 예약 시작을 유지 |
| `expectedEndAt` | dateTime | ✅ 15분 단위; 시작 전은 시작 이후의 양수 15분 배수 소요 시간, 진행 중은 반영 직전 서버 현재 시각 이후 |
| `visitPreference` | VisitPreferenceDTO | ✅ 변경안에서 사용자가 확인할 방문 가능 조건 |
| `visitDetailsRevision` | string | - 시작 전 주소 변경 시 요청 소유자만 제출; `PUT /requests/{requestId}/visit-details`로 본인이 확인한 최신 값; 기사 또는 `IN_PROGRESS` 변경안에서는 전송 불가 |

### AgreementTermsDTO

확정 합의·변경안의 조회용 조건이다. 변경 입력은 ReservationChangeTermsInputDTO를 사용한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `fields` | ServiceField[] | 해당 조건의 분야 |
| `scope` | string | 해당 항목의 작업 범위 |
| `quantity` | number | 양수 수량; 다른 항목을 합치지 않음 |
| `cost` | CostDTO | 확정·미확정 비용 조건 |
| `startAt` | dateTime | 예약 시작; 진행 중 변경에서는 기존 값 유지; 실제 시작은 `ReservationDTO.actualStartedAt` |
| `expectedEndAt` | dateTime | 해당 조건의 예상 종료; 진행 중 변경의 반영 시점에는 서버 현재 이후여야 함 |
| `visitPreference` | VisitPreferenceDTO | 해당 조건의 사용자 방문 가능 범위 |
| `region` | RegionValueDTO | 해당 합의 장소; 사용자 확인 방문 정보와 연결하며 진행 중 실제 장소 소급 변경 불가 |
| `visitDetails` | VisitDetailsDTO? | 서버가 기존 합의 또는 사용자 확인값에서 연결한 방문 정보; 종료 기사에게는 `null` |

### AgreementDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `agreementVersion` | string | 확정 합의 버전; 별도 추가 세분화 없음 |
| `terms` | AgreementTermsDTO | 당시 합의 조건; 수신자별 식별 정보 제거 |
| `agreedAt` | dateTime | 양측 확인·서버 반영 시각 |

### ReservationChangeDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `changeId` | string | 변경안 ID |
| `reservationId` | string | 해당 예약 |
| `revision` | string | 변경안 버전; 재수정 시 이전 수락 무효 |
| `type` | ChangeType | 시작 전·진행 중 |
| `baseAgreementVersion` | string | 기준 확정 합의 |
| `proposerRole` | Role | 제안자; 제출 시 자기 버전을 확인 |
| `terms` | AgreementTermsDTO | 제안 조건; 반영 전 기존 합의 유지 |
| `visitDetailsRevision` | string? | 시작 전 주소 변경안이 참조한 사용자 확인값; 기존 장소 유지·진행 중 변경이면 `null` |
| `userAccepted` | boolean | 같은 버전 사용자 확인 |
| `technicianAccepted` | boolean | 같은 버전 기사 확인 |
| `status` | ChangeStatus | 제안·반영·거절·철회·대체·무효 |
| `overlapConfirmationRequired` | boolean? | 현재 변경안에 사용자 중복 확인이 추가로 필요하면 `true`, 불필요하면 `false`; 미검사·현재 조건으로 판정 불가이면 `null` |
| `checkedAt` | dateTime? | 위 판정과 `checks`의 검사 시각; 미검사이면 `null`; 실제 반영 결과를 보장하지 않음 |
| `checks` | ScheduleCheckDTO[] | 위 검사 시각의 결과; 미검사는 빈 배열, 판정 불가이면 가능한 사유 반환 |

### ReservationDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 예약 ID |
| `workItemId` | string | 해당 항목 하나 |
| `consultationId` | string | 해당 선택·수락 관계 |
| `quoteId` | string | 최초 확정에 선택한 견적 식별자 |
| `quoteVersions` | QuoteVersionsDTO | 최초 확정 당시 공통·항목·기사 제안 버전 보존 |
| `technicianId` | string | 담당 기사 |
| `status` | ReservationStatus | 예약·실제 작업 상태 |
| `agreement` | AgreementDTO | 현재 확정 합의 |
| `agreementHistory` | AgreementDTO[] | 이전 합의 보존; 개인정보는 현재 관계 권한으로 필터링 |
| `changes` | ReservationChangeDTO[] | 변경안 이력; 종료 시 미확정안은 무효 |
| `actualStartedAt` | dateTime? | 실제 시작 서버 시각; 미시작 `null` |
| `actualEndedAt` | dateTime? | 실제 완료·중단 서버 시각; 미종료 `null` |
| `currentExpectedEndAt` | dateTime | 현재 유효한 종료 예상; 조기 시작으로 자동 당기지 않음 |
| `endEstimateSource` | EndEstimateSource | 합의 또는 실제 지연에 대한 운영상 갱신 |
| `endEstimateRevision` | string | 예약 확정 시 발급; `currentExpectedEndAt` 또는 `endEstimateSource` 변경 시 갱신하며 합의 반영에 따른 변경도 포함; 합의 버전과 독립적인 운영상 갱신 경합 검사값 |
| `overdue` | boolean | 서버 시각이 종료 예상에 도달한 미종료 작업 |
| `earlyStartConsent` | EarlyStartConsentDTO? | 최신 동의·철회 상태; 부여·철회 기록이 한 번도 없을 때만 `null`; 비활성 기록도 변경 식별값과 함께 유지 |
| `overlaps` | VisitOverlapDTO[]? | 요청 소유자에게만 현재 중복·재확인 대상 반환; 없으면 빈 배열; 기사에게는 `null` |
| `overlapConfirmationRequired` | boolean | 현재 조건에 사용자 중복 확인이 추가로 필요한지; 기사에게도 표시하되 다른 기사 관계의 상세 정보는 제공하지 않음 |
| `checks` | ScheduleCheckDTO[] | 후속 충돌·가능 충돌·재검사 필요; 자동 변경 없음 |
| `reason` | string? | 취소·중단 요청·중단 사유 |
| `performance` | PerformanceDTO? | 종료 기사 수행 기록; 프로필 사진 자동 첨부 없음 |
| `endLocationRevision` | string? | 종료 위치 정정 경합 검사값; 완료·중단 반영 시 위치가 `null`이어도 발급하고 이후 위치 변경 시 갱신; 종료 전에는 `null` |
| `preparation` | PreparationDTO? | 장비·부품·점검 준비사항 |
| `handoverDeliveryIds` | string[] | 현재 관계에서 허용된 최신 인계본; 없으면 빈 배열 |

### EarlyStartConsentDTO

실제 시작은 서버 시각으로 반환하며 proposedStartAt은 검사·확인용 입력이다. 비활성 기록도 revision을 유지한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `revision` | string | 동의 변경 식별값; 부여·철회·무효화·사용 때 갱신, 다음 expectedConsentRevision에 사용; 비활성 상태에서도 이전 값 재사용·null 초기화 없음 |
| `agreementVersion` | string | 마지막 동의 부여 당시 예약 합의; 부여 전 최초 철회 기록이면 철회 당시 합의; 무효화된 과거 동의는 현재 예약 합의와 다를 수 있음 |
| `proposedStartAt` | dateTime? | 마지막 동의의 사전 검사·확인용 예상 시작 시각; 부여 당시 예약 시작보다 이른 값; 부여 전 최초 철회 기록이면 `null`; 실제 시작 가능 시각을 제한하지 않음 |
| `active` | boolean | 조건 변경·취소·철회·1회 사용 시 `false` |
| `confirmedAt` | dateTime? | 마지막 동의 부여 서버 시각; 부여 전 최초 철회 기록이면 `null`; 철회·무효화는 이 과거 시각을 새 동의 시각으로 바꾸지 않음 |

### PerformanceDTO

완료·중단 입력과 수행 조회의 공용 구조이다. 종료 시각은 ReservationDTO.actualEndedAt으로 반환한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `confirmedCause` | string? | ✅ 현장 확인 원인; 미확인은 `null` |
| `performed` | string[] | ✅ 실제 수행 내역; 없으면 빈 배열 |
| `notPerformed` | string[] | ✅ 미수행 내역; 완료 시 없으면 빈 배열 |
| `unknowns` | string[] | ✅ 미확인 사항 |
| `parts` | string[] | ✅ 실제 사용 부품 |
| `endLocationId` | string? | ✅ 실제 종료 동 대표 위치; 확인할 수 없거나 기준 자료가 누락되면 `null`; 작업 지역 대표 위치는 실제 종료 위치로 확인한 경우에만 사용하며 임의 기본값·추정값을 채우지 않음 |

### PreparationDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `equipment` | string[] | ✅ 장비; 없으면 빈 배열 |
| `parts` | string[] | ✅ 준비 부품 |
| `inspectionItems` | string[] | ✅ 현장 점검 항목 |
| `note` | string? | - 방문 준비 설명; 사용자와 기사 간 대화 저장 불가 |

### DeliveryScopeDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `purpose` | DeliveryPurpose | ✅ 상담·확정 기사 인계·외부 PDF |
| `recipientTechnicianId` | string? | 상담·인계이면 필수; 외부 PDF이면 `null` |
| `consultationId` | string? | 기존 상담 전달 시 필수; 최초 선택 전 준비본은 `null` |
| `reservationId` | string? | 인계이면 해당 활성 예약 또는 허용된 종료 예약 필수 |
| `photoIds` | string[] | ✅ 사용자 선택 사진; 없으면 빈 배열 |
| `recordIds` | string[] | ✅ 선택한 기록 |
| `questionIds` | string[] | ✅ 선택한 사용자와 AI 문답; 외부 PDF에는 상담 자료 제외 |
| `includeSummary` | boolean | ✅ 확인된 항목 요약 포함 여부 |
| `includeReport` | boolean | ✅ 인계·외부 PDF에는 최신 확인 보고서 필수 |
| `includeQuoteContext` | boolean | ✅ 상담용은 `true`, 인계·외부 PDF는 `false`; 상담에 필요한 공개 전제를 함께 확인 |

### RedactionDTO

텍스트 경로는 아래 DTO 기준이며 {i}·{j}는 0부터 시작하는 배열 인덱스이다. 원본 수정 입력과 구분한다.

| 대상 | 경로 기준 | 허용하는 텍스트 `fieldPath` |
| --- | --- | --- |
| `PHOTO` | 해당 `photoId`의 PhotoEvidenceDTO | `observation`, `regions.{i}.description` |
| `RECORD` | 해당 `recordId`의 RecordDTO | `record.description`, `outcome.action`, `outcome.description` |
| `QUESTION` | 해당 `questionId`의 QuestionDTO | `text`, `answer`, `options.{i}.label` |
| `SUMMARY` | 해당 항목의 SummaryDTO | `text`, `facts.{i}.text`, `unknowns.{i}`, `riskSignals.{i}`, `limitations.{i}` |
| `REPORT` | 해당 항목의 ReportContentDTO | `content.markdown`, `content.facts.{i}.text`, `content.unknowns.{i}`, `photos.{i}.observation`, `photos.{i}.regions.{j}.description` |
| `QUOTE_CONTEXT` | 해당 항목의 ConsultationQuoteContextDTO | `facts.part`, `facts.workType`, `facts.otherField`, `facts.product.productType`, `facts.product.manufacturer`, `facts.product.modelName` |

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `targetType` | RedactionTarget | ✅ 가림할 자료 종류 |
| `resourceId` | string | ✅ 사진·기록·질문 ID; 요약·보고서·견적 전제는 해당 `workItemId` |
| `fieldPath` | string? | 텍스트 가림이면 대상별 허용 경로 필수; 자료 전체 제외·사진 픽셀·파일명 가림이면 생략 또는 `null` |
| `exclude` | boolean | ✅ 경로 없으면 자료 전체 제외 여부; 경로 있으면 nullable 문자열만 `null`로 제외 가능; `QUOTE_CONTEXT` 전체 제외 불가 |
| `boxes` | BoundingBoxDTO[] | ✅ 사진 가림 영역; 해당 없으면 빈 배열 |
| `replacementText` | string? | - 지정 문자열의 가림 결과 전체; 텍스트 가림 시 필수; `exclude=true` 또는 픽셀·파일명 가림이면 생략 또는 `null` |
| `safeFilename` | string? | - 개인정보 없는 제공 파일명 |

**가림 입력 조합**

| 가림 종류 | 입력 조건 |
| --- | --- |
| 텍스트 대체 | fieldPath·replacementText 필수; 지정 문자열 전체의 가린 값 |
| 문자열 제외 | fieldPath와 exclude=true; nullable 문자열만 null로 제외 가능 |
| 자료 전체 제외 | fieldPath 생략 또는 null, exclude=true; 목적별 필수 본문·견적 전제 전체 제외 불가 |
| 사진 픽셀·파일명 | fieldPath 없이 boxes·safeFilename 사용; boxes는 없으면 빈 배열 |
| 잘못된 경로·인덱스·중복 지시·비문자열 변경 | 422 VALIDATION_ERROR |

### PhotoEvidenceDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `photoId` | string | 근거 식별자; 원본 접근 권한을 뜻하지 않음 |
| `media` | MediaDTO | 본인 원본 또는 목적별 가림 처리본 |
| `capturedOn` | date? | 확인 촬영일; `null`은 미확인 표시 |
| `observation` | string | 사진과 연결한 관찰 설명 |
| `regions` | EvidenceRegionDTO[] | 기존 유효 변화 표시; 없으면 빈 배열 |

### ReportBodyDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `markdown` | string | ✅ 발견 부위·날짜·조건·관찰·조치·결과·미확인을 구분한 본문 |
| `photoIds` | string[] | ✅ 현존 근거 사진; 전부 삭제 시 빈 배열 허용 |
| `facts` | FactDTO[] | ✅ 설명과 원본 근거 연결 |
| `unknowns` | string[] | ✅ 미입력·미확인 사항 |

### ReportContentDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `content` | ReportBodyDTO | 현재 본문·근거 |
| `photos` | PhotoEvidenceDTO[] | 본문과 함께 표시할 사진·촬영일·관찰 |
| `createdAt` | dateTime | 생성 시각; 촬영일과 별개 |

### ReportDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `revision` | string | 현재 초안·본문 확인 식별값; 최초 저장 시 발급하고 초안 변경·확인·무효화 시 갱신; 초안 저장과 확인의 경합 검사값 |
| `sourceRevision` | string | 참조 자료 최신성 식별값 |
| `reviewStatus` | ReviewStatus | 초안·확인 완료·갱신 필요 |
| `draft` | ReportContentDTO? | 보고서 저장 API로 반영한 직접 수정·AI 초안; 사용자 확인 전 본문 |
| `current` | ReportContentDTO? | 확인 후 교체한 현재본; 삭제 근거가 있으면 제공 차단 |
| `confirmedAt` | dateTime? | 현재 확인 없으면 `null` |

### DeliveryContentDTO

가림 결과만 반환한다. 원본 저장 경로·외부 PDF의 상세 방문 정보는 포함하지 않는다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `summary` | SummaryDTO? | 허용·확인된 가림 처리 요약 |
| `photos` | PhotoEvidenceDTO[] | 선택·가림 처리한 사진만 |
| `records` | RecordDTO[] | 선택·가림 처리한 보완 자료 |
| `dialogue` | QuestionDTO[] | 선택한 사용자와 AI 문답만 |
| `report` | ReportContentDTO? | 해당 목적의 확인 보고서; 금지 정보 제거 |
| `quoteContext` | ConsultationQuoteContextDTO? | 상담용 본인 미리보기·사용자 확인 후 활성 상담 수신자에게만 제공; 최초 준비본도 생성 가능; 인계·외부 PDF·종료 관계는 `null` |

### DeliveryDTO

필드의 권한·상태별 반환은 아래 표를 따른다. quoteContext 유효성과 전달본 본문 제공 여부는 별개이다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `deliveryId` | string | 목적·수신자별 전달본 ID |
| `workItemId` | string | 소속 작업 항목 |
| `createdAt` | dateTime | 서버 생성 접수 시각; 목록 정렬 기준 |
| `revision` | string | 가림·공개 범위 확인 대상 버전 |
| `sourceRevision` | string | 참조 근거 버전 |
| `scope` | DeliveryScopeDTO | 목적·수신자·선택 범위 |
| `redactions` | RedactionDTO[]? | 소유자에게만 원본·필드 경로·적용 대상 버전이 유효한 지시 전체; 가림 없음은 `[]`, 대상 정정·삭제로 복구 불가 또는 수신자 조회는 `null`; 처리 상태와 별도로 반환 가능 |
| `redactionsUnavailableReason` | string? | 소유자에게만 복구 불가 사유; 정상·수신자는 `null`; 과거 본문 없음, `redactions=null`을 가림 없는 `[]`로 해석하지 않음 |
| `status` | ProcessingStatus | 처리·준비·실패·갱신 필요 |
| `reviewStatus` | ReviewStatus | 처리 성공과 사용자 확인은 별개 |
| `content` | DeliveryContentDTO? | 소유자의 유효한 `READY` 미리보기 또는 수신자의 최신 확인본만; 소유자의 대기·처리 중·실패·갱신 필요 상태 조회는 `null` |
| `metadataRemoved` | boolean | 파일·이미지 메타데이터 제거 결과 |
| `confirmedAt` | dateTime? | 확인 전·무효화 시 `null` |
| `error` | ErrorResponseDTO? | 처리 실패·갱신 필요·차단 사유; 정상 대기·처리 중·유효한 준비 완료이면 `null` |

### PdfJobDTO

파일 조회 경로는 인증된 `/pdf-jobs/{jobId}/content`이다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | PDF 생성 작업 ID |
| `deliveryId` | string | 외부 공유용 확인 전달본 |
| `deliveryRevision` | string | 생성 대상 확인 버전 |
| `status` | ProcessingStatus | 처리 중·완료·실패·갱신 필요 |
| `createdAt` | dateTime | 서버 생성 접수 시각 |
| `completedAt` | dateTime? | 아직 생성되지 않았으면 `null` |
| `downloadAvailable` | boolean | 현재 최신성·권한 검사 결과; 다운로드 직전 재검사 |
| `error` | ErrorResponseDTO? | 실패·무효화 원인 |

### DeletionJobDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | 삭제 상태 추적 ID; 삭제 후에도 본인 결과 조회용 |
| `targetType` | DeletionTarget | 사진·일반 기록·요청 전체 |
| `targetId` | string | 삭제 대상 식별자 |
| `status` | DeletionStatus | 접수·처리·완료·거절·실패 |
| `createdAt` | dateTime | `REJECTED`를 포함한 추적 작업의 서버 최초 생성 시각; 재시도 후에도 유지하며 목록 정렬에 사용 |
| `affectedWorkItemIds` | string[] | 정리·재확인이 필요한 모든 참조 항목 |
| `affectedResourceIds` | string[] | 관련 파생 결과 ID; 삭제 본문·파일 없음 |
| `accessBlocked` | boolean | 접수·부분 실패 시 대상·파생 자료 차단 유지; 삭제 전 업무상 거절(`REJECTED`)은 `false` |
| `restoredPhotoSlots` | integer | 삭제 완료 사진 수만큼 회복; 미완료 0 |
| `error` | ErrorResponseDTO? | 거절·실패 사유와 필요한 조치 |

### FieldErrorDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `field` | string | `metadata.photos.0.capturedOn` 등 필드 경로 |
| `fileIndex` | integer? | 파일별 오류는 업로드 순서의 0부터 시작하는 인덱스 |
| `code` | string | 필드·파일 오류 코드 |
| `message` | string | 수정 가능한 사유; 민감 입력값 미반환 |

### ResourceStateDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `resourceType` | ResourceType | 상태·변경 식별값이 가리키는 자원 종류 |
| `resourceId` | string | 권한 내 대상 ID; 삭제 거절·실패 작업도 연결 가능 |
| `status` | ResourceStatus? | `resourceType`별 상태 타입 표의 코드 하나; 별도 상태 필드가 없는 자원은 `null` |
| `revision` | string? | 최신 값; 조회 권한 없으면 구조 전체 미반환 |

---

## Enum 정의

> 아래 영문 리터럴은 상태·의미를 구분하기 위한 코드 제안이다. 상태의 업무 의미는 기준 문서를 따르며 최종 코드명은 FE·BE 확인 필요이다.

### ResourceType

| 값 | 연결 자원 |
| --- | --- |
| `REQUEST` | RequestDTO |
| `WORK_ITEM` | WorkItemDTO |
| `PHOTO` | PhotoDTO |
| `RECORD` | RecordDTO; 외부·자가 해결 결과 포함 |
| `PHOTO_GROUP` | PhotoGroupDTO |
| `DIALOGUE` | DialogueDTO |
| `TECHNICIAN` | TechnicianDTO |
| `CASE` | CaseDTO |
| `SCHEDULE` | ScheduleDTO; `resourceId`는 기사 ID |
| `CONSULTATION` | ConsultationDTO |
| `QUOTE` | QuoteDTO |
| `RESERVATION` | ReservationDTO; 합의·수행 이력 포함 |
| `RESERVATION_CHANGE` | ReservationChangeDTO |
| `AI_JOB` | AiJobDTO |
| `REPORT` | ReportDTO; `resourceId`는 작업 항목 ID |
| `DELIVERY` | DeliveryDTO |
| `PDF_JOB` | PdfJobDTO |
| `DELETION_JOB` | DeletionJobDTO |

### ResourceStatus

자원별 기존 상태 Enum을 참조하는 조건부 타입이다. JSON에서는 문자열 하나 또는 `null`로 전송하며, 다른 자원 종류의 상태 코드는 허용하지 않는다.

| `resourceType` | `status` 타입·출처 |
| --- | --- |
| `REQUEST` | RequestStatus; `RequestDTO.status` |
| `WORK_ITEM` | WorkItemStatus; `WorkItemDTO.status` |
| `CONSULTATION` | ConsultationStatus; `ConsultationDTO.status` |
| `QUOTE` | QuoteStatus; `QuoteDTO.status` |
| `RESERVATION` | ReservationStatus; `ReservationDTO.status` |
| `RESERVATION_CHANGE` | ChangeStatus; `ReservationChangeDTO.status` |
| `AI_JOB` | AiJobStatus; `AiJobDTO.status` |
| `REPORT` | ReviewStatus; `ReportDTO.reviewStatus` |
| `DELIVERY` | ProcessingStatus; `DeliveryDTO.status`; 공개 확인 상태는 상세 DTO의 `reviewStatus` 사용 |
| `PDF_JOB` | ProcessingStatus; `PdfJobDTO.status` |
| `DELETION_JOB` | DeletionStatus; `DeletionJobDTO.status` |
| `PHOTO`, `RECORD`, `PHOTO_GROUP`, `DIALOGUE`, `TECHNICIAN`, `CASE`, `SCHEDULE` | `null`; 상태 Enum이 없는 자원은 `revision`으로 변경 여부 구분 |

### Role

| 값 | 설명 |
| --- | --- |
| `USER` | 사용자 |
| `TECHNICIAN` | 기사 |

### ServiceField

| 값 | 설명 |
| --- | --- |
| `PLUMBING` | 수도·배관 |
| `DOORS_WINDOWS` | 문·창호 |
| `WALLS_WALLPAPER` | 벽면·도배 |
| `ELECTRICAL` | 조명·전기설비 |
| `APPLIANCES` | 생활가전 |

### SupportStatus

| 값 | 설명 |
| --- | --- |
| `SUPPORTED` | 지원 범위 |
| `UNSUPPORTED_REGION` | 서울 밖 |
| `UNSUPPORTED_FIELD` | 지원 5개 분야 밖 |
| `INPUT_REQUIRED` | 지역·분야 입력 필요 |
| `DATA_INCOMPLETE` | 서울 내 기준 자료 보완 필요 |

### RequestStatus

| 값 | 설명 |
| --- | --- |
| `OPEN` | 요청 진행·기록 가능 |
| `CLOSED` | 사용자 전체 종료 확인 완료; 삭제와 구분 |

### WorkItemStatus

| 값 | 설명 |
| --- | --- |
| `NEEDS_CONFIRMATION` | 요약·작업 사실 확인 전 |
| `EXPLORING` | 기사 탐색·상담 |
| `SELF_HELP` | 자가 해결 진행 |
| `MANUFACTURER_AS` | 공식 AS 경로 이용 |
| `RESERVED` | 항목 예약 확정 |
| `IN_PROGRESS` | 실제 작업 중 |
| `STOP_REQUESTED` | 사용자 중단 요청 중 |
| `RESOLVED` | 해당 항목 해결; 활성 관계 우회 종료 불가 |
| `NOT_CONTINUING` | 미해결 상태에서 더 진행하지 않음 |

### ResolutionPath

| 값 | 설명 |
| --- | --- |
| `SELF_HELP` | 검증된 자가 해결 |
| `MANUFACTURER_AS` | 등록 공식 AS |
| `TECHNICIAN` | 서비스 내 기사 상담·견적·예약 |
| `DIRECT_CONTACT` | 외부 직접 연락; 플랫폼 작업 생성 아님 |

### OutcomeResult

| 값 | 설명 |
| --- | --- |
| `RESOLVED` | 사용자 진술의 해결 |
| `UNRESOLVED` | 미해결 |
| `UNAVAILABLE` | 외부 경로 이용 불가 |

### AiUseStatus

| 값 | 설명 |
| --- | --- |
| `NOT_SELECTED` | AI 작업을 만들지 않은 정상 이용 경로 |
| `INCOMPLETE` | 이용 중·실패·시간 초과 등 분석 미완료 |
| `COMPLETED` | 분석 완료; 사용자 확인과 별개 |

### AiJobType

| 값 | 설명 |
| --- | --- |
| `DIAGNOSIS` | 지정 작업 항목의 증상·원인 후보·분야 초안; 기본 항목도 `workItemId` 필수 |
| `QUESTION` | 요청 전체의 추가 질문 하나; `workItemId` 없이 발행 슬롯·열린 질문·종료·5회 한도 검사 |
| `GUIDE_EXPLANATION` | 지정 작업 항목에 적용되는 검증 가이드의 표현만 맞춤화; `workItemId`·`guideId` 필수 |
| `CASE_MATCHING` | 지정 작업 항목의 원문 근거 사례 평가·추천 설명; `workItemId` 필수 |
| `PHOTO_COMPARISON` | 요청의 벽지 물자국 사진 묶음 비교; `photoGroupId` 필수, `workItemId` 전송 금지 |
| `REPORT_DRAFT` | 지정 작업 항목의 인계·경과 보고서 초안; `workItemId` 필수 |

### AiJobStatus

| 값 | 설명 |
| --- | --- |
| `QUEUED` | 서버 접수·대기 |
| `RUNNING` | 처리 중 |
| `SUCCEEDED` | 결과 저장 완료; 낡음·사용자 확인은 별도 |
| `FAILED` | 실패; 저장 입력·오류 유지 |
| `TIMED_OUT` | 접수 후 60초 도달; 늦은 성공으로 변경 불가 |

### ReviewStatus

| 값 | 설명 |
| --- | --- |
| `DRAFT` | 사용자 미확인 초안 |
| `CONFIRMED` | 해당 근거·본문·범위 확인 완료 |
| `NEEDS_UPDATE` | 변경·삭제로 갱신·재확인 필요 |

### GuidanceType

| 값 | 설명 |
| --- | --- |
| `EMERGENCY` | 검증된 긴급 대응·공식 대안 |
| `MANUFACTURER_AS` | 제조사 공식 지원·예약 경로 |

### GuidanceStatus

공유 코드 집합이다. 필드별 허용값·배열 조합은 `GuideResultDTO`와 `OfficialServiceResultDTO` 표를 따르며, 모든 필드에서 모든 코드를 사용하는 것은 아니다.

| 값 | 설명 |
| --- | --- |
| `AVAILABLE` | 등록·검증 안내 제공 |
| `INFORMATION_REQUIRED` | 제품 등 입력 보완 필요 |
| `NOT_REGISTERED` | 등록 안내 없음 |
| `NOT_APPLICABLE` | 조회 대상 외 또는 적용 불가; 실행 절차 없음 |
| `VALIDATION_FAILED` | 안내·경로 검증 실패; 실행 절차·미검증 경로 미제공 |

### DialogueAction

| 값 | 설명 |
| --- | --- |
| `ANSWER` | 현재 질문 답변 |
| `SKIP` | 현재 질문 건너뛰기; 한 회 소비 |
| `FINISH` | 현재 정보로 확인 단계 진행 |

### VisitMode

| 값 | 설명 |
| --- | --- |
| `FIXED` | 지정한 작업 시작 시각 |
| `FLEXIBLE` | 작업 전체가 들어갈 수 있는 가능 구간 |

### FactSource

| 값 | 설명 |
| --- | --- |
| `OBSERVATION` | 사진에서 관찰한 사실 |
| `USER_STATEMENT` | 사용자 진술 |
| `AI_INFERENCE` | AI 추정·원인 후보 |
| `UNKNOWN` | 미확인 |
| `FIELD_CONFIRMED` | 기사 현장 확인 |

### ComparisonStatus

| 값 | 설명 |
| --- | --- |
| `CHANGED` | 관찰 변화 있음 |
| `UNCHANGED` | 관찰 변화 없음; 빈 사각형 |
| `INCOMPARABLE` | 비교 불가; 사유·재촬영 안내 |
| `NOT_PERFORMED` | 사진 부족 등으로 비교 미수행 |

### CaseDataType

| 값 | 설명 |
| --- | --- |
| `MOCK` | 별도로 준비한 모의 사례 |
| `REPRODUCED` | 별도로 준비한 재현자료; 실제 접수 실적 아님 |

### EvaluationStatus

| 값 | 설명 |
| --- | --- |
| `NOT_REQUESTED` | 명시적 평가 미실행 |
| `RUNNING` | 평가 진행 중 |
| `COMPLETED` | 평가 완료; 빈 결과도 가능 |
| `INCOMPLETE` | 평가 실패·시간 초과·필수 결과 누락 |

### FeasibilityStatus

| 값 | 설명 |
| --- | --- |
| `MATCHED` | 해당 조건 검사 완료·충족 |
| `NOT_MATCHED` | 조건 불충족 |
| `UNKNOWN` | 자료·소요 시간 부족으로 미확인 |

### ConsultationStatus

| 값 | 설명 |
| --- | --- |
| `PENDING` | 사용자 선택·기사 응답 대기; 활성 관계 |
| `ACCEPTED` | 기사 수락; 활성 관계 |
| `REJECTED` | 기사 거절 |
| `CLOSED` | 종료·선택 해제·예약 종료·경쟁 확정으로 종료 |

### ConsultationAction

| 값 | 설명 |
| --- | --- |
| `ACCEPT` | 기사의 대기 상담 수락 |
| `REJECT` | 기사의 대기 상담 거절 |
| `CLOSE` | 당사자의 상담 종료; 활성 예약이면 차단 |
| `DESELECT` | 사용자의 선택 해제; 활성 예약이면 차단 |

### CostCategory

| 값 | 설명 |
| --- | --- |
| `LABOR` | 공임 |
| `VISIT` | 출장비 |
| `DIAGNOSIS` | 진단비 |
| `PART` | 부품비 |
| `ADDITIONAL_WORK` | 추가 작업 비용·조건 |

### QuoteStatus

| 값 | 설명 |
| --- | --- |
| `ACTIVE` | 최신 미확정 제안 |
| `REPLACED` | 새 수정 버전으로 대체 |
| `WITHDRAWN` | 기사 철회 |
| `REJECTED` | 사용자 거절 |
| `EXPIRED` | 서버 시각이 유효 종료에 도달 |
| `RECONFIRMATION_REQUIRED` | 전제 변경으로 재발행 필요 |
| `SELECTED` | 예약 확정 당시 선택; 합의 보존 |
| `UNSELECTABLE` | 상담 종료·동일 항목 경쟁 확정 등으로 선택 불가 |

### QuoteAction

| 값 | 설명 |
| --- | --- |
| `WITHDRAW` | 발행 기사 철회 |
| `REJECT` | 사용자 거절 |

### ReservationOperation

| 값 | 설명 |
| --- | --- |
| `CREATE` | 신규 예약 확정 사전 검사; 사용자 |
| `CHANGE_BEFORE_START` | 시작 전 변경 검사; 당사자 |
| `START_WORK` | 실제 시작 검사; 당사자; `proposedStartAt`을 이용한 조기 시작 동의 전 검사 포함 |
| `CHANGE_IN_PROGRESS` | 진행 중 변경 검사; 당사자 |

### TravelEndpointType

| 값 | 설명 |
| --- | --- |
| `DEPARTURE` | 기사 기준 출발 위치; `from`에만 사용 |
| `RESERVATION` | 기사 본인의 서비스 예약 |
| `EXTERNAL_VISIT` | 기사 본인이 등록한 외부 일정 |
| `RETURN` | 기사 기준 복귀 위치; `to`에만 사용 |

### ScheduleCheckStatus

| 값 | 설명 |
| --- | --- |
| `VALID` | 필요한 검사 충족 |
| `CONFLICT` | 실제 작업·이동 충돌 |
| `POSSIBLE_CONFLICT` | 종료 불명 등으로 충돌 가능 |
| `RECHECK_REQUIRED` | 기준 자료 부족·재검사 미완료 |

### ReservationStatus

| 값 | 설명 |
| --- | --- |
| `CONFIRMED` | 확정·방문 준비; 활성 |
| `IN_PROGRESS` | 실제 작업 중; 활성 |
| `STOP_REQUESTED` | 사용자 중단 요청; 점유 유지·완료 및 변경 반영 차단 |
| `CANCELLED` | 실제 시작 전 취소 |
| `COMPLETED` | 기사 실제 완료 |
| `STOPPED` | 기사 실제 중단; 완료와 구분 |

### ChangeType

| 값 | 설명 |
| --- | --- |
| `BEFORE_START` | 실제 시작 전 예약 변경; 30분 준비 적용 |
| `IN_PROGRESS` | 실제 시작 후 범위·금액·종료 변경; 30분 재적용 없음 |

### ChangeStatus

| 값 | 설명 |
| --- | --- |
| `PROPOSED` | 같은 버전 양측 확인 대기·조건 검사 필요 |
| `APPLIED` | 양측 확인·최신 검사 후 반영 |
| `REJECTED` | 상대 거절; 기존 합의 유지 |
| `WITHDRAWN` | 제안자 철회 |
| `SUPERSEDED` | 새 버전 제안으로 대체 |
| `INVALIDATED` | 종료·기준 변경으로 반영 불가 |

### ChangeAction

| 값 | 설명 |
| --- | --- |
| `ACCEPT` | 같은 변경안 버전 수락 |
| `REJECT` | 상대 변경안 거절 |
| `WITHDRAW` | 본인 제안 철회 |

### ConsentAction

| 값 | 설명 |
| --- | --- |
| `GRANT` | 사용자의 현재 예약 조기 시작 동의 |
| `REVOKE` | 사용자의 시작 전 동의 철회 |

### WorkEventType

| 값 | 설명 |
| --- | --- |
| `START` | 기사; 유효 확정 예약에서 실제 시작 |
| `REQUEST_STOP` | 사용자; 작업 중 사유 입력·점유 유지 |
| `STOP` | 기사; 사용자 요청 확인 또는 직접 중단·수행 기록 필수 |
| `COMPLETE` | 기사; 중단 요청 없는 작업 중·수행 기록 필수 |
| `UPDATE_EXPECTED_END` | 기사; 작업 중·중단 요청 중 운영상 종료 예상 갱신 |

### EndEstimateSource

| 값 | 설명 |
| --- | --- |
| `AGREEMENT` | 최초 또는 변경 합의의 예상 종료 |
| `OPERATIONS` | 실제 지연·초과 사실에 대한 운영상 갱신 |

### DeliveryPurpose

| 값 | 설명 |
| --- | --- |
| `CONSULTATION` | 선택 기사 상담용; 상세 주소·연락처 제외 |
| `HANDOVER` | 해당 예약 기사 인계; 관계별 범위 적용 |
| `EXTERNAL_PDF` | 임대인·관리사무소 제출용; 외부 수신자 계정·링크 없음 |

### RedactionTarget

| 값 | 설명 |
| --- | --- |
| `PHOTO` | 선택 사진의 픽셀·파일명 |
| `RECORD` | 선택한 사용자 기록 |
| `QUESTION` | 선택한 사용자와 AI 문답 |
| `SUMMARY` | 해당 항목 확인 요약 |
| `REPORT` | 해당 항목 확인 보고서 |
| `QUOTE_CONTEXT` | 상담 견적 전제의 허용된 자유 문자열 필드; `fieldPath`로 지정 |

### ProcessingStatus

| 값 | 설명 |
| --- | --- |
| `QUEUED` | 처리 접수 |
| `PROCESSING` | 처리 중 |
| `READY` | 가림·파일 생성 완료; 사용자 확인·권한은 별도 |
| `FAILED` | 처리 실패; 원본 대체 금지 |
| `STALE` | 근거·범위 변경으로 제공 불가 |

### DeletionTarget

| 값 | 설명 |
| --- | --- |
| `PHOTO` | 본인 요청 사진 및 모든 참조·파생 결과 |
| `RECORD` | 본인 일반 기록; 기사 수행 기록 제외 |
| `REQUEST` | 요청과 모든 연결 항목·자료 |

### DeletionStatus

| 값 | 설명 |
| --- | --- |
| `QUEUED` | 삭제 접수·접근 차단 |
| `PROCESSING` | 원본·참조·파일 정리 중 |
| `COMPLETED` | 모든 정리 확인 완료 |
| `REJECTED` | 소유 확인을 통과한 본인 일반 기록·요청 전체의 활성 관계로 접수 전 거절; 삭제·접근 차단 미시작; `403`·`404`는 작업 자체를 생성하지 않음 |
| `FAILED` | 부분 정리 실패·미완료; 접근 차단 유지 |
