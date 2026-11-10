# 고쳐야집 Backend API Specification (v0.1)

> Base URL: `/api/v1` (연동안, 미정)
>
> 인증 방식: 브라우저 쿠키 기반 세션 인증. 사전 발급 테스트 계정으로 로그인하면 서버가 세션을 생성하고 세션 식별자를 쿠키로 발급한다. 이후 요청의 세션 쿠키로 인증하고 활성 역할·관계별 권한을 검사한다.
>
> Last Updated: 2026-11-11

---

## 🆕 v0.1 확정 사항 요약

- **기준 문서**: [FE·BE 분업 작업 명세 v1.4](FE-BE-분업작업.md), [요구사항명세서 v1.7](요구사항명세서(기능들).md)를 따른다. 본 문서의 `v0.1`은 API 명세 초안 버전이다.
- **확정 범위와 연동안**: 업무 규칙은 기준 문서의 확정 사항이다. 현재 저장소에 API 구현이 없으므로 아래 HTTP Method·경로·필드명·DTO·Enum 코드·상태 코드·응답 래퍼는 **제안이며 FE·BE 확인 필요**이다. 실제 구현 계약으로 확정된 것으로 해석하지 않는다.
- **인증 방식 확정**: 브라우저 쿠키 기반 세션을 사용한다. 로그인 성공 시 `Set-Cookie`로 세션 식별자를 발급하고 브라우저는 이후 인증 요청의 `Cookie` 헤더로 전송한다. 로그아웃 시 서버 세션을 무효화하고 브라우저의 세션 쿠키를 만료시킨다.
- **미정 사항**: 배포 도메인, 로그인 자격증명 규격, 세션 쿠키 이름·속성, 세션 저장 방식·만료 시간·갱신 정책, 식별자 형식, 멱등 키 보관 기간, 페이지 크기, 문자열 길이, 포트폴리오 업로드 제한, PDF 처리 제한·인쇄 규격·조회 주기는 미정이다. FastAPI·PostgreSQL·OpenAI SDK는 사용 예정 기술이다.
- **전송 규칙 제안**: 성공 JSON은 `data`로 감싸고 오류는 공통 에러 구조를 직접 반환한다. JSON 요청은 `application/json`, 파일 업로드는 `multipart/form-data`이다. 날짜는 `YYYY-MM-DD`, 시각은 시간대를 포함한 ISO 8601로 제안하며 판정 시간대는 `Asia/Seoul`이다. 아래 상대 경로에는 Base URL을 붙인다.
- **입력 규칙 제안**: `PATCH`에서 생략한 필드는 유지하고 `null`은 nullable 필드만 해제한다. 필수 문자열은 공백만 허용하지 않는다. 중첩 입력의 필수·선택·검증 조건은 공통 DTO 설명을 함께 적용한다. 권한·상태·소유자·실제 시각은 클라이언트가 임의 지정할 수 없다.
- **공개 직접 연락**: 소개·지원 범위·긴급 안내·공개 기사 연락처는 비로그인으로 조회한다. 전화·외부 연락만으로 요청·상담·예약·점유·완료를 생성하지 않는다. 연락 가능 기사 부재와 실제 방문 가능 여부 미확인을 구분한다.
- **지원 범위**: 서울 전역의 수도·배관, 문·창호, 벽면·도배, 조명·전기설비, 생활가전을 지원한다. 범위 밖도 접수·기록은 허용한다. 시연 사례·공식 AS 자료·작업시간표 부재는 각각 표시하고 지원 제외와 혼동하지 않는다. 서울 이동자료 누락은 보완 대상으로 처리한다.
- **계정·관계 격리**: 계정과 기사 자원을 구분하고 자기 요청의 모든 항목에 기사로 참여하는 것을 차단한다. 기사 권한은 선택된 항목·상담·예약·전달본에 한정한다. 요청 소유자의 조회 권한을 기사 참여 권한으로 재사용하지 않는다.
- **독립 상태**: 요청 전체·작업 항목·상담·견적·예약·실제 작업을 구분한다. 한 견적·예약은 항목 하나, 항목별 활성 예약은 하나이다. 전체 종료는 모든 활성 관계 정리와 항목별 해결·진행하지 않음 확인 후에만 허용한다.
- **사용자 요청 사진**: JPEG·PNG, 실제 이미지 판독 가능, 파일당 `10,000,000` Byte 이하, 한 번 `1~5`장, 요청 전체 최대 `30`장이다. 경계값을 허용하고 오류 묶음은 전부 저장하지 않는다. 공유 참조는 중복 집계하지 않으며 동시 업로드도 한도를 지킨다. 기사 포트폴리오는 별도이다.
- **AI 선택·확인 분리**: AI 미선택이면 작업을 만들지 않는다. 실패 후에도 저장 입력과 직접 확인한 요약·분야로 진행한다. 추가 질문은 요청 전체 최대 `5`회이며 답변·건너뛰기 한 쌍을 한 회로 센다. 조회·정정·공개 범위 변경은 AI를 실행하지 않는다.
- **AI 비동기 처리**: 모든 AI 처리는 명시적 실행 요청과 상태 조회를 분리한다. 접수부터 대기·재시도·결과 저장까지 `60`초이며 도달 시 시간 초과이다. 일시적 연결·서비스 장애·요청 제한에만 남은 시간 내 자동 재시도 최대 `1`회이다. 수동 재시도는 새 작업으로 남기고 원래 실패·문답 횟수를 유지한다.
- **최신성·합의 버전**: `sourceRevision`은 근거 최신성, `commonVersion`·`itemVersion`·`proposalVersion`은 견적 전제, `agreementVersion`은 예약 합의를 나타내는 연동안이다. 자료 정정은 덮어쓰며 복원 이력을 쌓지 않는다. 확정 합의는 별도 보존하고 추가 세분화를 요구하지 않는다.
- **변경 영향**: 공통 장소 변경은 참조 항목 전체, 항목 사실 변경은 해당 항목, 기사 제안 변경은 해당 제안에만 적용한다. 참고 사진·설명만 바뀌면 관련 분석·보고서만 갱신 필요로 표시한다. 확정 예약은 별도 합의 전 기존 조건을 유지한다. 가림·공개 범위만 변경하면 전달본·PDF 확인만 무효화한다.
- **시간·충돌**: 방문 구간·제안·소요 시간·갱신 종료 예상은 `15`분 단위이며 자동 반올림하지 않는다. 신규 확정·시작 전 변경은 반영 직전 시작까지 `30`분 이상이어야 한다. 조기 시작·진행 중 합의에는 이를 재적용하지 않는다. 실제 시작·종료는 서버 시각이다. 작업 구간은 `[startAt, endAt)`이고 이동시간을 별도로 검사한다.
- **중복 방문·실제 초과**: 동일 기사의 작업·이동 충돌은 모든 요청에서 차단한다. 같은 요청의 다른 기사 방문 중복만 현재 대상·조건에 대한 사용자 확인으로 허용한다. 종료 예상에 도달한 미종료 작업은 초과이며 미갱신 동안 해당 기사 한국 날짜 당일 신규 확정을 차단한다. 후속 예약은 자동 이동·취소하지 않는다.
- **추천 구분**: 공개 연락 목록, 사례 추천, 일반 후보, 동선 추천을 구분한다. 사례 `3`점 이상 중 기사별 상위 `3`개 평균으로 최대 `5`명을 반환한다. 사례·기사 중복은 제거한다. 일반 후보에는 사례 점수를 만들지 않고 시간 미확인을 표시한다.
- **경과 분석**: 벽지 물자국의 동일 부위 사진만 비교한다. 확인 촬영일의 최초·최신을 기본쌍으로 하고 날짜 미확인·동일 날짜의 선후를 단정하지 않는다. 사각형은 표시 방향 정규화 이미지의 좌상단 기준 `0~1` 좌표이다. 한 장으로도 요약·상담·인계·예약이 가능하다.
- **전달·PDF**: 원본과 전달본을 구분한다. 선택 자료의 텍스트·사진·파일명 가림과 메타데이터 제거 후 사용자가 확인한다. 실패 자료는 차단한다. 외부 PDF에는 사진·Markdown 렌더링 본문을 포함하되 상담·견적·상세 주소·연락처·원본 접근 주소·가림 전 원본을 제외한다.
- **삭제**: 진행 중이거나 마지막 사진이어도 본인 사진 삭제를 허용하고 예약을 유지한다. 모든 참조 분석·전달본·임시/완성 PDF를 정리하며 삭제 완료 후 사진 한도를 회복한다. 일반 기록·요청 전체는 관련 활성 관계가 있으면 삭제할 수 없다. 부분 실패 시 접근 차단을 유지하고 남은 정리만 재시도한다.
- **원자성·멱등성**: 상태 전이 직전에 권한·최신성·일정·합의를 재검사하고 상태·점유·권한을 함께 반영한다. 재전송으로 중복 예약·종료 기록을 만들거나 실제 시각을 덮어쓰지 않는다. 멱등 키 적용 대상은 `Idempotency-Key` 요청 헤더로 중복을 식별하며, 모든 재응답에 현재 접근 권한을 검사한다.
- **HTTP 메서드와 멱등성**: `GET`·`PUT`·`DELETE`는 메서드 의미에 맞게 반복 요청의 효과가 같도록 구현하며 `Idempotency-Key`를 요구하지 않는다. 멱등성은 응답 상태 코드의 일치가 아니라 서버에 의도된 효과의 일치를 뜻한다. 키를 요구하지 않는 `PUT`·정정용 `PATCH`도 대상 식별자·버전·현재 상태를 검사하여 중복 반영을 막는다. 재전송에 `409 VERSION_CONFLICT`가 반환되면 최신 리소스 조회로 반영 여부를 확인한다.
- **멱등 키 전달 규칙**: 중복 생성·상태 전이·비동기 작업 실행 방지가 필요한 `POST`·`PATCH` 중 개별 **Headers** 표에 `Idempotency-Key`가 `✅`로 표시된 API에만 필수로 전송한다. 인증 API, 조건 조회용 `POST /reservation-checks`, 단순 필드 정정용 `PATCH`에는 요구하지 않는다.
  - `PATCH` 적용 대상은 상담 상태 변경(`/consultations/{consultationId}`), 견적 철회·거절(`/quotes/{quoteId}`), 예약 변경안 처리(`/reservation-changes/{changeId}`)이다. 요청·작업 항목·경과 기록·사례의 필드 정정은 제외한다.
  - FE는 처리 한 번마다 고유 키를 생성하고 같은 작업의 네트워크 재전송에는 같은 키를 사용한다. 요청 내용 수정, 별도 AI 재분석·수동 재시도, 삭제 정리의 새 재시도에는 새 키를 사용한다.
  - 헤더 값은 큰따옴표로 감싼 비어 있지 않은 ASCII 문자열 하나이다. 예: `Idempotency-Key: "550e8400-e29b-41d4-a716-446655440000"`. UUID는 값의 예시이며 쿠키의 세션 식별자·고장 접수의 `requestId`와 구분한다.
  - BE는 인증된 계정·HTTP Method·실제 요청 경로·키를 함께 사용해 중복을 판별한다. 같은 범위의 키에 다른 요청 내용을 보내면 `409 IDEMPOTENCY_KEY_REUSED`를 반환한다. 요청 내용 비교에는 JSON 필드값·파일 내용·파일별 메타정보를 사용하며 JSON 객체 키 순서와 multipart boundary 차이는 제외한다.
  - 같은 키·내용으로 이미 처리된 요청은 다시 실행하지 않고 기존 처리 결과를 반환한다. 원래 요청에서 소비한 버전 값만으로 재실행하거나 버전 충돌을 만들지 않는다. 재응답 전 현재 인증·관계 권한·삭제·자료 최신성을 검사하며, 접근 불가 자료나 삭제된 본문·파일을 과거 응답으로 다시 제공하지 않는다.
  - 최초 요청의 접수·상태 반영이 아직 처리 중이면 `409 IDEMPOTENCY_IN_PROGRESS`를 반환한다. 비동기 작업 ID를 이미 발급했다면 해당 작업이 실행 중이어도 기존 작업 ID의 `202 Accepted` 접수 결과를 반환하며 새 작업을 만들지 않는다. 작업 상태·실패 이력은 해당 조회 API에서 확인한다.
  - 필수 헤더 누락은 `400 IDEMPOTENCY_KEY_REQUIRED`, 빈 값·잘못된 형식·여러 값 전송은 `400 INVALID_IDEMPOTENCY_KEY`로 처리한다. 키 보관 기간은 구현 세부 정책으로 정하며, 키가 만료되어도 예약·상태·실제 시각의 중복 방지 검사는 유지한다.
