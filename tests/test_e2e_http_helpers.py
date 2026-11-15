"""HTTP E2E의 경로 분류·로그 도우미 단위 테스트. 실제 네트워크 검증은 아니다."""

import json
from types import SimpleNamespace

import httpx
import pytest

from scripts.e2e.scenarios import CheckFailed, JobFailed, Suite, endpoint_patterns


def test_endpoint_coverage_prefers_static_routes_over_path_parameters():
    patterns = endpoint_patterns({"paths": {
        "/v1/technicians/{technicianId}": {"get": {}},
        "/v1/technicians/me": {"get": {}, "patch": {}},
        "/health/ready": {"get": {}},
    }})
    matched = next(template for method, template, pattern in patterns
                   if method == "GET" and pattern.fullmatch("/v1/technicians/me"))
    assert matched == "/v1/technicians/me"
    assert all(template.startswith("/v1/") for _, template, _ in patterns)
    dynamic = next(pattern for _, template, pattern in patterns if "{" in template)
    assert dynamic.fullmatch("/v1/technicians/example-id")
    assert not dynamic.fullmatch("/v1/technicians/example-id/extra")


@pytest.fixture
def single_request(tmp_path):
    """한 번의 request 도우미 호출에만 응답하는 전송 대역을 만든다."""
    suite = Suite.__new__(Suite)
    suite.output = tmp_path
    suite.patterns = endpoint_patterns({"paths": {"/v1/requests/{requestId}": {"post": {}}}})
    suite.current = "request-helper-unit-test"
    suite.calls = []
    suite.covered = set()
    suite.assertions = 0
    suite.jobs = []
    suite.args = SimpleNamespace(poll_timeout=1)
    clients = []

    def configure(status, payload):
        transport = httpx.MockTransport(lambda request: httpx.Response(
            status, json=payload, headers={"Set-Cookie": "session=private-cookie"},
        ))
        client = httpx.Client(base_url="http://e2e.invalid", transport=transport)
        clients.append(client)
        suite.clients = {"user": client}
        return suite

    yield configure
    for client in clients:
        client.close()


def test_expected_error_is_logged_as_pass_without_credentials_or_original_id(single_request, capsys):
    suite = single_request(409, {"code": "CONFLICT", "message": "private-response-message"})
    result = suite.request("user", "POST", "/requests/private-resource-id", status=409,
                           code="CONFLICT", body={"password": "private-request-password"})
    assert result["code"] == "CONFLICT"
    console = capsys.readouterr().out
    assert "[HTTP PASS] POST /v1/requests/{requestId} -> 409 (expected 409)" in console
    assert "[FAIL]" not in console
    log = (suite.output / "http-calls.jsonl").read_text()
    recorded = json.loads(log)
    assert recorded["status"] == recorded["expectedStatus"] == 409
    assert not suite.covered
    for sensitive in ("private-resource-id", "private-request-password", "private-response-message",
                      "private-cookie"):
        assert sensitive not in console + log


def test_unexpected_http_failure_is_logged_before_assertion(single_request, capsys):
    suite = single_request(500, {"message": "private-database-connection-details"})
    with pytest.raises(CheckFailed, match="expected HTTP 201, got 500"):
        suite.request("user", "POST", "/requests/private-resource-id", status=201)
    console = capsys.readouterr().out
    assert "[HTTP FAIL] POST /v1/requests/{requestId} -> 500 (expected 201)" in console
    assert "private-database-connection-details" not in console
    assert not suite.covered


