"""Run black-box E2E journeys against the published Compose HTTP port.

The runner never imports the application or opens its database. Fixture setup and
teardown belong to fixtures.py; every operation below crosses the HTTP boundary.
Background jobs must be completed by the separately running Compose worker.
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
    """A safe-to-print assertion message, containing no response payload."""


class JobFailed(CheckFailed):
    """Keep only job status and error metadata after test resources are deleted."""

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
    "published-service-and-authentication": "서비스 상태·API 명세·회원가입·로그인·권한",
    "technician-profile-cases-and-schedule": "기사 프로필·준비 사례·방문 일정",
    "no-ai-consultation-reservation-handover-completion": "비AI 상담·견적·예약·인계 갱신·정상 완료",
    "record-editing-ai-choice-and-candidate-discovery": "사진·기록 정정·선택적 AI·기사 후보 탐색",
    "masked-external-pdf-and-reservation-changes": "가림 처리·실제 PDF 생성·견적 거절·예약 변경",
    "early-start-stop-and-ended-access": "조기 시작 동의·사용자 중단 요청·종료 후 접근 제한",
    "reservation-cancellation": "시작 전 예약 취소",
    "emergency-guidance-and-support-boundaries": "긴급 안내·미지원 지역의 기록 및 예약 제한",
    "optional-resolution-self_help": "검증된 자가 해결·사용자 결과 기록",
    "optional-resolution-manufacturer_as": "제조사 AS 경로·사용자 결과 기록",
    "optional-resolution-direct_contact": "외부 직접 연락·사용자 결과 기록",
    "worker-deletion-retry-and-session-expiry": "실제 worker 삭제 재시도·로그아웃",
}


def endpoint_patterns(document: dict[str, Any]) -> list[tuple[str, str, re.Pattern]]:
    """Only public v1 contract operations count towards API coverage."""
    patterns = []
    for path, operations in document["paths"].items():
        if not path.startswith("/v1/"):
            continue
        expression = re.escape(path)
        expression = re.sub(r"\\\{[^{}]+\\\}", "[^/]+", expression)
        for method in operations:
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                patterns.append((method.upper(), path, re.compile("^" + expression + "$")))
    # Static segments win over a neighbouring path parameter, e.g. /me.
    return sorted(patterns, key=lambda entry: (entry[1].count("{"), entry[1], entry[0]))


def utc_text(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


class Suite:
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
            self.planned_journeys.extend("optional-resolution-" + path for path in ("self_help", "manufacturer_as", "direct_contact"))
        self.planned_journeys.append("worker-deletion-retry-and-session-expiry")
        self.requests: set[str] = set()
        self.cleanup_errors: list[str] = []
        self.ai_result: dict[str, Any] | None = None
        self.image = base64.b64decode(config["photoBase64"], validate=True)
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
            "ranges": [{"startAt": utc_text(self.base_time + 3600), "endAt": utc_text(self.base_time + 21600)}],
        }
        self.technician_id: str | None = None

    def check(self, condition: Any, message: str, *, announce: bool = True) -> None:
        self.assertions += 1
        if announce:
            print(f"  [{'PASS' if condition else 'FAIL'}] {message}", flush=True)
        if not condition:
            raise CheckFailed(message)

    @contextmanager
    def journey(self, name: str):
        self.current = name
        started = time.monotonic()
        before = self.assertions
        label = JOURNEY_LABELS.get(name, name)
        print(f"[시나리오 {len(self.journeys) + 1}/{len(self.planned_journeys)}] {label} ({name})", flush=True)
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
        url = ("/v1" if api else "") + path
        template = next(
            (candidate for verb, candidate, pattern in self.patterns if verb == method and pattern.fullmatch(url)),
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
                method, url, json=body, data=form, files=files, params=params, headers=headers,
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
            print(f"  [HTTP {verdict}] {method} {template} -> {response.status_code} (expected {status})", flush=True)
        self.check(response.status_code == status, f"{method} {template}: expected HTTP {status}, got {response.status_code}", announce=False)
        if 200 <= response.status_code < 300 and api:
            self.covered.add(f"{method} {template}")
        if code is not None:
            self.check(error_payload.get("code") == code, f"{method} {template}: expected error code {code}")
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
        self.check("data" in payload, f"{method} {template}: missing data envelope", announce=False)
        return payload["data"]

    def write_call(self, event: dict[str, Any]) -> None:
        # Never persist cookies, authentication bodies, original URLs or payloads.
        with (self.output / "http-calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def poll(self, path: str, expected: str, *, actor: str = "user") -> dict[str, Any]:
        deadline = time.monotonic() + self.args.poll_timeout
        last_notice = 0.0
        previous_state = None
        polls = 0
        details = {
            "journey": self.current, "expectedStatus": expected, "status": None,
            "errorCode": None, "retryable": None, "polls": 0, "passed": False,
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
                endpoint=endpoint, status=state, errorCode=diagnostic_code(error.get("code")),
                retryable=error.get("retryable") if type(error.get("retryable")) is bool else None,
                polls=polls, passed=state == expected,
            )
            self.assertions += 1
            unexpected = state != expected and state not in {"QUEUED", "RUNNING", "PROCESSING"}
            timed_out = state != expected and time.monotonic() >= deadline
            if unexpected or timed_out:
                reason = (
                    f"Worker job expected {expected}; got {state}"
                    if unexpected else f"Worker job did not reach {expected} within timeout"
                )
                if details["errorCode"]:
                    reason += f"; errorCode={details['errorCode']}"
                print(f"  [JOB FAIL] GET {endpoint}: {reason}", flush=True)
                raise JobFailed(reason, details)
            if state != previous_state or time.monotonic() - last_notice > 15:
                verdict = "PASS" if state == expected else "WAIT"
                suffix = f"; errorCode={details['errorCode']}" if details["errorCode"] else ""
                print(f"  [JOB {verdict}] GET {endpoint}: {state} ({polls} polls){suffix}", flush=True)
                previous_state = state
                last_notice = time.monotonic()
            if state == expected:
                return result
            time.sleep(0.5)

    def upload(self) -> list[tuple[str, tuple[str, bytes, str]]]:
        return [("files", ("synthetic-e2e.png", self.image, "image/png"))]

    def root(self, request_id: str) -> dict[str, Any]:
        return self.request("user", "GET", f"/requests/{request_id}")

    def item(self, request_id: str, item_id: str) -> dict[str, Any]:
        return next(item for item in self.root(request_id)["workItems"] if item["workItemId"] == item_id)

    def create_request(self, label: str, *, product: dict | None = None) -> dict[str, Any]:
        metadata = {
            "symptom": f"E2E 가상 수전 누수: {label}",
            "region": {key: value for key, value in self.config["region"].items() if key != "version"},
            "photos": [{"capturedOn": None, "dateConfirmed": False, "description": "합성 사진; 촬영일 미확인"}],
        }
        if product:
            metadata["product"] = product
        result = self.request("user", "POST", "/requests", status=201,
                              form={"metadata": json.dumps(metadata, ensure_ascii=False)}, files=self.upload())
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
        item = self.item(request_id, item_id)
        return self.request("user", "PUT", f"/work-items/{item_id}/confirmation", body={
            "expectedRevision": item["revision"], "sourceRevision": item["sourceRevision"],
            "fields": ["PLUMBING"], "confirmed": True,
            "summary": {
                "text": "사용자 진술: 수전 누수. 원인은 현장 확인 전까지 미확인.",
                "facts": [], "unknowns": ["누수 원인"], "riskSignals": [],
                "limitations": ["합성 E2E 자료"], "onsiteInspectionNeeded": True,
            },
        })

    def prepare_item(self, request_id: str, item_id: str) -> dict[str, Any]:
        item = self.item(request_id, item_id)
        self.request("user", "PATCH", f"/work-items/{item_id}", body={
            "expectedRevision": item["revision"],
            "facts": {"part": "수전", "workType": self.config["workType"], "quantity": 1,
                      "fields": ["PLUMBING"], "visitPreference": self.preference},
            "resolutionPath": "TECHNICIAN",
        })
        item = self.confirm_item(request_id, item_id)
        self.check(item["reviewStatus"] == "CONFIRMED", "Explicit confirmation must confirm summary")
        root = self.root(request_id)
        region = self.config["region"]
        self.request("user", "PUT", f"/requests/{request_id}/visit-details", body={
            "expectedRevision": root["revision"], "confirmed": True,
            "visitDetails": {"address": f"{region['city']} {region['district']} {region['neighborhood']} 가상 101호",
                             "contact": "010-0000-0001"},
        })
        return self.item(request_id, item_id)

    def setup(self) -> None:
        with self.journey("published-service-and-authentication"):
            self.request("anonymous", "GET", "/health/live", api=False)
            self.request("anonymous", "GET", "/health/ready", api=False)
            document = self.request("anonymous", "GET", "/openapi.json", api=False)
            self.patterns = endpoint_patterns(document)
            self.check(len(self.patterns) >= 80, "Published OpenAPI must contain the current v1 contract")
            self.check(document["info"]["version"] == "v1.1", "Published API specification must be v1.1")
            docs = self.request("anonymous", "GET", "/docs", api=False, raw=True)
            self.check("swagger" in docs.text.lower(), "Swagger UI must be published")
            info = self.request("anonymous", "GET", "/public/service-info")
            self.check("PLUMBING" in info["fields"], "Service info must expose the supported field")
            self.request("anonymous", "GET", "/public/guidance", params={"type": "EMERGENCY"})
            guidance = self.request("anonymous", "GET", "/public/guidance", params={"type": "MANUFACTURER_AS"})
            self.check(guidance["officialService"]["status"] == "INFORMATION_REQUIRED", "Missing manufacturer must require input")
            signup = {"loginId": self.config["runId"] + "-signup", "password": uuid.uuid4().hex}
            account = self.request("signup", "POST", "/auth/signup", status=201, body=signup)
            self.check(account["availableRoles"] == ["USER"], "Signup may grant only USER")
            self.check(not self.clients["signup"].cookies, "Signup must not create a session")
            self.request("signup", "POST", "/auth/signup", status=409, code="ACCOUNT_EXISTS", body=signup)
            self.request("signup", "POST", "/auth/login", body=signup)
            self.request("signup", "GET", "/auth/me")
            self.request("signup", "PATCH", "/auth/role", status=403, code="ROLE_FORBIDDEN", body={"role": "TECHNICIAN"})
            self.request("signup", "POST", "/auth/logout", status=204)
            self.request("signup", "GET", "/auth/me", status=401)
            for actor in ("user", "other", "technician"):
                credentials = self.config["accounts"][actor]
                self.request(actor, "POST", "/auth/login", body={k: credentials[k] for k in ("loginId", "password")})
                self.request(actor, "GET", "/auth/me")
            session = self.request("technician", "PATCH", "/auth/role", body={"role": "TECHNICIAN"})
            self.check(session["activeRole"] == "TECHNICIAN", "Technician session must switch roles")

        with self.journey("technician-profile-cases-and-schedule"):
            technician = self.request("technician", "GET", "/technicians/me")
            self.technician_id = technician["technicianId"]
            photos = self.request("technician", "POST", "/technicians/me/portfolio-photos", status=201,
                                  form={"source": json.dumps(self.config["source"], ensure_ascii=False)}, files=self.upload())
            profile = {
                "displayName": "E2E 가상 기사", "fields": ["PLUMBING"],
                "regionIds": [self.config["region"]["regionId"]],
                "representativeMediaIds": [photos[0]["mediaId"]],
                "contacts": [{"contact": {"label": "가상 연락처", "value": "010-0000-0002"}, "isPublic": True}],
            }
            self.request("technician", "PUT", "/technicians/me/profile", body={
                "expectedRevision": technician["profileRevision"], "profile": profile,
            })
            self.request("anonymous", "GET", "/public/technicians", params={"field": "PLUMBING", "regionId": self.config["region"]["regionId"]})
            public = self.request("anonymous", "GET", f"/public/technicians/{self.technician_id}")
            self.check(public["directContactAvailable"], "Public technician must expose opted-in contact")
            case = self.request("technician", "POST", "/technicians/me/cases", status=201, body={"case": self.config["case"]})
            case = self.request("technician", "PATCH", f"/technicians/me/cases/{case['caseId']}", body={
                "expectedRevision": case["revision"], "case": self.config["updatedCase"],
            })
            self.request("user", "GET", f"/cases/{case['caseId']}")
            portfolio = self.request("user", "GET", f"/technicians/{self.technician_id}/portfolio")
            self.check(any(value["caseId"] == case["caseId"] for value in portfolio["cases"]), "Portfolio must contain the prepared case")
            schedule = self.request("technician", "GET", "/technicians/me/schedule", params=self.dates)
            self.request("technician", "PUT", "/technicians/me/schedule", body={
                "expectedRevision": schedule["revision"], **self.dates,
                "availability": [{"startAt": utc_text(self.base_time - 7200), "endAt": utc_text(self.base_time + 43200)}],
                "externalVisits": [],
            })

    def edit_sources(self, root: dict[str, Any]) -> None:
        request_id = root["requestId"]
        item_id = root["workItems"][0]["workItemId"]
        photo = self.photo(root)
        media_id = photo["media"]["mediaId"]
        self.request("other", "GET", f"/requests/{request_id}", status=403, code="ACCESS_DENIED")
        self.request("technician", "GET", f"/requests/{request_id}", status=403, code="ROLE_FORBIDDEN")
        self.request("other", "GET", f"/media/{media_id}", status=403, code="ACCESS_DENIED")
        self.request("anonymous", "GET", f"/media/{media_id}", status=401)
        media = self.request("user", "GET", f"/media/{media_id}", raw=True)
        self.check(media.headers.get("content-type", "").startswith("image/"), "Original upload must be readable only by its owner")
        self.request("user", "GET", "/requests", params={"limit": 0}, status=422)
        self.request("user", "GET", "/requests", params=[("limit", "1"), ("limit", "2")], status=400)
        self.request("user", "GET", "/requests", params={"limit": 100})
        revision = root["revision"]
        self.request("user", "PATCH", f"/requests/{request_id}", body={"expectedRevision": revision, "symptom": "정정된 E2E 가상 수전 누수"})
        self.request("user", "PATCH", f"/requests/{request_id}", status=409, code="VERSION_CONFLICT",
                     body={"expectedRevision": revision, "symptom": "오래된 편집"})
        photos = self.request("user", "POST", f"/requests/{request_id}/photos", status=201,
                              form={"metadata": json.dumps([{"capturedOn": None, "dateConfirmed": False, "description": "추가 합성 사진", "workItemIds": [item_id]}], ensure_ascii=False)},
                              files=self.upload())
        self.check(photos["storedCount"] == 2 and photos["remainingCount"] == 28, "Photo count must persist in PostgreSQL")
        edited = self.request("user", "PUT", f"/photos/{photo['photoId']}", form={
            "expectedRevision": photo["revision"],
            "metadata": json.dumps({"capturedOn": None, "dateConfirmed": False, "description": "설명을 정정한 합성 사진", "workItemIds": [item_id]}, ensure_ascii=False),
        }, files=[("file", ("replacement.png", self.image, "image/png"))])
        self.check(edited["description"] == "설명을 정정한 합성 사진", "Photo edits must be reflected")
        record_body = {"description": "사용자 관찰 기록", "photoIds": [photo["photoId"]], "workItemIds": [item_id]}
        record = self.request("user", "POST", f"/requests/{request_id}/records", status=201, body={"record": record_body})
        self.request("user", "PATCH", f"/records/{record['recordId']}", body={
            "expectedRevision": record["revision"], "record": {**record_body, "description": "정정된 사용자 관찰 기록"},
        })
        self.request("user", "POST", f"/work-items/{item_id}/outcomes", status=201, body={
            "outcome": {"path": "DIRECT_CONTACT", "result": "UNRESOLVED", "action": "외부 직접 연락",
                        "description": "합성 시나리오: 연락 후에도 미해결", "photoIds": [photo["photoId"]]},
        })
        root = self.root(request_id)
        self.request("user", "POST", f"/requests/{request_id}/work-items", status=201, body={
            "expectedRevision": root["revision"],
            "facts": {"part": "배관", "workType": self.config["workType"], "quantity": 1, "fields": ["PLUMBING"],
                      "product": {"productType": None, "manufacturer": None, "modelName": None}},
        })
        root = self.root(request_id)
        photo_ids = [value["photoId"] for value in root["photos"]["unknownDatePhotos"]]
        timeline = self.request("user", "PUT", f"/requests/{request_id}/photo-groups", body={
            "sourceRevision": root["sourceRevision"],
            "groups": [{"label": "동일 수전", "photoIds": photo_ids, "selectedPhotoIds": photo_ids}],
        })
        self.check(len(timeline["groups"]) == 1, "Photo grouping must persist")
        self.request("user", "GET", f"/requests/{request_id}/timeline")

    def ai_diagnosis(self, request_id: str, item_id: str) -> None:
        item = self.item(request_id, item_id)
        job = self.request("user", "POST", f"/requests/{request_id}/ai-jobs", status=202, body={
            "type": "DIAGNOSIS", "sourceRevision": item["sourceRevision"], "workItemId": item_id,
        })
        expected = self.config["ai"]["expectedStatus"]
        self.ai_result = {
            "expectedStatus": expected, "actualStatus": None, "providerMocked": False,
            "successPath": "NOT_COMPLETED", "errorCode": None,
        }
        try:
            result = self.poll(f"/ai-jobs/{job['jobId']}", expected)
        except JobFailed as error:
            self.ai_result.update(
                actualStatus=error.details["status"], errorCode=error.details["errorCode"],
                retryable=error.details["retryable"], successPath="NOT_COMPLETED",
            )
            raise
        self.ai_result.update(
            actualStatus=result["status"],
            errorCode=diagnostic_code((result.get("error") or {}).get("code")),
        )
        if expected == "FAILED":
            self.check((result.get("error") or {}).get("code") == self.config["ai"]["expectedErrorCode"], "Unconfigured AI must report AI_NOT_CONFIGURED")
            self.ai_result["successPath"] = "NOT_TESTED: provider credentials/model are not configured"
            print("  [NOT TESTED] Real AI success path: AI_NOT_CONFIGURED; actual worker failure path verified", flush=True)
        else:
            self.check(result.get("error") is None, "Configured AI must succeed without a provider error")
            self.check(result.get("result") is not None and not result["stale"], "Real AI success must contain current persisted output")
            self.ai_result["successPath"] = "TESTED: real provider DIAGNOSIS"
        self.request("user", "GET", f"/requests/{request_id}/ai-jobs", params={"type": "DIAGNOSIS", "limit": 1})
        self.check(self.item(request_id, item_id)["reviewStatus"] != "CONFIRMED", "AI output must not implicitly confirm user facts")
        root = self.root(request_id)
        dialogue = self.request("user", "PUT", f"/requests/{request_id}/ai-dialogue", body={
            "expectedRevision": root["dialogue"]["revision"], "action": "FINISH",
        })
        self.check(dialogue["finished"], "User must be able to finish optional AI dialogue")

    def candidates(self, request_id: str, item_id: str) -> None:
        self.request("user", "GET", f"/work-items/{item_id}/solutions")
        self.request("user", "GET", f"/work-items/{item_id}/case-recommendations")
        candidates = self.request("user", "GET", f"/work-items/{item_id}/general-candidates", params={"limit": 100})
        self.check(any(value["technician"]["technicianId"] == self.technician_id and value["timeFit"] == "MATCHED" for value in candidates["items"]), "Prepared technician must match region, field and time")
        item = self.item(request_id, item_id)
        self.request("user", "PUT", f"/work-items/{item_id}/route-exploration", body={
            "expectedRevision": item["revision"], "enabled": True, "confirmed": True,
        })
        date = datetime.fromtimestamp(self.base_time + 7200, timezone(timedelta(hours=9))).date().isoformat()
        routes = self.request("technician", "GET", "/technicians/me/route-candidates", params={"date": date, "limit": 100})
        matching = [value for value in routes["items"] if value["candidateId"].startswith(item_id + ".")]
        self.check(matching, "Opted-in work item must be a route candidate")
        interest = self.request("technician", "POST", f"/route-candidates/{matching[0]['candidateId']}/interests", status=201)
        interests = self.request("user", "GET", f"/work-items/{item_id}/interests")
        self.check(any(value["interestId"] == interest["interestId"] for value in interests), "Owner must receive technician interest")

    def report(self, request_id: str, item_id: str, *, previous: dict | None = None) -> dict[str, Any]:
        root = self.root(request_id)
        item = next(value for value in root["workItems"] if value["workItemId"] == item_id)
        if previous:
            previous = self.request("user", "GET", f"/work-items/{item_id}/report")
        details = root["visitDetails"]
        report = self.request("user", "PUT", f"/work-items/{item_id}/report", body={
            "expectedRevision": previous["revision"] if previous else None,
            "sourceRevision": item["sourceRevision"],
            "report": {"markdown": "# 합성 E2E 경과 보고\n사용자 관찰: 누수. 원인 미확인.\n"
                                   f"가상 방문정보 제거 검증: {details['contact']} / {details['address']}",
                       "photoIds": [self.photo(root)["photoId"]], "facts": [], "unknowns": ["원인"]},
        })
        self.request("user", "GET", f"/work-items/{item_id}/report")
        report = self.request("user", "PUT", f"/work-items/{item_id}/report/confirmation", body={
            "expectedRevision": report["revision"], "sourceRevision": report["sourceRevision"], "confirmed": True,
        })
        self.check(report["reviewStatus"] == "CONFIRMED", "Report must require explicit owner confirmation")
        return report

    def delivery(self, request_id: str, item_id: str, purpose: str, *, reservation_id: str | None = None,
                 replaces: str | None = None) -> dict[str, Any]:
        root = self.root(request_id)
        item = next(value for value in root["workItems"] if value["workItemId"] == item_id)
        photo = self.photo(root)
        scope = {
            "purpose": purpose, "photoIds": [photo["photoId"]], "recordIds": [], "questionIds": [],
            "includeSummary": True, "includeReport": purpose != "CONSULTATION", "includeQuoteContext": purpose == "CONSULTATION",
        }
        if purpose != "EXTERNAL_PDF":
            scope["recipientTechnicianId"] = self.technician_id
        if reservation_id:
            scope["reservationId"] = reservation_id
        body = {
            "sourceRevision": item["sourceRevision"], "scope": scope,
            "redactions": [{"targetType": "PHOTO", "resourceId": photo["photoId"], "exclude": False, "boxes": [[0, 0, 0.5, 0.5]]}],
        }
        if replaces:
            body["replacesDeliveryId"] = replaces
        created = self.request("user", "POST", f"/work-items/{item_id}/deliveries", status=202, body=body)
        delivery = self.poll(f"/deliveries/{created['deliveryId']}", "READY")
        self.check(delivery["metadataRemoved"], "Worker must remove metadata from delivered images")
        if purpose == "EXTERNAL_PDF":
            content_text = json.dumps(delivery["content"], ensure_ascii=False)
            self.check(all(value not in content_text for value in root["visitDetails"].values()),
                       "External PDF delivery must remove private visit details even from report text")
        transformed = delivery["content"]["photos"][0]["media"]
        self.check(transformed["mediaId"] != photo["media"]["mediaId"], "Delivery must reference a separate transformed image")
        masked = self.request("user", "GET", f"/media/{transformed['mediaId']}", raw=True)
        self.check(masked.content.startswith(b"\x89PNG\r\n\x1a\n"), "Worker must produce the masked PNG")
        with Image.open(io.BytesIO(masked.content)) as image:
            pixel = image.convert("RGB").getpixel((image.width // 4, image.height // 4))
            self.check(pixel == (0, 0, 0), "Delivered image must actually obscure pixels inside the selected mask")
        delivery = self.request("user", "PUT", f"/deliveries/{created['deliveryId']}/confirmation", body={
            "expectedRevision": delivery["revision"], "sourceRevision": delivery["sourceRevision"], "confirmed": True,
        })
        self.check(delivery["reviewStatus"] == "CONFIRMED", "Processed delivery must be explicitly confirmed")
        self.request("user", "GET", f"/work-items/{item_id}/deliveries", params={"purpose": purpose, "status": "READY", "limit": 100})
        return delivery

    def pdf(self, delivery: dict[str, Any]) -> str:
        delivery_id = delivery["deliveryId"]
        job = self.request("user", "POST", f"/deliveries/{delivery_id}/pdf-jobs", status=202, body={"deliveryRevision": delivery["revision"]})
        result = self.poll(f"/pdf-jobs/{job['jobId']}", "READY")
        self.check(result["downloadAvailable"], "Real worker PDF must be downloadable")
        self.request("user", "GET", f"/deliveries/{delivery_id}/pdf-jobs", params={"status": "READY", "limit": 1})
        pdf = self.request("user", "GET", f"/pdf-jobs/{job['jobId']}/content", raw=True)
        self.check(pdf.content.startswith(b"%PDF-"), "PDF download must contain a PDF document")
        self.check(pdf.headers.get("content-type", "").startswith("application/pdf"), "PDF content type must be correct")
        self.request("other", "GET", f"/pdf-jobs/{job['jobId']}/content", status=403, code="ACCESS_DENIED")
        return job["jobId"]

    def reserve(self, request_id: str, item_id: str, *, reject_first: bool = False) -> tuple[dict, str]:
        delivery = self.delivery(request_id, item_id, "CONSULTATION")
        relation = self.request("user", "POST", f"/work-items/{item_id}/consultations", status=201,
                                body={"technicianId": self.technician_id, "deliveryId": delivery["deliveryId"]})
        consultation_id = relation["consultationId"]
        relation = self.request("technician", "GET", f"/consultations/{consultation_id}")
        self.check(relation["status"] == "PENDING", "New consultation must await technician acceptance")
        self.request("technician", "PATCH", f"/consultations/{consultation_id}", body={"expectedRevision": relation["revision"], "action": "ACCEPT"})
        for actor in ("user", "technician"):
            consultations = self.request(actor, "GET", "/consultations", params={"status": "ACCEPTED", "limit": 100})
            self.check(any(value["consultationId"] == consultation_id for value in consultations["items"]), "Both parties must see the accepted consultation")
        visible = self.request("technician", "GET", f"/deliveries/{delivery['deliveryId']}")
        self.check(visible["redactions"] is None, "Technician must not receive private redaction instructions")
        root = self.root(request_id)
        item = next(value for value in root["workItems"] if value["workItemId"] == item_id)
        terms = {
            "versions": {"commonVersion": root["commonVersion"], "itemVersion": item["itemVersion"], "proposalVersion": None},
            "fields": ["PLUMBING"], "scope": "합성 E2E 수전 교체", "quantity": 1, "durationMinutes": 60,
            "startAt": self.times["start"], "expiresAt": self.times["expires"],
            "cost": {"minimumVisitFee": 0, "minimumDiagnosticFee": 0, "discountCondition": "E2E 시간 합의",
                     "lines": [{"category": "LABOR", "description": "가상 작업비", "confirmed": True,
                                "beforeAmount": 100000, "afterAmount": 90000, "condition": None}]},
        }
        quote_body = {"contextDeliveryId": delivery["deliveryId"], "terms": terms}
        quote = self.request("technician", "POST", f"/consultations/{consultation_id}/quotes", status=201, body=quote_body)
        if reject_first:
            rejected = self.request("user", "PATCH", f"/quotes/{quote['quoteId']}", body={"expectedRevision": quote["revision"], "action": "REJECT"})
            self.check(rejected["status"] == "REJECTED", "User must be able to reject a quote")
            quote = self.request("technician", "POST", f"/consultations/{consultation_id}/quotes", status=201, body=quote_body)
        self.check(quote["selectable"] and quote["price"]["afterTotal"] == 90000, "Issued quote must expose the agreed price and be selectable")
        self.request("user", "GET", f"/work-items/{item_id}/quotes")
        check = self.request("user", "POST", "/reservation-checks", body={"operation": "CREATE", "quoteId": quote["quoteId"]})
        self.check(check["allowed"], "Real schedule and travel checks must permit the prepared reservation")
        check = self.request("user", "PUT", f"/reservation-checks/{check['checkId']}/confirmation", body={"confirmed": True})
        self.check(check["overlapConfirmed"], "Owner must be able to confirm reservation checks")
        body = {"quoteId": quote["quoteId"], "versions": quote["terms"]["versions"], "visitDetailsRevision": root["visitDetailsRevision"]}
        key = uuid.uuid4().hex
        reservation = self.request("user", "POST", f"/work-items/{item_id}/reservations", status=201, body=body, key=key)
        replay = self.request("user", "POST", f"/work-items/{item_id}/reservations", status=201, body=body, key=key)
        self.check(replay["reservationId"] == reservation["reservationId"], "Reservation retry must return the same resource")
        self.request("user", "POST", f"/work-items/{item_id}/reservations", status=409, code="IDEMPOTENCY_KEY_REUSED",
                     body={**body, "visitDetailsRevision": "different-e2e-input"}, key=key)
        self.check(reservation["status"] == "CONFIRMED", "Chosen quote must become a confirmed reservation")
        for actor in ("user", "technician"):
            self.request(actor, "GET", "/reservations", params={"status": "CONFIRMED", "limit": 100})
        visible = self.request("technician", "GET", f"/reservations/{reservation['reservationId']}")
        self.check(visible["agreement"]["terms"]["visitDetails"]["contact"] == "010-0000-0001", "Active reservation must disclose the confirmed visit contact")
        return reservation, delivery["deliveryId"]

    def start(self, reservation: dict[str, Any]) -> dict[str, Any]:
        reservation_id = reservation["reservationId"]
        version = reservation["agreement"]["agreementVersion"]
        self.request("technician", "POST", f"/reservations/{reservation_id}/work-events", status=409,
                     code="EARLY_START_CONSENT_REQUIRED", body={"event": "START", "agreementVersion": version})
        self.request("user", "PUT", f"/reservations/{reservation_id}/early-start-consent", body={
            "agreementVersion": version, "expectedConsentRevision": None, "action": "GRANT", "proposedStartAt": self.times["early"],
        })
        started = self.request("technician", "POST", f"/reservations/{reservation_id}/work-events", body={"event": "START", "agreementVersion": version})
        self.check(started["status"] == "IN_PROGRESS", "Only explicit early-start consent may start work early")
        return started

    def close_request(self, request_id: str, *, resolved: bool = False) -> None:
        root = self.root(request_id)
        result = self.request("user", "POST", f"/requests/{request_id}/closure", body={
            "expectedRevision": root["revision"],
            "items": [{"workItemId": item["workItemId"], "resolved": resolved, "reason": "합성 E2E 검증 종료"} for item in root["workItems"]],
        })
        self.check(result["status"] == "CLOSED", "Owner must explicitly close all request items")

    def delete_request(self, request_id: str) -> None:
        job = self.request("user", "POST", "/deletion-jobs", status=202, body={
            "targetType": "REQUEST", "targetId": request_id, "includeAllReferences": True,
        })
        self.check(job["accessBlocked"], "Deletion must block access before physical cleanup")
        self.request("user", "GET", f"/requests/{request_id}", status=404)
        completed = self.poll(f"/deletion-jobs/{job['jobId']}", "COMPLETED")
        self.check(completed["error"] is None and completed["restoredPhotoSlots"] > 0, "Worker must physically delete request photos")
        self.requests.discard(request_id)
        self.request("user", "POST", f"/deletion-jobs/{job['jobId']}/retry", status=409, code="INVALID_STATE")

    def completion_journey(self) -> None:
        with self.journey("no-ai-consultation-reservation-handover-completion"):
            root = self.create_request("정상 완료")
            request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
            item = self.prepare_item(request_id, item_id)
            self.check(item["aiUseStatus"] == "NOT_SELECTED", "No-AI path must allow explicit confirmation and reservation")
            reservation, consultation_delivery = self.reserve(request_id, item_id)
            report = self.report(request_id, item_id)
            handover = self.delivery(request_id, item_id, "HANDOVER", reservation_id=reservation["reservationId"])
            self.request("technician", "GET", f"/deliveries/{handover['deliveryId']}")
            photo_id = self.photo(root)["photoId"]
            self.request("user", "POST", f"/requests/{request_id}/records", status=201, body={
                "record": {"description": "방문 전 추가 경과", "photoIds": [photo_id], "workItemIds": [item_id]},
            })
            stale = self.request("user", "GET", f"/deliveries/{handover['deliveryId']}")
            self.check(stale["status"] == "STALE", "New source evidence must invalidate the old handover")
            self.confirm_item(request_id, item_id)
            self.report(request_id, item_id, previous=report)
            handover = self.delivery(request_id, item_id, "HANDOVER", reservation_id=reservation["reservationId"], replaces=handover["deliveryId"])
            reservation = self.start(reservation)
            result = self.request("technician", "POST", f"/reservations/{reservation['reservationId']}/work-events", body={
                "event": "COMPLETE", "agreementVersion": reservation["agreement"]["agreementVersion"],
                "performance": {"confirmedCause": "합성 패킹 손상", "performed": ["패킹 교체"], "notPerformed": [],
                                "unknowns": [], "parts": ["패킹"], "endLocationId": self.config["locationId"]},
            })
            self.check(result["status"] == "COMPLETED", "Technician completion must preserve performance and end the reservation")
            self.check(self.item(request_id, item_id)["status"] == "RESOLVED", "Normal completion must resolve the work item")
            ended = self.request("technician", "GET", f"/reservations/{reservation['reservationId']}")
            self.check(ended["agreement"]["terms"]["visitDetails"] is None, "Finished relationship must hide visit details")
            frozen = self.request("technician", "GET", f"/deliveries/{handover['deliveryId']}")
            self.check(frozen["content"]["quoteContext"] is None, "Ended handover must contain only permitted historical evidence")
            private = self.root(request_id)["visitDetails"]
            frozen_text = json.dumps(frozen["content"], ensure_ascii=False)
            self.check(all(value not in frozen_text for value in private.values()), "Historical handover must remove embedded private visit information")
            self.request("technician", "GET", f"/deliveries/{consultation_delivery}", status=403, code="ACCESS_DENIED")
            self.close_request(request_id, resolved=True)
            # Remove this isolated run's ended trip before the next journey. The
            # actual travel rules must not be bypassed by moving the server clock.
            self.delete_request(request_id)

    def stop_journey(self) -> None:
        with self.journey("record-editing-ai-choice-and-candidate-discovery"):
            root = self.create_request("변경 및 중단")
            request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
            self.edit_sources(root)
            self.ai_diagnosis(request_id, item_id)
            self.prepare_item(request_id, item_id)
            self.candidates(request_id, item_id)

        with self.journey("masked-external-pdf-and-reservation-changes"):
            self.report(request_id, item_id)
            delivery = self.delivery(request_id, item_id, "EXTERNAL_PDF")
            pdf_id = self.pdf(delivery)
            reservation, consultation_delivery = self.reserve(request_id, item_id, reject_first=True)
            reservation_id = reservation["reservationId"]
            old_version = reservation["agreement"]["agreementVersion"]
            self.request("technician", "PUT", f"/reservations/{reservation_id}/preparation-notes", body={
                "preparation": {"equipment": ["렌치"], "parts": [], "inspectionItems": ["연결부"], "note": "E2E 합성 준비사항"},
            })
            terms = reservation["agreement"]["terms"]
            change = self.request("user", "POST", f"/reservations/{reservation_id}/changes", status=201, body={
                "type": "BEFORE_START", "agreementVersion": old_version,
                "terms": {"fields": terms["fields"], "scope": "합성 변경 작업", "quantity": 1, "cost": terms["cost"],
                          "visitPreference": self.preference, "startAt": self.times["changed_start"], "expectedEndAt": self.times["changed_end"]},
            })
            applied = self.request("technician", "PATCH", f"/reservation-changes/{change['changeId']}", body={"expectedRevision": change["revision"], "action": "ACCEPT"})
            self.check(applied["status"] == "APPLIED", "Both parties must agree before changes take effect")
            self.request("user", "POST", f"/reservations/{reservation_id}/cancellation", status=409, code="VERSION_CONFLICT", body={"agreementVersion": old_version})
            reservation = self.request("user", "GET", f"/reservations/{reservation_id}")
            self.check(len(reservation["agreementHistory"]) == 2, "Agreement history must preserve the original and accepted change")

        with self.journey("early-start-stop-and-ended-access"):
            started = self.start(reservation)
            version = started["agreement"]["agreementVersion"]
            self.request("technician", "POST", f"/reservations/{reservation_id}/work-events", body={
                "event": "UPDATE_EXPECTED_END", "agreementVersion": version,
                "expectedEndEstimateRevision": started["endEstimateRevision"], "expectedEndAt": self.times["extended_end"],
            })
            stopping = self.request("user", "POST", f"/reservations/{reservation_id}/work-events", body={
                "event": "REQUEST_STOP", "agreementVersion": version, "reason": "합성 E2E 중단 요청",
            })
            self.check(stopping["status"] == "STOP_REQUESTED", "User stop request must remain distinct from technician stop")
            performance = {"confirmedCause": None, "performed": ["연결부 점검"], "notPerformed": ["교체"],
                           "unknowns": ["원인"], "parts": [], "endLocationId": None}
            self.request("technician", "POST", f"/reservations/{reservation_id}/work-events", status=409, code="INVALID_STATE",
                         body={"event": "COMPLETE", "agreementVersion": version, "performance": performance})
            stopped = self.request("technician", "POST", f"/reservations/{reservation_id}/work-events", body={
                "event": "STOP", "agreementVersion": version, "performance": performance,
            })
            self.check(stopped["status"] == "STOPPED", "Technician must persist unfinished work when stopping")
            self.request("technician", "PUT", f"/reservations/{reservation_id}/end-location", body={
                "expectedEndLocationRevision": stopped["endLocationRevision"], "endLocationId": self.config["locationId"],
            })
            ended = self.request("technician", "GET", f"/reservations/{reservation_id}")
            self.check(ended["agreement"]["terms"]["visitDetails"] is None, "Stopped reservation must hide visit details")
            self.request("technician", "GET", f"/deliveries/{consultation_delivery}", status=403, code="ACCESS_DENIED")
            pdf = self.request("user", "GET", f"/pdf-jobs/{pdf_id}")
            self.check(not pdf["downloadAvailable"], "Changed evidence must invalidate the old PDF")
            self.request("user", "GET", f"/pdf-jobs/{pdf_id}/content", status=409)
            self.close_request(request_id)
            self.delete_request(request_id)

    def cancellation_journey(self) -> None:
        with self.journey("reservation-cancellation"):
            root = self.create_request("시작 전 취소")
            request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
            page_request = self.create_request("페이지 탐색")
            first_page = self.request("user", "GET", "/requests", params={"limit": 1})
            self.check(first_page["nextCursor"] is not None, "Request list must provide a cursor when more records exist")
            second_page = self.request("user", "GET", "/requests", params={"limit": 1, "cursor": first_page["nextCursor"]})
            self.check(first_page["items"][0]["requestId"] != second_page["items"][0]["requestId"],
                       "Cursor pagination must not duplicate the previous request")
            self.delete_request(page_request["requestId"])
            self.prepare_item(request_id, item_id)
            reservation, _ = self.reserve(request_id, item_id)
            cancelled = self.request("user", "POST", f"/reservations/{reservation['reservationId']}/cancellation", body={
                "agreementVersion": reservation["agreement"]["agreementVersion"], "reason": "합성 E2E 취소",
            })
            self.check(cancelled["status"] == "CANCELLED", "Cancellation must end a reservation before work starts")
            self.close_request(request_id)
            self.delete_request(request_id)

    def alternative_journeys(self) -> None:
        with self.journey("emergency-guidance-and-support-boundaries"):
            guidance = self.request("anonymous", "GET", "/public/guidance", params={
                "type": "EMERGENCY", "triggerId": self.config["emergencyTriggerId"],
            })
            self.check(guidance["guide"]["status"] == "AVAILABLE", "Registered emergency trigger must expose verified guidance without AI")
            root = self.create_request("미지원 지역 기록")
            request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
            changed = self.request("user", "PATCH", f"/requests/{request_id}", body={
                "expectedRevision": root["revision"],
                "region": {"city": "부산광역시", "district": "가상구", "neighborhood": "가상동"},
            })
            self.check(changed["support"]["status"] == "UNSUPPORTED_REGION", "Unsupported region must still permit request records")
            self.confirm_item(request_id, item_id)
            self.request("user", "GET", f"/work-items/{item_id}/general-candidates", status=422, code="SERVICE_UNSUPPORTED")
            self.close_request(request_id)
            self.delete_request(request_id)
        for path in ("SELF_HELP", "MANUFACTURER_AS", "DIRECT_CONTACT"):
            with self.journey("optional-resolution-" + path.lower()):
                root = self.create_request(path, product=self.config["product"])
                request_id, item_id = root["requestId"], root["workItems"][0]["workItemId"]
                item = self.prepare_item(request_id, item_id)
                item = self.request("user", "PATCH", f"/work-items/{item_id}", body={"expectedRevision": item["revision"], "resolutionPath": path})
                self.check(item["resolutionPath"] == path, "User must explicitly choose the resolution path")
                solutions = self.request("user", "GET", f"/work-items/{item_id}/solutions")
                self.check(path in solutions["availablePaths"], "Chosen resolution must be offered by current verified reference data")
                if path == "SELF_HELP":
                    self.check(solutions["selfHelp"]["status"] == "AVAILABLE", "Self-help must use an applicable verified guide")
                if path == "MANUFACTURER_AS":
                    self.check(solutions["officialService"]["status"] == "AVAILABLE", "Known manufacturer must expose the prepared official-support route")
                self.request("user", "POST", f"/work-items/{item_id}/outcomes", status=201, body={
                    "outcome": {"path": path, "result": "RESOLVED", "action": "합성 경로 확인",
                                "description": "사용자 진술의 해결 기록이며 기사 현장 확인이 아님", "photoIds": [self.photo(root)["photoId"]]},
                })
                self.check(self.item(request_id, item_id)["activeReservationId"] is None, "External or self-help outcomes must not fabricate a platform reservation")
                self.close_request(request_id, resolved=True)
                self.delete_request(request_id)

    def finish(self) -> None:
        with self.journey("worker-deletion-retry-and-session-expiry"):
            job_id = self.config["failedDeletionJobId"]
            failed = self.request("user", "GET", f"/deletion-jobs/{job_id}")
            self.check(failed["status"] == "FAILED" and failed["error"]["retryable"], "Prepared failure must be a retryable deletion job")
            self.request("user", "POST", f"/deletion-jobs/{job_id}/retry", status=202)
            completed = self.poll(f"/deletion-jobs/{job_id}", "COMPLETED")
            self.check(completed["restoredPhotoSlots"] == 0 and completed["error"] is None,
                       "Real worker must complete the prepared empty-request deletion retry")
            self.request("user", "GET", "/deletion-jobs", params={"status": "COMPLETED", "targetType": "REQUEST", "limit": 100})
            for actor in ("user", "other", "technician"):
                self.request(actor, "POST", "/auth/logout", status=204)
                self.request(actor, "GET", "/auth/me", status=401)

    def cleanup(self) -> None:
        """Attempt public deletion; fixture teardown also handles active relations."""
        self.current = "best-effort-cleanup"
        for request_id in list(self.requests):
            try:
                self.delete_request(request_id)
            except (CheckFailed, httpx.HTTPError, KeyError, ValueError) as error:
                # Only the safe exception class is retained. Root fixture cleanup
                # removes owned active relations if the API correctly rejects it.
                self.cleanup_errors.append(type(error).__name__)

    def run(self) -> bool:
        failure = None
        started = time.monotonic()
        print(f"[SUITE] {self.args.suite}: {len(self.planned_journeys)} planned journeys", flush=True)
        try:
            self.setup()
            self.completion_journey()
            self.stop_journey()
            self.cancellation_journey()
            if self.args.suite == "scenarios":
                self.alternative_journeys()
            self.finish()
            missing = self.missing_endpoints()
            if self.args.suite == "api":
                self.check(not missing, f"API coverage incomplete: {len(missing)} contract endpoints were not exercised successfully")
        except CheckFailed as error:
            failure = str(error)
        except Exception as error:
            # A malformed response or unexpected implementation error must fail
            # the run, without leaking exception messages containing credentials.
            failure = f"{self.current}: unexpected {type(error).__name__} (payload omitted)"
        finally:
            if self.requests:
                self.cleanup()
            for client in self.clients.values():
                client.close()
        summary = {
            "suite": self.args.suite, "passed": failure is None, "failure": failure,
            "seconds": round(time.monotonic() - started, 2),
            "httpCalls": len(self.calls), "assertions": self.assertions,
            "journeys": self.journeys, "jobs": self.jobs, "ai": self.ai_result,
            "notRunJourneys": [name for name in self.planned_journeys if name not in {entry["name"] for entry in self.journeys}],
            "coverage": {"total": len(self.patterns), "covered": len(self.covered),
                         "missing": self.missing_endpoints(), "successful": sorted(self.covered),
                         "failedHttp": sorted({f"{call['method']} {call['endpoint']}" for call in self.calls if not call.get("passed", False)})},
            "cleanup": {"pendingRequestCount": len(self.requests), "errors": self.cleanup_errors,
                        "fixtureCleanup": "performed by runner.py finally block"},
            "execution": {"transport": "real HTTP", "database": "Compose PostgreSQL",
                          "jobs": "Compose worker", "applicationImported": False},
        }
        (self.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[{'PASS' if failure is None else 'FAIL'}] {self.args.suite}: {len(self.calls)} HTTP calls, {self.assertions} assertions, {len(self.covered)}/{len(self.patterns)} endpoints", flush=True)
        if failure:
            print(f"[FAIL] {failure}", flush=True)
        for entry in self.journeys:
            verdict = "PASS" if entry["passed"] else "FAIL"
            print(f"  [{verdict}] {entry['label']}: {entry['assertions']} assertions", flush=True)
        for name in summary["notRunJourneys"]:
            print(f"  [NOT RUN] {JOURNEY_LABELS[name]}", flush=True)
        failed_endpoints = sorted({f"{call['method']} {call['endpoint']}" for call in self.calls if not call.get("passed", False)})
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
        print(f"[FAIL] Runner initialization: {type(error).__name__} (details omitted)", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