- **구현 제외·검수**: 회원가입·비밀번호 찾기, 사용자와 기사 간 채팅·대화 저장·통화·푸시, 결제·정산·리뷰·관리자, 외부 공유 링크·Markdown 파일 다운로드, 실제 접수자료의 공개 사례·별도 AI 활용 전환 API는 제공하지 않는다. `W22` 기준 자료 구축과 `W23`·`AC-01~63` 검수는 내부 작업이며 공개 관리 API를 추가하지 않는다. 일반 API 성능 수치는 후속 검수의 미정 사항이다.

---

## 📋 API 엔드포인트 총괄표

| # | 분류 | Method | Endpoint | 인증 | 선행 조건 | 설명 | 업데이트 날짜 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Authentication | POST | `/auth/login` | ❌ | 사전 발급 계정 | 테스트 계정 로그인 | 2026-11-11 |
| 2 | Authentication | POST | `/auth/logout` | ✅ | 본인 | 로그아웃 | 2026-11-11 |
| 3 | Authentication | GET | `/auth/me` | ✅ | 본인 | 현재 계정·역할 조회 | 2026-11-11 |
| 4 | Authentication | PATCH | `/auth/role` | ✅ | 본인 | 활성 역할 전환 | 2026-11-11 |
| 5 | Public | GET | `/public/service-info` | ❌ | 없음 | 소개·지원 범위 조회 | 2026-11-11 |
| 6 | Public | GET | `/public/technicians` | ❌ | 없음 | 공개 기사 연락 목록 | 2026-11-11 |
| 7 | Public | GET | `/public/technicians/{technicianId}` | ❌ | 없음 | 공개 기사 프로필 조회 | 2026-11-11 |
| 8 | Public | GET | `/public/guidance` | ❌ | 없음 | 긴급·공식 안내 조회 | 2026-11-11 |
| 9 | Requests | POST | `/requests` | ✅ | 본인 | 사진·증상 최초 접수 | 2026-11-11 |
| 10 | Requests | GET | `/requests` | ✅ | 본인 | 본인 요청 목록 | 2026-11-11 |
| 11 | Requests | GET | `/requests/{requestId}` | ✅ | 본인 | 요청 상세·이력 조회 | 2026-11-11 |
| 12 | Requests | PATCH | `/requests/{requestId}` | ✅ | 본인 | 공통 증상·지역 정정 | 2026-11-11 |
| 13 | Requests | PUT | `/requests/{requestId}/visit-details` | ✅ | 본인 | 상세 방문 정보 확인 | 2026-11-11 |
| 14 | Requests | POST | `/requests/{requestId}/closure` | ✅ | 본인 | 요청 전체 종료 | 2026-11-11 |
| 15 | Requests | POST | `/requests/{requestId}/work-items` | ✅ | 본인 | 독립 작업 항목 추가 | 2026-11-11 |
| 16 | Requests | PATCH | `/work-items/{workItemId}` | ✅ | 본인 | 작업 사실·해결 경로 변경 | 2026-11-11 |
| 17 | Requests | PUT | `/work-items/{workItemId}/confirmation` | ✅ | 본인 | 요약·분야 사용자 확인 | 2026-11-11 |
| 18 | Requests | GET | `/work-items/{workItemId}/solutions` | ✅ | 본인 | 항목별 해결 안내 | 2026-11-11 |
| 19 | Requests | POST | `/work-items/{workItemId}/outcomes` | ✅ | 본인 | 자가 조치·외부 해결 결과 기록 | 2026-11-11 |
| 20 | History | POST | `/requests/{requestId}/photos` | ✅ | 본인 | 추가 사진 업로드 | 2026-11-11 |
| 21 | History | PUT | `/photos/{photoId}` | ✅ | 본인 | 사진·촬영일·설명 정정 | 2026-11-11 |
| 22 | History | GET | `/media/{mediaId}` | ✅ | 자료 종류·관계 권한 | 권한 있는 이미지 조회 | 2026-11-11 |
| 23 | History | POST | `/requests/{requestId}/records` | ✅ | 본인 | 경과·보완 기록 추가 | 2026-11-11 |
| 24 | History | PATCH | `/records/{recordId}` | ✅ | 본인 | 본인 경과 기록 정정 | 2026-11-11 |
| 25 | History | GET | `/requests/{requestId}/timeline` | ✅ | 본인 | 날짜별 경과·비교쌍 조회 | 2026-11-11 |
| 26 | History | PUT | `/requests/{requestId}/photo-groups` | ✅ | 본인 | 동일 부위 묶음·비교쌍 설정 | 2026-11-11 |
| 27 | AI | POST | `/requests/{requestId}/ai-jobs` | ✅ | 본인 | AI 작업 명시적 실행·재시도 | 2026-11-11 |
| 28 | AI | GET | `/ai-jobs/{jobId}` | ✅ | 본인 | AI 상태·결과·오류 조회 | 2026-11-11 |
| 29 | AI | PUT | `/requests/{requestId}/ai-dialogue` | ✅ | 본인 | 답변·건너뛰기·문답 종료 | 2026-11-11 |
| 30 | Technicians | GET | `/technicians/me` | ✅ | 기사 본인 | 본인 기사 자원 조회 | 2026-11-11 |
| 31 | Technicians | PUT | `/technicians/me/profile` | ✅ | 기사 본인 | 프로필 등록·수정 | 2026-11-11 |
| 32 | Technicians | POST | `/technicians/me/portfolio-photos` | ✅ | 기사 본인 | 본인 포트폴리오 사진 업로드 | 2026-11-11 |
| 33 | Technicians | GET | `/technicians/{technicianId}/portfolio` | ✅ | 로그인; 공개 검증 자료 | 포트폴리오·사례 목록 조회 | 2026-11-11 |
| 34 | Technicians | POST | `/technicians/me/cases` | ✅ | 기사 본인 | 준비된 시공 사례 등록 | 2026-11-11 |
| 35 | Technicians | PATCH | `/technicians/me/cases/{caseId}` | ✅ | 기사 본인 | 본인 사례 정정 | 2026-11-11 |
| 36 | Technicians | GET | `/cases/{caseId}` | ✅ | 로그인; 공개 검증 자료 | 사례 상세 조회 | 2026-11-11 |
| 37 | Technicians | GET | `/technicians/me/schedule` | ✅ | 기사 본인 | 본인 일정표 조회 | 2026-11-11 |
| 38 | Technicians | PUT | `/technicians/me/schedule` | ✅ | 기사 본인 | 가능 시간·외부 일정 변경 | 2026-11-11 |
| 39 | Matching | GET | `/work-items/{workItemId}/case-recommendations` | ✅ | 본인 | 사례 기반 기사 추천 조회 | 2026-11-11 |
| 40 | Matching | GET | `/work-items/{workItemId}/general-candidates` | ✅ | 본인 | 일반 기사 후보 조회 | 2026-11-11 |
| 41 | Matching | PUT | `/work-items/{workItemId}/route-exploration` | ✅ | 본인 | 동선 탐색 공개·중단 | 2026-11-11 |
| 42 | Matching | GET | `/technicians/me/route-candidates` | ✅ | 기사 본인 | 기사 동선 추천 작업 조회 | 2026-11-11 |
| 43 | Matching | POST | `/route-candidates/{candidateId}/interests` | ✅ | 기사 본인; 탐색 공개 중 | 상담 참여 의사 표시 | 2026-11-11 |
| 44 | Matching | GET | `/work-items/{workItemId}/interests` | ✅ | 본인 | 참여 기사 조회 | 2026-11-11 |
| 45 | Consultations | POST | `/work-items/{workItemId}/consultations` | ✅ | 소유자; 지역·방문 조건·요약 확인 | 기사 선택·상담 요청 | 2026-11-11 |
| 46 | Consultations | GET | `/consultations` | ✅ | 현재 역할의 당사자 | 참여 상담 목록 | 2026-11-11 |
| 47 | Consultations | GET | `/consultations/{consultationId}` | ✅ | 관계 당사자 | 상담 상세·전달 이력 조회 | 2026-11-11 |
| 48 | Consultations | PATCH | `/consultations/{consultationId}` | ✅ | 관계 당사자; 액션별 권한 | 상담 수락·거절·종료·해제 | 2026-11-11 |
| 49 | Consultations | POST | `/consultations/{consultationId}/quotes` | ✅ | 수락된 활성 상담의 기사 | 견적 신규 발행·수정본 발행 | 2026-11-11 |
| 50 | Consultations | PATCH | `/quotes/{quoteId}` | ✅ | 발행 기사 또는 요청 소유자 | 견적 철회·거절 | 2026-11-11 |
| 51 | Consultations | GET | `/work-items/{workItemId}/quotes` | ✅ | 본인 | 항목별 견적 비교 | 2026-11-11 |
| 52 | Reservations | POST | `/reservation-checks` | ✅ | 소유자 또는 관련 기사 | 예약·변경·시작 조건 사전 검사 | 2026-11-11 |
| 53 | Reservations | PUT | `/reservation-checks/{checkId}/overlap-confirmation` | ✅ | 해당 요청 소유자 | 다른 기사 방문 중복 확인 | 2026-11-11 |
| 54 | Reservations | POST | `/work-items/{workItemId}/reservations` | ✅ | 소유자; 최신 견적·방문 정보 확인 | 견적 선택·예약 확정 | 2026-11-11 |
| 55 | Reservations | GET | `/reservations` | ✅ | 현재 역할의 당사자 | 당사자 예약 목록 | 2026-11-11 |
| 56 | Reservations | GET | `/reservations/{reservationId}` | ✅ | 예약 당사자 | 예약·작업·인계 상세 | 2026-11-11 |
| 57 | Reservations | POST | `/reservations/{reservationId}/cancellation` | ✅ | 예약 당사자; 실제 시작 전 | 시작 전 예약 취소 | 2026-11-11 |
| 58 | Reservations | POST | `/reservations/{reservationId}/changes` | ✅ | 예약 당사자 | 시작 전·진행 중 변경안 제안 | 2026-11-11 |
| 59 | Reservations | PATCH | `/reservation-changes/{changeId}` | ✅ | 예약 당사자; 동일 변경 버전 | 변경안 수락·거절·철회 | 2026-11-11 |
| 60 | Work | PUT | `/reservations/{reservationId}/early-start-consent` | ✅ | 요청 소유자; 시작 전 | 조기 시작 동의·철회 | 2026-11-11 |
| 61 | Work | POST | `/reservations/{reservationId}/work-events` | ✅ | 액션별 사용자 또는 담당 기사 | 시작·중단 요청·중단·완료·종료 예상 갱신 | 2026-11-11 |
| 62 | Work | PUT | `/reservations/{reservationId}/preparation-notes` | ✅ | 해당 활성 예약 담당 기사 | 방문 준비사항 등록·수정 | 2026-11-11 |
| 63 | Handover | POST | `/work-items/{workItemId}/deliveries` | ✅ | 본인 | 가림·공개 범위 전달본 준비 | 2026-11-11 |
| 64 | Handover | GET | `/deliveries/{deliveryId}` | ✅ | 소유자 또는 허용 수신자 | 전달본 처리 상태·미리보기·열람 | 2026-11-11 |
| 65 | Handover | PUT | `/deliveries/{deliveryId}/confirmation` | ✅ | 본인 | 처리 결과·공개 범위 확인 | 2026-11-11 |
| 66 | Handover | PUT | `/work-items/{workItemId}/report` | ✅ | 본인 | 보고서 직접 작성·수정 초안 | 2026-11-11 |
| 67 | Handover | GET | `/work-items/{workItemId}/report` | ✅ | 본인 | 본인 보고서·초안 조회 | 2026-11-11 |
| 68 | Handover | POST | `/work-items/{workItemId}/report-confirmation` | ✅ | 본인 | 최신 보고서 본문 확인 | 2026-11-11 |
| 69 | Handover | POST | `/deliveries/{deliveryId}/pdf-jobs` | ✅ | 본인 | 사진 포함 PDF 생성 | 2026-11-11 |
| 70 | Handover | GET | `/pdf-jobs/{jobId}` | ✅ | 본인 | PDF 생성 상태 조회 | 2026-11-11 |
| 71 | Handover | GET | `/pdf-jobs/{jobId}/content` | ✅ | 본인 | 확인된 PDF 다운로드 | 2026-11-11 |
| 72 | Deletion | POST | `/deletion-jobs` | ✅ | 본인 | 사진·일반 기록·요청 전체 삭제 | 2026-11-11 |
| 73 | Deletion | GET | `/deletion-jobs/{jobId}` | ✅ | 본인 | 삭제 처리 상태 조회 | 2026-11-11 |
| 74 | Deletion | POST | `/deletion-jobs/{jobId}/retry` | ✅ | 본인 | 삭제 미완료 정리 재시도 | 2026-11-11 |

