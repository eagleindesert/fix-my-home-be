import json
from datetime import timedelta

from sqlalchemy import select

from app.contract_data import ENDPOINTS
from app.db import Account, Job, Resource, now
from app.services.context import Context
from app.security import Actor
from app.time_rules import iso
from app.worker import run_once
from conftest import APIClient as TestClient, create_request, login, picture, result, setup_item


def test_contract_routes_and_health(client):
    schema = client.get("/openapi.json").json()
    assert sum(len([m for m in p if m in ("get", "post", "put", "patch", "delete")]) for p in schema["paths"].values()) == 79
    for endpoint in ENDPOINTS:
        assert endpoint["method"].lower() in schema["paths"]["/v1"+endpoint["path"]]
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    result(client.get("/v1/public/service-info"), "ServiceInfoDTO")


def test_session_role_origin_and_private_media(client, environment):
    assert client.get("/v1/requests").status_code == 401
    login(client)
    root = create_request(client)
    media_id = root["photos"]["unknownDatePhotos"][0]["media"]["mediaId"]
    assert client.get(f"/v1/media/{media_id}").status_code == 200
    with TestClient(environment[2]) as other:
        login(other, "other")
        assert other.get(f"/v1/requests/{root['requestId']}").status_code == 403
        assert other.get(f"/v1/media/{media_id}").status_code == 403
    assert client.patch("/v1/auth/role", json={"role": "TECHNICIAN"}).status_code == 403
    assert client.post("/v1/auth/logout", headers={"Origin": "https://hostile.example"}).status_code == 403
    assert client.post("/v1/auth/logout").status_code == 204
    assert client.get("/v1/auth/me").status_code == 401


def test_multipart_atomic_replay_and_json_duplicates(client):
    login(client)
    root = create_request(client)
    again = create_request(client)
    assert root["requestId"] == again["requestId"]
    assert len(result(client.get("/v1/requests"), "PageDTO<RequestListItemDTO>")["items"]) == 1
    bad = client.post("/v1/requests", headers={"Idempotency-Key": '"bad-batch"'},
                      data={"metadata": json.dumps({"symptom": "불량 사진", "photos": [{"dateConfirmed": False}, {"dateConfirmed": False}]})},
                      files=[("files", ("ok.png", picture(), "image/png")), ("files", ("bad.png", b"not an image", "image/png"))])
    assert bad.status_code == 422
    assert len(result(client.get("/v1/requests"))["items"]) == 1
    duplicate = client.post("/v1/auth/login", content='{"loginId":"owner","loginId":"other","password":"x"}', headers={"Content-Type": "application/json"})
    assert duplicate.status_code == 400
    conflict = client.post("/v1/requests", headers={"Idempotency-Key": '"request-key"'},
                           data={"metadata": json.dumps({"symptom": "변경", "photos": [{"dateConfirmed": False}]})},
                           files=[("files", ("sink.png", picture(), "image/png"))])
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def prepare_technician(client, factory, settings, start, login_id="tech"):
    session = login(client, login_id, "TECHNICIAN")
    tech = result(client.get("/v1/technicians/me"), "TechnicianDTO")
    result(client.put("/v1/technicians/me/profile", json={"expectedRevision": tech["profileRevision"],
        "profile": {"displayName": "검증 기사", "fields": ["PLUMBING"], "regionIds": ["region-test"],
                    "contacts": [{"contact": {"label": "전화", "value": "010-0000-0000"}, "isPublic": True}], "representativeMediaIds": []}}), "TechnicianDTO")
    with factory() as db, db.begin():
        ctx = Context(db, Actor(session["accountId"], "TECHNICIAN", tech["technicianId"], None), settings)
        ctx.create("SCHEDULE", {"availability": [{"startAt": iso(start-timedelta(hours=3)), "endAt": iso(start+timedelta(hours=5))}],
                   "externalVisits": [], "departureLocationId": "test-location", "returnLocationId": "test-location"}, technician_id=tech["technicianId"])
    return tech


