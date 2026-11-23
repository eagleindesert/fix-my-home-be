"""원본과 독립된 전달본 생성, 공개 범위 확인 및 관계 기반 열람."""

import copy
import re

from app.db import now
from app.errors import require
from app.media import mask_image
from app.services import reference, requests, views
from app.services.context import ACTIVE_RESERVATIONS
from app.time_rules import iso

PATHS = {
    "PHOTO": r"(?:observation|regions\.\d+\.description)",
    "RECORD": r"(?:record\.description|outcome\.(?:action|description))",
    "QUESTION": r"(?:text|answer|options\.\d+\.label)",
    "SUMMARY": r"(?:text|facts\.\d+\.text|unknowns\.\d+|riskSignals\.\d+|limitations\.\d+)",
    "REPORT": r"(?:content\.markdown|content\.facts\.\d+\.text|content\.unknowns\.\d+|photos\.\d+\.(?:observation|regions\.\d+\.description))",
    "QUOTE_CONTEXT": r"facts\.(?:part|workType|otherField|product\.(?:productType|manufacturer|modelName))",
}


def report_resource(ctx, item):
    rows = ctx.find("REPORT", item_id=item.id)
    return rows[0] if rows else None


def report_view(ctx, item):
    row = report_resource(ctx, item)
    if not row:
        require(False, "RESOURCE_NOT_FOUND", "작성한 보고서가 없습니다.", 404)
    return {"revision": str(row.revision), "sourceRevision": row.data["sourceRevision"],
            "reviewStatus": row.data["reviewStatus"], "draft": row.data.get("draft"),
            "current": row.data.get("current"), "confirmedAt": row.data.get("confirmedAt")}


def latest_regions_for_photo(ctx, row):
    from app.services.ai import latest_comparisons
    root = ctx.get(row.request_id, "REQUEST")
    regions = []
    for comparison in latest_comparisons(ctx, root):
        if comparison.get("status") != "CHANGED":
            continue
        for region in comparison.get("regions", []):
            if region.get("photoId") == row.id:
                regions.append(copy.deepcopy(region))
    return regions


def photo_evidence(ctx, row):
    return {"photoId": row.id, "media": views.media(ctx.file_for(row)),
            "capturedOn": row.data["capturedOn"], "observation": row.data.get("description") or "관찰 설명 미입력",
            "regions": latest_regions_for_photo(ctx, row)}


def edit_report(ctx, item, body):
    ctx.check_source(item, body["sourceRevision"])
    row = report_resource(ctx, item)
    require(body["expectedRevision"] == (str(row.revision) if row else None), "VERSION_CONFLICT", "보고서가 변경되었습니다.")
    photos = ctx.validate_references(body["report"]["photoIds"], "PHOTO", item.request_id, item.id)
    requests.validate_facts_references(ctx, item, body["report"]["facts"])
    values = {"draft": {"content": body["report"], "photos": [photo_evidence(ctx, p) for p in photos],
                        "createdAt": iso(now())}, "sourceRevision": body["sourceRevision"],
              "reviewStatus": "DRAFT", "confirmedAt": None, "current": None}
    if row:
        ctx.save(row, **values)
    else:
        ctx.create("REPORT", values, request_id=item.request_id, item_id=item.id)
    stale_deliveries(ctx, item)
    return report_view(ctx, item)


def confirm_report(ctx, item, body):
    row = report_resource(ctx, item)
    require(row, "RESOURCE_NOT_FOUND", "작성한 보고서가 없습니다.", 404)
    ctx.check_revision(row, body["expectedRevision"])
    ctx.check_source(item, body["sourceRevision"])
    require(body["confirmed"] and row.data["sourceRevision"] == body["sourceRevision"] and row.data["draft"],
            "STALE_SOURCE", "최신 자료로 작성한 초안을 확인하세요.")
    ctx.save(row, current=row.data["draft"], draft=None, reviewStatus="CONFIRMED", confirmedAt=iso(now()))
    return report_view(ctx, item)


def stale_deliveries(ctx, item):
    for row in ctx.find(item_id=item.id):
        if row.kind in ("DELIVERY", "PDF_JOB"):
            row.status = "STALE"
            ctx.save(row, reviewStatus="NEEDS_UPDATE")


