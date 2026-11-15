import io
import json
import asyncio
from datetime import timedelta

import pytest
from alembic import command
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from app.admin import create_account
from app.config import Settings
from app.contracts import validate_type
from app.db import ReferenceData, Resource, now
from app.main import create_app
from app.schema import alembic_config
from app.time_rules import iso


def test_event_loop():
    """A timer also wakes select in restricted runners that block socketpair writes."""
    loop = asyncio.new_event_loop()
    def tick():
        loop.call_later(0.01, tick)
    loop.call_soon(tick)
    return loop


class APIClient(TestClient):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("backend_options", {"loop_factory": test_event_loop})
        super().__init__(*args, **kwargs)


@pytest.fixture
def environment(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db", storage_dir=tmp_path / "media",
                        log_dir=tmp_path / "logs", public_origin="http://testserver")
    engine = create_engine(settings.database_url.get_secret_value(), connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db, db.begin():
        for login, roles in (("owner", ["USER"]), ("other", ["USER"]), ("tech", ["USER", "TECHNICIAN"]), ("tech2", ["USER", "TECHNICIAN"])):
            create_account(db, settings, login, "testing-password-123", roles)
        db.add(ReferenceData(id="region-test", kind="REGION", version="TEST-ONLY", verified=True,
                            data={"city": "서울특별시", "district": "테스트구", "neighborhood": "테스트동", "representativeLocationId": "test-location"}))
        db.add(ReferenceData(id="travel-test", kind="TRAVEL", version="TEST-ONLY", verified=True,
                            data={"fromLocationId": "test-location", "toLocationId": "test-location", "minutes": 15}))
        db.add(ReferenceData(id="duration-test", kind="DURATION", version="TEST-ONLY", verified=True,
                            data={"workType": "수전 교체", "quantity": 1, "minutes": 60}))
    app = create_app(settings, factory)
    yield settings, factory, app
    engine.dispose()


@pytest.fixture
def client(environment):
    with APIClient(environment[2], raise_server_exceptions=True) as client:
        yield client


def login(client, login_id="owner", role="USER"):
    response = client.post("/v1/auth/login", json={"loginId": login_id, "password": "testing-password-123"})
    assert response.status_code == 200, response.text
    if role != "USER":
        response = client.patch("/v1/auth/role", json={"role": role})
        assert response.status_code == 200, response.text
    return response.json()["data"]


def picture(color="red"):
    value = io.BytesIO()
    Image.new("RGB", (80, 60), color).save(value, format="PNG")
    return value.getvalue()


def result(response, kind=None, status=200):
    assert response.status_code == status, response.text
    data = response.json()["data"]
    if kind:
        validate_type(data, kind, "response", output=True)
    return data


def create_request(client, key="request-key"):
    metadata = {"symptom": "싱크대 수전에서 물이 샙니다.", "photos": [{"capturedOn": None, "dateConfirmed": False, "description": "수전 사진"}],
                "region": {"city": "서울특별시", "district": "테스트구", "neighborhood": "테스트동", "regionId": "region-test"}}
    return result(client.post("/v1/requests", headers={"Idempotency-Key": f'"{key}"'},
                             data={"metadata": json.dumps(metadata)}, files=[("files", ("sink.png", picture(), "image/png"))]), "RequestDTO", 201)


def setup_item(client, root):
    item = root["workItems"][0]
    start = (now()+timedelta(days=1)).replace(hour=5, minute=0, second=0, microsecond=0)
    preference = {"mode": "FLEXIBLE", "fixedStartAt": None, "ranges": [{"startAt": iso(start-timedelta(hours=2)), "endAt": iso(start+timedelta(hours=4))}]}
    item = result(client.patch(f"/v1/work-items/{item['workItemId']}", json={"expectedRevision": item["revision"],
        "facts": {"part": "싱크대", "workType": "수전 교체", "quantity": 1, "fields": ["PLUMBING"], "visitPreference": preference}}), "WorkItemDTO")
    summary = {"text": "수전에서 누수 관찰, 원인은 현장 점검 필요", "facts": [], "unknowns": ["누수 원인"], "riskSignals": [], "limitations": [], "onsiteInspectionNeeded": True}
    item = result(client.put(f"/v1/work-items/{item['workItemId']}/confirmation", headers={"Idempotency-Key": '"confirm-item"'},
                            json={"expectedRevision": item["revision"], "sourceRevision": item["sourceRevision"], "summary": summary, "fields": ["PLUMBING"], "confirmed": True}), "WorkItemDTO")
    root = result(client.get(f"/v1/requests/{root['requestId']}"), "RequestDTO")
    root = result(client.put(f"/v1/requests/{root['requestId']}/visit-details", json={"expectedRevision": root["revision"], "visitDetails": {"address": "서울특별시 테스트구 테스트동 101호", "contact": "010-1234-5678"}, "confirmed": True}), "RequestDTO")
    return root, item, start