범례: `✅` 유효한 세션 쿠키로 인증 필요, `❌` 인증 불필요. 인증 성공과 관계별 인가는 별개이다. `본인`은 사용자 역할의 요청 소유자이며, 기사·당사자 조건은 별도 표기한다. API 경로·본문 구조는 확인이 필요한 연동안이다. 인증이 필요한 모든 API에 공통 `401`·`403`, 식별자 조회에 `404`, 상태 변경에 최신성·삭제 검사가 적용된다. `Idempotency-Key`가 필수인 API에는 공통 에러 표의 멱등 키 관련 `400`·`409`도 적용한다.

---

## 1. 인증·역할 (Authentication)

> `W01` · `FR-ACT-01~03`. 브라우저 쿠키 기반 세션 인증을 사용한다. 인증이 필요한 모든 API에는 브라우저가 세션 식별자를 담은 `Cookie` 헤더를 전송하며, 개별 **Headers** 표의 항목과 함께 적용한다. 서버는 세션의 유효성과 활성 역할·관계별 권한을 검사한다. 쿠키 이름·속성과 세션 저장·만료·갱신 세부 정책은 미정이다.

### POST `/auth/login` — 테스트 계정 로그인

- **인증 요구사항**: ❌
- **선행 조건**: 사전 발급 계정
- **설명**: 발급된 계정을 검증하고 서버 세션을 생성한다. 브라우저는 응답의 세션 쿠키를 저장하여 이후 인증 요청에 전송한다. 자격증명 필드명은 연동안이며 확인 필요이다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `loginId` | string | ✅ | 발급 계정 | 로그인 식별값 |
| `password` | string | ✅ | 발급 자격증명 | 로그·응답에 포함하지 않음 |

**Response 200 OK**

`Set-Cookie` 응답 헤더로 세션 식별자 쿠키를 발급한다. 쿠키 이름·속성은 미정이다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | SessionDTO | 처리 결과 |

**예외 응답**

- **401 Unauthorized**: 테스트 계정 인증 실패 (`INVALID_CREDENTIALS`)

---

### POST `/auth/logout` — 로그아웃

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 요청의 세션 쿠키에 연결된 서버 세션을 무효화한다. FE는 비공개 캐시를 비운다. 요청 본문은 없습니다.

**Response 204 No Content**

응답 본문은 없습니다. `Set-Cookie` 응답 헤더로 로그인 시 발급한 세션 쿠키를 만료시킨다.

---

### GET `/auth/me` — 현재 계정·역할 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 세션 쿠키로 인증한 계정과 현재 세션의 활성 역할, 연결된 기사 식별자를 조회한다. 요청 본문은 없습니다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | SessionDTO | 처리 결과 |

---

### PATCH `/auth/role` — 활성 역할 전환

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 현재 세션의 활성 역할을 전환한다. 계정 소유권과 기사 자원 연결은 유지하며 FE는 이전 역할의 비공개 캐시를 비운다.

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

## 2. 공개 정보·직접 연락 (Public)

> `W02`, `W04`, `W22` · `FR-ACT-01`, `FR-CON-05~06`, `FR-SOL-05`. 로그인·접수·AI·일정 입력을 요구하지 않는다. 공개 정보만 반환하고 빈 목록은 정상 응답이다.

### GET `/public/service-info` — 소개·지원 범위 조회

- **인증 요구사항**: ❌
- **설명**: 서비스 소개, 지원 분야·동 목록, 자료 버전과 재촬영 기본 안내를 제공한다. 요청 본문은 없습니다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ServiceInfoDTO | 처리 결과 |

---

### GET `/public/technicians` — 공개 기사 연락 목록

- **인증 요구사항**: ❌
- **설명**: 공개 연락수단이 있는 기사만 조회한다. 실제 대응·방문 가능 여부는 미확인이다. 요청 본문은 없습니다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `field` | ServiceField | - | 없음 | 전문 분야 |
| `regionId` | string | - | 없음 | 활동 지역 식별자 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 (제안) | 1~100 (제안·확인 필요) |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<PublicTechnicianDTO> | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

### GET `/public/technicians/{technicianId}` — 공개 기사 프로필 조회

- **인증 요구사항**: ❌
- **설명**: 공개 동의한 표시명·분야·지역·업무 연락수단만 반환한다. 공개 중단한 연락처는 제외한다. 요청 본문은 없습니다.

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
- **설명**: 사전 검증·등록된 긴급 대응과 공식 AS·대안 경로를 제공한다. 등록 없음·제품 정보 부족을 구분한다. URL·연락처·즉시 방문 가능성을 생성하지 않는다. 요청 본문은 없습니다.

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

- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

## 3. 요청·작업 항목·해결 경로 (Requests)

> `W03~07` · `FR-REQ-01~11`, `FR-AI-04`, `FR-SOL-01~04`. 사용자 역할의 요청 소유자만 접근한다. 기본 항목 하나로 접수하며 복수 분야만으로 항목을 자동 분리하지 않는다.

### POST `/requests` — 사진·증상 최초 접수

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 최소 사진 한 장과 증상으로 요청·기본 항목을 함께 생성한다. 지역·상세 주소·제품 정보·AI 실행은 최초 접수의 필수 조건이 아니다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `multipart/form-data` | ✅ |