def create(ctx, item, body):
    ctx.check_source(item, body["sourceRevision"])
    scope = {"recipientTechnicianId": None, "consultationId": None, "reservationId": None,
             **copy.deepcopy(body["scope"])}
    purpose = scope["purpose"]
    if purpose == "EXTERNAL_PDF":
        require(not any(scope[k] for k in ("recipientTechnicianId", "consultationId", "reservationId")) and
                scope["includeReport"] and not scope["includeQuoteContext"], "INVALID_SCOPE", "외부 PDF는 수신 관계 없는 보고서 전달본이어야 합니다.", 422)
    elif purpose == "CONSULTATION":
        require(scope["recipientTechnicianId"] and scope["includeQuoteContext"] and not scope["reservationId"],
                "INVALID_SCOPE", "상담 수신자와 견적 전제가 필요합니다.", 422)
        ctx.no_self(item, scope["recipientTechnicianId"])
        if scope["consultationId"]:
            relation = ctx.own(scope["consultationId"], "CONSULTATION")
            require(relation.item_id == item.id and relation.technician_id == scope["recipientTechnicianId"] and relation.status in ("PENDING", "ACCEPTED"),
                    "INVALID_SCOPE", "활성 상담의 수신자를 확인하세요.", 422)
    else:
        require(scope["reservationId"] and scope["includeReport"] and not scope["includeQuoteContext"], "INVALID_SCOPE", "인계할 활성 예약과 보고서가 필요합니다.", 422)
        reservation = ctx.own(scope["reservationId"], "RESERVATION")
        require(reservation.item_id == item.id and reservation.status in ACTIVE_RESERVATIONS and
                reservation.technician_id == scope["recipientTechnicianId"], "INVALID_SCOPE", "인계 수신자를 확인하세요.", 422)
        scope["consultationId"] = reservation.parent_id
    if scope["includeSummary"] or scope["includeQuoteContext"]:
        require(item.data["reviewStatus"] == "CONFIRMED", "CONFIRMATION_REQUIRED", "최신 요약을 먼저 확인하세요.")
    root = ctx.get(item.request_id, "REQUEST")
    photos = ctx.validate_references(scope["photoIds"], "PHOTO", root.id, item.id)
    records = ctx.validate_references(scope["recordIds"], "RECORD", root.id)
    questions = {q["questionId"]: q for q in root.data["questions"]}
    require(len(set(scope["questionIds"])) == len(scope["questionIds"]) and set(scope["questionIds"]) <= questions.keys(),
            "INVALID_REFERENCE", "문답 참조를 확인하세요.", 422)
    report = report_resource(ctx, item)
    if scope["includeReport"]:
        require(report and report.data["reviewStatus"] == "CONFIRMED" and report.data["sourceRevision"] == item.data["sourceRevision"],
                "CONFIRMATION_REQUIRED", "최신 보고서를 확인하세요.")
        require(set(report.data["current"]["content"]["photoIds"]) <= set(scope["photoIds"]), "INVALID_SCOPE", "보고서 사진을 공개 범위에 포함하세요.", 422)
    content = {"summary": item.data["summary"] if scope["includeSummary"] else None,
               "photos": [photo_evidence(ctx, p) for p in photos], "records": [views.record(ctx, r) for r in records],
               "dialogue": [questions[q] for q in scope["questionIds"]],
               "report": report.data["current"] if scope["includeReport"] else None, "quoteContext": None}
    if scope["includeQuoteContext"]:
        reference.require_supported(ctx, root, item)
        require(item.data["facts"].get("visitPreference"), "INVALID_SCOPE", "견적 전제에 방문 조건이 필요합니다.", 422)
        content["quoteContext"] = {"deliveryId": "pending", "commonVersion": root.data["commonVersion"],
            "itemVersion": item.data["itemVersion"], "sourceRevision": item.data["sourceRevision"],
            "region": reference.region(ctx, root.data["region"]), "facts": copy.deepcopy(item.data["facts"]),
            "durationEstimate": reference.duration(ctx, item)}
    if body.get("replacesDeliveryId"):
        previous = ctx.own(body["replacesDeliveryId"], "DELIVERY")
        require(previous.item_id == item.id and previous.data["scope"]["purpose"] == purpose, "INVALID_SCOPE", "같은 항목·목적의 전달본만 교체합니다.", 422)
        previous.status = "STALE"
        ctx.save(previous, reviewStatus="NEEDS_UPDATE")
        for pdf in ctx.find("PDF_JOB", parent_id=previous.id):
            pdf.status = "STALE"
            ctx.save(pdf)
    row = ctx.create("DELIVERY", {"sourceRevision": body["sourceRevision"], "scope": scope,
                     "redactions": body["redactions"], "reviewStatus": "DRAFT", "content": None,
                     "metadataRemoved": False, "confirmedAt": None, "error": None},
                     request_id=root.id, item_id=item.id, technician_id=scope["recipientTechnicianId"], status="QUEUED")
    if content["quoteContext"]:
        content["quoteContext"]["deliveryId"] = row.id
    payload = {"content": copy.deepcopy(content), "redactions": body["redactions"], "itemId": item.id,
               "reportId": report.id if report else None}
    redact(copy.deepcopy(content), payload, validate_only=True)
    ctx.enqueue(row, "DELIVERY", payload)
    return row