def consultation_and_quote(owner, technician, environment, root, item, start, tech):
    settings, factory, _ = environment
    delivery = result(owner.post(f"/v1/work-items/{item['workItemId']}/deliveries", headers={"Idempotency-Key": '"delivery"'}, json={
        "sourceRevision": item["sourceRevision"], "scope": {"purpose": "CONSULTATION", "recipientTechnicianId": tech["technicianId"],
            "photoIds": [root["photos"]["unknownDatePhotos"][0]["photoId"]], "recordIds": [], "questionIds": [],
            "includeSummary": True, "includeReport": False, "includeQuoteContext": True}, "redactions": []}), "DeliveryDTO", 202)
    assert run_once(factory, settings)
    delivery = result(owner.get(f"/v1/deliveries/{delivery['deliveryId']}"), "DeliveryDTO")
    assert delivery["status"] == "READY", delivery
    delivery = result(owner.put(f"/v1/deliveries/{delivery['deliveryId']}/confirmation", headers={"Idempotency-Key": '"delivery-confirm"'}, json={
        "expectedRevision": delivery["revision"], "sourceRevision": item["sourceRevision"], "confirmed": True}), "DeliveryDTO")
    relation = result(owner.post(f"/v1/work-items/{item['workItemId']}/consultations", headers={"Idempotency-Key": '"consult"'}, json={
        "technicianId": tech["technicianId"], "deliveryId": delivery["deliveryId"]}), "ConsultationDTO", 201)
    relation = result(technician.patch(f"/v1/consultations/{relation['consultationId']}", headers={"Idempotency-Key": '"accept"'}, json={
        "expectedRevision": relation["revision"], "action": "ACCEPT"}), "ConsultationDTO")
    root = result(owner.get(f"/v1/requests/{root['requestId']}"), "RequestDTO")
    terms = {"versions": {"commonVersion": root["commonVersion"], "itemVersion": item["itemVersion"], "proposalVersion": None},
             "fields": ["PLUMBING"], "scope": "수전 교체", "quantity": 1, "durationMinutes": 60,
             "startAt": iso(start), "expiresAt": iso(start-timedelta(minutes=30)),
             "cost": {"minimumVisitFee": 0, "minimumDiagnosticFee": 0, "lines": [
                 {"category": "LABOR", "description": "수전 교체", "confirmed": True, "beforeAmount": 100000, "afterAmount": 90000, "condition": None}],
                      "discountCondition": "합의 시간 방문 할인"}}
    quote = result(technician.post(f"/v1/consultations/{relation['consultationId']}/quotes", headers={"Idempotency-Key": '"quote"'},
                                   json={"contextDeliveryId": delivery["deliveryId"], "terms": terms}), "QuoteDTO", 201)
    return root, relation, quote, delivery


def test_non_ai_consultation_quote_reservation_cancel_and_replay(client, environment):
    login(client)
    root, item, start = setup_item(client, create_request(client))
    settings, factory, app = environment
    with TestClient(app, raise_server_exceptions=True) as technician:
        tech = prepare_technician(technician, factory, settings, start)
        root, relation, quote, delivery = consultation_and_quote(client, technician, environment, root, item, start, tech)
        assert technician.get(f"/v1/requests/{root['requestId']}").status_code == 403
        check = result(client.post("/v1/reservation-checks", json={"operation": "CREATE", "quoteId": quote["quoteId"]}), "ReservationCheckDTO")
        assert check["allowed"], check
        body = {"quoteId": quote["quoteId"], "versions": quote["terms"]["versions"], "visitDetailsRevision": root["visitDetailsRevision"]}
        path = f"/v1/work-items/{item['workItemId']}/reservations"
        reservation = result(client.post(path, headers={"Idempotency-Key": '"reserve"'}, json=body), "ReservationDTO", 201)
        assert reservation["status"] == "CONFIRMED"
        assigned = result(technician.get(f"/v1/reservations/{reservation['reservationId']}"), "ReservationDTO")
        assert assigned["agreement"]["terms"]["visitDetails"]["contact"] == "010-1234-5678"
        cancelled = result(client.post(f"/v1/reservations/{reservation['reservationId']}/cancellation", headers={"Idempotency-Key": '"cancel"'},
                                      json={"agreementVersion": reservation["agreement"]["agreementVersion"]}), "ReservationDTO")
        assert cancelled["status"] == "CANCELLED"
        replayed = result(client.post(path, headers={"Idempotency-Key": '"reserve"'}, json=body), "ReservationDTO", 201)
        assert replayed["reservationId"] == reservation["reservationId"]
        assert replayed["status"] == "CANCELLED"
        ended = result(technician.get(f"/v1/reservations/{reservation['reservationId']}"), "ReservationDTO")
        assert ended["agreement"]["terms"]["visitDetails"] is None
        assert technician.get(f"/v1/deliveries/{delivery['deliveryId']}").status_code == 403


def test_deletion_blocks_immediately_and_cleans_files(client, environment):
    login(client)
    root = create_request(client)
    photo = root["photos"]["unknownDatePhotos"][0]
    job = result(client.post("/v1/deletion-jobs", headers={"Idempotency-Key": '"delete"'}, json={
        "targetType": "PHOTO", "targetId": photo["photoId"], "includeAllReferences": True}), "DeletionJobDTO", 202)
    assert client.get(f"/v1/media/{photo['media']['mediaId']}").status_code == 404
    during = result(client.get(f"/v1/requests/{root['requestId']}"), "RequestDTO")
    assert during["photos"]["remainingCount"] == 29
    assert run_once(environment[1], environment[0])
    finished = result(client.get(f"/v1/deletion-jobs/{job['jobId']}"), "DeletionJobDTO")
    assert finished["status"] == "COMPLETED", finished
    assert finished["restoredPhotoSlots"] == 1
    assert result(client.get(f"/v1/requests/{root['requestId']}"))["photos"]["remainingCount"] == 30
    assert not list(environment[0].storage_dir.iterdir())