**Request Body (`multipart/form-data`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `files` | binary[] | ✅ | 1~5장; 공통 사진 제한 | 반복 파일 파트 |
| `metadata` | RequestInputDTO | ✅ | JSON 파트; 사진 순서 일치 | 증상·사진 설명·선택 입력 |

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
- **설명**: 요청 전체 상태와 항목별 상태를 구분한다. 요청 본문은 없습니다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `status` | RequestStatus | - | 전체 | 전체 요청 종료 여부 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 (제안) | 1~100 (제안·확인 필요) |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<RequestListItemDTO> | 처리 결과 |

---

### GET `/requests/{requestId}` — 요청 상세·이력 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 공통 자료와 항목별 상담·견적·예약·작업·외부 결과 이력을 연결해 반환한다. 사용자 진술과 기사 수행 기록을 구분한다. 요청 본문은 없습니다.

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
- **설명**: 현재 값을 덮어쓰고 수정일을 갱신한다. 공통 장소 변경은 참조 견적을 재확인 대상으로 만들며 확정 예약은 별도 합의 전 유지한다.

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
| `region` | RegionInputDTO | - | 실제 지역 | 서울 밖도 저장 허용 |
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
- **설명**: 작업 지역과 상세 주소 일치를 검증한다. 주소 변경은 예약별 변경 합의 전 기존 주소를 유지하며 동일 장소 연락처 정정은 확인 후 활성 담당 기사에게 반영한다.

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
| `visitDetails` | VisitDetailsDTO | ✅ | 주소·연락처·지역 일치 | 본인이 확인한 방문 정보 |
| `confirmed` | boolean | ✅ | `true` | 입력값 사용자 확인 |

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
- **설명**: 모든 항목의 종료 선택과 활성 관계 부재를 원자적으로 검사한다. 진행하지 않음을 수리 완료로 표시하지 않는다.

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
- **설명**: 사용자가 확인한 독립 부위·작업을 추가한다. 같은 분야의 다른 작업도 구분할 수 있다.

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
- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

### PATCH `/work-items/{workItemId}` — 작업 사실·해결 경로 변경

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 해당 항목의 사실 변경에만 견적 재확인을 적용한다. 경로 변경·외부 해결만으로 활성 관계를 종료하지 않는다.

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
| `facts` | WorkItemFactsDTO | - | DTO 조건 | 변경한 사실 묶음 |
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
- **설명**: AI 초안 또는 직접 작성 요약을 최신 근거로 확인한다. AI 미선택·실패 기록은 그대로 유지하며 분야 사실이 바뀌면 해당 항목 견적만 재확인한다.

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

- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

### GET `/work-items/{workItemId}/solutions` — 항목별 해결 안내

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 검증된 자가 해결 가이드·공식 AS·기사 연결 경로를 반환한다. 적용 불가이면 실행 절차를 비우고 중단·대체 경로를 안내한다. AI 설명 맞춤화는 별도 명시적 작업으로 실행한다. 요청 본문은 없습니다.

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
- **설명**: 자가 해결·공식 AS·직접 연락 결과를 사용자 진술로 저장한다. 통화 내역·연결 성공은 수집하지 않으며 기존 상담·예약·전체 요청을 자동 종료하지 않는다.

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
| `outcome` | OutcomeInputDTO | ✅ | DTO 조건 | 조치와 해결·미해결 결과 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RecordDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

## 4. 사진·경과 기록 (History)

> `W03`, `W16~17` · `FR-REQ-03`, `FR-REQ-09`, `FR-HIS-01~10`. 사용자 요청 사진의 쓰기는 소유자 전용이다. 정정은 복원 이력 없이 덮어쓰며 AI를 자동 실행하지 않는다.

### POST `/requests/{requestId}/photos` — 추가 사진 업로드

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 접수 보완·경과·조치 결과 사진을 같은 요청에 추가하고 모든 참조 항목의 관련 결과에 갱신 필요를 표시한다.

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
| `metadata` | PhotoInputDTO[] | ✅ | 파일 수·순서 일치 | 촬영일 확인·항목 연결 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PhotoCollectionDTO | 처리 결과 |

**예외 응답**

- **413 Content Too Large**: 사용자 요청 사진 파일당 10,000,000 Byte 초과 (`FILE_TOO_LARGE`)
- **415 Unsupported Media Type**: 실제 파일 형식 또는 Content-Type 미지원 (`UNSUPPORTED_MEDIA_TYPE`)
- **422 Unprocessable Content**: 묶음 내 손상 이미지·메타정보 불일치·파일별 오류; 전부 미저장 (`UPLOAD_BATCH_REJECTED`)
- **409 Conflict**: 동시 업로드를 포함한 요청 저장 사진 30장 초과 (`PHOTO_LIMIT_EXCEEDED`)

---

### PUT `/photos/{photoId}` — 사진·촬영일·설명 정정

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 파일을 교체하거나 촬영일·설명을 정정한다. 서버 업로드일을 촬영일로 대체하지 않으며 이전 파일 복원본을 보관하지 않는다.

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
| `file` | binary | - | JPEG·PNG; ≤10,000,000 Byte | 교체할 때만 전송 |
| `metadata` | PhotoInputDTO | ✅ | DTO 조건 | 정정할 현재 메타정보 |
| `expectedRevision` | string | ✅ | 최신 사진 값 일치 | 경합 검사 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PhotoDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **413 Content Too Large**: 사용자 요청 사진 파일당 10,000,000 Byte 초과 (`FILE_TOO_LARGE`)
- **415 Unsupported Media Type**: 실제 파일 형식 또는 Content-Type 미지원 (`UNSUPPORTED_MEDIA_TYPE`)
- **422 Unprocessable Content**: 묶음 내 손상 이미지·메타정보 불일치·파일별 오류; 전부 미저장 (`UPLOAD_BATCH_REJECTED`)

---

### GET `/media/{mediaId}` — 권한 있는 이미지 조회

- **인증 요구사항**: ✅
- **선행 조건**: 자료 종류·관계 권한
- **설명**: 요청 원본은 소유자만, 전달본은 허용 관계만 조회한다. 포트폴리오·사례는 사용 가능·비식별 검증을 통과한 공개 범위만 조회한다. 삭제·정정·관계 종료 권한을 다운로드에도 적용한다. 요청 본문은 없습니다.

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
- **설명**: 증상·조치·결과·설명을 사진과 연결한다. 기사와의 대화 저장 용도로 사용하지 않는다.

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
| `record` | RecordInputDTO | ✅ | 본인 요청의 참조 자료 | 날짜·설명·관련 항목 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RecordDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 타 요청·타 항목·타 기사·삭제 자료 참조 (`INVALID_REFERENCE`)

---

### PATCH `/records/{recordId}` — 본인 경과 기록 정정

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 현재 내용을 덮어쓰고 관련 파생 결과만 갱신 필요로 전환한다. 기사 수행 기록 수정 API가 아니다.

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
| `record` | RecordInputDTO | ✅ | 본인 작성 기록 | 수정할 현재 내용 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | RecordDTO | 처리 결과 |

**예외 응답**

- **403 Forbidden**: 소유·관계·자료 범위 권한 없음; 비공개 최신 상태는 제공하지 않음 (`ACCESS_DENIED`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)

---

### GET `/requests/{requestId}/timeline` — 날짜별 경과·비교쌍 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 확인 촬영일순 사진과 날짜 미확인 사진을 분리하고 기록·부위 묶음·기본 비교쌍을 반환한다. 요청 본문은 없습니다.

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
- **설명**: 동일 부위의 서로 다른 두 사진만 선택한다. 기본은 확인 날짜의 최초·최신이며 날짜 동률은 사진 식별자로 재현한다. 미확인 날짜 사진은 수동 선택만 허용하고 시간 선후를 단정하지 않는다.

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
| `sourceRevision` | string | ✅ | 최신 자료와 일치 | 사용자에게 표시한 근거 자료 식별값 |
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

> `W06`, `W10`, `W17`, `W19`, `W21` · `FR-AI-01~06`, `FR-ERR-01~02`. 사용자 역할의 소유자만 실행·조회한다. 성공과 사용자 확인은 별개이다. `60`초·자동 재시도 `1`회는 모든 AI 종류에 적용하며 PDF·삭제 작업에는 적용하지 않는다.

### POST `/requests/{requestId}/ai-jobs` — AI 작업 명시적 실행·재시도

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 증상 정리·질문·가이드 표현·사례 평가·사진 비교·보고서 초안 중 하나를 접수한다. 수동 재시도는 새 작업 ID를 발급한다. 제6절 이후의 조회나 수정은 이 API를 자동 호출하지 않는다.

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
| `sourceRevision` | string | ✅ | 최신 자료와 일치 | 사용자에게 표시한 근거 자료 식별값 |
| `workItemId` | string | - | 항목 기능이면 필수 | 요청 소속 항목 |
| `photoGroupId` | string | - | 사진 비교이면 필수 | 현재 선택 비교쌍 |
| `guideId` | string | - | 가이드 표현이면 필수 | 적용 가능한 검증 가이드 |
| `retryOfJobId` | string | - | 본인 실패·시간 초과 작업 | 수동 재시도 연결 |

**Response 202 Accepted**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | AiJobDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **409 Conflict**: 요청 전체 추가 질문 5회 한도 초과 (`QUESTION_LIMIT_REACHED`)
- **422 Unprocessable Content**: 벽지 물자국 외 사진 변화 분석 (`ANALYSIS_NOT_SUPPORTED`)
- **422 Unprocessable Content**: 해당 기능의 필수 정보·사진 근거 부족 (`INSUFFICIENT_INPUT`)

---

### GET `/ai-jobs/{jobId}` — AI 상태·결과·오류 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 저장된 작업만 조회한다. 처리 실패·시간 초과도 작업 조회 자체는 `200`이며 오류를 `data.error`로 반환한다. 낡은 결과는 표시하되 최신 확정본에 반영하지 않고 삭제 근거는 반환하지 않는다. 요청 본문은 없습니다.

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
- **설명**: 질문 하나의 답변 또는 건너뛰기를 한 회로 확정한다. 현재 정보로 진행은 언제든 가능하며 재접속·재시도로 누적 횟수를 초기화하지 않는다. 다음 질문 생성은 명시적 AI 작업으로 요청한다.

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
| `action` | DialogueAction | ✅ | `ANSWER`, `SKIP`, `FINISH` | 문답 처리 |
| `questionId` | string | - | 답변·건너뛰기이면 필수 | 현재 질문 |
| `answer` | string | - | `ANSWER`이면 `answer` 또는 `optionId` 필수 | 사용자 답변 |
| `optionId` | string | - | 구조화 질문의 유효 선택지 | 긴급 분기에도 사용 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DialogueDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 요청 전체 추가 질문 5회 한도 초과 (`QUESTION_LIMIT_REACHED`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

## 6. 기사 프로필·사례·일정 (Technicians)

> `W08~09`, `W22` · `FR-PRO-01~05`. 쓰기와 본인 일정 조회는 기사 역할의 연결된 기사만 허용한다. 포트폴리오 용량·개수·삭제 정책은 미정이며 요청 사진 제한을 적용하지 않는다. 실제 접수자료를 사례로 가져오는 경로는 없다.

### GET `/technicians/me` — 본인 기사 자원 조회

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 프로필·비공개 공개설정·포트폴리오 목록·연결 자원을 조회한다. 요청 본문은 없습니다.

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | TechnicianDTO | 처리 결과 |

---

### PUT `/technicians/me/profile` — 프로필 등록·수정

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 공개 연락수단의 등록·수정·공개 중단을 반영한다. 다른 계정의 연락처를 대신 사용하지 않는다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `profile` | TechnicianProfileInputDTO | ✅ | 본인 자원 | 공개 정보·공개 설정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | TechnicianDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

### POST `/technicians/me/portfolio-photos` — 본인 포트폴리오 사진 업로드

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 과거 작업 사진을 본인 마이페이지에 저장한다. 요청·상담·예약 수행 내역에 첨부하지 않는다. 파일 제한은 확인 필요이다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `multipart/form-data` | ✅ |

**Request Body (`multipart/form-data`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `files` | binary[] | ✅ | 형식·용량·개수 미정 | 프로필용 사진 |
| `source` | SourceDTO | ✅ | 출처·사용 가능 여부 확인 | 실제 접수자료 전환 금지 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | MediaDTO[] | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 준비 자료 출처·사용 가능 여부·비식별 검증 실패 (`SOURCE_NOT_VERIFIED`)

---

### GET `/technicians/{technicianId}/portfolio` — 포트폴리오·사례 목록 조회

- **인증 요구사항**: ✅
- **선행 조건**: 로그인; 공개 검증 자료
- **설명**: 본인은 자신의 자료를 조회하며 타인은 공개 범위·출처·비식별 검증을 통과한 자료만 조회한다. 요청 본문은 없습니다.

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
- **설명**: 최초 증상·현장 확인 원인 또는 미확인·작업·부품·전후 사진·출처를 구분한다. 이번 시연은 별도로 준비한 모의·재현자료만 사용한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |
| `Content-Type` | `application/json` | ✅ |

**Request Body (`application/json`)**

| 필드 | 타입 | 필수 | Validation | 설명 |
| --- | --- | --- | --- | --- |
| `case` | CaseInputDTO | ✅ | 본인 프로필 사진·검증 자료 | 사례 내용 |

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
- **설명**: 수정 내용을 검색·추천에 반영한다. 관련 평가 결과는 최신성 검사를 적용하고 AI를 자동 실행하지 않는다.

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
| `case` | CaseInputDTO | ✅ | 본인 사례 | 수정한 현재 내용 |

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
- **설명**: 출처·모의/재현 표시·담당 기사·전후 사진을 제공한다. 실제 시공 실적으로 표시하지 않는다. 요청 본문은 없습니다.

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
- **설명**: 가능 구간·외부 일정·확정 예약·이동·진행 작업·초과·재검사 상태와 고정 출발·복귀 위치를 반환한다. 요청 본문은 없습니다.

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

- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

### PUT `/technicians/me/schedule` — 가능 시간·외부 일정 변경

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 지정 날짜 구간의 편집 가능 일정만 교체한다. 모든 요청의 확정 예약·작업·이동을 보호하며 충돌하면 변경 전체를 저장하지 않는다.

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

- **409 Conflict**: 기사 작업·이동 충돌·다른 실제 작업 진행 중 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **409 Conflict**: 서울 동·이동·작업 기준 자료 부족으로 필요한 검사 불가 (`REFERENCE_DATA_MISSING`)

---

## 7. 사례 매칭·동선 탐색 (Matching)

> `W10~11` · `FR-MAT-01~06`, `FR-FLX-01~05`. 자기 기사는 제외한다. 사례 추천은 확인 요약·분야·작업 지역·방문 조건을 사용한다. 일반 후보는 시간 미확인 상태에서도 상담 선택 가능하다. 추천 조회는 AI를 실행하지 않는다.

### GET `/work-items/{workItemId}/case-recommendations` — 사례 기반 기사 추천 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 명시적 `CASE_MATCHING` 작업 결과를 조회한다. 3점 이상 사례의 기사별 상위 3개 평균을 사용하고 조건을 충족한 최대 5명을 반환한다. 미실행·평가 미완료·사례 없음·적합 기사 없음을 구분한다. 요청 본문은 없습니다.

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

---

### GET `/work-items/{workItemId}/general-candidates` — 일반 기사 후보 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 확인 분야·지역으로 기사 식별자순 탐색한다. 사례·시연 자료 없음은 차단 사유가 아니며 사례 점수 없이 시간 적합성·미확인 조건을 표시한다. 요청 본문은 없습니다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 (제안) | 1~100 (제안·확인 필요) |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<CandidateDTO> | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 해당 기능의 필수 정보·사진 근거 부족 (`INSUFFICIENT_INPUT`)

---

### PUT `/work-items/{workItemId}/route-exploration` — 동선 탐색 공개·중단

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 항목별 최소 공개 정보를 사용자가 확인한 경우만 기사 추천에 노출한다. 중단하면 미선택 기사 목록에서 제외하며 기존 상담·예약은 유지한다.

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
| `enabled` | boolean | ✅ | 활성화 시 필수 정보 확인 | 탐색 시작·중단 |
| `confirmed` | boolean | ✅ | 활성화 시 `true` | 분야·동·시간·추정 시간 공개 확인 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | WorkItemDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 해당 기능의 필수 정보·사진 근거 부족 (`INSUFFICIENT_INPUT`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)

---

### GET `/technicians/me/route-candidates` — 기사 동선 추천 작업 조회

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인
- **설명**: 공개 확인된 항목의 최소 정보만 반환한다. 삽입 가능한 구간별 추가 이동시간의 최솟값 오름차순, 동률은 접수 시각·추천 식별자순이다. 효율만 미산정이면 뒤에 분리하며 충돌 검사 불가를 적합으로 표시하지 않는다. 요청 본문은 없습니다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `date` | date | ✅ | 없음 | 탐색일 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 (제안) | 1~100 (제안·확인 필요) |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<RouteCandidateDTO> | 처리 결과 |

---

### POST `/route-candidates/{candidateId}/interests` — 상담 참여 의사 표시

- **인증 요구사항**: ✅
- **선행 조건**: 기사 본인; 탐색 공개 중
- **설명**: 추천용 식별자에 참여 의사만 표시한다. 상세 자료·정식 견적·예약 권한은 생기지 않는다. 요청 본문은 없습니다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
| `Idempotency-Key` | `"<client-generated-key>"` (공통 멱등 키 규칙) | ✅ |

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `candidateId` | string | 동선 추천용 식별자 식별자; 실제 형식 미정 |

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
- **설명**: 항목 소유자가 참여 기사의 공개 프로필·사례를 비교하고 상담 상대를 선택할 수 있게 한다. 요청 본문은 없습니다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | InterestDTO[] | 처리 결과 |

---

## 8. 상담 관계·견적 (Consultations)

> `W12~13` · `FR-CON-01~04`, `FR-QTE-01~05`. 사용자 또는 해당 관계 기사만 접근한다. 상담은 대화 저장이 아니며 수락된 활성 상담에서만 정식 견적을 발행한다. 직접 선택에는 동선 탐색·참여 의사가 필요하지 않다.

### POST `/work-items/{workItemId}/consultations` — 기사 선택·상담 요청

- **인증 요구사항**: ✅
- **선행 조건**: 소유자; 지역·방문 조건·요약 확인
- **설명**: 기사별로 사용자가 확인한 전달 범위로 새 상담을 생성한다. 복수 기사 선택은 개별 호출한다. 재상담은 새 선택·공개 확인·수락·견적 발행을 거친다.

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
| `deliveryId` | string | ✅ | 동일 항목·수신 기사; 확인 완료 | 상담용 전달본 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ConsultationDTO | 처리 결과 |

**예외 응답**

- **403 Forbidden**: 자기 계정 요청의 기사 참여 시도 (`SELF_PARTICIPATION_FORBIDDEN`)
- **409 Conflict**: 목적·수신자에 맞는 최신 전달 확인 없음 (`DELIVERY_NOT_CONFIRMED`)
- **409 Conflict**: 전체 종료 또는 삭제 중인 요청에 새 관계·자료 생성 시도 (`RESOURCE_CLOSED`)

---

### GET `/consultations` — 참여 상담 목록

- **인증 요구사항**: ✅
- **선행 조건**: 현재 역할의 당사자
- **설명**: 사용자는 자기 요청의 관계, 기사는 본인이 선택된 관계만 조회한다. 타 기사 견적·자료를 노출하지 않는다. 요청 본문은 없습니다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `status` | ConsultationStatus | - | 전체 | 관계 상태 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 (제안) | 1~100 (제안·확인 필요) |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<ConsultationDTO> | 처리 결과 |

---

### GET `/consultations/{consultationId}` — 상담 상세·전달 이력 조회

- **인증 요구사항**: ✅
- **선행 조건**: 관계 당사자
- **설명**: 선택·수락·종료 이력과 본 관계의 견적·허용 전달본을 조회한다. 종료 유형별 권한을 적용한다. 요청 본문은 없습니다.

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
- **설명**: 수락·거절은 기사, 선택 해제는 사용자, 종료는 당사자가 수행한다. 종료 시 해당 미확정 견적을 무효화한다. 활성 예약은 상담 해제로 우회 취소할 수 없다.

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
- **설명**: 미확정 제안의 수정은 새 버전을 발행하고 이전 견적을 대체한다. 이미 선택된 견적·확정 합의는 수정하지 않고 예약 변경 절차를 사용한다. 소요 시간과 전체 방문 구간·이동을 재검사한다.

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
| `terms` | QuoteTermsDTO | ✅ | 비용·시간·전제 검증 | 확정 비용·미확정 조건·방문 제안 |
| `replacesQuoteId` | string | - | 본 상담의 최신 미확정 견적 | 수정 발행 시 지정 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | QuoteDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 수락된 활성 상담·사용자 선택이 없음 (`CONSULTATION_NOT_ACTIVE`)
- **409 Conflict**: 항목에 활성 예약 존재 또는 상담 종료로 예약 취소 시도 (`ACTIVE_RESERVATION_EXISTS`)
- **409 Conflict**: 기사 작업·이동 충돌·다른 실제 작업 진행 중 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 음수·소수 원 금액·최소 비용 미확인·동일 조건 할인 위반 (`INVALID_COST`)

---

### PATCH `/quotes/{quoteId}` — 견적 철회·거절

- **인증 요구사항**: ✅
- **선행 조건**: 발행 기사 또는 요청 소유자
- **설명**: 철회는 발행 기사, 거절은 사용자만 수행한다. 이미 선택된 견적의 합의는 예약 변경·취소 절차를 따른다.

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
- **설명**: 같은 항목의 견적·선택 가능 여부·최소 비용·미확정 조건·동일 조건 할인 계산을 비교한다. 요청 본문은 없습니다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `workItemId` | string | 작업 항목 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | QuoteDTO[] | 처리 결과 |

---

## 9. 예약·변경 합의 (Reservations)

> `W14~15`, `W21` · `FR-RES-01~06`, `FR-WRK-08`. 확인용 사전 검사와 반영 직전 재검사를 구분한다. 검사 성공은 예약 보장이 아니다. 같은 요청의 다른 기사 방문만 사용자 중복 확인을 적용하며 동일 기사 충돌은 허용하지 않는다.

### POST `/reservation-checks` — 예약·변경·시작 조건 사전 검사

- **인증 요구사항**: ✅
- **선행 조건**: 소유자 또는 관련 기사
- **설명**: 신규 확정·시작 전 변경·작업 시작·진행 중 변경의 최신 조건과 중복 방문 대상을 조회한다. 예약·점유·AI 작업은 생성하지 않는다. 조건 불충족은 `200`의 `allowed=false`로 반환한다.

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

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationCheckDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

### PUT `/reservation-checks/{checkId}/overlap-confirmation` — 다른 기사 방문 중복 확인

- **인증 요구사항**: ✅
- **선행 조건**: 해당 요청 소유자
- **설명**: 검사 결과의 중복 대상·시간·조건을 사용자가 확인한다. 사용자 제안 후 기사 수락·작업 시작에도 이 확인을 참조한다. 대상·구간·조건이 달라지면 재확인하며 동일 기사 충돌을 허용하지 않는다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
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
- **409 Conflict**: 기사 작업·이동 충돌·다른 실제 작업 진행 중 (`TECHNICIAN_CONFLICT`)

---

### POST `/work-items/{workItemId}/reservations` — 견적 선택·예약 확정

- **인증 요구사항**: ✅
- **선행 조건**: 소유자; 최신 견적·방문 정보 확인
- **설명**: 활성 수락 상담·선택·전제 버전·만료·30분 준비·사용자 구간·작업·이동·중복 확인을 원자적으로 검사한다. 같은 항목 경쟁 관계만 종료하며 확정 합의·점유·권한을 함께 저장한다.

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
- **409 Conflict**: 기사 작업·이동 충돌·다른 실제 작업 진행 중 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 (`OVERLAP_CONFIRMATION_REQUIRED`)
- **409 Conflict**: 서울 동·이동·작업 기준 자료 부족으로 필요한 검사 불가 (`REFERENCE_DATA_MISSING`)
- **409 Conflict**: 초과 미갱신·종료 불명·일정 재검사 미완료로 확정 불가 (`SCHEDULE_RECHECK_REQUIRED`)
- **422 Unprocessable Content**: 서울 밖 또는 미지원 분야의 조건 충족 추천·예약 시도 (`SERVICE_UNSUPPORTED`)

---

### GET `/reservations` — 당사자 예약 목록

- **인증 요구사항**: ✅
- **선행 조건**: 현재 역할의 당사자
- **설명**: 항목별 합의·변경 대기·초과·충돌 상태를 구분한다. 조회 시점 서버 시각으로 초과 규칙을 적용한다. 요청 본문은 없습니다.

**Query Parameters**

| 파라미터 | 타입 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- | --- |
| `status` | ReservationStatus | - | 전체 | 예약 상태 |
| `cursor` | string | - | 없음 | 이전 응답의 `nextCursor` |
| `limit` | integer | - | 20 (제안) | 1~100 (제안·확인 필요) |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | PageDTO<ReservationDTO> | 처리 결과 |

---

### GET `/reservations/{reservationId}` — 예약·작업·인계 상세

- **인증 요구사항**: ✅
- **선행 조건**: 예약 당사자
- **설명**: 합의 이력·실제 시각·변경안·준비사항·수행 내역·후속 충돌을 조회한다. 상세 방문 정보는 해당 활성 예약 기사에게만 제공하고 종료 시 제거한다. 요청 본문은 없습니다.

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
- **설명**: 상대 응답 없이 취소한다. 예정 시각 경과만으로 차단하지 않는다. 점유 해제·상담 종료·선택 해제·권한 축소·항목 재탐색을 함께 반영한다.

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
- **설명**: 제안자는 제출 버전을 확인한 것으로 기록한다. 재수정은 새 버전으로 이전 수락을 무효화한다. 협의 중에는 기존 합의를 유지하며 진행 중에는 새 항목 추가·실제 시작 수정이 불가하다.

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
| `terms` | AgreementTermsDTO | ✅ | 유형별 변경 허용 범위 | 새 범위·비용·종료·방문 조건 |
| `replacesChangeId` | string | - | 기존 미반영 변경안 | 재수정 대상 |

**Response 201 Created**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationChangeDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

### PATCH `/reservation-changes/{changeId}` — 변경안 수락·거절·철회

- **인증 요구사항**: ✅
- **선행 조건**: 예약 당사자; 동일 변경 버전
- **설명**: 같은 버전 양측 수락 후 반영 직전 재검사한다. 시작 전은 30분 준비, 진행 중은 미래 종료·후속 충돌 해소를 검사한다. 원견적 사후 만료는 거절 사유가 아니다. 실패하면 기존 조건·점유를 유지한다.

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
| `overlapConfirmation` | OverlapConfirmationDTO | - | 변경된 중복이 있으면 필수 | 사용자 본인만 확인 가능 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationChangeDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **409 Conflict**: 기사 작업·이동 충돌·다른 실제 작업 진행 중 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 (`OVERLAP_CONFIRMATION_REQUIRED`)
- **409 Conflict**: 반영 직전 방문 시작이 미래가 아니거나 30분 미만 (`INSUFFICIENT_LEAD_TIME`)

---

## 10. 실제 작업·방문 준비 (Work)

> `W15`, `W19` · `FR-WRK-01~08`, `FR-HND-05`. 실제 시각을 클라이언트에서 받지 않는다. 사용자 중단 요청은 점유를 해제하지 않는다. 완료·중단 후 실제 위치·서버 종료 시각·이동을 재검사한 잔여 시간만 개방한다.

### PUT `/reservations/{reservationId}/early-start-consent` — 조기 시작 동의·철회

- **인증 요구사항**: ✅
- **선행 조건**: 요청 소유자; 시작 전
- **설명**: 현재 예약 조건과 조기 시작 대상 시각에 동의하거나 철회한다. 실제 시작 한 번만 유효하며 조건 변경·취소·철회로 무효화한다. 30분 준비를 다시 요구하지 않는다.

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
| `action` | ConsentAction | ✅ | 부여 또는 철회 | 사용자 확인 |
| `proposedStartAt` | dateTime | - | 부여 시 필수 | 동의한 조기 시작 대상 시각 |
| `overlapConfirmation` | OverlapConfirmationDTO | - | 새 중복이 있으면 필수 | 사용자 확인 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **409 Conflict**: 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 (`OVERLAP_CONFIRMATION_REQUIRED`)

---

### POST `/reservations/{reservationId}/work-events` — 시작·중단 요청·중단·완료·종료 예상 갱신

- **인증 요구사항**: ✅
- **선행 조건**: 액션별 사용자 또는 담당 기사
- **설명**: `REQUEST_STOP`은 사용자, 나머지는 담당 기사만 수행한다. 시작은 다른 진행·중단 요청 작업 부재·이동·동의·최신 중복을 검사한다. 완료는 중단 요청이 없을 때만 가능하다. 실제 초과의 운영상 예상은 충돌이 있어도 사실대로 저장하고 충돌을 표시하며 계약 금액·범위를 바꾸지 않는다.

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
| `performance` | PerformanceInputDTO | - | 완료·중단이면 필수 | 원인·수행·미수행·부품·종료 위치 |
| `expectedEndAt` | dateTime | - | 예상 갱신이면 필수; 현재 이후·15분 단위 | 운영상 종료 예상 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReservationDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 허용되지 않은 상태 전이·처리 순서 (`INVALID_STATE`)
- **409 Conflict**: 현재 조건의 유효한 조기 시작 동의 없음 (`EARLY_START_CONSENT_REQUIRED`)
- **409 Conflict**: 기사 작업·이동 충돌·다른 실제 작업 진행 중 (`TECHNICIAN_CONFLICT`)
- **409 Conflict**: 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 (`OVERLAP_CONFIRMATION_REQUIRED`)
- **409 Conflict**: 조회한 리소스·전제·합의 버전과 현재 값이 다름 (`VERSION_CONFLICT`)
- **422 Unprocessable Content**: 필수 입력·15분 단위·범위·조건부 필드 오류 (`VALIDATION_ERROR`)

---

### PUT `/reservations/{reservationId}/preparation-notes` — 방문 준비사항 등록·수정

- **인증 요구사항**: ✅
- **선행 조건**: 해당 활성 예약 담당 기사
- **설명**: 장비·부품·현장 점검 사항을 항목·예약에 저장한다. 사용자와 기사 간 질문·답변이나 사진 업로드 용도로 사용하지 않는다. 당사자는 예약 상세에서 조회한다.

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

> `W18~19` · `FR-HND-01~05`, `FR-INF-01~02`, `FR-INF-05`. 작성·확인은 요청 소유자, 수신자 조회는 관계별 허용 범위만 가능하다. 원본 접근 권한을 전달하지 않는다. 자료·가림·범위 변경 시 이전 확인을 재사용하지 않는다.

### POST `/work-items/{workItemId}/deliveries` — 가림·공개 범위 전달본 준비

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 선택 자료의 텍스트·사진·파일명을 가리거나 제외하고 메타데이터를 제거한다. 상담 전에는 수신 기사에 묶인 비공개 준비본을 만들며 상담 선택 후에만 열람 권한을 부여한다. 변경 제출은 기존 전달본·PDF 확인을 무효화한다.

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
| `replacesDeliveryId` | string | - | 동일 항목·목적의 기존본 | 재작성 대상 |

**Response 202 Accepted**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DeliveryDTO | 처리 결과 |

**예외 응답**

- **422 Unprocessable Content**: 타 요청·타 항목·타 기사·삭제 자료 참조 (`INVALID_REFERENCE`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)

---

### GET `/deliveries/{deliveryId}` — 전달본 처리 상태·미리보기·열람

- **인증 요구사항**: ✅
- **선행 조건**: 소유자 또는 허용 수신자
- **설명**: 소유자는 처리 완료 미확정 미리보기를 검토할 수 있다. 수신자는 최신 확인·관계 권한을 통과한 범위만 조회한다. 실패·미완료 자료를 원본으로 대체하지 않는다. 요청 본문은 없습니다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `deliveryId` | string | 전달본 식별자; 실제 형식 미정 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | DeliveryDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 처리 중·실패·갱신 필요·삭제 근거로 파생 자료 제공 불가 (`DERIVED_CONTENT_UNAVAILABLE`)

---

### PUT `/deliveries/{deliveryId}/confirmation` — 처리 결과·공개 범위 확인

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 현재 근거·가림 결과·자료 범위를 사용자가 확인한다. 확인만으로 상담 관계를 생성하지 않는다. 활성 관계의 보완 자료는 확인 후 해당 관계에만 제공한다.

**Headers**

| 헤더 | 값 | 필수 |
| --- | --- | --- |
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

- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **409 Conflict**: 가림·메타데이터 제거 실패 또는 미완료 (`REDACTION_INCOMPLETE`)

---

### PUT `/work-items/{workItemId}/report` — 보고서 직접 작성·수정 초안

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 사진·촬영일·관찰·발견 조건·조치·미확인을 연결한 Markdown 초안을 작성한다. 새 초안은 확인 후 현재 보고서를 교체하고 이전 본문 복원 이력은 남기지 않는다.

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
| `sourceRevision` | string | ✅ | 최신 자료와 일치 | 사용자에게 표시한 근거 자료 식별값 |
| `report` | ReportInputDTO | ✅ | 현존 근거 참조 | 사진과 Markdown 본문 |

**Response 200 OK**

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `data` | ReportDTO | 처리 결과 |

**예외 응답**

- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **422 Unprocessable Content**: 타 요청·타 항목·타 기사·삭제 자료 참조 (`INVALID_REFERENCE`)

---

### GET `/work-items/{workItemId}/report` — 본인 보고서·초안 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 본인에게 미확정·갱신 필요 상태를 표시한다. 삭제 근거가 포함된 출력은 제공하지 않는다. 기사 인계는 관계별 전달본으로 조회한다. 요청 본문은 없습니다.

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

### POST `/work-items/{workItemId}/report-confirmation` — 최신 보고서 본문 확인

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 최신 근거와 수정 초안을 확인하여 현재 보고서로 반영한다. 목적별 전달·PDF에는 별도의 가림·공개 범위 확인이 필요하다.

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

- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)
- **409 Conflict**: 처리 중·실패·갱신 필요·삭제 근거로 파생 자료 제공 불가 (`DERIVED_CONTENT_UNAVAILABLE`)

---

### POST `/deliveries/{deliveryId}/pdf-jobs` — 사진 포함 PDF 생성

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 확인된 외부 공유용 보고서 전달본을 PDF로 렌더링한다. 사진·촬영일·기존 변화 표시·본문·생성 시각·미확인 상태를 함께 표시한다. 이 API는 AI를 실행하지 않는다.

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

### GET `/pdf-jobs/{jobId}` — PDF 생성 상태 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 처리 중·완료·실패·갱신 필요를 조회한다. 성공 이후에도 근거·권한이 바뀌면 다운로드 불가로 표시한다. 요청 본문은 없습니다.

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
- **설명**: 제공 직전에 근거·공개 확인·가림·권한을 다시 검사한다. 외부 공개 URL과 Markdown 원본 다운로드는 제공하지 않는다. 이미 내려받은 파일은 자동 회수·갱신하지 않는다. 요청 본문은 없습니다.

**Path Variables**

| 변수 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | 해당 종류의 비동기 작업 식별자; 실제 형식 미정 |

**Response 200 OK**

| 항목 | 값 |
| --- | --- |
| Content-Type | `application/pdf` |
| Content-Disposition | `attachment`; 개인정보 없는 파일명 |
| Body | 사진·그림과 렌더링한 Markdown 본문을 포함한 PDF |
| 제외 정보 | 상담·견적·상세 주소·연락처·원본 URL·가림 전 원본·금지 메타데이터 |

**예외 응답**

- **409 Conflict**: 처리 중·실패·갱신 필요·삭제 근거로 파생 자료 제공 불가 (`DERIVED_CONTENT_UNAVAILABLE`)
- **409 Conflict**: 근거 자료가 변경·삭제됨 (`STALE_SOURCE`)

---

## 12. 본인 자료 삭제 (Deletion)

> `W20~21` · `FR-INF-06~07`. 삭제는 작업 리소스로 접수·조회·재시도한다. 사진은 활성 관계·마지막 한 장 여부와 무관하게 허용한다. 일반 기록·요청 전체는 관련 활성 상담·예약·작업이 있으면 거절한다.

### POST `/deletion-jobs` — 사진·일반 기록·요청 전체 삭제

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 소유·영향 범위를 재검사하고 대상과 참조 결과의 새 접근·늦은 결과 반영을 차단한다. 모든 참조·원본·전달본·임시/완성 PDF를 정리한다. 전체 삭제는 모든 연결 자료를 제거하되 기사 프로필·다른 요청·별도 평가 자료는 유지한다.

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

- **403 Forbidden**: 소유·관계·자료 범위 권한 없음; 비공개 최신 상태는 제공하지 않음 (`ACCESS_DENIED`)
- **409 Conflict**: 일반 기록·전체 삭제 또는 전체 종료를 막는 활성 관계 (`ACTIVE_RELATION_EXISTS`)

---

### GET `/deletion-jobs/{jobId}` — 삭제 처리 상태 조회

- **인증 요구사항**: ✅
- **선행 조건**: 본인
- **설명**: 완료·처리 중·거절·실패·영향 범위·접근 차단·회복 사진 수를 반환한다. 삭제 본문·파일을 상태 이력에 복제하지 않는다. 요청 본문은 없습니다.

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
- **설명**: 부분 실패의 남은 정리만 이어서 수행한다. 전체 제거 확인 전 완료로 표시하지 않으며 관련 예약은 종료하지 않는다. 요청 본문은 없습니다.

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

## 공통 에러 응답

### 공통 에러 응답 구조

> `W21`의 원인 코드·대상 필드·재시도·최신 상태·권한 여부·필요 조치를 반영한 `ErrorResponseDTO` 제안이다. 구현 코드가 없어 실제 응답 래퍼·필드·HTTP 매핑은 확인 필요이다. 아래 필드를 루트에 반환하며 `data`로 감싸지 않는다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `code` | string | 원인 코드 |
| `message` | string | 사용자에게 표시할 사유 |
| `fieldErrors` | FieldErrorDTO[] | 필드·파일별 사유; 없으면 빈 배열 |
| `retryable` | boolean | 수정 없이 동일 작업 재시도가 가능한지 |
| `permissionDenied` | boolean | 인증·인가 문제 여부 |
| `currentState` | ResourceStateDTO? | 권한 범위 내 최신 상태; 없거나 공개 불가이면 `null` |
| `requiredActions` | string[] | 재조회·입력 보완·관계 정리·수동 복귀 등 필요한 조치 |

중첩 오류 경로는 `fieldErrors.0.field`, `currentState.revision`처럼 표시한다. 삭제 거절·실패 상태를 추적하는 작업이 생성된 경우 `currentState.resourceId`로 해당 작업을 연결한다. 권한 없는 대상의 존재·필드·상태는 노출하지 않는다.

### HTTP 상태 코드별 예외 조건

| HTTP Status | 에러 코드 | 예시 메시지 / 추가 정보 |
| --- | --- | --- |
| 400 Bad Request | `BAD_REQUEST` | 본문 구문·파트 형식이 올바르지 않음 |
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
| 409 Conflict | `QUESTION_LIMIT_REACHED` | 요청 전체 추가 질문 5회 한도 초과 |
| 409 Conflict | `EXPLORATION_CLOSED` | 동선 탐색 중단·최소 공개 철회 |
| 409 Conflict | `ACTIVE_RELATION_EXISTS` | 일반 기록·전체 삭제 또는 전체 종료를 막는 활성 관계 |
| 409 Conflict | `ACTIVE_RESERVATION_EXISTS` | 항목에 활성 예약 존재 또는 상담 종료로 예약 취소 시도 |
| 409 Conflict | `CONSULTATION_NOT_ACTIVE` | 수락된 활성 상담·사용자 선택이 없음 |
| 409 Conflict | `QUOTE_UNAVAILABLE` | 만료·철회·거절·대체·전제 변경·관계 종료로 선택 불가 |
| 409 Conflict | `INSUFFICIENT_LEAD_TIME` | 반영 직전 방문 시작이 미래가 아니거나 30분 미만 |
| 409 Conflict | `TECHNICIAN_CONFLICT` | 기사 작업·이동 충돌·다른 실제 작업 진행 중 |
| 409 Conflict | `OVERLAP_CONFIRMATION_REQUIRED` | 같은 요청의 다른 기사 방문 중복에 최신 사용자 확인 필요 |
| 409 Conflict | `EARLY_START_CONSENT_REQUIRED` | 현재 조건의 유효한 조기 시작 동의 없음 |
| 409 Conflict | `WORK_ALREADY_STARTED` | 실제 시작 후 일반 취소·시작 전 변경 시도 |
| 409 Conflict | `SCHEDULE_RECHECK_REQUIRED` | 초과 미갱신·종료 불명·일정 재검사 미완료로 확정 불가 |
| 409 Conflict | `REFERENCE_DATA_MISSING` | 서울 동·이동·작업 기준 자료 부족으로 필요한 검사 불가 |
| 409 Conflict | `DELIVERY_NOT_CONFIRMED` | 목적·수신자에 맞는 최신 전달 확인 없음 |
| 409 Conflict | `REDACTION_INCOMPLETE` | 가림·메타데이터 제거 실패 또는 미완료 |
| 409 Conflict | `DERIVED_CONTENT_UNAVAILABLE` | 처리 중·실패·갱신 필요·삭제 근거로 파생 자료 제공 불가 |
| 413 Content Too Large | `FILE_TOO_LARGE` | 사용자 요청 사진 파일당 10,000,000 Byte 초과 |
| 415 Unsupported Media Type | `UNSUPPORTED_MEDIA_TYPE` | 실제 파일 형식 또는 Content-Type 미지원 |
| 422 Unprocessable Content | `VALIDATION_ERROR` | 필수 입력·15분 단위·범위·조건부 필드 오류 |
| 422 Unprocessable Content | `UPLOAD_BATCH_REJECTED` | 묶음 내 손상 이미지·메타정보 불일치·파일별 오류; 전부 미저장 |
| 422 Unprocessable Content | `INVALID_REFERENCE` | 타 요청·타 항목·타 기사·삭제 자료 참조 |
| 422 Unprocessable Content | `ADDRESS_REGION_MISMATCH` | 상세 주소와 입력 작업 지역 불일치 |
| 422 Unprocessable Content | `SERVICE_UNSUPPORTED` | 서울 밖 또는 미지원 분야의 조건 충족 추천·예약 시도 |
| 422 Unprocessable Content | `ANALYSIS_NOT_SUPPORTED` | 벽지 물자국 외 사진 변화 분석 |
| 422 Unprocessable Content | `INSUFFICIENT_INPUT` | 해당 기능의 필수 정보·사진 근거 부족 |
| 422 Unprocessable Content | `INVALID_COMPARISON_PAIR` | 다른 부위·같은 사진·유효하지 않은 비교쌍 |
| 422 Unprocessable Content | `GUIDE_NOT_APPLICABLE` | 적용 조건을 충족하지 않은 가이드 실행 경로 선택 |
| 422 Unprocessable Content | `INVALID_COST` | 음수·소수 원 금액·최소 비용 미확인·동일 조건 할인 위반 |
| 422 Unprocessable Content | `SOURCE_NOT_VERIFIED` | 준비 자료 출처·사용 가능 여부·비식별 검증 실패 |
| 500 Internal Server Error | `INTERNAL_ERROR` | 저장·내부 처리 실패; 상세 내부 정보는 미노출 |
| 503 Service Unavailable | `SERVICE_UNAVAILABLE` | 일시적 처리 불가; 재시도 가능 여부를 함께 반환 |

AI 작업 내부 오류 `AI_TIMEOUT`, `AI_PROVIDER_ERROR`, `AI_OUTPUT_INVALID`는 `AiJobDTO.error`에서 구분하는 코드 제안이다. 정상 작업 조회는 `200`을 유지한다. 인증·입력·검증 오류와 정상 판단 유보·비교 불가·미지원은 자동 재시도하지 않는다. PDF·삭제도 조회는 `200`이며 작업 상태와 오류로 처리 실패를 구분한다.

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

세션으로 인증한 계정·역할 정보를 반환한다. 세션 식별자는 `Set-Cookie` 응답 헤더로 전달하며 JSON 본문에 포함하지 않는다. 세션 만료 정보의 본문 제공 여부는 미정이다.

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
| `regions` | RegionDTO[] | 서울 전역 지원 동; 행정/법정동 체계·코드는 확인 필요 |
| `referenceVersions` | ReferenceVersionsDTO | 지역·이동·작업시간표 버전·가정 |
| `emergencyTriggers` | TriggerDTO[] | 사전 정의 긴급 입력; 빈 배열은 등록 없음 |
| `retakeGuide` | string[] | 동일 부위·유사 구도·거리 촬영 안내 |

### TriggerDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `triggerId` | string | 구조화 긴급 입력 ID |
| `label` | string | 표시 문구 |
| `version` | string | 사전 정의 규칙 버전 |

### RegionInputDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `city` | string | ✅ 시·도; 서울 밖도 접수 가능 |
| `district` | string | ✅ 시·군·구 |
| `neighborhood` | string | ✅ 읍·면·동 |
| `regionId` | string? | - 기준 자료 ID; 미매핑이면 `null` |

### RegionDTO

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
| `regions` | RegionDTO[] | 활동 지역 |
| `contacts` | ContactDTO[] | 공개 중인 업무 연락수단만; 비공개 값은 제외 |
| `directContactAvailable` | boolean | 공개 연락수단 존재 여부 |
| `visitAvailability` | string | 리터럴 `UNKNOWN`; 실제 방문 가능성은 직접 협의 |

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
| `verified` | boolean | 서버 검증 결과; 클라이언트 자기 선언만으로 확정하지 않음 |

### GuidanceDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `status` | GuidanceStatus | 등록 안내·정보 부족·없음·적용 불가·검증 실패 구분 |
| `guides` | GuideDTO[] | 검증된 안내만; 불가이면 실행 절차를 제공하지 않음 |
| `officialRoutes` | OfficialRouteDTO[] | 사전 확인된 공식 대안; 없으면 빈 배열 |
| `missingFields` | string[] | AS 안내에 필요한 제품 정보만 요청 |
| `message` | string | 실제 방문 가능 여부는 미확인; 안내 불가 사유 등 |

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
| `guidance` | GuidanceDTO | 고정 가이드·공식 AS·보완 필요 |
| `selectedPath` | ResolutionPath? | 미선택이면 `null` |

### ProductDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `productType` | string? | - 제품 종류; 모름은 `null` |
| `manufacturer` | string? | - 제조사; 다른 필드와 독립적으로 모름 허용 |
| `modelName` | string? | - 모델명; 모름은 `null` |

### SymptomContextDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `locationDescription` | string? | - 고장 부위; 상세 방문 주소와 별개 |
| `discoveredOn` | date? | - 최초 발견일; 업로드·수정일과 구분 |
| `conditions` | string? | - 발생 조건 |
| `recurring` | boolean? | - 반복 여부; 모르면 `null` |
| `attemptedActions` | string[] | - 시도한 조치; 미입력은 빈 배열 |

### RequestInputDTO

최초 접수는 AI를 자동 실행하지 않는다. 긴급 표시는 검증된 정적 안내로 즉시 연결한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `symptom` | string | ✅ 증상 텍스트; 공백 불가 |
| `photos` | PhotoInputDTO[] | ✅ `files`와 수·순서 일치; 최초에는 항목 ID 생략 가능 |
| `context` | SymptomContextDTO? | - 증상 보충 정보 |
| `product` | ProductDTO? | - 제품 정보; 최초 모두 모름 허용 |
| `region` | RegionInputDTO? | - 작업 지역; 추천·상담 전 보완 |
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
| `context` | SymptomContextDTO | 발생 조건·발견일 |
| `region` | RegionInputDTO? | 미입력이면 `null` |
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
| `resourceType` | string | 연결 자원의 종류; 허용 코드 확정 필요 |
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

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `part` | string? | ✅ 사용자 확인한 부위; 최초 기본 항목의 미확인 값만 `null` 허용 |
| `workType` | string? | ✅ 작업 종류; 최초 기본 항목의 미확인 값만 `null` 허용 |
| `quantity` | number? | ✅ 확인 시 양수; 최초 기본 항목의 미확인 값만 `null` 허용; 단위는 확인 필요 |
| `fields` | ServiceField[] | ✅ 확인 분야 집합; 미확인 기본 항목은 빈 배열 가능 |
| `otherField` | string? | - 미지원 분야 설명; 기록 허용 |
| `product` | ProductDTO | ✅ 각 필드 독립적으로 모름 허용 |
| `visitPreference` | VisitPreferenceDTO? | - 최초 접수에서 미입력 가능; 상담 전 보완 |

### WorkItemDTO

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
| `recordIds` | string[] | ✅ 현존 기록 근거; 없으면 빈 배열 |

### PhotoInputDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `capturedOn` | date? | - 사용자가 확인한 촬영일; 모름은 `null` |
| `dateConfirmed` | boolean | ✅ `true`일 때 촬영일 필수; `false`이면 `capturedOn=null` |
| `description` | string? | - 사진 설명 |
| `workItemIds` | string[] | - 이 사진을 참조할 같은 요청 항목; 최초는 기본 항목에 연결 |

### PhotoDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `photoId` | string | 요청 사진 ID; 공유 참조도 1장으로 계산 |
| `revision` | string | 사진 수정 식별값 |
| `media` | MediaDTO | 소유자에게만 원본 조회 허용 |
| `capturedOn` | date? | 사용자 확인 촬영일; 미확인 `null` |
| `suggestedCapturedOn` | date? | EXIF 촬영일 후보; 자동 확정하지 않음 |
| `dateConfirmed` | boolean | 사용자 날짜 확인 여부 |
| `description` | string? | 현재 사진 설명 |
| `workItemIds` | string[] | 공유 참조 항목 |
| `uploadedAt` | dateTime | 서버 최초 업로드 시각 |
| `updatedAt` | dateTime | 서버 최종 수정 시각 |

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

### RecordInputDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `occurredOn` | date? | - 실제 경과 날짜; 모름 허용 |
| `description` | string | ✅ 증상·조치·결과·보완 사실 |
| `photoIds` | string[] | ✅ 같은 요청 사진; 없으면 빈 배열 |
| `workItemIds` | string[] | ✅ 관련 항목; 요청 공통이면 빈 배열 |

### OutcomeInputDTO

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
| `record` | RecordInputDTO | 현재 기록 |
| `outcome` | OutcomeInputDTO? | 외부·자가 결과이면 반환 |
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
| `label` | string | 동일 부위 설명 |
| `photoIds` | string[] | 포함 사진 |
| `comparisonPhotoIds` | string[] | 기본·수동 선택된 2장; 부족하면 빈 배열 |
| `chronologyKnown` | boolean | 미확인 날짜·동일 날짜이면 `false` |
| `reason` | string? | 기본쌍 제외·자료 부족 사유 |

### TimelineDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `sourceRevision` | string | 현재 근거 식별값 |
| `photos` | PhotoCollectionDTO | 날짜 확인 여부별 사진 |
| `records` | RecordDTO[] | 실제 경과 날짜 기준; 날짜 미확인은 별도 표시 |
| `groups` | PhotoGroupDTO[] | 묶음·비교쌍 |
| `retakeGuide` | string[] | 재촬영 안내 |

### DialogueDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `revision` | string | 문답 변경 식별값 |
| `completedRounds` | integer | 요청 전체 누적 답변·건너뛰기 횟수; `0~5` |
| `finished` | boolean | 현재 정보로 진행 또는 질문 종료 여부 |
| `questions` | QuestionDTO[] | 요청 전체 문답; 새 작업·접속으로 초기화하지 않음 |
| `emergencyGuidance` | GuidanceDTO? | 긴급 입력에 해당하면 AI와 독립적으로 반환 |

### QuestionDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `questionId` | string | 질문 ID; 발행 슬롯을 원자적으로 관리해 여섯 번째 질문 방지 |
| `text` | string | 질문 하나 |
| `options` | QuestionOptionDTO[] | 구조화 선택지; 자유 답변이면 빈 배열 |
| `answer` | string? | 답변 전·건너뛰기이면 `null` |
| `optionId` | string? | 선택지 답변이면 해당 ID |
| `skipped` | boolean | 건너뛰기 여부; 동일 질문 재전송으로 횟수 증가 금지 |

### QuestionOptionDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `optionId` | string | 선택지 ID |
| `label` | string | 표시 내용 |
| `triggerId` | string? | 사전 정의 긴급 규칙 연결; 없으면 `null` |

### AiJobDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `jobId` | string | AI 작업 식별자 |
| `type` | AiJobType | 처리 종류 |
| `requestId` | string | 소유 요청 |
| `workItemId` | string? | 요청 공통 처리이면 `null` |
| `sourceRevision` | string | 실행 입력의 근거 식별값 |
| `status` | AiJobStatus | 대기·처리·성공·실패·시간 초과 |
| `receivedAt` | dateTime | 서버 접수 시각 |
| `startedAt` | dateTime? | 시작 전 `null` |
| `finishedAt` | dateTime? | 미종결이면 `null` |
| `deadlineAt` | dateTime | 접수 시각 +60초; 자동 재시도에도 유지 |
| `attempts` | AiAttemptDTO[] | 최초·자동 재시도 기록; 최대 2회 시도 |
| `retryOfJobId` | string? | 수동 재시도의 원래 실패 작업 |
| `stale` | boolean | 입력 변경으로 최신 확정에 사용 불가 |
| `result` | AiResultDTO? | 완료 결과; 미완료·삭제 근거 차단 시 `null` |
| `error` | ErrorResponseDTO? | 실패·시간 초과 원인; 정상 비교 불가는 오류가 아님 |

### AiAttemptDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `number` | integer | 시도 번호 `1~2` |
| `startedAt` | dateTime | 시도 시각 |
| `finishedAt` | dateTime? | 종료 전 `null` |
| `errorCode` | string? | 오류 식별자; 상세 AI 제공자 오류는 비공개 |

### AiResultDTO

종류에 해당하는 결과만 채우고 나머지는 `null` 또는 빈 배열로 반환한다. 질문 생성·문답 완료는 요청 전체 5회 제한을 공유한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `summary` | SummaryDTO? | `DIAGNOSIS` 초안 |
| `fieldCandidates` | ServiceField[] | 분야 후보; 미해당이면 빈 배열 |
| `question` | QuestionDTO? | `QUESTION` 결과; 질문 종료이면 `null` |
| `guideExplanation` | string? | `GUIDE_EXPLANATION`; 고정 가이드 의미 검증 통과한 설명 |
| `caseRecommendations` | CaseRecommendationsDTO? | `CASE_MATCHING` 결과 |
| `comparison` | PhotoComparisonDTO? | `PHOTO_COMPARISON` 결과 |
| `reportDraft` | ReportInputDTO? | `REPORT_DRAFT` 미확정 초안 |

### PhotoComparisonDTO

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

### TechnicianProfileInputDTO

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
| `profile` | TechnicianProfileInputDTO | 비공개 설정 포함; 본인 전용 |
| `portfolio` | PortfolioDTO | 본인 프로필 사진·사례 |

### PortfolioDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `technicianId` | string | 소유 기사 |
| `photos` | MediaDTO[] | 공개 검증 범위 또는 본인 자료 |
| `cases` | CaseDTO[] | 별도 준비된 사례; 없는 경우 빈 배열 |

### CaseInputDTO

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
| `content` | CaseInputDTO | 원문·출처·모의 구분 |
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
| `departureLocationId` | string? | 기준 출발 위치; 누락은 미확인 |
| `returnLocationId` | string? | 기준 복귀 위치 |
| `checks` | ScheduleCheckDTO[] | 이동·충돌·재검사 결과 |
| `openRanges` | TimeRangeDTO[] | 재검사 완료 후 개방한 잔여 구간 |
| `referenceVersions` | ReferenceVersionsDTO | 같은 동 내부 이동도 기준표 적용 |

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

점수 1=무관, 2=분야만 유사, 3=일부 증상·작업 관련, 4=주요 증상·작업 관련, 5=주요 증상·조건·작업 근거 밀접. 일반 후보는 별도 API로 제공한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `evaluationStatus` | EvaluationStatus | 미실행·처리 중·완료·미완료 구분 |
| `sourceRevision` | string | 평가 근거 식별값 |
| `stale` | boolean | 관련 입력·사례 변경으로 갱신 필요 |
| `recommendations` | CaseRecommendationDTO[] | 중복 없는 적합 상위 최대 5명 |
| `reason` | string? | 연관 사례 없음·적합 기사 없음·평가 미완료 등을 구분 |

### RouteCandidateDTO

이 DTO에 요청·계정 ID, 자유 입력 증상, 사진, AI 문답, 상세 주소·연락처를 추가하지 않는다. 정렬용 접수 시각은 서버가 사용한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `candidateId` | string | 비공개 요청 접근에 사용할 수 없는 추천용 ID |
| `fields` | ServiceField[] | 최소 공개 확인 분야 |
| `region` | RegionDTO | 시·군·구·동까지만 공개 |
| `visitPreference` | VisitPreferenceDTO | 최소 공개 확인 방문 조건 |
| `durationEstimate` | DurationEstimateDTO | 기사 확인 전 추정·미확인 구분 |
| `timeFit` | FeasibilityStatus | 작업·이동 검사 불가이면 `UNKNOWN` |
| `route` | RouteCalculationDTO? | 삽입 가능한 구간 중 최소 추가 이동 근거; 미산정 `null` |
| `reason` | string? | 미산정·보완 사유 |

### RouteCalculationDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `insertionRange` | TimeRangeDTO | 삽입 가능한 작업 구간 |
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
| `deliveryIds` | string[] | 현재 권한·최신성 검사 통과 자료만; 종료 유형에 따라 빈 배열 |
| `quotes` | QuoteDTO[] | 해당 관계의 견적만 |
| `events` | RelationEventDTO[] | 선택·수락·거절·종료 이력; 대화 없음 |

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
| `afterAmount` | integer? | 확정이면 필수; `0 ≤ afterAmount ≤ beforeAmount` |
| `condition` | string? | 미확정이면 발생 조건 필수; 미확정 금액은 양쪽 `null` |

### CostDTO

최소 비용은 해당 확정 출장·진단 항목과의 포함 관계를 검사해 중복 합산하지 않는다. 할인 전후는 같은 기사·범위·수량·비용 항목이며 미확정 비용은 합계에서 제외한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `minimumVisitFee` | integer | ✅ 최소 발생 출장비; 없음 확인은 0원·미입력 금지 |
| `minimumDiagnosticFee` | integer | ✅ 최소 발생 진단비; 없음 확인은 0원 |
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

서버가 `endAt = startAt + durationMinutes`를 산출한다. 전체 작업이 사용자 가능 구간에 들어가야 하며 이동은 별도 검사한다.

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

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `checkId` | string | 현재 처리·대상·조건을 묶는 검사 식별값 |
| `operation` | ReservationOperation | 신규 확정·시작 전 변경·시작·진행 중 변경 |
| `allowed` | boolean | 조회 시점 조건 충족 여부; 예약·점유 보장 아님 |
| `checks` | ScheduleCheckDTO[] | 부족 조건과 필요한 조치 |
| `overlaps` | VisitOverlapDTO[] | 같은 요청의 다른 기사 방문 중복만 |
| `overlapConfirmed` | boolean | 표시된 대상·구간·조건에 대한 사용자 확인 |
| `checkedAt` | dateTime | 서버 검사 시각 |

### VisitOverlapDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `reservationId` | string | 중복 상대 예약; 동일 요청만 |
| `workItemId` | string | 상대 작업 항목 |
| `technicianId` | string | 다른 기사 |
| `agreementVersion` | string | 상대 예약 현재 합의 |
| `range` | TimeRangeDTO | 실제 확인할 겹침 구간 |

### OverlapConfirmationDTO

사용자가 별도 확인 API로 저장한 확인은 기사 수락·시작에도 적용한다. 반영 직전 대상·구간·조건이 같아야 하며 달라지면 `OVERLAP_CONFIRMATION_REQUIRED`를 반환한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `checkId` | string | ✅ 최신 검사 대상·구간·조건 식별값 |
| `confirmed` | boolean | ✅ `true`; 사용자만 제출 가능 |

### AgreementTermsDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `fields` | ServiceField[] | ✅ 합의한 분야 |
| `scope` | string | ✅ 해당 항목의 작업 범위 |
| `quantity` | number | ✅ 양수; 다른 항목을 합치지 않음 |
| `cost` | CostDTO | ✅ 확정·미확정 비용 조건 |
| `startAt` | dateTime | ✅ 예약 시작; 진행 중 변경에서 수정 불가 |
| `expectedEndAt` | dateTime | ✅ 15분 단위; 시작 전은 양수 15분 배수 소요 시간, 진행 중은 서버 현재 이후 |
| `visitPreference` | VisitPreferenceDTO | ✅ 변경안에서 사용자 확인할 가능 조건 |
| `region` | RegionInputDTO | ✅ 해당 합의 장소; 진행 중 실제 장소 소급 변경 불가 |
| `visitDetails` | VisitDetailsDTO? | 입력 시 방문 정보 필수; 응답에서 종료 기사에게는 `null` |

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
| `userAccepted` | boolean | 같은 버전 사용자 확인 |
| `technicianAccepted` | boolean | 같은 버전 기사 확인 |
| `status` | ChangeStatus | 제안·반영·거절·철회·대체·무효 |
| `checks` | ScheduleCheckDTO[] | 현재 반영 검사 결과 |

### ReservationDTO

활성 상태는 `CONFIRMED`, `IN_PROGRESS`, `STOP_REQUESTED`이다. 취소·완료·중단은 해당 상담·선택을 함께 종료한다. 완료는 해당 항목만 해결, 취소·중단은 해당 항목만 재탐색하며 전체 요청은 자동 종료하지 않는다. 초과 미갱신 제한은 자정이 지나도 새 당일에 적용하며 다음 날도 종료 불명으로 충돌을 판단할 수 없으면 신규 확정을 차단한다.

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
| `overdue` | boolean | 서버 시각이 종료 예상에 도달한 미종료 작업 |
| `earlyStartConsent` | EarlyStartConsentDTO? | 최신 동의·철회 상태 |
| `overlaps` | VisitOverlapDTO[] | 현재 중복·재확인 대상 |
| `checks` | ScheduleCheckDTO[] | 후속 충돌·가능 충돌·재검사 필요; 자동 변경 없음 |
| `reason` | string? | 취소·중단 요청·중단 사유 |
| `performance` | PerformanceInputDTO? | 종료 기사 수행 기록; 프로필 사진 자동 첨부 없음 |
| `preparation` | PreparationDTO? | 장비·부품·점검 준비사항 |
| `handoverDeliveryIds` | string[] | 현재 관계에서 허용된 최신 인계본; 없으면 빈 배열 |

### EarlyStartConsentDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `agreementVersion` | string | 동의한 예약 조건 |
| `proposedStartAt` | dateTime | 사용자가 확인한 조기 시작 대상 시각 |
| `active` | boolean | 조건 변경·취소·철회·1회 사용 시 `false` |
| `confirmedAt` | dateTime | 서버 동의 시각 |

### PerformanceInputDTO

기사는 사용자 요청·예약에 사진을 업로드하지 않는다. 반영된 합의 버전은 예약에 연결하고 실제 종료는 서버가 기록한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `confirmedCause` | string? | ✅ 현장 확인 원인; 미확인은 `null` |
| `performed` | string[] | ✅ 실제 수행 내역; 없으면 빈 배열 |
| `notPerformed` | string[] | ✅ 미수행 내역; 완료 시 없으면 빈 배열 |
| `unknowns` | string[] | ✅ 미확인 사항 |
| `parts` | string[] | ✅ 실제 사용 부품 |
| `endLocationId` | string | ✅ 실제 종료 동 대표 위치; 누락 자료는 시간 개방 불가 |

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

### RedactionDTO

사진 가림은 픽셀에 반영하고 메타데이터를 제거한다. 요청값만으로 처리 성공을 선언하지 않으며 결과를 검사하고 사용자가 다시 확인한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `targetType` | RedactionTarget | ✅ 가림할 자료 종류 |
| `resourceId` | string | ✅ 사진·기록·질문 ID; 요약·보고서는 해당 `workItemId` |
| `exclude` | boolean | ✅ 자료 전체 제외 여부 |
| `boxes` | BoundingBoxDTO[] | ✅ 사진 가림 영역; 해당 없으면 빈 배열 |
| `replacementText` | string? | - 금지 정보를 제거한 텍스트 전체; 없으면 `null` |
| `safeFilename` | string? | - 개인정보 없는 제공 파일명 |

### PhotoEvidenceDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `photoId` | string | 근거 식별자; 원본 접근 권한을 뜻하지 않음 |
| `media` | MediaDTO | 본인 원본 또는 목적별 가림 처리본 |
| `capturedOn` | date? | 확인 촬영일; `null`은 미확인 표시 |
| `observation` | string | 사진과 연결한 관찰 설명 |
| `regions` | EvidenceRegionDTO[] | 기존 유효 변화 표시; 없으면 빈 배열 |

### ReportInputDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `markdown` | string | ✅ 발견 부위·날짜·조건·관찰·조치·결과·미확인을 구분한 본문 |
| `photoIds` | string[] | ✅ 현존 근거 사진; 전부 삭제 시 빈 배열 허용 |
| `facts` | FactDTO[] | ✅ 설명과 원본 근거 연결 |
| `unknowns` | string[] | ✅ 미입력·미확인 사항 |

### ReportContentDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `content` | ReportInputDTO | 현재 본문·근거 |
| `photos` | PhotoEvidenceDTO[] | 본문과 함께 표시할 사진·촬영일·관찰 |
| `createdAt` | dateTime | 생성 시각; 촬영일과 별개 |

### ReportDTO

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `revision` | string | 현재 초안·본문 확인 식별값 |
| `sourceRevision` | string | 참조 자료 최신성 식별값 |
| `reviewStatus` | ReviewStatus | 초안·확인 완료·갱신 필요 |
| `draft` | ReportContentDTO? | 사용자 확인 전 수정·AI 초안 |
| `current` | ReportContentDTO? | 확인 후 교체한 현재본; 삭제 근거가 있으면 제공 차단 |
| `confirmedAt` | dateTime? | 현재 확인 없으면 `null` |

### DeliveryContentDTO

원본 저장 경로를 포함하지 않는다. 상세 방문 정보는 활성 예약의 권한 있는 응답으로 별도 제공하며 외부 PDF에 넣지 않는다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `summary` | SummaryDTO? | 허용·확인된 가림 처리 요약 |
| `photos` | PhotoEvidenceDTO[] | 선택·가림 처리한 사진만 |
| `records` | RecordDTO[] | 선택·가림 처리한 보완 자료 |
| `dialogue` | QuestionDTO[] | 선택한 사용자와 AI 문답만 |
| `report` | ReportContentDTO? | 해당 목적의 확인 보고서; 금지 정보 제거 |

### DeliveryDTO

상담 거절·해제·경쟁 확정·예약 취소 후 기사는 비식별 상태·견적 이력만 조회한다. 완료·중단 기사는 종료 당시 허용본만 조회하고 상세 주소·연락처·후속 자료는 제외한다. 정정·삭제는 종료본에도 우선 적용한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `deliveryId` | string | 목적·수신자별 전달본 ID |
| `revision` | string | 가림·공개 범위 확인 대상 버전 |
| `sourceRevision` | string | 참조 근거 버전 |
| `scope` | DeliveryScopeDTO | 목적·수신자·선택 범위 |
| `status` | ProcessingStatus | 처리·준비·실패·갱신 필요 |
| `reviewStatus` | ReviewStatus | 처리 성공과 사용자 확인은 별개 |
| `content` | DeliveryContentDTO? | 소유자 처리완료 미리보기 또는 수신자 최신 확인본만 |
| `metadataRemoved` | boolean | 파일·이미지 메타데이터 제거 결과 |
| `confirmedAt` | dateTime? | 확인 전·무효화 시 `null` |
| `error` | ErrorResponseDTO? | 처리 실패·차단 사유 |

### PdfJobDTO

AI 제한시간·재시도 정책을 적용하지 않는다. 다운로드는 인증된 `/pdf-jobs/{jobId}/content`만 사용한다.

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
| `affectedWorkItemIds` | string[] | 정리·재확인이 필요한 모든 참조 항목 |
| `affectedResourceIds` | string[] | 관련 파생 결과 ID; 삭제 본문·파일 없음 |
| `accessBlocked` | boolean | 부분 실패에도 대상·파생 자료 차단 유지 |
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
| `resourceId` | string | 권한 내 대상 ID; 삭제 거절·실패 작업도 연결 가능 |
| `status` | string | 해당 자원의 Enum 상태 코드 |
| `revision` | string? | 최신 값; 조회 권한 없으면 구조 전체 미반환 |

---

## Enum 정의

> 아래 영문 리터럴은 상태·의미를 구분하기 위한 코드 제안이다. 상태의 업무 의미는 기준 문서를 따르며 최종 코드명은 FE·BE 확인 필요이다.

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
| `DIAGNOSIS` | 증상·원인 후보·분야 초안 |
| `QUESTION` | 추가 질문 하나; 요청 전체 한도 검사 |
| `GUIDE_EXPLANATION` | 검증 가이드의 표현만 맞춤화 |
| `CASE_MATCHING` | 원문 근거 사례 평가·추천 설명 |
| `PHOTO_COMPARISON` | 벽지 물자국의 동일 부위 비교 |
| `REPORT_DRAFT` | 인계·경과 보고서 초안 |

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

| 값 | 설명 |
| --- | --- |
| `AVAILABLE` | 등록·검증 안내 제공 |
| `INFORMATION_REQUIRED` | 제품 등 입력 보완 필요 |
| `NOT_REGISTERED` | 등록 안내 없음 |
| `NOT_APPLICABLE` | 적용 불가; 실행 절차 차단 |
| `VALIDATION_FAILED` | 검증 실패; 생성 절차 차단 |

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
| `START_WORK` | 실제 시작 검사; 당사자 |
| `CHANGE_IN_PROGRESS` | 진행 중 변경 검사; 당사자 |

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
| `REJECTED` | 소유·활성 관계 등으로 거절 |
| `FAILED` | 부분 정리 실패·미완료; 접근 차단 유지 |