def redact(content, payload, validate_only=False):
    targets = {("PHOTO", p["photoId"]): p for p in content["photos"]}
    targets.update({("RECORD", r["recordId"]): r for r in content["records"]})
    targets.update({("QUESTION", q["questionId"]): q for q in content["dialogue"]})
    targets[("SUMMARY", payload["itemId"])] = content["summary"]
    targets[("REPORT", payload["itemId"])] = content["report"]
    targets[("QUOTE_CONTEXT", payload["itemId"])] = content["quoteContext"]
    seen, excluded, masks = set(), set(), {}
    for r in sorted(payload["redactions"], key=lambda r: r["targetType"] == "REPORT"):
        identity = r["targetType"], r["resourceId"]
        target = targets.get(identity)
        require(target is not None, "INVALID_REFERENCE", "가릴 자료가 공개 범위에 없습니다.", 422)
        path = r.get("fieldPath")
        key = (*identity, path)
        require(key not in seen and identity not in excluded, "INVALID_REDACTION", "가림 지시가 중복되거나 충돌합니다.", 422)
        seen.add(key)
        if r["exclude"] and not path:
            require(identity[0] in ("PHOTO", "RECORD", "QUESTION") and not r["boxes"] and not r.get("replacementText"),
                    "INVALID_REDACTION", "필수 요약·보고서·견적 전제는 제외할 수 없습니다.", 422)
            excluded.add(identity)
        if r["boxes"]:
            require(identity[0] == "PHOTO" and not path, "INVALID_REDACTION", "영역 가림은 사진 전체 대상으로 지정하세요.", 422)
            masks[identity[1]] = r["boxes"]
        if path:
            require(re.fullmatch(PATHS[identity[0]], path) and (r.get("replacementText") is not None or r["exclude"]) and not r["boxes"] and not r.get("safeFilename"),
                    "INVALID_REDACTION", "허용된 텍스트 경로와 교체 문구가 필요합니다.", 422)
            parts, node = path.split("."), target
            try:
                for part in parts[:-1]:
                    node = node[int(part)] if isinstance(node, list) else node[part]
                last = int(parts[-1]) if isinstance(node, list) else parts[-1]
                require(isinstance(node[last], (str, type(None))), "INVALID_REDACTION", "텍스트 필드만 교체할 수 있습니다.", 422)
                if r["exclude"]:
                    nullable = (identity[0] == "QUESTION" and path == "answer") or (identity[0] == "QUOTE_CONTEXT" and path.startswith("facts."))
                    require(nullable and r.get("replacementText") is None, "INVALID_REDACTION", "nullable 텍스트만 null로 제외할 수 있습니다.", 422)
                node[last] = None if r["exclude"] else r["replacementText"]
                if identity[0] == "PHOTO" and content["report"]:
                    for copy_photo in content["report"]["photos"]:
                        if copy_photo["photoId"] == identity[1]:
                            copy_photo[parts[0]] = copy.deepcopy(target[parts[0]])
            except (KeyError, IndexError, TypeError, ValueError):
                require(False, "INVALID_REDACTION", "존재하지 않는 텍스트 경로입니다.", 422)
        require(not r.get("replacementText") or path, "INVALID_REDACTION", "교체 문구의 필드 경로가 필요합니다.", 422)
    content["photos"] = [p for p in content["photos"] if ("PHOTO", p["photoId"]) not in excluded]
    content["records"] = [r for r in content["records"] if ("RECORD", r["recordId"]) not in excluded]
    content["dialogue"] = [q for q in content["dialogue"] if ("QUESTION", q["questionId"]) not in excluded]
    photo_ids = {p["photoId"] for p in content["photos"]}
    record_ids = {r["recordId"] for r in content["records"]}
    # Excluded sources cannot remain as dangling references in the published document.
    for summary in (content["summary"], content["report"]["content"] if content["report"] else None):
        if summary:
            summary["facts"] = [fact for fact in summary["facts"] if
                                not any(("PHOTO", p) in excluded for p in fact["photoIds"]) and
                                not any(("RECORD", r) in excluded for r in fact["recordIds"])]
            for fact in summary["facts"]:
                fact["photoIds"] = [p for p in fact["photoIds"] if p in photo_ids]
                fact["recordIds"] = [r for r in fact["recordIds"] if r in record_ids]
    if content["report"]:
        content["report"]["photos"] = [p for p in content["report"]["photos"] if p["photoId"] in photo_ids]
        content["report"]["content"]["photoIds"] = [p for p in content["report"]["content"]["photoIds"] if p in photo_ids]
    return content, masks


