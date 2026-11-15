import io
from datetime import timedelta
from pathlib import Path

from openai import APIConnectionError
import httpx
from PIL import Image

from app.db import Job, Resource, now
from app.services.context import Context
from app.security import Actor
from app.time_rules import iso
from app.worker import claim, execute, run_once
from conftest import create_request, login, result, setup_item


def empty_result(**values):
    return {"summary": None, "fieldCandidates": [], "question": None, "guideExplanation": None,
            "caseRecommendations": None, "comparison": None, "reportDraft": None, **values}


def diagnosis(*_):
    return empty_result(summary={"text": "사진에서 누수가 의심되며 원인은 미확인입니다.", "facts": [], "unknowns": ["원인"],
                                 "riskSignals": [], "limitations": ["사진만으로 확인 불가"], "onsiteInspectionNeeded": True}, fieldCandidates=["PLUMBING"])


def create_ai(client, root, item, key="ai"):
    return result(client.post(f"/v1/requests/{root['requestId']}/ai-jobs", headers={"Idempotency-Key": f'"{key}"'},
            json={"type": "DIAGNOSIS", "sourceRevision": item["sourceRevision"], "workItemId": item["workItemId"]}), "AiJobDTO", 202)


def test_ai_explicit_success_does_not_confirm_summary(client, environment):
    login(client)
    root = create_request(client)
    item = root["workItems"][0]
    assert not run_once(environment[1], environment[0])
    job = create_ai(client, root, item)
    assert run_once(environment[1], environment[0], diagnosis)
    completed = result(client.get(f"/v1/ai-jobs/{job['jobId']}"), "AiJobDTO")
    assert completed["status"] == "SUCCEEDED", completed
    assert len(completed["attempts"]) == 1
    fresh = result(client.get(f"/v1/requests/{root['requestId']}"))["workItems"][0]
    assert fresh["reviewStatus"] != "CONFIRMED" and fresh["summary"] is None


def test_ai_retry_once_and_total_deadline(client, environment):
    login(client)
    root = create_request(client)
    job = create_ai(client, root, root["workItems"][0])
    def transient(*_):
        raise APIConnectionError(request=httpx.Request("POST", "https://invalid.example"))
    assert run_once(environment[1], environment[0], transient)
    assert run_once(environment[1], environment[0], transient)
    assert not run_once(environment[1], environment[0], transient)
    completed = result(client.get(f"/v1/ai-jobs/{job['jobId']}"), "AiJobDTO")
    assert completed["status"] == "FAILED" and len(completed["attempts"]) == 2
    root = result(client.get(f"/v1/requests/{root['requestId']}"))
    expired = create_ai(client, root, root["workItems"][0], "expired")
    with environment[1]() as db, db.begin():
        row = db.get(Resource, expired["jobId"])
        row.data = {**row.data, "deadlineAt": iso(now()-timedelta(seconds=1))}
        db.get(Job, row.id).deadline_at = now()-timedelta(seconds=1)
    def should_not_call(*_):
        raise AssertionError("Expired job must never call provider")
    run_once(environment[1], environment[0], should_not_call)
    completed = result(client.get(f"/v1/ai-jobs/{expired['jobId']}"), "AiJobDTO")
    assert completed["status"] == "TIMED_OUT" and completed["attempts"] == []


def test_source_change_during_ai_call_blocks_late_publish(client, environment):
    login(client)
    root = create_request(client)
    job = create_ai(client, root, root["workItems"][0])
    def changing_provider(*_):
        latest = result(client.get(f"/v1/requests/{root['requestId']}"))
        result(client.patch(f"/v1/requests/{root['requestId']}", json={"expectedRevision": latest["revision"], "symptom": "보완된 진술"}))
        return diagnosis()
    run_once(environment[1], environment[0], changing_provider)
    completed = result(client.get(f"/v1/ai-jobs/{job['jobId']}"), "AiJobDTO")
    assert completed["status"] == "FAILED" and completed["stale"] and completed["result"] is None


