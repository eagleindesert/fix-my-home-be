"""API 응답 투영. 비공개 원본과 관계별 전달본을 구분한다."""

import copy

from app.services import reference
from app.time_rules import iso


def media(file):
    return {"mediaId": file.id, "contentType": file.mime,
            "sizeBytes": file.size, "width": file.width, "height": file.height}


def photo(ctx, row):
    return {"photoId": row.id, "revision": str(row.revision), "media": media(ctx.file_for(row)),
            "capturedOn": row.data.get("capturedOn"), "suggestedCapturedOn": row.data.get("suggestedCapturedOn"),
            "dateConfirmed": row.data["dateConfirmed"], "description": row.data.get("description"),
            "workItemIds": row.data.get("workItemIds", []), "uploadedAt": iso(row.created_at), "updatedAt": iso(row.updated_at)}


def photos(ctx, root):
    rows = ctx.find("PHOTO", request_id=root.id)
    confirmed = [photo(ctx, row) for row in rows if row.data["dateConfirmed"]]
    unknown = [photo(ctx, row) for row in rows if not row.data["dateConfirmed"]]
    confirmed.sort(key=lambda row: (row["capturedOn"], row["photoId"]))
    # A slot is only restored once physical deletion has completed.
    from sqlalchemy import select, func
    from app.db import Resource
    count = ctx.db.scalar(select(func.count()).select_from(Resource).where(Resource.kind == "PHOTO", Resource.request_id == root.id))
    return {"confirmedDatePhotos": confirmed, "unknownDatePhotos": unknown,
            "storedCount": count, "remainingCount": max(0, 30-count)}


def work_item(ctx, row):
    root = ctx.get(row.request_id, "REQUEST")
    result = {"workItemId": row.id, "requestId": root.id, "revision": str(row.revision),
              "status": row.status, "support": reference.support(ctx, root.data.get("region"), row.data["facts"])}
    for key in ("itemVersion", "sourceRevision", "facts", "summary", "reviewStatus", "aiUseStatus",
                "resolutionPath", "activeReservationId", "routeExplorationEnabled"):
        result[key] = copy.deepcopy(row.data[key])
    return result


def record(ctx, row):
    return {"recordId": row.id, "revision": str(row.revision), "record": copy.deepcopy(row.data["record"]),
            "outcome": copy.deepcopy(row.data.get("outcome")), "sourceType": "USER_STATEMENT", "updatedAt": iso(row.updated_at)}


def request_view(ctx, root):
    return {"requestId": root.id, "revision": str(root.revision), "commonVersion": root.data["commonVersion"],
            "sourceRevision": root.data["sourceRevision"], "status": root.status,
            "symptom": root.data["symptom"], "urgent": root.data["urgent"],
            "emergencyGuidance": reference.guidance(ctx) if root.data["urgent"] else None,
            "context": copy.deepcopy(root.data["context"]), "region": root.data.get("region"),
            "support": reference.support(ctx, root.data.get("region")),
            "visitDetails": root.data.get("visitDetails"), "visitDetailsRevision": root.data.get("visitDetailsRevision"),
            "photos": photos(ctx, root), "workItems": [work_item(ctx, row) for row in ctx.find("WORK_ITEM", request_id=root.id)],
            "dialogue": dialogue(ctx, root), "history": [
                {"workItemId": row.item_id, "resourceType": row.kind, "resourceId": row.id,
                 "occurredAt": iso(row.created_at), "description": "사용자 진술" if row.kind == "RECORD" else row.kind}
                for row in ctx.find(request_id=root.id) if row.kind in ("RECORD", "CONSULTATION", "QUOTE", "RESERVATION", "RESERVATION_CHANGE")],
            "closures": root.data.get("closures", []), "updatedAt": iso(root.updated_at)}


def request_list(ctx, root):
    return {"requestId": root.id, "symptom": root.data["symptom"], "status": root.status,
            "workItems": [work_item(ctx, r) for r in ctx.find("WORK_ITEM", request_id=root.id)], "updatedAt": iso(root.updated_at)}


def dialogue(ctx, root):
    return {"revision": root.data["dialogueRevision"], "completedRounds": sum(
        q.get("answer") is not None or q.get("skipped", False) for q in root.data["questions"]),
        "finished": root.data["dialogueFinished"], "questions": [{k: v for k, v in q.items() if k != "submittedAnswer"} for q in copy.deepcopy(root.data["questions"])],
        "emergencyGuidance": reference.guidance(ctx) if root.data["urgent"] else None}


def public_technician(ctx, row):
    profile = row.data["profile"]
    contacts = [copy.deepcopy(c["contact"]) for c in profile["contacts"] if c["isPublic"]]
    return {"technicianId": row.id, "displayName": profile["displayName"], "fields": profile["fields"],
            "regions": [{**r.data, "regionId": r.id, "version": r.version} for r in ctx.references("REGION") if r.id in profile["regionIds"]],
            "contacts": contacts, "directContactAvailable": bool(contacts), "visitAvailability": "UNKNOWN"}


def case(ctx, row):
    def files(ids):
        from app.db import StoredFile
        return [media(ctx.db.get(StoredFile, value)) for value in ids if ctx.db.get(StoredFile, value)]
    return {"caseId": row.id, "technicianId": row.technician_id, "revision": str(row.revision),
            "content": copy.deepcopy(row.data["case"]), "beforePhotos": files(row.data["case"]["beforeMediaIds"]),
            "afterPhotos": files(row.data["case"]["afterMediaIds"])}


def portfolio(ctx, tech):
    assets = [media(ctx.file_for(r)) for r in ctx.find("PORTFOLIO_PHOTO", technician_id=tech.id)]
    return {"technicianId": tech.id, "photos": assets,
            "representativePhotos": [a for a in assets if a["mediaId"] in tech.data["profile"]["representativeMediaIds"]],
            "cases": [case(ctx, r) for r in ctx.find("CASE", technician_id=tech.id)]}


def technician(ctx, tech):
    return {"technicianId": tech.id, "profileRevision": str(tech.revision),
            "profile": copy.deepcopy(tech.data["profile"]), "portfolio": portfolio(ctx, tech)}


def timeline(ctx, root):
    return {"sourceRevision": root.data["sourceRevision"], "photos": photos(ctx, root),
            "records": [record(ctx, r) for r in ctx.find("RECORD", request_id=root.id)],
            "groups": [copy.deepcopy(r.data) | {"groupId": r.id, "sourceRevision": root.data["sourceRevision"]}
                       for r in ctx.find("PHOTO_GROUP", request_id=root.id)], "retakeGuide": reference.RETAKE_GUIDE}