def render(ctx, row, payload):
    content, masks = redact(copy.deepcopy(payload["content"]), payload)
    if row.data["scope"]["purpose"] == "EXTERNAL_PDF":
        content = scrub_visit_details(ctx, row, content)
    for photo in content["photos"]:
        original = ctx.get(photo["photoId"], "PHOTO")
        file = ctx.file_for(original)
        data, width, height = mask_image(ctx.files.read(file.key), masks.get(original.id, []))
        output = ctx.store_file(row, data, "image/png", width, height)
        photo["media"] = views.media(output)
    if content["report"]:
        lookup = {p["photoId"]: p["media"] for p in content["photos"]}
        for photo in content["report"]["photos"]:
            photo["media"] = lookup[photo["photoId"]]
    row.status = "READY"
    ctx.save(row, content=content, metadataRemoved=True, error=None)


def current(ctx, row):
    item = ctx.get(row.item_id, "WORK_ITEM")
    source = row.data.get("endedSourceRevision") or row.data["sourceRevision"]
    return row.status == "READY" and row.data["reviewStatus"] == "CONFIRMED" and source == item.data["sourceRevision"]


def can_read_delivery(ctx, row):
    if ctx.actor.role == "USER":
        return row.owner_id == ctx.actor.account_id
    if ctx.actor.technician_id != row.technician_id or not current(ctx, row):
        return False
    scope = row.data["scope"]
    if scope["purpose"] == "HANDOVER":
        reservation = ctx.get(scope["reservationId"], "RESERVATION")
        return reservation.status in ACTIVE_RESERVATIONS or bool(row.data.get("endedContent"))
    if scope["purpose"] == "CONSULTATION" and scope["consultationId"]:
        return ctx.get(scope["consultationId"], "CONSULTATION").status in ("PENDING", "ACCEPTED")
    return False


def usable_delivery(ctx, delivery_id, item, purpose, technician_id=None):
    row = ctx.get(delivery_id, "DELIVERY")
    require(row.item_id == item.id and row.data["scope"]["purpose"] == purpose and
            row.data["scope"]["recipientTechnicianId"] == technician_id, "INVALID_SCOPE", "전달본의 대상·목적을 확인하세요.", 422)
    require(current(ctx, row), "CONFIRMATION_REQUIRED", "최신 전달본 처리 결과를 확인하세요.")
    return row


