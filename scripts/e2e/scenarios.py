"""Compose의 실제 HTTP API로 실행하는 E2E 시나리오 명세와 검증 코드.

실행 전제
    runner.py가 실행 중인 Compose의 API·PostgreSQL·worker를 확인하고,
    fixtures.py가 이번 실행 전용 계정·기준 자료·합성 사진을 준비한다.
    이 모듈은 애플리케이션을 import하거나 DB를 직접 조회하지 않는다.
    전달본·PDF·삭제·AI 작업은 별도 worker가 처리하며 HTTP로 완료를 확인한다.

행위자
    anonymous: 비로그인 방문자. 공개 안내 및 인증 없는 접근을 확인한다.
    signup: 이번 실행에서 가입할 계정. 가입·로그인·역할 제한을 확인한다.
    user: 접수·사진·기록·예약의 소유자.
    other: 자료를 소유하지 않은 다른 사용자. 접근 거절을 확인한다.
    technician: 기사 역할로 전환한 계정. 상담·견적·작업 이벤트를 처리한다.

시나리오 색인 — 아래 번호는 명세 번호이며 터미널의 실행 순번과 다를 수 있다.
    01. 서비스 공개·회원가입·인증·역할 권한          → setup()
    02. 기사 프로필·사례·방문 가능 일정             → setup()
    03. 비AI 상담·예약·인계 갱신·정상 완료          → completion_journey()
    04. 원본 정정·선택적 AI 진단·기사 후보 탐색     → stop_journey()
    05. 외부 PDF·견적 거절·시작 전 예약 변경       → stop_journey()
    06. 조기 시작 동의·중단·종료 후 접근 제한      → stop_journey()
    07. 접수 목록 페이지 탐색·시작 전 예약 취소    → cancellation_journey()
    08. 긴급 안내·미지원 지역의 기사 후보 조회 제한 → alternative_journeys()
    09. 자가 해결 선택·사용자 해결 결과 기록       → alternative_journeys()
    10. 제조사 AS 선택·사용자 해결 결과 기록       → alternative_journeys()
    11. 외부 직접 연락 선택·사용자 해결 결과 기록  → alternative_journeys()
    12. 삭제 작업 재시도·로그아웃                  → finish()

실행 범위와 의존 관계
    api: 01~07, 12의 8개 흐름. 공개 OpenAPI의 /v1/ 업무 API 중 성공 응답으로
         호출하지 못한 메서드·경로가 남으면 실패한다.
    scenarios: 01~12의 12개 흐름. 호출 범위는 기록하되 전체 API 호출을 요구하지 않는다.
    두 모드 모두 위 순서로 실행한다. 01~02의 세션·기사 프로필·일정은 이후에 공유하고,
    04~06은 하나의 접수·작업 항목·예약·PDF를 이어서 사용한다.
    앞선 검증이 실패하면 후속 시나리오는 실행하지 않고 정리를 시도한다.

명세를 읽는 방법
    각 journey 블록의 사전 조건·기대 결과와 단계 주석을 함께 읽는다.
    공통 동작의 검증 조건은 create_request(), reserve(), delivery() 등의
    docstring에 적었다. request()는 HTTP 상태·지정한 오류 코드·응답 외피를,
    check()는 개별 결과를, poll()은 worker 작업의 최종 상태를 검사한다.
    4xx 기대 응답도 명세와 일치하면 통과하지만 전체 API의 성공 호출로 세지는 않는다.

검증 한계
    AI는 DIAGNOSIS만 실행하며, 설정이 없으면 AI_NOT_CONFIGURED 실패를 검사한다.
    이 경우 실제 AI 성공 경로는 미검증으로 남긴다. 다른 AI 작업과 출력 품질 평가는
    포함하지 않는다. 08은 미지원 지역의 후보 조회 차단까지만 검사한다.
    09~11은 경로 선택과 사용자 진술 기록이며 실제 수리·외부 연락을 수행하지 않는다.
    12는 로그아웃 직후 인증 해제를 확인하며 시간 경과에 따른 세션 만료는 검사하지 않는다.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from PIL import Image


class CheckFailed(Exception):
    """응답 본문을 포함하지 않아 출력해도 되는 검증 실패 메시지."""


class JobFailed(CheckFailed):
    """테스트 자료 삭제 후에도 작업 상태와 오류 진단 정보를 보존하는 실패."""

    def __init__(self, message: str, details: dict[str, Any]):
        super().__init__(message)
        self.details = dict(details)


def diagnostic_code(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value):
        return value
    return "UNKNOWN"


JOURNEY_LABELS = {
    # 01~02: setup() — 이후 시나리오에서 사용할 세션·기사 정보를 준비한다.
    "published-service-and-authentication": "서비스 상태·API 명세·회원가입·로그인·권한",
    "technician-profile-cases-and-schedule": "기사 프로필·준비 사례·방문 일정",
    # 03: completion_journey()
    "no-ai-consultation-reservation-handover-completion": "비AI 상담·견적·예약·인계 갱신·정상 완료",
    # 04~06: stop_journey() — 같은 접수와 예약의 상태 변화를 이어서 검사한다.
    "record-editing-ai-choice-and-candidate-discovery": "사진·기록 정정·선택적 AI·기사 후보 탐색",
    "masked-external-pdf-and-reservation-changes": "가림 처리·실제 PDF 생성·견적 거절·예약 변경",
    "early-start-stop-and-ended-access": "조기 시작 동의·사용자 중단 요청·종료 후 접근 제한",
    # 07: cancellation_journey()
    "reservation-cancellation": "시작 전 예약 취소",
    # 08~11: alternative_journeys() — scenarios 모드에서만 실행한다.
    "emergency-guidance-and-support-boundaries": "긴급 안내·미지원 지역의 기록 및 기사 후보 조회 제한",
    "optional-resolution-self_help": "검증된 자가 해결·사용자 결과 기록",
    "optional-resolution-manufacturer_as": "제조사 AS 경로·사용자 결과 기록",
    "optional-resolution-direct_contact": "외부 직접 연락·사용자 결과 기록",
    # 12: finish() — api 모드에서는 여덟 번째로 실행한다.
    "worker-deletion-retry-and-session-expiry": "실제 worker 삭제 재시도·로그아웃",
}


def endpoint_patterns(document: dict[str, Any]) -> list[tuple[str, str, re.Pattern]]:
    """OpenAPI의 /v1/ 업무 API만 호출 범위에 포함한다."""
    patterns = []
    for path, operations in document["paths"].items():
        if not path.startswith("/v1/"):
            continue
        expression = re.escape(path)
        expression = re.sub(r"\\\{[^{}]+\\\}", "[^/]+", expression)
        for method in operations:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                patterns.append((method.upper(), path, re.compile("^" + expression + "$")))
    # /me 같은 고정 경로를 /{technicianId} 같은 매개변수 경로보다 먼저 비교한다.
    return sorted(patterns, key=lambda entry: (entry[1].count("{"), entry[1], entry[0]))


def utc_text(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


class Suite:
    """실행별 세션과 자료를 공유하며 시나리오를 순서대로 검증한다."""

    def __init__(self, args: argparse.Namespace, config: dict[str, Any]):
        self.args = args
        self.config = config
        self.output = Path(args.output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.origin = args.origin or config["origin"]
        self.clients = {
            actor: httpx.Client(
                base_url=args.base_url.rstrip("/"),
                headers={"Origin": self.origin},
                timeout=args.http_timeout,
                follow_redirects=False,
                trust_env=False,
            )
            for actor in ("anonymous", "signup", "user", "other", "technician")
        }
        self.patterns: list[tuple[str, str, re.Pattern]] = []
        self.covered: set[str] = set()
        self.calls: list[dict[str, Any]] = []
        self.assertions = 0
        self.journeys: list[dict[str, Any]] = []
        self.jobs: list[dict[str, Any]] = []
        self.current = "initialization"
        self.planned_journeys = [
            "published-service-and-authentication",
            "technician-profile-cases-and-schedule",
            "no-ai-consultation-reservation-handover-completion",
            "record-editing-ai-choice-and-candidate-discovery",
            "masked-external-pdf-and-reservation-changes",
            "early-start-stop-and-ended-access",
            "reservation-cancellation",
        ]
        if args.suite == "scenarios":
            self.planned_journeys.append("emergency-guidance-and-support-boundaries")
            self.planned_journeys.extend(
                "optional-resolution-" + path
                for path in ("self_help", "manufacturer_as", "direct_contact")
            )
        self.planned_journeys.append("worker-deletion-retry-and-session-expiry")
        self.requests: set[str] = set()
        self.cleanup_errors: list[str] = []
        self.ai_result: dict[str, Any] | None = None
        self.image = base64.b64decode(config["photoBase64"], validate=True)
        # 현재를 15분 단위로 내림한다. 예약은 2시간 뒤, 조기 시작 동의는 현재로 둔다.
        # 모든 흐름이 같은 시간대를 쓰므로 완료한 접수는 다음 예약 전에 삭제한다.
        self.base_time = int(time.time()) // 900 * 900
        self.times = {
            "start": utc_text(self.base_time + 7200),
            "expires": utc_text(self.base_time + 5400),
            "changed_start": utc_text(self.base_time + 8100),
            "changed_end": utc_text(self.base_time + 11700),
            "extended_end": utc_text(self.base_time + 12600),
            "early": utc_text(self.base_time),
        }
        seoul = timezone(timedelta(hours=9))
        self.dates = {
            "from": datetime.fromtimestamp(self.base_time - 7200, seoul).date().isoformat(),
            "to": datetime.fromtimestamp(self.base_time + 43200, seoul).date().isoformat(),
        }
        self.preference = {
            "mode": "FLEXIBLE",
            "fixedStartAt": None,
            "ranges": [
                {
                    "startAt": utc_text(self.base_time + 3600),
                    "endAt": utc_text(self.base_time + 21600),
                },
            ],
        }
        self.technician_id: str | None = None

    # 공통 검증·HTTP 기록: 아래 도우미의 실패는 현재 시나리오와 실행 전체를 중단한다.

    def check(self, condition: Any, message: str, *, announce: bool = True) -> None:
        self.assertions += 1
        if announce:
            print(f"  [{'PASS' if condition else 'FAIL'}] {message}", flush=True)
        if not condition:
            raise CheckFailed(message)

    @contextmanager
    def journey(self, name: str):
        """시나리오별 통과 여부·검증 횟수·소요 시간을 summary.json에 남긴다."""
        self.current = name
        started = time.monotonic()
        before = self.assertions
        label = JOURNEY_LABELS.get(name, name)
        print(
            f"[시나리오 {len(self.journeys) + 1}/{len(self.planned_journeys)}] {label} ({name})",
            flush=True,
        )
        entry = {"name": name, "label": label, "passed": False}
        self.journeys.append(entry)
        try:
            yield
            entry["passed"] = True
            print(f"[PASS] {label}", flush=True)
        finally:
            entry["assertions"] = self.assertions - before
            entry["seconds"] = round(time.monotonic() - started, 2)

    def request(
        self,
        actor: str,
        method: str,
        path: str,
        *,
        status: int = 200,
        code: str | None = None,
        body: dict[str, Any] | None = None,
        form: dict[str, str] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
        params: Any = None,
        key: str | None = None,
        raw: bool = False,
        api: bool = True,
        quiet: bool = False,
    ) -> Any:
        """예상 HTTP 상태와 오류 코드를 검사하고 /v1 성공 응답의 data를 반환한다.

        status 기본값은 200이다. code를 지정하면 오류 코드도 일치해야 한다.
        204는 빈 본문, 그 밖의 /v1 성공 응답은 data 외피를 요구한다.
        raw=True는 파일·HTML 응답을 그대로 반환하며 내용은 호출자가 검사한다.
        로그에는 본문·쿠키 대신 메서드·경로 양식·상태·검증 결과만 기록한다.
        """
        url = ("/v1" if api else "") + path
        template = next(
            (
                candidate
                for verb, candidate, pattern in self.patterns
                if verb == method and pattern.fullmatch(url)
            ),
            url if not api else "<unmatched v1 endpoint>",
        )
        headers = {}
        if method != "GET":
            headers["Idempotency-Key"] = '"' + (key or uuid.uuid4().hex) + '"'
        event = {
            "sequence": len(self.calls) + 1,
            "journey": self.current,
            "actor": actor,
            "method": method,
            "endpoint": template,
            "expectedStatus": status,
        }
        self.calls.append(event)
        try:
            response = self.clients[actor].request(
                method,
                url,
                json=body,
                data=form,
                files=files,
                params=params,
                headers=headers,
            )
        except httpx.HTTPError as error:
            event.update(status=None, passed=False, transportError=type(error).__name__)
            self.write_call(event)
            print(f"  [HTTP FAIL] {method} {template}: {type(error).__name__}", flush=True)
            raise CheckFailed(f"{method} {template}: transport {type(error).__name__}") from None
        event["status"] = response.status_code
        event["passed"] = response.status_code == status
        error_payload = None
        if code is not None and response.status_code == status:
            error_payload = response.json()
            event["expectedCode"] = code
            event["passed"] = error_payload.get("code") == code
        self.write_call(event)
        if not quiet or response.status_code != status:
            verdict = "PASS" if event["passed"] else "FAIL"
            print(
                f"  [HTTP {verdict}] {method} {template} -> {response.status_code} "
                f"(expected {status})",
                flush=True,
            )
        self.check(
            response.status_code == status,
            f"{method} {template}: expected HTTP {status}, got {response.status_code}",
            announce=False,
        )
        if 200 <= response.status_code < 300 and api:
            self.covered.add(f"{method} {template}")
        if code is not None:
            self.check(
                error_payload.get("code") == code,
                f"{method} {template}: expected error code {code}",
            )
        if raw:
            return response
        if status == 204:
            self.check(not response.content, "204 response must have no body")
            return None
        payload = response.json()
        if status >= 400:
            return payload
        if not api:
            return payload
        self.check(
            "data" in payload,
            f"{method} {template}: missing data envelope",
            announce=False,
        )
        return payload["data"]

    def write_call(self, event: dict[str, Any]) -> None:
        # 쿠키·인증 본문·실제 ID가 담긴 URL·요청 및 응답 본문은 기록하지 않는다.
        with (self.output / "http-calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def poll(self, path: str, expected: str, *, actor: str = "user") -> dict[str, Any]:
        """worker 작업이 expected에 도달할 때까지 조회하고 최종 상태를 검증한다.

        QUEUED·RUNNING·PROCESSING 동안만 대기한다. 예상과 다른 종료 상태나
        제한 시간 초과는 즉시 실패하며 작업 상태·오류 코드·재시도 가능 여부를 남긴다.
        expected가 FAILED이면 예상한 실패 상태도 통과할 수 있다.
        """
        deadline = time.monotonic() + self.args.poll_timeout
        last_notice = 0.0
        previous_state = None
        polls = 0
        details = {
            "journey": self.current,
            "expectedStatus": expected,
            "status": None,
            "errorCode": None,
            "retryable": None,
            "polls": 0,
            "passed": False,
        }
        self.jobs.append(details)
        while True:
            result = self.request(actor, "GET", path, quiet=True)
            polls += 1
            state = diagnostic_code(result.get("status"))
            error = result.get("error")
            error = error if isinstance(error, dict) else {}
            endpoint = self.calls[-1]["endpoint"]
            details.update(
                endpoint=endpoint,
                status=state,
                errorCode=diagnostic_code(error.get("code")),
                retryable=error.get("retryable") if type(error.get("retryable")) is bool else None,
                polls=polls,
                passed=state == expected,
            )
            self.assertions += 1
            unexpected = state != expected and state not in {"QUEUED", "RUNNING", "PROCESSING"}
            timed_out = state != expected and time.monotonic() >= deadline
            if unexpected or timed_out:
                reason = (
                    f"Worker job expected {expected}; got {state}"
                    if unexpected
                    else f"Worker job did not reach {expected} within timeout"
                )
                if details["errorCode"]:
                    reason += f"; errorCode={details['errorCode']}"
                print(f"  [JOB FAIL] GET {endpoint}: {reason}", flush=True)
                raise JobFailed(reason, details)
            if state != previous_state or time.monotonic() - last_notice > 15:
                verdict = "PASS" if state == expected else "WAIT"
                suffix = f"; errorCode={details['errorCode']}" if details["errorCode"] else ""
                print(
                    f"  [JOB {verdict}] GET {endpoint}: {state} ({polls} polls){suffix}",
                    flush=True,
                )
                previous_state = state
                last_notice = time.monotonic()
            if state == expected:
                return result
            time.sleep(0.5)

    # 공통 업무 단계: 시나리오 본문에서 호출하며, 이 안의 검증도 해당 시나리오에 합산한다.

    def upload(self) -> list[tuple[str, tuple[str, bytes, str]]]:
        return [("files", ("synthetic-e2e.png", self.image, "image/png"))]

    def root(self, request_id: str) -> dict[str, Any]:
        return self.request("user", "GET", f"/requests/{request_id}")

    def item(self, request_id: str, item_id: str) -> dict[str, Any]:
        return next(
            (item for item in self.root(request_id)["workItems"] if item["workItemId"] == item_id),
        )

    def create_request(self, label: str, *, product: dict | None = None) -> dict[str, Any]:
        """합성 누수 증상과 사진 1장으로 접수한다.

        기대 결과: HTTP 201, 접수 OPEN, 첫 작업 항목의 AI 사용 NOT_SELECTED,
        사진 storedCount=1. 생성한 접수 ID는 실패 시 정리할 목록에 보관한다.
        """
        metadata = {
            "symptom": f"E2E 가상 수전 누수: {label}",
            "region": {
                key: value
                for key, value in self.config["region"].items()
                if key != "version"
            },
            "photos": [
                {"capturedOn": None, "dateConfirmed": False, "description": "합성 사진; 촬영일 미확인"},
            ],
        }
        if product:
            metadata["product"] = product
        result = self.request(
            "user",
            "POST",
            "/requests",
            status=201,
            form={"metadata": json.dumps(metadata, ensure_ascii=False)},
            files=self.upload(),
        )
        self.requests.add(result["requestId"])
        self.check(result["status"] == "OPEN", "New request must be OPEN")
        self.check(result["workItems"][0]["aiUseStatus"] == "NOT_SELECTED", "AI must be opt-in")
        self.check(result["photos"]["storedCount"] == 1, "Uploaded photo must occupy one slot")
        return result

    @staticmethod
    def photo(root: dict[str, Any]) -> dict[str, Any]:
        photos = root["photos"]
        return (photos["unknownDatePhotos"] + photos["confirmedDatePhotos"])[0]

    def confirm_item(self, request_id: str, item_id: str) -> dict[str, Any]:
        """최신 원본 버전에 대해 사용자가 PLUMBING 분야와 요약을 명시적으로 확인한다."""
        item = self.item(request_id, item_id)
        return self.request(
            "user",
            "PUT",
            f"/work-items/{item_id}/confirmation",
            body={
                "expectedRevision": item["revision"],
                "sourceRevision": item["sourceRevision"],
                "fields": ["PLUMBING"],
                "confirmed": True,
                "summary": {
                    "text": "사용자 진술: 수전 누수. 원인은 현장 확인 전까지 미확인.",
                    "facts": [],
                    "unknowns": ["누수 원인"],
                    "riskSignals": [],
                    "limitations": ["합성 E2E 자료"],
                    "onsiteInspectionNeeded": True,
                },
            },
        )

    def prepare_item(self, request_id: str, item_id: str) -> dict[str, Any]:
        """기사 상담·예약에 필요한 작업 사실과 방문 정보를 사용자가 확인한다.

        수전·작업 종류·수량·분야·가능 시간을 입력하고 TECHNICIAN 경로를 선택한다.
        요약의 reviewStatus=CONFIRMED를 검사한 뒤 가상 주소·연락처를 확인한다.
        """
        item = self.item(request_id, item_id)
        self.request(
            "user",
            "PATCH",
            f"/work-items/{item_id}",
            body={
                "expectedRevision": item["revision"],
                "facts": {
                    "part": "수전",
                    "workType": self.config["workType"],
                    "quantity": 1,
                    "fields": ["PLUMBING"],
                    "visitPreference": self.preference,
                },
                "resolutionPath": "TECHNICIAN",
            },
        )
        item = self.confirm_item(request_id, item_id)
        self.check(
            item["reviewStatus"] == "CONFIRMED",
            "Explicit confirmation must confirm summary",
        )
        root = self.root(request_id)
        region = self.config["region"]
        self.request(
            "user",
            "PUT",
            f"/requests/{request_id}/visit-details",
            body={
                "expectedRevision": root["revision"],
                "confirmed": True,
                "visitDetails": {
                    "address": (
                        f"{region['city']} {region['district']} {region['neighborhood']} 가상 101호"
                    ),
                    "contact": "010-0000-0001",
                },
            },
        )
        return self.item(request_id, item_id)

    def edit_sources(self, root: dict[str, Any]) -> None:
        """04의 원본 접근 권한·정정·사진·기록·작업 분리·그룹화를 검증한다.

        사전 조건: user 소유의 새 접수에 사진 1장과 작업 항목 1개가 있다.
        기대 결과: 타 사용자·기사·비로그인의 접근 거절, 잘못된 목록 인자 422/400,
        오래된 revision 편집 409 VERSION_CONFLICT, 사진 2장·잔여 28장,
        사진 설명 정정 반영, 기록 생성·수정 및 추가 작업 항목 생성 성공,
        사진 그룹 1개 저장과 타임라인 조회 성공.
        """
        request_id = root["requestId"]
        item_id = root["workItems"][0]["workItemId"]
        photo = self.photo(root)
        media_id = photo["media"]["mediaId"]

        # 1) 소유자만 원본을 읽는다. 목록의 범위 밖 limit와 중복 limit도 거절한다.
        self.request("other", "GET", f"/requests/{request_id}", status=403, code="ACCESS_DENIED")
        self.request(
            "technician",
            "GET",
            f"/requests/{request_id}",
            status=403,
            code="ROLE_FORBIDDEN",
        )
        self.request("other", "GET", f"/media/{media_id}", status=403, code="ACCESS_DENIED")
        self.request("anonymous", "GET", f"/media/{media_id}", status=401)
        media = self.request("user", "GET", f"/media/{media_id}", raw=True)
        self.check(
            media.headers.get("content-type", "").startswith("image/"),
            "Original upload must be readable only by its owner",
        )
        self.request("user", "GET", "/requests", params={"limit": 0}, status=422)
        self.request(
            "user",
            "GET",
            "/requests",
            params=[("limit", "1"), ("limit", "2")],
            status=400,
        )
        self.request("user", "GET", "/requests", params={"limit": 100})

        # 2) 증상을 수정한 뒤 같은 이전 revision으로 재수정하면 충돌해야 한다.
        revision = root["revision"]
        self.request(
            "user",
            "PATCH",
            f"/requests/{request_id}",
            body={"expectedRevision": revision, "symptom": "정정된 E2E 가상 수전 누수"},
        )
        self.request(
            "user",
            "PATCH",
            f"/requests/{request_id}",
            status=409,
            code="VERSION_CONFLICT",
            body={"expectedRevision": revision, "symptom": "오래된 편집"},
        )

        # 3) 사진을 한 장 추가하고 원래 사진의 파일·설명·작업 항목 연결을 수정한다.
        photos = self.request(
            "user",
            "POST",
            f"/requests/{request_id}/photos",
            status=201,
            form={
                "metadata": json.dumps(
                    [
                        {
                            "capturedOn": None,
                            "dateConfirmed": False,
                            "description": "추가 합성 사진",
                            "workItemIds": [item_id],
                        },
                    ],
                    ensure_ascii=False,
                ),
            },
            files=self.upload(),
        )
        self.check(
            photos["storedCount"] == 2 and photos["remainingCount"] == 28,
            "Photo count must persist in PostgreSQL",
        )
        edited = self.request(
            "user",
            "PUT",
            f"/photos/{photo['photoId']}",
            form={
                "expectedRevision": photo["revision"],
                "metadata": json.dumps(
                    {
                        "capturedOn": None,
                        "dateConfirmed": False,
                        "description": "설명을 정정한 합성 사진",
                        "workItemIds": [item_id],
                    },
                    ensure_ascii=False,
                ),
            },
            files=[("file", ("replacement.png", self.image, "image/png"))],
        )
        self.check(edited["description"] == "설명을 정정한 합성 사진", "Photo edits must be reflected")

        # 4) 관찰 기록을 등록·정정하고 외부 직접 연락 후 미해결이라는 사용자 진술을 남긴다.
        record_body = {
            "description": "사용자 관찰 기록",
            "photoIds": [photo["photoId"]],
            "workItemIds": [item_id],
        }
        record = self.request(
            "user",
            "POST",
            f"/requests/{request_id}/records",
            status=201,
            body={"record": record_body},
        )
        self.request(
            "user",
            "PATCH",
            f"/records/{record['recordId']}",
            body={
                "expectedRevision": record["revision"],
                "record": {**record_body, "description": "정정된 사용자 관찰 기록"},
            },
        )
        self.request(
            "user",
            "POST",
            f"/work-items/{item_id}/outcomes",
            status=201,
            body={
                "outcome": {
                    "path": "DIRECT_CONTACT",
                    "result": "UNRESOLVED",
                    "action": "외부 직접 연락",
                    "description": "합성 시나리오: 연락 후에도 미해결",
                    "photoIds": [photo["photoId"]],
                },
            },
        )

        # 5) 별도 배관 작업 항목을 추가하고 사진을 한 그룹으로 묶어 타임라인을 조회한다.
        root = self.root(request_id)
        self.request(
            "user",
            "POST",
            f"/requests/{request_id}/work-items",
            status=201,
            body={
                "expectedRevision": root["revision"],
                "facts": {
                    "part": "배관",
                    "workType": self.config["workType"],
                    "quantity": 1,
                    "fields": ["PLUMBING"],
                    "product": {"productType": None, "manufacturer": None, "modelName": None},
                },
            },
        )
        root = self.root(request_id)
        photo_ids = [value["photoId"] for value in root["photos"]["unknownDatePhotos"]]
        timeline = self.request(
            "user",
            "PUT",
            f"/requests/{request_id}/photo-groups",
            body={
                "sourceRevision": root["sourceRevision"],
                "groups": [
                    {"label": "동일 수전", "photoIds": photo_ids, "selectedPhotoIds": photo_ids},
                ],
            },
        )
        self.check(len(timeline["groups"]) == 1, "Photo grouping must persist")
        self.request("user", "GET", f"/requests/{request_id}/timeline")

    def ai_diagnosis(self, request_id: str, item_id: str) -> None:
        """04에서 사용자가 선택한 DIAGNOSIS 작업을 실제 worker로 실행한다.

        설정 있음: SUCCEEDED, error 없음, result 존재, stale=False를 요구한다.
        설정 없음: FAILED와 fixture의 AI_NOT_CONFIGURED 오류 코드를 요구하고
        실제 AI 성공 경로를 NOT_TESTED로 기록한다. 예상과 다른 실패는 실행을 중단한다.
        작업 후 요약이 자동 CONFIRMED가 되지 않는지와 AI 대화 종료 가능 여부도 검사한다.
        """
        item = self.item(request_id, item_id)
        job = self.request(
            "user",
            "POST",
            f"/requests/{request_id}/ai-jobs",
            status=202,
            body={
                "type": "DIAGNOSIS",
                "sourceRevision": item["sourceRevision"],
                "workItemId": item_id,
            },
        )
        expected = self.config["ai"]["expectedStatus"]
        self.ai_result = {
            "expectedStatus": expected,
            "actualStatus": None,
            "providerMocked": False,
            "successPath": "NOT_COMPLETED",
            "errorCode": None,
        }
        try:
            result = self.poll(f"/ai-jobs/{job['jobId']}", expected)
        except JobFailed as error:
            self.ai_result.update(
                actualStatus=error.details["status"],
                errorCode=error.details["errorCode"],
                retryable=error.details["retryable"],
                successPath="NOT_COMPLETED",
            )
            raise
        self.ai_result.update(
            actualStatus=result["status"],
            errorCode=diagnostic_code((result.get("error") or {}).get("code")),
        )
        if expected == "FAILED":
            self.check(
                (result.get("error") or {}).get("code") == self.config["ai"]["expectedErrorCode"],
                "Unconfigured AI must report AI_NOT_CONFIGURED",
            )
            self.ai_result["successPath"] = (
                "NOT_TESTED: provider credentials/model are not configured"
            )
            print(
                "  [NOT TESTED] Real AI success path: AI_NOT_CONFIGURED; "
                "actual worker failure path verified",
                flush=True,
            )
        else:
            self.check(
                result.get("error") is None,
                "Configured AI must succeed without a provider error",
            )
            self.check(
                result.get("result") is not None and not result["stale"],
                "Real AI success must contain current persisted output",
            )
            self.ai_result["successPath"] = "TESTED: real provider DIAGNOSIS"
        self.request(
            "user",
            "GET",
            f"/requests/{request_id}/ai-jobs",
            params={"type": "DIAGNOSIS", "limit": 1},
        )
        self.check(
            self.item(request_id, item_id)["reviewStatus"] != "CONFIRMED",
            "AI output must not implicitly confirm user facts",
        )
        root = self.root(request_id)
        dialogue = self.request(
            "user",
            "PUT",
            f"/requests/{request_id}/ai-dialogue",
            body={
                "expectedRevision": root["dialogue"]["revision"],
                "action": "FINISH",
            },
        )
        self.check(dialogue["finished"], "User must be able to finish optional AI dialogue")

    def candidates(self, request_id: str, item_id: str) -> None:
        """04에서 일반 후보와 동선 탐색 후보를 조회하고 기사의 관심 표시를 확인한다.

        사전 조건: 사용자가 작업 요약·방문 정보를 확인했고 02의 기사 일정이 있다.
        기대 결과: 준비 기사에 timeFit=MATCHED, 사용자 동의 후 동선 후보에 작업 포함,
        기사가 등록한 interestId를 해당 작업의 소유자도 조회할 수 있다.
        해결 경로·사례 추천 API는 성공 응답을 확인하며 추천 품질은 평가하지 않는다.
        """
        self.request("user", "GET", f"/work-items/{item_id}/solutions")
        self.request("user", "GET", f"/work-items/{item_id}/case-recommendations")
        candidates = self.request(
            "user",
            "GET",
            f"/work-items/{item_id}/general-candidates",
            params={"limit": 100},
        )
        self.check(
            any(
                value["technician"]["technicianId"] == self.technician_id
                and value["timeFit"] == "MATCHED"
                for value in candidates["items"]
            ),
            "Prepared technician must match region, field and time",
        )
        item = self.item(request_id, item_id)
        self.request(
            "user",
            "PUT",
            f"/work-items/{item_id}/route-exploration",
            body={
                "expectedRevision": item["revision"],
                "enabled": True,
                "confirmed": True,
            },
        )
        date = (
            datetime.fromtimestamp(self.base_time + 7200, timezone(timedelta(hours=9)))
            .date()
            .isoformat()
        )
        routes = self.request(
            "technician",
            "GET",
            "/technicians/me/route-candidates",
            params={"date": date, "limit": 100},
        )
        matching = [
            value
            for value in routes["items"]
            if value["candidateId"].startswith(item_id + ".")
        ]
        self.check(matching, "Opted-in work item must be a route candidate")
        interest = self.request(
            "technician",
            "POST",
            f"/route-candidates/{matching[0]['candidateId']}/interests",
            status=201,
        )
        interests = self.request("user", "GET", f"/work-items/{item_id}/interests")
        self.check(
            any(value["interestId"] == interest["interestId"] for value in interests),
            "Owner must receive technician interest",
        )

    def report(
        self,
        request_id: str,
        item_id: str,
        *,
        previous: dict | None = None,
    ) -> dict[str, Any]:
        """최신 원본으로 경과 보고서를 저장·조회하고 사용자가 CONFIRMED로 확인한다.

        previous가 있으면 기존 보고서의 최신 revision으로 갱신한다.
        가상 주소·연락처를 본문에도 넣어 외부 전달본과 종료 후 인계서에서 제거되는지
        delivery() 및 03의 후속 검증에서 확인할 수 있게 한다.
        """
        root = self.root(request_id)
        item = next(value for value in root["workItems"] if value["workItemId"] == item_id)
        if previous:
            previous = self.request("user", "GET", f"/work-items/{item_id}/report")
        details = root["visitDetails"]
        report = self.request(
            "user",
            "PUT",
            f"/work-items/{item_id}/report",
            body={
                "expectedRevision": previous["revision"] if previous else None,
                "sourceRevision": item["sourceRevision"],
                "report": {
                    "markdown": (
                        "# 합성 E2E 경과 보고\n사용자 관찰: 누수. 원인 미확인.\n"
                        f"가상 방문정보 제거 검증: {details['contact']} / {details['address']}"
                    ),
                    "photoIds": [self.photo(root)["photoId"]],
                    "facts": [],
                    "unknowns": ["원인"],
                },
            },
        )
        self.request("user", "GET", f"/work-items/{item_id}/report")
        report = self.request(
            "user",
            "PUT",
            f"/work-items/{item_id}/report/confirmation",
            body={
                "expectedRevision": report["revision"],
                "sourceRevision": report["sourceRevision"],
                "confirmed": True,
            },
        )
        self.check(
            report["reviewStatus"] == "CONFIRMED",
            "Report must require explicit owner confirmation",
        )
        return report

    def delivery(
        self,
        request_id: str,
        item_id: str,
        purpose: str,
        *,
        reservation_id: str | None = None,
        replaces: str | None = None,
    ) -> dict[str, Any]:
        """사진 가림 처리를 포함한 전달본을 만들고 worker 처리 후 소유자가 확인한다.

        CONSULTATION은 요약·견적 맥락, HANDOVER는 요약·보고서·예약 연결,
        EXTERNAL_PDF는 요약·보고서를 포함한다. replaces는 이전 인계본을 교체한다.
        기대 결과: READY, metadataRemoved=True, 원본과 다른 mediaId의 PNG,
        선택한 좌상단 가림 영역 내부 픽셀 RGB=(0, 0, 0), 확인 후 CONFIRMED.
        EXTERNAL_PDF는 보고서 본문을 포함한 content 전체에서 방문 주소·연락처가
        사라지는지도 검사한다. 메타데이터 제거 여부는 응답 플래그를 기준으로 판정한다.
        """
        root = self.root(request_id)
        item = next(value for value in root["workItems"] if value["workItemId"] == item_id)
        photo = self.photo(root)
        scope = {
            "purpose": purpose,
            "photoIds": [photo["photoId"]],
            "recordIds": [],
            "questionIds": [],
            "includeSummary": True,
            "includeReport": purpose != "CONSULTATION",
            "includeQuoteContext": purpose == "CONSULTATION",
        }
        if purpose != "EXTERNAL_PDF":
            scope["recipientTechnicianId"] = self.technician_id
        if reservation_id:
            scope["reservationId"] = reservation_id
        body = {
            "sourceRevision": item["sourceRevision"],
            "scope": scope,
            "redactions": [
                {
                    "targetType": "PHOTO",
                    "resourceId": photo["photoId"],
                    "exclude": False,
                    "boxes": [[0, 0, 0.5, 0.5]],
                },
            ],
        }
        if replaces:
            body["replacesDeliveryId"] = replaces
        created = self.request(
            "user",
            "POST",
            f"/work-items/{item_id}/deliveries",
            status=202,
            body=body,
        )
        delivery = self.poll(f"/deliveries/{created['deliveryId']}", "READY")
        self.check(
            delivery["metadataRemoved"],
            "Worker must remove metadata from delivered images",
        )
        if purpose == "EXTERNAL_PDF":
            content_text = json.dumps(delivery["content"], ensure_ascii=False)
            self.check(
                all(value not in content_text for value in root["visitDetails"].values()),
                "External PDF delivery must remove private visit details even from report text",
            )
        transformed = delivery["content"]["photos"][0]["media"]
        self.check(
            transformed["mediaId"] != photo["media"]["mediaId"],
            "Delivery must reference a separate transformed image",
        )
        masked = self.request("user", "GET", f"/media/{transformed['mediaId']}", raw=True)
        self.check(
            masked.content.startswith(b"\x89PNG\r\n\x1a\n"),
            "Worker must produce the masked PNG",
        )
        with Image.open(io.BytesIO(masked.content)) as image:
            pixel = image.convert("RGB").getpixel((image.width // 4, image.height // 4))
            self.check(
                pixel == (0, 0, 0),
                "Delivered image must actually obscure pixels inside the selected mask",
            )
        delivery = self.request(
            "user",
            "PUT",
            f"/deliveries/{created['deliveryId']}/confirmation",
            body={
                "expectedRevision": delivery["revision"],
                "sourceRevision": delivery["sourceRevision"],
                "confirmed": True,
            },
        )
        self.check(
            delivery["reviewStatus"] == "CONFIRMED",
            "Processed delivery must be explicitly confirmed",
        )
        self.request(
            "user",
            "GET",
            f"/work-items/{item_id}/deliveries",
            params={"purpose": purpose, "status": "READY", "limit": 100},
        )
        return delivery

    def pdf(self, delivery: dict[str, Any]) -> str:
        """확인한 전달본의 PDF 생성을 요청하고 READY 후 실제 파일을 다운로드한다.

        기대 결과: downloadAvailable=True, %PDF- 시그니처, application/pdf 타입,
        다른 사용자의 다운로드 403 ACCESS_DENIED. 반환한 작업 ID는 06에서
        원본 변경 후 이전 PDF의 다운로드 차단을 검사하는 데 사용한다.
        """
        delivery_id = delivery["deliveryId"]
        job = self.request(
            "user",
            "POST",
            f"/deliveries/{delivery_id}/pdf-jobs",
            status=202,
            body={"deliveryRevision": delivery["revision"]},
        )
        result = self.poll(f"/pdf-jobs/{job['jobId']}", "READY")
        self.check(result["downloadAvailable"], "Real worker PDF must be downloadable")
        self.request(
            "user",
            "GET",
            f"/deliveries/{delivery_id}/pdf-jobs",
            params={"status": "READY", "limit": 1},
        )
        pdf = self.request("user", "GET", f"/pdf-jobs/{job['jobId']}/content", raw=True)
        self.check(pdf.content.startswith(b"%PDF-"), "PDF download must contain a PDF document")
        self.check(
            pdf.headers.get("content-type", "").startswith("application/pdf"),
            "PDF content type must be correct",
        )
        self.request(
            "other",
            "GET",
            f"/pdf-jobs/{job['jobId']}/content",
            status=403,
            code="ACCESS_DENIED",
        )
        return job["jobId"]

    def reserve(
        self,
        request_id: str,
        item_id: str,
        *,
        reject_first: bool = False,
    ) -> tuple[dict, str]:
        """상담 전달 → 기사 수락 → 견적 → 사전 검사·사용자 확인 → 예약 확정을 검증한다.

        사전 조건: 확인된 작업 사실·방문 정보와 02의 기사 프로필·일정이 있다.
        기대 결과: 양측 상담 목록에 ACCEPTED 상담 포함, 기사에게 가림 지시 비공개,
        선택 가능한 견적의 할인 후 금액 90,000원, 예약 사전 검사 allowed=True,
        사용자 overlapConfirmed=True, 예약 CONFIRMED, 기사에게 방문 연락처 공개.
        reject_first=True이면 첫 견적을 REJECTED로 거절하고 새 견적을 사용한다.
        같은 키·본문의 예약 재요청은 같은 ID, 같은 키·다른 본문은
        409 IDEMPOTENCY_KEY_REUSED여야 한다. 예약과 상담 전달본 ID를 반환한다.
        """
        # 1) 가림 처리한 상담 전달본을 보내고 기사 수락 후 양측 조회 권한을 확인한다.
        delivery = self.delivery(request_id, item_id, "CONSULTATION")
        relation = self.request(
            "user",
            "POST",
            f"/work-items/{item_id}/consultations",
            status=201,
            body={"technicianId": self.technician_id, "deliveryId": delivery["deliveryId"]},
        )
        consultation_id = relation["consultationId"]
        relation = self.request("technician", "GET", f"/consultations/{consultation_id}")
        self.check(
            relation["status"] == "PENDING",
            "New consultation must await technician acceptance",
        )
        self.request(
            "technician",
            "PATCH",
            f"/consultations/{consultation_id}",
            body={"expectedRevision": relation["revision"], "action": "ACCEPT"},
        )
        for actor in ("user", "technician"):
            consultations = self.request(
                actor,
                "GET",
                "/consultations",
                params={"status": "ACCEPTED", "limit": 100},
            )
            self.check(
                any(value["consultationId"] == consultation_id for value in consultations["items"]),
                "Both parties must see the accepted consultation",
            )
        visible = self.request("technician", "GET", f"/deliveries/{delivery['deliveryId']}")
        self.check(
            visible["redactions"] is None,
            "Technician must not receive private redaction instructions",
        )

        # 2) 60분 작업·10만 원에서 9만 원으로 할인된 견적을 발행한다.
        root = self.root(request_id)
        item = next(value for value in root["workItems"] if value["workItemId"] == item_id)
        terms = {
            "versions": {
                "commonVersion": root["commonVersion"],
                "itemVersion": item["itemVersion"],
                "proposalVersion": None,
            },
            "fields": ["PLUMBING"],
            "scope": "합성 E2E 수전 교체",
            "quantity": 1,
            "durationMinutes": 60,
            "startAt": self.times["start"],
            "expiresAt": self.times["expires"],
            "cost": {
                "minimumVisitFee": 0,
                "minimumDiagnosticFee": 0,
                "discountCondition": "E2E 시간 합의",
                "lines": [
                    {
                        "category": "LABOR",
                        "description": "가상 작업비",
                        "confirmed": True,
                        "beforeAmount": 100000,
                        "afterAmount": 90000,
                        "condition": None,
                    },
                ],
            },
        }
        quote_body = {"contextDeliveryId": delivery["deliveryId"], "terms": terms}
        quote = self.request(
            "technician",
            "POST",
            f"/consultations/{consultation_id}/quotes",
            status=201,
            body=quote_body,
        )
        if reject_first:
            rejected = self.request(
                "user",
                "PATCH",
                f"/quotes/{quote['quoteId']}",
                body={"expectedRevision": quote["revision"], "action": "REJECT"},
            )
            self.check(rejected["status"] == "REJECTED", "User must be able to reject a quote")
            quote = self.request(
                "technician",
                "POST",
                f"/consultations/{consultation_id}/quotes",
                status=201,
                body=quote_body,
            )
        self.check(
            quote["selectable"] and quote["price"]["afterTotal"] == 90000,
            "Issued quote must expose the agreed price and be selectable",
        )
        self.request("user", "GET", f"/work-items/{item_id}/quotes")

        # 3) 실제 일정·이동 조건에 대한 예약 검사 결과를 사용자가 명시적으로 확인한다.
        check = self.request(
            "user",
            "POST",
            "/reservation-checks",
            body={"operation": "CREATE", "quoteId": quote["quoteId"]},
        )
        self.check(
            check["allowed"],
            "Real schedule and travel checks must permit the prepared reservation",
        )
        check = self.request(
            "user",
            "PUT",
            f"/reservation-checks/{check['checkId']}/confirmation",
            body={"confirmed": True},
        )
        self.check(check["overlapConfirmed"], "Owner must be able to confirm reservation checks")

        # 4) 예약 생성·동일 요청 재시도·같은 키의 본문 변경을 차례로 검사한다.
        body = {
            "quoteId": quote["quoteId"],
            "versions": quote["terms"]["versions"],
            "visitDetailsRevision": root["visitDetailsRevision"],
        }
        key = uuid.uuid4().hex
        reservation = self.request(
            "user",
            "POST",
            f"/work-items/{item_id}/reservations",
            status=201,
            body=body,
            key=key,
        )
        replay = self.request(
            "user",
            "POST",
            f"/work-items/{item_id}/reservations",
            status=201,
            body=body,
            key=key,
        )
        self.check(
            replay["reservationId"] == reservation["reservationId"],
            "Reservation retry must return the same resource",
        )
        self.request(
            "user",
            "POST",
            f"/work-items/{item_id}/reservations",
            status=409,
            code="IDEMPOTENCY_KEY_REUSED",
            body={**body, "visitDetailsRevision": "different-e2e-input"},
            key=key,
        )
        self.check(
            reservation["status"] == "CONFIRMED",
            "Chosen quote must become a confirmed reservation",
        )

        # 5) 양측 예약 목록을 조회하고 활성 예약을 가진 기사에게 연락처가 공개되는지 본다.
        for actor in ("user", "technician"):
            self.request(
                actor,
                "GET",
                "/reservations",
                params={"status": "CONFIRMED", "limit": 100},
            )
        visible = self.request(
            "technician",
            "GET",
            f"/reservations/{reservation['reservationId']}",
        )
        self.check(
            visible["agreement"]["terms"]["visitDetails"]["contact"] == "010-0000-0001",
            "Active reservation must disclose the confirmed visit contact",
        )
        return reservation, delivery["deliveryId"]

    def start(self, reservation: dict[str, Any]) -> dict[str, Any]:
        """예정 시각 전 START는 동의 없이 거절되고 동의 후에만 IN_PROGRESS가 된다.

        먼저 409 EARLY_START_CONSENT_REQUIRED를 확인한다. 사용자가 현재 합의 버전에
        GRANT한 뒤 기사가 다시 START한다. 03과 06에서 같은 조기 시작 검증을 사용한다.
        """
        reservation_id = reservation["reservationId"]
        version = reservation["agreement"]["agreementVersion"]
        self.request(
            "technician",
            "POST",
            f"/reservations/{reservation_id}/work-events",
            status=409,
            code="EARLY_START_CONSENT_REQUIRED",
            body={"event": "START", "agreementVersion": version},
        )
        self.request(
            "user",
            "PUT",
            f"/reservations/{reservation_id}/early-start-consent",
            body={
                "agreementVersion": version,
                "expectedConsentRevision": None,
                "action": "GRANT",
                "proposedStartAt": self.times["early"],
            },
        )
        started = self.request(
            "technician",
            "POST",
            f"/reservations/{reservation_id}/work-events",
            body={"event": "START", "agreementVersion": version},
        )
        self.check(
            started["status"] == "IN_PROGRESS",
            "Only explicit early-start consent may start work early",
        )
        return started

    def close_request(self, request_id: str, *, resolved: bool = False) -> None:
        """소유자가 모든 작업의 해결 여부를 명시해 접수를 CLOSED로 종료한다."""
        root = self.root(request_id)
        result = self.request(
            "user",
            "POST",
            f"/requests/{request_id}/closure",
            body={
                "expectedRevision": root["revision"],
                "items": [
                    {
                        "workItemId": item["workItemId"],
                        "resolved": resolved,
                        "reason": "합성 E2E 검증 종료",
                    }
                    for item in root["workItems"]
                ],
            },
        )
        self.check(result["status"] == "CLOSED", "Owner must explicitly close all request items")

    def delete_request(self, request_id: str) -> None:
        """삭제 요청 직후 접근 차단, worker 완료, 완료 작업의 재시도 거절을 검증한다.

        기대 결과: 202와 accessBlocked=True, 접수 재조회 404, 삭제 작업 COMPLETED,
        error 없음·restoredPhotoSlots>0, 완료한 작업 재시도 409 INVALID_STATE.
        사진이 있는 접수에 사용한다. 사진 없는 fixture의 실패 작업은 12에서 검사한다.
        """
        job = self.request(
            "user",
            "POST",
            "/deletion-jobs",
            status=202,
            body={
                "targetType": "REQUEST",
                "targetId": request_id,
                "includeAllReferences": True,
            },
        )
        self.check(job["accessBlocked"], "Deletion must block access before physical cleanup")
        self.request("user", "GET", f"/requests/{request_id}", status=404)
        completed = self.poll(f"/deletion-jobs/{job['jobId']}", "COMPLETED")
        self.check(
            completed["error"] is None and completed["restoredPhotoSlots"] > 0,
            "Worker must physically delete request photos",
        )
        self.requests.discard(request_id)
        self.request(
            "user",
            "POST",
            f"/deletion-jobs/{job['jobId']}/retry",
            status=409,
            code="INVALID_STATE",
        )

    # 시나리오 실행 본문: 색인의 01~12 순서로 읽고 run()에서 순차 실행한다.

    def setup(self) -> None:
        """01~02를 실행하고 이후 흐름에서 공유할 로그인 세션·기사 프로필·일정을 준비한다."""
        # 01. 서비스 공개·회원가입·인증·역할 권한
        # 사전 조건: fixture의 user·other·technician 계정과 공개 API가 준비되어 있다.
        # 기대 결과: v1.1 명세·공개 안내 조회, USER 전용 가입, 중복 가입 409,
        #            일반 계정의 기사 전환 403, 로그아웃 후 401, 기사의 역할 전환 성공.
        with self.journey("published-service-and-authentication"):
            # 1) health·OpenAPI·Swagger를 조회하고 v1 업무 API의 호출 범위를 수집한다.
            self.request("anonymous", "GET", "/health/live", api=False)
            self.request("anonymous", "GET", "/health/ready", api=False)
            document = self.request("anonymous", "GET", "/openapi.json", api=False)
            self.patterns = endpoint_patterns(document)
            self.check(
                len(self.patterns) >= 80,
                "Published OpenAPI must contain the current v1 contract",
            )
            self.check(
                document["info"]["version"] == "v1.1",
                "Published API specification must be v1.1",
            )
            docs = self.request("anonymous", "GET", "/docs", api=False, raw=True)
            self.check("swagger" in docs.text.lower(), "Swagger UI must be published")

            # 2) 공개 분야·긴급 안내를 조회하고 제조사 미입력 상태를 확인한다.
            info = self.request("anonymous", "GET", "/public/service-info")
            self.check(
                "PLUMBING" in info["fields"],
                "Service info must expose the supported field",
            )
            self.request("anonymous", "GET", "/public/guidance", params={"type": "EMERGENCY"})
            guidance = self.request(
                "anonymous",
                "GET",
                "/public/guidance",
                params={"type": "MANUFACTURER_AS"},
            )
            self.check(
                guidance["officialService"]["status"] == "INFORMATION_REQUIRED",
                "Missing manufacturer must require input",
            )

            # 3) 가입은 세션을 만들지 않는다. 중복 가입과 권한 없는 기사 전환을 거절한다.
            signup = {"loginId": self.config["runId"] + "-signup", "password": uuid.uuid4().hex}
            account = self.request("signup", "POST", "/auth/signup", status=201, body=signup)
            self.check(account["availableRoles"] == ["USER"], "Signup may grant only USER")
            self.check(not self.clients["signup"].cookies, "Signup must not create a session")
            self.request(
                "signup",
                "POST",
                "/auth/signup",
                status=409,
                code="ACCOUNT_EXISTS",
                body=signup,
            )
            self.request("signup", "POST", "/auth/login", body=signup)
            self.request("signup", "GET", "/auth/me")
            self.request(
                "signup",
                "PATCH",
                "/auth/role",
                status=403,
                code="ROLE_FORBIDDEN",
                body={"role": "TECHNICIAN"},
            )
            self.request("signup", "POST", "/auth/logout", status=204)
            self.request("signup", "GET", "/auth/me", status=401)

            # 4) 나머지 행위자는 로그인 상태를 유지하고 기사만 TECHNICIAN 역할로 전환한다.
            for actor in ("user", "other", "technician"):
                credentials = self.config["accounts"][actor]
                self.request(
                    actor,
                    "POST",
                    "/auth/login",
                    body={k: credentials[k] for k in ("loginId", "password")},
                )
                self.request(actor, "GET", "/auth/me")
            session = self.request(
                "technician",
                "PATCH",
                "/auth/role",
                body={"role": "TECHNICIAN"},
            )
            self.check(
                session["activeRole"] == "TECHNICIAN",
                "Technician session must switch roles",
            )

        # 02. 기사 프로필·사례·방문 가능 일정
        # 사전 조건: 01에서 로그인과 기사 역할 전환을 마쳤다.
        # 기대 결과: 공개 연락 가능 표시, 생성·수정한 사례의 포트폴리오 포함,
        #            이후 예약 시간대를 포함하는 방문 가능 일정의 저장 성공.
        with self.journey("technician-profile-cases-and-schedule"):
            # 1) 대표 사진·분야·지역·공개 연락처를 등록하고 공개 프로필을 확인한다.
            technician = self.request("technician", "GET", "/technicians/me")
            self.technician_id = technician["technicianId"]
            photos = self.request(
                "technician",
                "POST",
                "/technicians/me/portfolio-photos",
                status=201,
                form={"source": json.dumps(self.config["source"], ensure_ascii=False)},
                files=self.upload(),
            )
            profile = {
                "displayName": "E2E 가상 기사",
                "fields": ["PLUMBING"],
                "regionIds": [self.config["region"]["regionId"]],
                "representativeMediaIds": [photos[0]["mediaId"]],
                "contacts": [
                    {"contact": {"label": "가상 연락처", "value": "010-0000-0002"}, "isPublic": True},
                ],
            }
            self.request(
                "technician",
                "PUT",
                "/technicians/me/profile",
                body={
                    "expectedRevision": technician["profileRevision"],
                    "profile": profile,
                },
            )
            self.request(
                "anonymous",
                "GET",
                "/public/technicians",
                params={"field": "PLUMBING", "regionId": self.config["region"]["regionId"]},
            )
            public = self.request("anonymous", "GET", f"/public/technicians/{self.technician_id}")
            self.check(
                public["directContactAvailable"],
                "Public technician must expose opted-in contact",
            )

            # 2) 준비 사례를 등록·수정하고 사용자가 사례와 포트폴리오를 조회한다.
            case = self.request(
                "technician",
                "POST",
                "/technicians/me/cases",
                status=201,
                body={"case": self.config["case"]},
            )
            case = self.request(
                "technician",
                "PATCH",
                f"/technicians/me/cases/{case['caseId']}",
                body={
                    "expectedRevision": case["revision"],
                    "case": self.config["updatedCase"],
                },
            )
            self.request("user", "GET", f"/cases/{case['caseId']}")
            portfolio = self.request("user", "GET", f"/technicians/{self.technician_id}/portfolio")
            self.check(
                any(value["caseId"] == case["caseId"] for value in portfolio["cases"]),
                "Portfolio must contain the prepared case",
            )

            # 3) 현재 기준 -2~+12시간을 방문 가능 시간으로 저장하고 외부 일정은 비운다.
            schedule = self.request(
                "technician",
                "GET",
                "/technicians/me/schedule",
                params=self.dates,
            )
            self.request(
                "technician",
                "PUT",
                "/technicians/me/schedule",
                body={
                    "expectedRevision": schedule["revision"],
                    **self.dates,
                    "availability": [
                        {
                            "startAt": utc_text(self.base_time - 7200),
                            "endAt": utc_text(self.base_time + 43200),
                        },
                    ],
                    "externalVisits": [],
                },
            )

    def completion_journey(self) -> None:
        """03. AI 없이 상담·예약하고, 인계본을 갱신한 뒤 작업을 정상 완료한다.

        사전 조건: 01~02 완료. 새 접수는 AI 미선택 상태이며 준비 기사에게 예약한다.
        진행: 접수·사용자 확인 → 상담·견적·예약 → 보고서·인계 → 원본 추가·인계 교체
              → 조기 시작 동의·작업 시작 → 기사 완료 → 종료 후 권한 검사 → 접수 종료·삭제.
        기대 결과: AI 미선택 상태에서도 예약 가능, 원본 추가 시 이전 인계본 STALE,
        기사 완료 후 예약 COMPLETED·작업 RESOLVED, 종료 예약의 방문 정보 비공개,
        보존 인계서의 견적 맥락·본문 내 방문 정보 제거, 상담 전달본 접근 403.
        """
        with self.journey("no-ai-consultation-reservation-handover-completion"):
            # 1) AI를 선택하지 않고 사용자 확인만으로 상담·견적·예약을 진행한다.
            root = self.create_request("정상 완료")
            request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
            item = self.prepare_item(request_id, item_id)
            self.check(
                item["aiUseStatus"] == "NOT_SELECTED",
                "No-AI path must allow explicit confirmation and reservation",
            )
            reservation, consultation_delivery = self.reserve(request_id, item_id)

            # 2) 확인한 보고서·인계본을 만들고 예약 기사에게 조회를 허용한다.
            report = self.report(request_id, item_id)
            handover = self.delivery(
                request_id,
                item_id,
                "HANDOVER",
                reservation_id=reservation["reservationId"],
            )
            self.request("technician", "GET", f"/deliveries/{handover['deliveryId']}")

            # 3) 새 경과 기록으로 이전 인계본을 무효화하고 재확인·재발행한다.
            photo_id = self.photo(root)["photoId"]
            self.request(
                "user",
                "POST",
                f"/requests/{request_id}/records",
                status=201,
                body={
                    "record": {
                        "description": "방문 전 추가 경과",
                        "photoIds": [photo_id],
                        "workItemIds": [item_id],
                    },
                },
            )
            stale = self.request("user", "GET", f"/deliveries/{handover['deliveryId']}")
            self.check(
                stale["status"] == "STALE",
                "New source evidence must invalidate the old handover",
            )
            self.confirm_item(request_id, item_id)
            self.report(request_id, item_id, previous=report)
            handover = self.delivery(
                request_id,
                item_id,
                "HANDOVER",
                reservation_id=reservation["reservationId"],
                replaces=handover["deliveryId"],
            )

            # 4) 조기 시작 동의 후 작업을 시작하고 수행 내역·종료 위치를 담아 완료한다.
            reservation = self.start(reservation)
            result = self.request(
                "technician",
                "POST",
                f"/reservations/{reservation['reservationId']}/work-events",
                body={
                    "event": "COMPLETE",
                    "agreementVersion": reservation["agreement"]["agreementVersion"],
                    "performance": {
                        "confirmedCause": "합성 패킹 손상",
                        "performed": ["패킹 교체"],
                        "notPerformed": [],
                        "unknowns": [],
                        "parts": ["패킹"],
                        "endLocationId": self.config["locationId"],
                    },
                },
            )
            self.check(
                result["status"] == "COMPLETED",
                "Technician completion must preserve performance and end the reservation",
            )
            self.check(
                self.item(request_id, item_id)["status"] == "RESOLVED",
                "Normal completion must resolve the work item",
            )

            # 5) 종료 후 기사의 예약·인계 조회에서 방문 정보를 제거하고 상담본은 차단한다.
            ended = self.request(
                "technician",
                "GET",
                f"/reservations/{reservation['reservationId']}",
            )
            self.check(
                ended["agreement"]["terms"]["visitDetails"] is None,
                "Finished relationship must hide visit details",
            )
            frozen = self.request("technician", "GET", f"/deliveries/{handover['deliveryId']}")
            self.check(
                frozen["content"]["quoteContext"] is None,
                "Ended handover must contain only permitted historical evidence",
            )
            private = self.root(request_id)["visitDetails"]
            frozen_text = json.dumps(frozen["content"], ensure_ascii=False)
            self.check(
                all(value not in frozen_text for value in private.values()),
                "Historical handover must remove embedded private visit information",
            )
            self.request(
                "technician",
                "GET",
                f"/deliveries/{consultation_delivery}",
                status=403,
                code="ACCESS_DENIED",
            )

            # 6) 사용자가 해결 종료한다. 다음 예약에 이전 이동 이력이 영향을 주지 않도록
            #    이번 접수를 삭제하며, 서버 시각을 바꿔 이동 규칙을 우회하지 않는다.
            self.close_request(request_id, resolved=True)
            self.delete_request(request_id)

    def stop_journey(self) -> None:
        """04~06을 한 접수로 이어서 실행한다. 블록 사이의 자료를 초기화하지 않는다.

        04의 request_id·item_id로 05에서 PDF와 예약을 만들고,
        06에서 그 예약을 중단한 뒤 같은 PDF·상담 전달본의 접근 제한을 확인한다.
        """
        # 04. 원본 정정·선택적 AI 진단·기사 후보 탐색
        # 사전 조건: 01~02 완료. 이 블록에서 사진 1장이 있는 새 접수를 만든다.
        # 기대 결과: edit_sources()의 권한·버전·사진·기록 검사 통과,
        #            설정별 AI 상태 일치, 사용자 확인 후 준비 기사와 동선 후보 조회,
        #            기사의 관심 표시를 소유자가 조회할 수 있다.
        with self.journey("record-editing-ai-choice-and-candidate-discovery"):
            # 1) 원본을 정정하고 추가 작업 항목·사진 그룹·타임라인을 만든다.
            root = self.create_request("변경 및 중단")
            request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
            self.edit_sources(root)

            # 2) AI 진단과 대화 종료 후 사용자가 작업 사실·방문 정보를 직접 확인한다.
            self.ai_diagnosis(request_id, item_id)
            self.prepare_item(request_id, item_id)

            # 3) 일반 기사 후보를 찾고 동선 탐색에 동의해 기사의 관심 표시를 받는다.
            self.candidates(request_id, item_id)

        # 05. 외부 PDF·견적 거절·시작 전 예약 변경
        # 사전 조건: 04의 같은 접수·작업 항목이 사용자 확인을 마쳤다.
        # 기대 결과: 가림 처리된 전달본·PDF와 다운로드 권한 검사 통과,
        #            첫 견적 REJECTED 후 새 견적으로 예약, 상대방 수락 후 변경 APPLIED,
        #            이전 합의 버전으로 취소 시 409 VERSION_CONFLICT, 합의 이력 2건.
        with self.journey("masked-external-pdf-and-reservation-changes"):
            # 1) 보고서를 확인하고 방문 정보를 제거한 외부 전달본·PDF를 생성한다.
            self.report(request_id, item_id)
            delivery = self.delivery(request_id, item_id, "EXTERNAL_PDF")
            pdf_id = self.pdf(delivery)

            # 2) 첫 견적 거절·재발행 후 예약을 확정하고 기사의 준비사항을 저장한다.
            reservation, consultation_delivery = self.reserve(
                request_id,
                item_id,
                reject_first=True,
            )
            reservation_id = reservation["reservationId"]
            old_version = reservation["agreement"]["agreementVersion"]
            self.request(
                "technician",
                "PUT",
                f"/reservations/{reservation_id}/preparation-notes",
                body={
                    "preparation": {
                        "equipment": ["렌치"],
                        "parts": [],
                        "inspectionItems": ["연결부"],
                        "note": "E2E 합성 준비사항",
                    },
                },
            )

            # 3) 사용자가 시작 전 작업·시간 변경을 제안하고 기사가 수락한다.
            terms = reservation["agreement"]["terms"]
            change = self.request(
                "user",
                "POST",
                f"/reservations/{reservation_id}/changes",
                status=201,
                body={
                    "type": "BEFORE_START",
                    "agreementVersion": old_version,
                    "terms": {
                        "fields": terms["fields"],
                        "scope": "합성 변경 작업",
                        "quantity": 1,
                        "cost": terms["cost"],
                        "visitPreference": self.preference,
                        "startAt": self.times["changed_start"],
                        "expectedEndAt": self.times["changed_end"],
                    },
                },
            )
            applied = self.request(
                "technician",
                "PATCH",
                f"/reservation-changes/{change['changeId']}",
                body={"expectedRevision": change["revision"], "action": "ACCEPT"},
            )
            self.check(
                applied["status"] == "APPLIED",
                "Both parties must agree before changes take effect",
            )

            # 4) 이전 합의 버전은 취소에 쓸 수 없고 기존·변경 합의 이력은 모두 남는다.
            self.request(
                "user",
                "POST",
                f"/reservations/{reservation_id}/cancellation",
                status=409,
                code="VERSION_CONFLICT",
                body={"agreementVersion": old_version},
            )
            reservation = self.request("user", "GET", f"/reservations/{reservation_id}")
            self.check(
                len(reservation["agreementHistory"]) == 2,
                "Agreement history must preserve the original and accepted change",
            )

        # 06. 조기 시작 동의·중단·종료 후 접근 제한
        # 사전 조건: 05에서 변경한 예약과 그 전에 만든 PDF·상담 전달본을 이어받는다.
        # 기대 결과: 동의 후 IN_PROGRESS, 사용자 요청 STOP_REQUESTED,
        #            중단 요청 뒤 COMPLETE는 409 INVALID_STATE, 기사 STOP은 STOPPED,
        #            종료 예약의 방문 정보 비공개, 상담본 403, 이전 PDF 다운로드 409.
        with self.journey("early-start-stop-and-ended-access"):
            # 1) 조기 시작 동의를 받고 시작한 뒤 예상 종료 시각을 갱신한다.
            started = self.start(reservation)
            version = started["agreement"]["agreementVersion"]
            self.request(
                "technician",
                "POST",
                f"/reservations/{reservation_id}/work-events",
                body={
                    "event": "UPDATE_EXPECTED_END",
                    "agreementVersion": version,
                    "expectedEndEstimateRevision": started["endEstimateRevision"],
                    "expectedEndAt": self.times["extended_end"],
                },
            )

            # 2) 사용자의 중단 요청과 기사의 중단 확정을 구분하고 완료 전환은 거절한다.
            stopping = self.request(
                "user",
                "POST",
                f"/reservations/{reservation_id}/work-events",
                body={
                    "event": "REQUEST_STOP",
                    "agreementVersion": version,
                    "reason": "합성 E2E 중단 요청",
                },
            )
            self.check(
                stopping["status"] == "STOP_REQUESTED",
                "User stop request must remain distinct from technician stop",
            )
            performance = {
                "confirmedCause": None,
                "performed": ["연결부 점검"],
                "notPerformed": ["교체"],
                "unknowns": ["원인"],
                "parts": [],
                "endLocationId": None,
            }
            self.request(
                "technician",
                "POST",
                f"/reservations/{reservation_id}/work-events",
                status=409,
                code="INVALID_STATE",
                body={"event": "COMPLETE", "agreementVersion": version, "performance": performance},
            )
            stopped = self.request(
                "technician",
                "POST",
                f"/reservations/{reservation_id}/work-events",
                body={
                    "event": "STOP",
                    "agreementVersion": version,
                    "performance": performance,
                },
            )
            self.check(
                stopped["status"] == "STOPPED",
                "Technician must persist unfinished work when stopping",
            )

            # 3) 중단 후 종료 위치를 보완하고 종료된 관계의 방문 정보·상담 접근을 막는다.
            self.request(
                "technician",
                "PUT",
                f"/reservations/{reservation_id}/end-location",
                body={
                    "expectedEndLocationRevision": stopped["endLocationRevision"],
                    "endLocationId": self.config["locationId"],
                },
            )
            ended = self.request("technician", "GET", f"/reservations/{reservation_id}")
            self.check(
                ended["agreement"]["terms"]["visitDetails"] is None,
                "Stopped reservation must hide visit details",
            )
            self.request(
                "technician",
                "GET",
                f"/deliveries/{consultation_delivery}",
                status=403,
                code="ACCESS_DENIED",
            )

            # 4) 이전 PDF는 원본 변경으로 다운로드할 수 없다. 모든 작업을 미해결로 닫는다.
            pdf = self.request("user", "GET", f"/pdf-jobs/{pdf_id}")
            self.check(
                not pdf["downloadAvailable"],
                "Changed evidence must invalidate the old PDF",
            )
            self.request("user", "GET", f"/pdf-jobs/{pdf_id}/content", status=409)
            self.close_request(request_id)
            self.delete_request(request_id)

    def cancellation_journey(self) -> None:
        """07. 접수 목록의 커서 페이지를 확인하고 시작 전 예약을 취소한다.

        사전 조건: 01~02 완료. 앞선 흐름의 접수 삭제가 끝나 기사 일정에 여유가 있다.
        진행: 접수 2건 생성 → limit=1로 다음 페이지 조회 → 보조 접수 삭제
              → 사용자 확인·상담·견적·예약 → 현재 합의 버전으로 취소 → 접수 종료·삭제.
        기대 결과: nextCursor 존재, 두 페이지의 첫 접수 ID가 다름, 예약 CANCELLED.
        """
        with self.journey("reservation-cancellation"):
            # 1) 접수 두 건으로 커서 이동 시 이전 접수가 중복되지 않는지 확인한다.
            root = self.create_request("시작 전 취소")
            request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
            page_request = self.create_request("페이지 탐색")
            first_page = self.request("user", "GET", "/requests", params={"limit": 1})
            self.check(
                first_page["nextCursor"] is not None,
                "Request list must provide a cursor when more records exist",
            )
            second_page = self.request(
                "user",
                "GET",
                "/requests",
                params={"limit": 1, "cursor": first_page["nextCursor"]},
            )
            self.check(
                first_page["items"][0]["requestId"] != second_page["items"][0]["requestId"],
                "Cursor pagination must not duplicate the previous request",
            )
            self.delete_request(page_request["requestId"])

            # 2) 예약은 확정하되 시작하지 않고 현재 합의 버전으로 취소한다.
            self.prepare_item(request_id, item_id)
            reservation, _ = self.reserve(request_id, item_id)
            cancelled = self.request(
                "user",
                "POST",
                f"/reservations/{reservation['reservationId']}/cancellation",
                body={
                    "agreementVersion": reservation["agreement"]["agreementVersion"],
                    "reason": "합성 E2E 취소",
                },
            )
            self.check(
                cancelled["status"] == "CANCELLED",
                "Cancellation must end a reservation before work starts",
            )

            # 3) 사용자가 미해결로 접수를 닫고 삭제한다.
            self.close_request(request_id)
            self.delete_request(request_id)

    def alternative_journeys(self) -> None:
        """scenarios 모드 전용 08~11. 각 흐름은 새 접수를 만들고 종료·삭제한다."""
        # 08. 긴급 안내·미지원 지역의 기사 후보 조회 제한
        # 사전 조건: fixture에 검증된 긴급 트리거·안내가 있고 01의 세션이 유효하다.
        # 진행: 비로그인 긴급 안내 조회 → 접수 지역을 미지원 지역으로 수정
        #       → 사용자 확인 → 일반 기사 후보 조회 → 미해결 종료·삭제.
        # 기대 결과: 긴급 안내 AVAILABLE, 접수 수정은 허용하며 UNSUPPORTED_REGION,
        #            기사 후보 조회는 422 SERVICE_UNSUPPORTED. 예약 생성은 호출하지 않는다.
        with self.journey("emergency-guidance-and-support-boundaries"):
            # 1) AI 호출 없이 등록된 긴급 트리거의 검증 안내를 조회한다.
            guidance = self.request(
                "anonymous",
                "GET",
                "/public/guidance",
                params={
                    "type": "EMERGENCY",
                    "triggerId": self.config["emergencyTriggerId"],
                },
            )
            self.check(
                guidance["guide"]["status"] == "AVAILABLE",
                "Registered emergency trigger must expose verified guidance without AI",
            )

            # 2) 미지원 지역의 접수 기록은 유지하지만 기사 후보 조회는 거절한다.
            root = self.create_request("미지원 지역 기록")
            request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
            changed = self.request(
                "user",
                "PATCH",
                f"/requests/{request_id}",
                body={
                    "expectedRevision": root["revision"],
                    "region": {"city": "부산광역시", "district": "가상구", "neighborhood": "가상동"},
                },
            )
            self.check(
                changed["support"]["status"] == "UNSUPPORTED_REGION",
                "Unsupported region must still permit request records",
            )
            self.confirm_item(request_id, item_id)
            self.request(
                "user",
                "GET",
                f"/work-items/{item_id}/general-candidates",
                status=422,
                code="SERVICE_UNSUPPORTED",
            )
            self.close_request(request_id)
            self.delete_request(request_id)

        # 09~11. 자가 해결·제조사 AS·외부 직접 연락 경로 (각각 별도 시나리오로 기록)
        # 사전 조건: fixture의 제품 정보·검증된 자가 해결 안내·제조사 AS 정보가 있다.
        # 공통 진행: 제품 포함 접수 → 사용자 확인 → 해결 경로 변경 → 제공 경로 조회
        #            → 사진을 연결한 사용자 RESOLVED 결과 기록 → 해결 종료·삭제.
        # 공통 기대: 선택 경로가 저장되고 availablePaths에 포함되며 activeReservationId=None.
        # 09 SELF_HELP: selfHelp.status=AVAILABLE인 안내가 제공된다.
        # 10 MANUFACTURER_AS: officialService.status=AVAILABLE인 AS 경로가 제공된다.
        # 11 DIRECT_CONTACT: 경로 선택·사용자 결과 기록만 확인한다. 실제 연락은 하지 않는다.
        for path in ("SELF_HELP", "MANUFACTURER_AS", "DIRECT_CONTACT"):
            with self.journey("optional-resolution-" + path.lower()):
                # 1) 공통 준비 후 TECHNICIAN 대신 이번 흐름의 해결 경로를 명시적으로 선택한다.
                root = self.create_request(path, product=self.config["product"])
                request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
                item = self.prepare_item(request_id, item_id)
                item = self.request(
                    "user",
                    "PATCH",
                    f"/work-items/{item_id}",
                    body={"expectedRevision": item["revision"], "resolutionPath": path},
                )
                self.check(
                    item["resolutionPath"] == path,
                    "User must explicitly choose the resolution path",
                )

                # 2) 선택한 경로의 제공 여부와 자가 해결·제조사별 안내 상태를 확인한다.
                solutions = self.request("user", "GET", f"/work-items/{item_id}/solutions")
                self.check(
                    path in solutions["availablePaths"],
                    "Chosen resolution must be offered by current verified reference data",
                )
                if path == "SELF_HELP":
                    self.check(
                        solutions["selfHelp"]["status"] == "AVAILABLE",
                        "Self-help must use an applicable verified guide",
                    )
                if path == "MANUFACTURER_AS":
                    self.check(
                        solutions["officialService"]["status"] == "AVAILABLE",
                        "Known manufacturer must expose the prepared official-support route",
                    )

                # 3) 해결 결과는 사용자 진술이다. 플랫폼 예약 없이 해결 종료할 수 있어야 한다.
                self.request(
                    "user",
                    "POST",
                    f"/work-items/{item_id}/outcomes",
                    status=201,
                    body={
                        "outcome": {
                            "path": path,
                            "result": "RESOLVED",
                            "action": "합성 경로 확인",
                            "description": "사용자 진술의 해결 기록이며 기사 현장 확인이 아님",
                            "photoIds": [self.photo(root)["photoId"]],
                        },
                    },
                )
                self.check(
                    self.item(request_id, item_id)["activeReservationId"] is None,
                    "External or self-help outcomes must not fabricate a platform reservation",
                )
                self.close_request(request_id, resolved=True)
                self.delete_request(request_id)

    def finish(self) -> None:
        """12. 사전 구성한 삭제 실패를 재시도하고 모든 공유 세션에서 로그아웃한다.

        사전 조건: fixture가 사진 없는 접수의 재시도 가능한 FAILED 삭제 작업을 준비했다.
        진행: 실패 상태 조회 → retry 202 → worker COMPLETED 대기 → 완료 목록 조회
              → user·other·technician 로그아웃 및 /auth/me 재조회.
        기대 결과: 삭제 error 없음·restoredPhotoSlots=0, 각 로그아웃 204·재조회 401.
        시간 경과에 따른 세션 만료는 검사하지 않는다. 이후 시나리오가 없어야 한다.
        """
        with self.journey("worker-deletion-retry-and-session-expiry"):
            # 1) 실패 상태 자체만 fixture로 준비하고 재시도 처리는 실제 worker가 수행한다.
            job_id = self.config["failedDeletionJobId"]
            failed = self.request("user", "GET", f"/deletion-jobs/{job_id}")
            self.check(
                failed["status"] == "FAILED" and failed["error"]["retryable"],
                "Prepared failure must be a retryable deletion job",
            )
            self.request("user", "POST", f"/deletion-jobs/{job_id}/retry", status=202)
            completed = self.poll(f"/deletion-jobs/{job_id}", "COMPLETED")
            self.check(
                completed["restoredPhotoSlots"] == 0 and completed["error"] is None,
                "Real worker must complete the prepared empty-request deletion retry",
            )
            self.request(
                "user",
                "GET",
                "/deletion-jobs",
                params={"status": "COMPLETED", "targetType": "REQUEST", "limit": 100},
            )

            # 2) 공유 로그인 세션을 종료하고 인증이 해제됐는지 즉시 확인한다.
            for actor in ("user", "other", "technician"):
                self.request(actor, "POST", "/auth/logout", status=204)
                self.request(actor, "GET", "/auth/me", status=401)

    def cleanup(self) -> None:
        """남은 접수를 HTTP로 삭제 시도한다. 활성 관계 등의 잔여 정리는 runner가 맡는다."""
        self.current = "best-effort-cleanup"
        for request_id in list(self.requests):
            try:
                self.delete_request(request_id)
            except (CheckFailed, httpx.HTTPError, KeyError, ValueError) as error:
                # 예외 메시지의 민감 정보는 남기지 않는다. API가 활성 관계 때문에 삭제를
                # 거절하면 runner의 fixture 정리가 이번 실행 소유 자료의 정리를 맡는다.
                self.cleanup_errors.append(type(error).__name__)

    def run(self) -> bool:
        """시나리오를 순차 실행하고 실패·미실행·HTTP 호출 범위·작업 상태를 저장한다."""
        failure = None
        started = time.monotonic()
        print(
            f"[SUITE] {self.args.suite}: {len(self.planned_journeys)} planned journeys",
            flush=True,
        )
        try:
            self.setup()  # 01~02: 인증·기사 프로필·사례·일정
            self.completion_journey()  # 03: AI 없이 예약·인계·정상 완료
            self.stop_journey()  # 04~06: 원본 정정·AI·PDF·예약 변경·중단
            self.cancellation_journey()  # 07: 페이지 탐색·시작 전 취소
            if self.args.suite == "scenarios":
                self.alternative_journeys()  # 08~11: 긴급 안내·미지원 지역·대체 해결 경로
            self.finish()  # 12: 삭제 재시도·공유 세션 로그아웃
            missing = self.missing_endpoints()
            if self.args.suite == "api":
                self.check(
                    not missing,
                    f"API coverage incomplete: {len(missing)} contract endpoints "
                    "were not exercised successfully",
                )
        except CheckFailed as error:
            failure = str(error)
        except Exception as error:
            # 잘못된 응답·예상하지 못한 오류도 실행 실패로 처리하되,
            # 인증 정보가 담길 수 있는 예외 메시지는 출력하지 않는다.
            failure = f"{self.current}: unexpected {type(error).__name__} (payload omitted)"
        finally:
            if self.requests:
                self.cleanup()
            for client in self.clients.values():
                client.close()
        summary = {
            "suite": self.args.suite,
            "passed": failure is None,
            "failure": failure,
            "seconds": round(time.monotonic() - started, 2),
            "httpCalls": len(self.calls),
            "assertions": self.assertions,
            "journeys": self.journeys,
            "jobs": self.jobs,
            "ai": self.ai_result,
            "notRunJourneys": [
                name
                for name in self.planned_journeys
                if name not in {entry["name"] for entry in self.journeys}
            ],
            "coverage": {
                "total": len(self.patterns),
                "covered": len(self.covered),
                "missing": self.missing_endpoints(),
                "successful": sorted(self.covered),
                "failedHttp": sorted(
                    {
                        f"{call['method']} {call['endpoint']}"
                        for call in self.calls
                        if not call.get("passed", False)
                    },
                ),
            },
            "cleanup": {
                "pendingRequestCount": len(self.requests),
                "errors": self.cleanup_errors,
                "fixtureCleanup": "performed by runner.py finally block",
            },
            "execution": {
                "transport": "real HTTP",
                "database": "Compose PostgreSQL",
                "jobs": "Compose worker",
                "applicationImported": False,
            },
        }
        (self.output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"[{'PASS' if failure is None else 'FAIL'}] {self.args.suite}: "
            f"{len(self.calls)} HTTP calls, {self.assertions} assertions, "
            f"{len(self.covered)}/{len(self.patterns)} endpoints",
            flush=True,
        )
        if failure:
            print(f"[FAIL] {failure}", flush=True)
        for entry in self.journeys:
            verdict = "PASS" if entry["passed"] else "FAIL"
            print(f"  [{verdict}] {entry['label']}: {entry['assertions']} assertions", flush=True)
        for name in summary["notRunJourneys"]:
            print(f"  [NOT RUN] {JOURNEY_LABELS[name]}", flush=True)
        failed_endpoints = sorted(
            {
                f"{call['method']} {call['endpoint']}"
                for call in self.calls
                if not call.get("passed", False)
            },
        )
        for endpoint in failed_endpoints:
            print(f"  [FAILED HTTP] {endpoint}", flush=True)
        for endpoint in sorted(self.covered):
            print(f"  [COVERED] {endpoint}", flush=True)
        for endpoint in self.missing_endpoints():
            print(f"  [NOT COVERED] {endpoint}", flush=True)
        return failure is None

    def missing_endpoints(self) -> list[str]:
        return sorted({f"{method} {path}" for method, path, _ in self.patterns} - self.covered)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--suite", choices=("api", "scenarios"), required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--origin", default=None)
    parser.add_argument("--http-timeout", type=float, default=15)
    parser.add_argument("--poll-timeout", type=float, default=90)
    args = parser.parse_args()
    if args.http_timeout <= 0 or args.poll_timeout <= 0:
        parser.error("timeouts must be positive")
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        return 0 if Suite(args, config).run() else 1
    except Exception as error:
        print(
            f"[FAIL] Runner initialization: {type(error).__name__} (details omitted)",
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
