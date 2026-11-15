from datetime import timedelta

from app.services import reservations, scheduling
from app.time_rules import iso
from conftest import APIClient, create_request, login, result, setup_item
from test_api import consultation_and_quote, prepare_technician


def reserve(owner, technician, environment):
    login(owner)
    root, item, start = setup_item(owner, create_request(owner))
    settings, factory, _ = environment
    tech = prepare_technician(technician, factory, settings, start)
    root, relation, quote, _ = consultation_and_quote(owner, technician, environment, root, item, start, tech)
    reservation = result(owner.post(f"/v1/work-items/{item['workItemId']}/reservations", headers={"Idempotency-Key": '"reserve"'},
        json={"quoteId": quote["quoteId"], "versions": quote["terms"]["versions"], "visitDetailsRevision": root["visitDetailsRevision"]}), "ReservationDTO", 201)
    return root, item, reservation, start


def test_change_requires_both_and_invalidates_old_agreement(client, environment):
    with APIClient(environment[2]) as tech:
        root, item, reservation, start = reserve(client, tech, environment)
        rejected = client.post("/v1/deletion-jobs", headers={"Idempotency-Key": '"cannot-delete-active"'},
                               json={"targetType": "REQUEST", "targetId": root["requestId"], "includeAllReferences": True})
        assert rejected.status_code == 409
        rejected_id = rejected.json()["currentState"]["resourceId"]
        rejected_job = result(client.get(f"/v1/deletion-jobs/{rejected_id}"), "DeletionJobDTO")
        assert rejected_job["status"] == "REJECTED" and not rejected_job["accessBlocked"]
        terms = reservation["agreement"]["terms"]
        change = result(client.post(f"/v1/reservations/{reservation['reservationId']}/changes", headers={"Idempotency-Key": '"change"'}, json={
            "type": "BEFORE_START", "agreementVersion": reservation["agreement"]["agreementVersion"], "terms": {
                "fields": terms["fields"], "scope": "수전과 연결부 점검", "quantity": 1, "cost": terms["cost"],
                "startAt": iso(start+timedelta(minutes=15)), "expectedEndAt": iso(start+timedelta(minutes=75)),
                "visitPreference": terms["visitPreference"]}}), "ReservationChangeDTO", 201)
        assert change["userAccepted"] and not change["technicianAccepted"]
        assert result(client.get(f"/v1/reservations/{reservation['reservationId']}"))["agreement"]["terms"]["startAt"] == terms["startAt"]
        accepted = result(tech.patch(f"/v1/reservation-changes/{change['changeId']}", headers={"Idempotency-Key": '"change-accept"'},
                                    json={"expectedRevision": change["revision"], "action": "ACCEPT"}), "ReservationChangeDTO")
        assert accepted["status"] == "APPLIED"
        current = result(client.get(f"/v1/reservations/{reservation['reservationId']}"), "ReservationDTO")
        assert len(current["agreementHistory"]) == 2
        assert current["agreement"]["agreementVersion"] != reservation["agreement"]["agreementVersion"]
        stale = client.post(f"/v1/reservations/{reservation['reservationId']}/cancellation", headers={"Idempotency-Key": '"stale-cancel"'},
                            json={"agreementVersion": reservation["agreement"]["agreementVersion"]})
        assert stale.status_code == 409 and stale.json()["code"] == "VERSION_CONFLICT"


def test_early_start_stop_request_and_location_correction(client, environment, monkeypatch):
    with APIClient(environment[2]) as tech:
        root, item, reservation, start = reserve(client, tech, environment)
        actual = start-timedelta(minutes=15)+timedelta(seconds=7)
        monkeypatch.setattr(reservations, "now", lambda: actual)
        monkeypatch.setattr(scheduling, "now", lambda: actual)
        path = f"/v1/reservations/{reservation['reservationId']}"
        version = reservation["agreement"]["agreementVersion"]
        denied = tech.post(path+"/work-events", headers={"Idempotency-Key": '"start-denied"'}, json={"event": "START", "agreementVersion": version})
        assert denied.status_code == 409 and denied.json()["code"] == "EARLY_START_CONSENT_REQUIRED"
        consent = result(client.put(path+"/early-start-consent", json={"agreementVersion": version, "expectedConsentRevision": None,
            "action": "GRANT", "proposedStartAt": iso(start-timedelta(minutes=15))}), "ReservationDTO")
        started = result(tech.post(path+"/work-events", headers={"Idempotency-Key": '"start"'}, json={"event": "START", "agreementVersion": version}), "ReservationDTO")
        assert started["actualStartedAt"] == iso(actual)
        assert started["currentExpectedEndAt"] == reservation["currentExpectedEndAt"]
        stopped_request = result(client.post(path+"/work-events", headers={"Idempotency-Key": '"request-stop"'},
            json={"event": "REQUEST_STOP", "agreementVersion": version, "reason": "작업 중단 요청"}), "ReservationDTO")
        assert stopped_request["status"] == "STOP_REQUESTED"
        performance = {"confirmedCause": None, "performed": ["점검"], "notPerformed": ["교체"], "unknowns": ["원인"], "parts": [], "endLocationId": None}
        complete = tech.post(path+"/work-events", headers={"Idempotency-Key": '"cannot-complete"'}, json={"event": "COMPLETE", "agreementVersion": version, "performance": performance})
        assert complete.status_code == 409
        ended = result(tech.post(path+"/work-events", headers={"Idempotency-Key": '"stop"'}, json={"event": "STOP", "agreementVersion": version, "performance": performance}), "ReservationDTO")
        assert ended["status"] == "STOPPED" and ended["actualEndedAt"] == iso(actual)
        assert ended["agreement"]["terms"]["visitDetails"] is None
        assert ended["checks"][0]["status"] == "RECHECK_REQUIRED"
        fixed = result(tech.put(path+"/end-location", json={"expectedEndLocationRevision": ended["endLocationRevision"], "endLocationId": "test-location"}), "ReservationDTO")
        assert fixed["actualEndedAt"] == ended["actualEndedAt"] and fixed["endLocationRevision"] != ended["endLocationRevision"]
        restored = result(client.get(f"/v1/requests/{root['requestId']}"), "RequestDTO")
        assert restored["status"] == "OPEN" and restored["workItems"][0]["status"] == "EXPLORING"