def test_masked_delivery_pdf_and_source_invalidation(client, environment):
    login(client)
    settings, factory, _ = environment
    settings.pdf_font = Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")
    root, item, _ = setup_item(client, create_request(client))
    photo = root["photos"]["unknownDatePhotos"][0]
    path = f"/v1/work-items/{item['workItemId']}/report"
    report = result(client.put(path, json={"expectedRevision": None, "sourceRevision": item["sourceRevision"],
                    "report": {"markdown": "# 누수 기록\n원인은 미확인입니다.", "photoIds": [photo["photoId"]], "facts": [], "unknowns": ["원인"]}}), "ReportDTO")
    result(client.put(path+"/confirmation", headers={"Idempotency-Key": '"report-confirm"'}, json={"expectedRevision": report["revision"], "sourceRevision": item["sourceRevision"], "confirmed": True}), "ReportDTO")
    delivery = result(client.post(f"/v1/work-items/{item['workItemId']}/deliveries", headers={"Idempotency-Key": '"pdf-delivery"'}, json={
        "sourceRevision": item["sourceRevision"], "scope": {"purpose": "EXTERNAL_PDF", "photoIds": [photo["photoId"]], "recordIds": [], "questionIds": [],
        "includeSummary": False, "includeReport": True, "includeQuoteContext": False}, "redactions": [
            {"targetType": "PHOTO", "resourceId": photo["photoId"], "exclude": False, "boxes": [[0, 0, .5, .5]]}]}), "DeliveryDTO", 202)
    run_once(factory, settings)
    delivery = result(client.get(f"/v1/deliveries/{delivery['deliveryId']}"), "DeliveryDTO")
    assert delivery["status"] == "READY", delivery
    processed = delivery["content"]["photos"][0]["media"]["mediaId"]
    with Image.open(io.BytesIO(client.get(f"/v1/media/{processed}").content)) as image:
        assert image.getpixel((10, 10)) == (0, 0, 0)
        assert not image.getexif()
    delivery = result(client.put(f"/v1/deliveries/{delivery['deliveryId']}/confirmation", headers={"Idempotency-Key": '"pdf-delivery-confirm"'},
        json={"expectedRevision": delivery["revision"], "sourceRevision": item["sourceRevision"], "confirmed": True}), "DeliveryDTO")
    pdf = result(client.post(f"/v1/deliveries/{delivery['deliveryId']}/pdf-jobs", headers={"Idempotency-Key": '"pdf"'},
                            json={"deliveryRevision": delivery["revision"]}), "PdfJobDTO", 202)
    run_once(factory, settings)
    pdf = result(client.get(f"/v1/pdf-jobs/{pdf['jobId']}"), "PdfJobDTO")
    assert pdf["status"] == "READY", pdf
    binary = client.get(f"/v1/pdf-jobs/{pdf['jobId']}/content")
    assert binary.status_code == 200 and binary.content.startswith(b"%PDF")
    latest = result(client.get(f"/v1/requests/{root['requestId']}"))
    result(client.patch(f"/v1/requests/{root['requestId']}", json={"expectedRevision": latest["revision"], "symptom": "원본 정정"}))
    assert client.get(f"/v1/pdf-jobs/{pdf['jobId']}/content").status_code == 409
    assert result(client.get(f"/v1/pdf-jobs/{pdf['jobId']}"))["downloadAvailable"] is False


def test_deleted_source_cannot_be_published_by_claimed_job(client, environment):
    login(client)
    root = create_request(client)
    ai_job = create_ai(client, root, root["workItems"][0])
    claimed = claim(environment[1], environment[0])
    deletion = result(client.post("/v1/deletion-jobs", headers={"Idempotency-Key": '"delete-root"'}, json={
        "targetType": "REQUEST", "targetId": root["requestId"], "includeAllReferences": True}), "DeletionJobDTO", 202)
    execute(environment[1], environment[0], claimed, diagnosis)
    assert client.get(f"/v1/ai-jobs/{ai_job['jobId']}").status_code == 404
    run_once(environment[1], environment[0])
    assert result(client.get(f"/v1/deletion-jobs/{deletion['jobId']}"))["status"] == "COMPLETED"