def confirm(ctx, row, body):
    ctx.check_revision(row, body["expectedRevision"])
    ctx.check_source(ctx.get(row.item_id), body["sourceRevision"])
    require(row.status == "READY" and row.data["metadataRemoved"] and body["confirmed"] and
            row.data["sourceRevision"] == body["sourceRevision"], "CONFIRMATION_REQUIRED", "최신 처리 결과만 확인할 수 있습니다.")
    ctx.save(row, reviewStatus="CONFIRMED", confirmedAt=iso(now()))
    return row


def view(ctx, row):
    require(can_read_delivery(ctx, row), "ACCESS_DENIED", "해당 전달본을 열람할 수 없습니다.", 403)
    owner = ctx.actor.role == "USER"
    content = row.data["content"] if row.status == "READY" else None
    if not owner and row.data.get("endedContent"):
        content = row.data["endedContent"]
    return {"deliveryId": row.id, "workItemId": row.item_id, "createdAt": iso(row.created_at),
            "revision": str(row.revision), "sourceRevision": row.data["sourceRevision"], "scope": row.data["scope"],
            "redactions": row.data["redactions"] if owner else None,
            "redactionsUnavailableReason": None if owner else "가림 지시는 요청 소유자만 조회할 수 있습니다.",
            "status": row.status, "reviewStatus": row.data["reviewStatus"], "content": content,
            "metadataRemoved": row.data["metadataRemoved"], "confirmedAt": row.data["confirmedAt"], "error": row.data["error"]}


def end_relationship(ctx, reservation):
    # Freeze only a previously processed, explicitly confirmed handover. Images
    # retain the owner's irreversible masks; no original file is ever copied.
    frozen = []
    for row in ctx.find("DELIVERY", item_id=reservation.item_id):
        if row.data["scope"].get("reservationId") != reservation.id:
            continue
        if reservation.status in ("COMPLETED", "STOPPED") and current(ctx, row):
            snapshot = scrub_visit_details(ctx, reservation, copy.deepcopy(row.data["content"]))
            snapshot["quoteContext"] = None
            ctx.save(row, endedContent=snapshot)
            frozen.append(row.id)
    return frozen


def scrub_visit_details(ctx, reservation, value):
    private = []
    root = reservation if reservation.kind == "REQUEST" else ctx.get(reservation.request_id, "REQUEST")
    details = [root.data.get("visitDetails"), reservation.data.get("agreement", {}).get("terms", {}).get("visitDetails")]
    details += [a["terms"].get("visitDetails") for a in reservation.data.get("agreementHistory", [])]
    for detail in details:
        if detail:
            private.extend(v for v in detail.values() if isinstance(v, str) and v)
    def clean(node):
        if isinstance(node, str):
            for text in sorted(set(private), key=len, reverse=True):
                node = node.replace(text, "[비공개 방문 정보]")
            return re.sub(r"(?<!\d)(?:\+82[- ]?)?0?1[016789][- .]?\d{3,4}[- .]?\d{4}(?!\d)", "[비공개 연락처]", node)
        if isinstance(node, list):
            return [clean(v) for v in node]
        if isinstance(node, dict):
            return {k: None if k == "visitDetails" else clean(v) for k, v in node.items()}
        return node
    return clean(value)


def create_pdf(ctx, row, body):
    ctx.check_revision(row, body["deliveryRevision"])
    require(current(ctx, row) and row.data["scope"]["purpose"] == "EXTERNAL_PDF", "CONFIRMATION_REQUIRED", "확인된 외부 PDF 전달본이 필요합니다.")
    job = ctx.create("PDF_JOB", {"deliveryRevision": str(row.revision), "completedAt": None, "error": None},
                     parent_id=row.id, request_id=row.request_id, item_id=row.item_id, status="QUEUED")
    ctx.enqueue(job, "PDF", {"deliveryId": row.id, "deliveryRevision": str(row.revision)})
    return job


def pdf_view(ctx, row):
    delivery = ctx.get(row.parent_id, "DELIVERY")
    available = row.status == "READY" and current(ctx, delivery) and str(delivery.revision) == row.data["deliveryRevision"]
    return {"jobId": row.id, "deliveryId": row.parent_id, "deliveryRevision": row.data["deliveryRevision"],
            "status": row.status if available or row.status != "READY" else "STALE", "createdAt": iso(row.created_at),
            "completedAt": row.data["completedAt"], "downloadAvailable": available, "error": row.data["error"]}
