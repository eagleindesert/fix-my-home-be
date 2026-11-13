import json

import pytest
from sqlalchemy.exc import SQLAlchemyError

from conftest import APIClient, login


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_every_http_method_and_error_has_access_log(environment, method):
    settings, _, app = environment
    with APIClient(app) as client:
        response = client.request(method, "/does-not-exist?private=not-for-logs")
    events = [json.loads(line) for line in (settings.log_dir / "api.log").read_text().splitlines()]
    event = next(event for event in reversed(events) if event["message"] == "http.request")
    assert event["method"] == method and event["statusCode"] == response.status_code
    assert set(("uri", "clientIp", "userId", "elapsedMs", "requestId")) <= event.keys()
    assert "not-for-logs" not in json.dumps(events)


def test_database_error_logs_actual_503_without_exception_parameters(environment):
    settings, _, app = environment
    def broken():
        raise SQLAlchemyError("do-not-log-this-password")
    app.add_api_route("/test-database-failure", broken, methods=["GET"])
    with APIClient(app) as client:
        assert client.get("/test-database-failure").status_code == 503
    lines = (settings.log_dir / "api.log").read_text()
    events = [json.loads(line) for line in lines.splitlines()]
    assert events[-1]["statusCode"] == 503
    assert "do-not-log-this-password" not in lines
