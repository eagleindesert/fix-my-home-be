import hashlib
import json

from app.db import ReferenceData, Resource
from conftest import create_request, login, picture, result, setup_item


def test_missing_manufacturer_is_normal_guidance_response(client):
    guide = result(client.get("/api/v1/public/guidance?type=MANUFACTURER_AS"), "GuidanceDTO")
    assert guide["guide"]["status"] == "NOT_APPLICABLE"
    assert guide["officialService"]["status"] == "INFORMATION_REQUIRED"
    assert guide["officialService"]["missingFields"] == ["manufacturer"]


def test_source_name_alone_cannot_publish_unreviewed_portfolio(client, environment):
    login(client, "tech", "TECHNICIAN")
    source = {"title": "테스트 준비 사진", "reference": "unit-test-fixture", "version": "TEST-ONLY", "usageBasis": "직접 만든 가상 이미지"}
    settings, factory, _ = environment
    with factory() as db, db.begin():
        db.add(ReferenceData(id="approved-source", kind="SOURCE", version="TEST-ONLY", verified=True,
            data={**source, "verifiedAt": "2026-11-13", "identifiersRemoved": True, "assetSha256": []}))
    def upload(key):
        return client.post("/api/v1/technicians/me/portfolio-photos", headers={"Idempotency-Key": f'"{key}"'},
                           data={"source": json.dumps(source)}, files=[("files", ("fixture.png", picture(), "image/png"))])
    rejected = upload("unreviewed")
    assert rejected.status_code == 422 and rejected.json()["code"] == "SOURCE_NOT_VERIFIED"
    with factory() as db, db.begin():
        row = db.get(ReferenceData, "approved-source")
        row.data = {**row.data, "assetSha256": [hashlib.sha256(picture()).hexdigest()]}
    accepted = result(upload("approved"), "MediaDTO[]", 201)
    assert len(accepted) == 1


def test_same_account_cannot_consult_with_own_technician_resource(client):
    session = login(client, "tech", "USER")
    root, item, _ = setup_item(client, create_request(client))
    response = client.post(f"/api/v1/work-items/{item['workItemId']}/consultations", headers={"Idempotency-Key": '"self"'},
                           json={"technicianId": session["technicianId"], "deliveryId": "not-needed"})
    assert response.status_code == 403 and response.json()["code"] == "SELF_PARTICIPATION_FORBIDDEN"