@pytest.mark.parametrize("error_code", ["BAD_REQUEST", "AI_INVALID_OUTPUT"])
def test_ai_job_failure_survives_cleanup_in_summary(tmp_path, monkeypatch, capsys, error_code):
    """실제 모델 호출 대신 실패 응답 한 건으로 진단 정보 보존을 검증한다."""
    suite = Suite(SimpleNamespace(
        output=tmp_path, origin=None, base_url="http://e2e.invalid",
        http_timeout=1, poll_timeout=1, suite="api",
    ), {
        "origin": "http://e2e.invalid", "photoBase64": "",
        "ai": {"expectedStatus": "SUCCEEDED", "expectedErrorCode": None},
    })
    for client in suite.clients.values():
        client.close()

    def respond(request):
        if request.method == "POST":
            return httpx.Response(202, json={"data": {"jobId": "private-job-id"}})
        return httpx.Response(200, json={"data": {
            "jobId": "private-job-id", "status": "FAILED",
            "error": {
                "code": error_code, "retryable": False,
                "message": "private-provider-response", "currentState": {"key": "private-key"},
            },
            "attempts": [{"number": 1, "errorCode": error_code}],
            "result": "private-model-output",
        }})

    suite.clients = {"user": httpx.Client(
        base_url="http://e2e.invalid", transport=httpx.MockTransport(respond),
    )}
    suite.patterns = endpoint_patterns({"paths": {
        "/v1/requests/{requestId}/ai-jobs": {"post": {}},
        "/v1/ai-jobs/{jobId}": {"get": {}},
    }})
    monkeypatch.setattr(suite, "item", lambda *args: {"sourceRevision": "revision"})

    def fail_during_ai():
        with suite.journey("record-editing-ai-choice-and-candidate-discovery"):
            suite.ai_diagnosis("private-request-id", "private-item-id")

    def cleanup():
        suite.requests.clear()

    monkeypatch.setattr(suite, "setup", fail_during_ai)
    monkeypatch.setattr(suite, "cleanup", cleanup)
    suite.requests.add("private-request-id")
    assert suite.run() is False
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert error_code in summary["failure"]
    assert summary["ai"]["expectedStatus"] == "SUCCEEDED"
    assert summary["ai"]["actualStatus"] == "FAILED"
    assert summary["ai"]["errorCode"] == error_code
    assert summary["jobs"][0]["passed"] is False
    assert summary["jobs"][0]["retryable"] is False
    assert summary["cleanup"]["pendingRequestCount"] == 0
    console = capsys.readouterr().out
    assert "[JOB FAIL]" in console
    assert error_code in console
    recorded = console + "".join(path.read_text() for path in tmp_path.iterdir())
    for value in ("private-job-id", "private-request-id", "private-item-id",
                  "private-provider-response", "private-key", "private-model-output"):
        assert value not in recorded


def test_expected_unconfigured_ai_failure_is_a_passing_job_check(single_request, capsys):
    suite = single_request(200, {"data": {
        "status": "FAILED", "error": {"code": "AI_NOT_CONFIGURED", "retryable": False},
    }})
    suite.patterns = endpoint_patterns({"paths": {"/v1/ai-jobs/{jobId}": {"get": {}}}})
    result = suite.poll("/ai-jobs/private-job-id", "FAILED")
    assert result["status"] == "FAILED"
    assert suite.jobs[0]["passed"] is True
    assert suite.jobs[0]["errorCode"] == "AI_NOT_CONFIGURED"
    console = capsys.readouterr().out
    assert "[JOB PASS]" in console
    assert "[JOB FAIL]" not in console


def test_poll_timeout_keeps_the_last_worker_state(single_request, monkeypatch, capsys):
    suite = single_request(200, {"data": {"status": "RUNNING", "error": None}})
    suite.patterns = endpoint_patterns({"paths": {"/v1/ai-jobs/{jobId}": {"get": {}}}})
    ticks = iter((0, 2))
    monkeypatch.setattr("scripts.e2e.scenarios.time.monotonic", lambda: next(ticks))
    with pytest.raises(JobFailed, match="within timeout"):
        suite.poll("/ai-jobs/private-job-id", "SUCCEEDED")
    assert suite.jobs[0]["status"] == "RUNNING"
    assert suite.jobs[0]["passed"] is False
    assert "[JOB FAIL]" in capsys.readouterr().out
