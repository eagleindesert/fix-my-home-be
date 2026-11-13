import gzip
import json
import copy
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.config import Settings
from app.contracts import load_json, validate_type
from app.errors import DomainError
from app.observability import client_ip, configure_logging
from app.schema import validate_schema
from app.services.consultations import price
from app.services.reservations import covers_start_check
from app.time_rules import as_utc, fits_preference, iso, overlap, quarter


def test_half_open_intervals_and_quarters():
    start = as_utc("2026-11-13T10:00:00+09:00")
    end = start+timedelta(hours=1)
    assert not overlap((start, end), (end, end+timedelta(hours=1)))
    assert overlap((start, end), (end-timedelta(seconds=1), end+timedelta(hours=1)))
    with pytest.raises(DomainError):
        quarter("2026-11-13T10:01:00+09:00")
    with pytest.raises(DomainError):
        as_utc("2026-11-13T10:00:00")
    assert not fits_preference(start, end, {"mode": "FLEXIBLE", "fixedStartAt": None,
        "ranges": [{"startAt": iso(start), "endAt": iso(end-timedelta(minutes=15))}]})


def test_price_and_unconfirmed_amounts():
    cost = {"minimumVisitFee": 10000, "minimumDiagnosticFee": 0, "discountCondition": "조건",
            "lines": [{"category": "VISIT", "description": "출장", "confirmed": True, "beforeAmount": 10000, "afterAmount": 10000, "condition": None},
                      {"category": "LABOR", "description": "작업", "confirmed": True, "beforeAmount": 20000, "afterAmount": 15000, "condition": None},
                      {"category": "PART", "description": "현장 확인 부품", "confirmed": False, "beforeAmount": None, "afterAmount": None, "condition": "필요시 별도 합의"}]}
    assert price(cost) == {"beforeTotal": 30000, "afterTotal": 25000, "discountAmount": 5000, "discountRate": 16.7, "minimumTotal": 10000}
    cost["lines"][2]["afterAmount"] = 1000
    with pytest.raises(DomainError):
        price(cost)


def test_coordinates_and_duplicate_json():
    assert validate_type([0, 0, 1, 1], "BoundingBoxDTO", "box") == [0, 0, 1, 1]
    for box in ([0, 0, 0, 1], [-1, 0, 1, 1], [0, 0, float("nan"), 1]):
        with pytest.raises(DomainError):
            validate_type(box, "BoundingBoxDTO", "box")
    with pytest.raises(DomainError):
        load_json('{"x": 1, "x": 2}')


def test_proxy_headers_only_from_configured_proxy():
    headers = {"x-forwarded-for": "1.1.1.1, 203.0.113.8", "x-real-ip": "203.0.113.9"}
    assert client_ip("198.51.100.2", headers, "172.30.0.1") == "198.51.100.2"
    assert client_ip("172.30.0.1", headers, "172.30.0.1") == "203.0.113.8"
    assert client_ip("172.30.0.1", {"x-forwarded-for": "invalid", "x-real-ip": "203.0.113.9"}, "172.30.0.1") == "203.0.113.9"


def test_log_rotation_compresses_and_bounds_archives(tmp_path):
    settings = Settings(log_dir=tmp_path, log_max_bytes=1024, log_backups=2)
    logger = configure_logging(settings, "rotation-test")
    for index in range(60):
        logger.info("request", extra={"fields": {"method": "PATCH", "uri": "/api/v1/requests/example", "statusCode": 409,
                    "clientIp": "203.0.113.1", "userId": "user", "elapsedMs": index}})
    archives = list(tmp_path.glob("*.gz"))
    assert len(archives) == 2
    for archive in archives:
        with gzip.open(archive, "rt") as stream:
            assert all(json.loads(line)["method"] == "PATCH" for line in stream)


def test_schema_drift_is_not_auto_repaired(environment):
    with environment[1]() as db:
        validate_schema(db.connection())
        db.execute(text("ALTER TABLE accounts ADD COLUMN unexpected TEXT"))
        db.commit()
        with pytest.raises(RuntimeError, match="스키마"):
            validate_schema(db.connection())


def test_overlap_confirmation_covers_reduced_actual_interval_but_not_expansion():
    overlap = {"reservationId": "other", "workItemId": "other-item", "technicianId": "other-technician",
               "agreementVersion": "v1", "range": {"startAt": "2026-11-14T10:00:00+09:00", "endAt": "2026-11-14T11:00:00+09:00"}}
    approved = {"operation": "START_WORK", "version": "our-v1", "start": overlap["range"]["startAt"],
                "end": overlap["range"]["endAt"], "overlaps": [overlap]}
    actual = copy.deepcopy(approved)
    actual["start"] = actual["overlaps"][0]["range"]["startAt"] = "2026-11-14T10:00:07+09:00"
    assert covers_start_check(approved, actual)
    actual["overlaps"][0]["range"]["startAt"] = "2026-11-14T09:59:59+09:00"
    assert not covers_start_check(approved, actual)
    actual = copy.deepcopy(approved)
    actual["overlaps"][0]["agreementVersion"] = "changed"
    assert not covers_start_check(approved, actual)
