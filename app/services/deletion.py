"""논리적 접근 차단을 먼저 커밋한 뒤 파일과 모든 파생 참조를 정리한다."""

import copy

from sqlalchemy import select

from app.db import Idempotency, Job, Resource, StoredFile
from app.errors import DomainError, require
from app.time_rules import iso


def create(ctx, body):
    require(body["includeAllReferences"] is True, "VALIDATION_ERROR", "모든 파생 참조 정리를 확인하세요.", 422)
    target = ctx.own(body["targetId"], body["targetType"])
    root = target if target.kind == "REQUEST" else ctx.get(target.request_id, "REQUEST")
    if target.kind != "PHOTO" and ctx.active_relations(request_id=root.id):
        error = DomainError("ACTIVE_RELATION_EXISTS", "활성 상담·예약을 먼저 정리하세요.")
        return ctx.create("DELETION_JOB", {"targetType": target.kind, "targetId": target.id,
                          "affectedWorkItemIds": [], "affectedResourceIds": [], "accessBlocked": False,
                          "restoredPhotoSlots": 0, "error": error.body()}, status="REJECTED")
    rows = ctx.find(request_id=root.id)
    affected = [root, *rows] if target.kind == "REQUEST" else [target, *[r for r in rows if r.kind in ("AI_JOB", "REPORT", "DELIVERY", "PDF_JOB")]]
    ids = sorted({r.id for r in affected})
    files = list(ctx.db.scalars(select(StoredFile).where(StoredFile.resource_id.in_(ids))))
    for row in affected:
        row.deleting = True
    if target.kind != "REQUEST":
        ctx.invalidate_sources(root)
        for row in rows:
            if row.deleting:
                continue
            data = copy.deepcopy(row.data)
            if row.kind == "RECORD":
                data["record"]["photoIds"] = [p for p in data["record"]["photoIds"] if p != target.id]
                if data.get("outcome"):
                    data["outcome"]["photoIds"] = [p for p in data["outcome"]["photoIds"] if p != target.id]
            elif row.kind == "PHOTO_GROUP":
                data["photoIds"] = [p for p in data["photoIds"] if p != target.id]
                data.update(selectedPhotoIds=[], comparisonPhotoIds=[], chronologyKnown=False, reason="근거 사진 삭제 후 비교쌍을 다시 확인하세요.")
            elif row.kind == "WORK_ITEM" and data.get("summary"):
                data["summary"]["facts"] = [fact for fact in data["summary"]["facts"]
                                           if target.id not in [*fact["photoIds"], *fact["recordIds"]]]
                data["reviewStatus"] = "NEEDS_UPDATE"
            ctx.save(row, **data)
    # Successful replay caches must not retain deleted images, statements or PII.
    affected_ids = set(ids)
    for idem in ctx.db.scalars(select(Idempotency)):
        if affected_ids.intersection((idem.result or {}).get("resourceIds", [])):
            idem.result = {"deleted": True}
    job = ctx.create("DELETION_JOB", {"targetType": target.kind, "targetId": target.id,
                     "affectedWorkItemIds": [r.id for r in rows if r.kind == "WORK_ITEM"],
                     "affectedResourceIds": ids, "accessBlocked": True, "restoredPhotoSlots": 0, "error": None},
                     status="QUEUED")
    ctx.enqueue(job, "DELETE", {"resourceIds": ids, "fileKeys": [f.key for f in files],
                               "photoCount": sum(r.kind == "PHOTO" for r in affected)})
    return job


def retry(ctx, row):
    require(row.status == "FAILED", "INVALID_STATE", "실패한 삭제 작업만 재시도할 수 있습니다.")
    job = ctx.db.get(Job, row.id)
    require(job, "INVALID_STATE", "삭제 작업 정보가 없습니다.")
    job.state, job.lease_token, job.lease_until = "QUEUED", None, None
    row.status = "QUEUED"
    return ctx.save(row, error=None)


def finish(ctx, row, payload):
    for key in payload["fileKeys"]:
        ctx.files.delete(key)
    for resource_id in payload["resourceIds"]:
        for file in ctx.db.scalars(select(StoredFile).where(StoredFile.resource_id == resource_id)):
            ctx.db.delete(file)
        queued = ctx.db.get(Job, resource_id)
        if queued:
            ctx.db.delete(queued)
    ctx.db.flush()
    # Children first works with both PostgreSQL cascades and local SQLite tests.
    resources = [ctx.db.get(Resource, rid) for rid in payload["resourceIds"]]
    for resource in sorted([r for r in resources if r], key=lambda r: r.kind == "REQUEST"):
        ctx.db.delete(resource)
    row.status = "COMPLETED"
    ctx.save(row, restoredPhotoSlots=payload["photoCount"], error=None)


def view(row):
    return {"jobId": row.id, "status": row.status, "createdAt": iso(row.created_at), **row.data}
