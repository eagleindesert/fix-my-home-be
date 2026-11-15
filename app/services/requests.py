"""요청·항목·사진·기록의 작성과 정정. 관계 상태는 자동 종료하지 않는다."""

import copy

from sqlalchemy import select, func

from app.contracts import validate_type
from app.db import Resource, uid
from app.errors import DomainError, require
from app.media import normalize_image
from app.services.context import ACTIVE_RESERVATIONS
from app.time_rules import interval, quarter

PRODUCT = {"productType": None, "manufacturer": None, "modelName": None}
SYMPTOM_CONTEXT = {"locationDescription": None, "discoveredOn": None, "conditions": None,
                   "recurring": None, "attemptedActions": []}


def new_item(ctx, root, facts=None):
    values = {"part": None, "workType": None, "quantity": None, "fields": [], "otherField": None,
              "product": copy.deepcopy(PRODUCT), "visitPreference": None}
    values.update(facts or {})
    validate_facts(values)
    return ctx.create("WORK_ITEM", {"facts": values, "itemVersion": uid(), "sourceRevision": uid(),
                      "summary": None, "reviewStatus": "DRAFT", "aiUseStatus": "NOT_SELECTED",
                      "resolutionPath": None, "activeReservationId": None, "routeExplorationEnabled": False},
                      request_id=root.id, status="NEEDS_CONFIRMATION")


def validate_facts(facts):
    require(facts.get("quantity") is None or facts["quantity"] > 0, "VALIDATION_ERROR", "수량은 양수여야 합니다.", 422)
    fields = facts.get("fields", [])
    require(len(fields) == len(set(fields)), "VALIDATION_ERROR", "분야는 중복할 수 없습니다.", 422)
    preference = facts.get("visitPreference")
    if preference:
        if preference["mode"] == "FIXED":
            require(preference.get("fixedStartAt") and not preference.get("ranges"), "VALIDATION_ERROR", "특정 시각을 확인하세요.", 422)
            quarter(preference["fixedStartAt"])
        else:
            require(preference.get("ranges") and not preference.get("fixedStartAt"), "VALIDATION_ERROR", "방문 가능 구간이 필요합니다.", 422)
            for item in preference["ranges"]:
                interval(item)


def add_photos(ctx, root, files, metadata, default_items=None):
    require(1 <= len(files) <= 5 and len(metadata) == len(files), "UPLOAD_BATCH_REJECTED", "사진 1~5장과 같은 순서의 메타정보가 필요합니다.", 422)
    count = ctx.db.scalar(select(func.count()).select_from(Resource).where(Resource.kind == "PHOTO", Resource.request_id == root.id))
    require(count + len(files) <= 30, "PHOTO_LIMIT_EXCEEDED", "요청 전체 사진은 30장까지 저장할 수 있습니다.")
    normalized, errors = [], []
    for i, (file, meta) in enumerate(zip(files, metadata, strict=True)):
        try:
            validate_type(meta, "PhotoInputDTO", f"metadata.{i}")
            check_photo_metadata(ctx, root, meta)
            normalized.append(normalize_image(file["bytes"]))
        except DomainError as error:
            errors.append({"field": f"files.{i}", "code": error.code, "message": error.message, "fileIndex": i})
    if errors:
        raise DomainError("UPLOAD_BATCH_REJECTED", "업로드 묶음을 저장하지 않았습니다.", 422, fields=errors)
    affected_items, shared = set(), False
    for meta, (data, width, height, suggested) in zip(metadata, normalized, strict=True):
        linked_items = meta.get("workItemIds", default_items or [])
        affected_items.update(linked_items)
        shared = shared or not linked_items
        photo = ctx.create("PHOTO", {"capturedOn": meta.get("capturedOn"), "dateConfirmed": meta["dateConfirmed"],
                           "description": meta.get("description"), "suggestedCapturedOn": suggested,
                           "workItemIds": linked_items}, request_id=root.id)
        ctx.store_file(photo, data, "image/jpeg", width, height)
    ctx.invalidate_sources(root, None if shared else affected_items)


def check_photo_metadata(ctx, root, meta):
    require(bool(meta.get("capturedOn")) == meta["dateConfirmed"], "VALIDATION_ERROR", "촬영일과 확인 여부가 일치해야 합니다.", 422)
    for item_id in meta.get("workItemIds", []):
        item = ctx.get(item_id, "WORK_ITEM")
        require(item.request_id == root.id, "INVALID_REFERENCE", "다른 요청의 항목입니다.", 422)


def create_request(ctx, body, files):
    validate_type(body, "RequestInputDTO", "metadata")
    root = ctx.create("REQUEST", {"symptom": body["symptom"], "context": {**SYMPTOM_CONTEXT, **(body.get("context") or {})},
                      "region": body.get("region"), "urgent": body.get("urgent", False),
                      "commonVersion": uid(), "sourceRevision": uid(), "visitDetails": None,
                      "visitDetailsRevision": None, "dialogueRevision": uid(), "questions": [],
                      "dialogueFinished": False, "closures": []}, status="OPEN")
    item = new_item(ctx, root, {"product": {**PRODUCT, **(body.get("product") or {})}})
    add_photos(ctx, root, files, body["photos"], [item.id])
    return root


def patch_request(ctx, root, body):
    ctx.check_revision(root, body["expectedRevision"])
    ctx.open_request(root)
    values = {k: v for k, v in body.items() if k != "expectedRevision"}
    if "context" in values:
        values["context"] = {**root.data["context"], **values["context"]}
    if "region" in values and values["region"] != root.data.get("region"):
        values.update(commonVersion=uid(), visitDetailsRevision=None, visitDetailsConfirmed=False)
        ctx.invalidate_quotes(request_id=root.id)
    ctx.save(root, **values)
    ctx.invalidate_sources(root)
    return root


def visit_details(ctx, root, body):
    ctx.check_revision(root, body["expectedRevision"])
    require(body["confirmed"] is True, "VALIDATION_ERROR", "방문 정보 확인이 필요합니다.", 422)
    region = root.data.get("region")
    address = body["visitDetails"]["address"]
    require(region and all(region[k] in address for k in ("district", "neighborhood")),
            "ADDRESS_REGION_MISMATCH", "주소와 등록 작업 지역이 일치해야 합니다.", 422)
    previous = root.data.get("visitDetails")
    ctx.save(root, visitDetails=body["visitDetails"], visitDetailsRevision=uid(), visitDetailsConfirmed=True)
    if previous and previous["address"] == address:
        for reservation in ctx.find("RESERVATION", request_id=root.id):
            if reservation.status in ACTIVE_RESERVATIONS:
                agreement = copy.deepcopy(reservation.data["agreement"])
                agreement["terms"]["visitDetails"]["contact"] = body["visitDetails"]["contact"]
                ctx.save(reservation, agreement=agreement)
    return root


def patch_item(ctx, item, body):
    ctx.check_revision(item, body["expectedRevision"])
    root = ctx.open_request(item)
    values = {}
    if "facts" in body:
        facts = copy.deepcopy(item.data["facts"])
        for key, value in body["facts"].items():
            facts[key] = {**facts[key], **value} if key == "product" else value
        validate_facts(facts)
        values.update(facts=facts, itemVersion=uid())
        ctx.invalidate_quotes(item_id=item.id)
    if "resolutionPath" in body:
        path = body["resolutionPath"]
        if path == "SELF_HELP":
            from app.services.reference import guidance
            require(any(g["applicable"] for g in guidance(ctx, "SELF_HELP", item.data["facts"]["product"])["guide"]["guides"]), "GUIDE_NOT_APPLICABLE", "적용 가능한 검증 가이드가 필요합니다.", 422)
        require(not ctx.active_relations(item_id=item.id), "ACTIVE_RELATION_EXISTS", "활성 상담·예약은 먼저 정리해야 합니다.")
        values["resolutionPath"] = path
        item.status = path if path in ("SELF_HELP", "MANUFACTURER_AS") else "EXPLORING"
    ctx.save(item, **values)
    if "facts" in body:
        ctx.invalidate_sources(root, [item.id])
    return item


def validate_facts_references(ctx, item, facts):
    for fact in facts:
        ctx.validate_references(fact["photoIds"], "PHOTO", item.request_id, item.id)
        ctx.validate_references(fact["recordIds"], "RECORD", item.request_id, item.id)
        reservations = fact["performanceReservationIds"]
        if fact["sourceType"] == "FIELD_CONFIRMED":
            require(reservations, "INVALID_REFERENCE", "현장 확인 근거가 필요합니다.", 422)
        for value in reservations:
            r = ctx.get(value, "RESERVATION")
            require(r.item_id == item.id and r.status in ("COMPLETED", "STOPPED") and r.data.get("performance"),
                    "INVALID_REFERENCE", "해당 항목의 종료된 수행 기록만 인용할 수 있습니다.", 422)


def confirm_item(ctx, item, body):
    ctx.check_revision(item, body["expectedRevision"])
    ctx.check_source(item, body["sourceRevision"])
    require(body["confirmed"] and (body["fields"] or body.get("otherField")), "VALIDATION_ERROR", "확인된 분야가 필요합니다.", 422)
    validate_facts_references(ctx, item, body["summary"]["facts"])
    facts = copy.deepcopy(item.data["facts"])
    changed = facts["fields"] != body["fields"] or facts.get("otherField") != body.get("otherField")
    facts.update(fields=body["fields"], otherField=body.get("otherField"))
    validate_facts(facts)
    if changed:
        ctx.invalidate_quotes(item_id=item.id)
    if changed or item.data["summary"] != body["summary"]:
        ctx.invalidate_sources(ctx.get(item.request_id, "REQUEST"), [item.id])
    if item.status == "NEEDS_CONFIRMATION":
        item.status = "EXPLORING"
    return ctx.save(item, facts=facts, summary={"riskSignals": [], "limitations": [], "onsiteInspectionNeeded": None, **body["summary"]},
                    reviewStatus="CONFIRMED", itemVersion=uid() if changed else item.data["itemVersion"])


def close_request(ctx, root, body):
    ctx.check_revision(root, body["expectedRevision"])
    require(not ctx.active_relations(request_id=root.id), "ACTIVE_RELATION_EXISTS", "모든 항목의 활성 관계를 먼저 정리하세요.")
    items = ctx.find("WORK_ITEM", request_id=root.id)
    selected = body["items"]
    require(len(selected) == len(items) and {r["workItemId"] for r in selected} == {r.id for r in items},
            "VALIDATION_ERROR", "전체 항목을 중복 없이 확인해야 합니다.", 422)
    for value in selected:
        require(value["resolved"] or value.get("reason"), "VALIDATION_ERROR", "미해결 종료 사유가 필요합니다.", 422)
        item = ctx.get(value["workItemId"], "WORK_ITEM")
        item.status = "RESOLVED" if value["resolved"] else "NOT_CONTINUING"
        ctx.save(item, routeExplorationEnabled=False)
    root.status = "CLOSED"
    return ctx.save(root, closures=selected)


def add_record(ctx, root, body, item=None):
    if "outcome" in body:
        outcome = body["outcome"]
        data = {"description": outcome["description"], "occurredOn": outcome.get("occurredOn"),
                "photoIds": outcome["photoIds"], "workItemIds": [item.id]}
    else:
        data, outcome = body["record"], None
    ctx.validate_references(data["photoIds"], "PHOTO", root.id)
    for item_id in data["workItemIds"]:
        require(ctx.get(item_id, "WORK_ITEM").request_id == root.id, "INVALID_REFERENCE", "다른 요청의 항목입니다.", 422)
    row = ctx.create("RECORD", {"record": data, "outcome": outcome}, request_id=root.id, item_id=item.id if item else None)
    ctx.invalidate_sources(root, data["workItemIds"] or None)
    return row


def set_groups(ctx, root, body):
    ctx.check_source(root, body["sourceRevision"])
    seen = set()
    keep = []
    for data in body["groups"]:
        photos = ctx.validate_references(data["photoIds"], "PHOTO", root.id)
        require(not seen.intersection(data["photoIds"]), "INVALID_COMPARISON_PAIR", "사진은 한 부위 묶음에만 연결하세요.", 422)
        seen.update(data["photoIds"])
        selected = data.get("selectedPhotoIds", [])
        require(not selected or len(selected) == 2 and len(set(selected)) == 2 and set(selected) <= set(data["photoIds"]),
                "INVALID_COMPARISON_PAIR", "동일 묶음의 서로 다른 두 사진을 선택하세요.", 422)
        dated = sorted([p for p in photos if p.data["dateConfirmed"]], key=lambda p: (p.data["capturedOn"], p.id))
        comparison = selected or ([dated[0].id, dated[-1].id] if len(dated) >= 2 else [])
        pair = [ctx.get(value, "PHOTO") for value in comparison]
        chronology = len(pair) == 2 and all(p.data["dateConfirmed"] for p in pair) and pair[0].data["capturedOn"] != pair[1].data["capturedOn"]
        values = {"label": data["label"], "photoIds": data["photoIds"], "selectedPhotoIds": selected,
                  "comparisonPhotoIds": comparison, "chronologyKnown": chronology,
                  "reason": None if chronology else "사진이 부족하거나 시간 선후가 미확인입니다."}
        if data.get("groupId"):
            row = ctx.get(data["groupId"], "PHOTO_GROUP")
            require(row.request_id == root.id, "INVALID_REFERENCE", "다른 요청의 묶음입니다.", 422)
            ctx.save(row, **values)
        else:
            row = ctx.create("PHOTO_GROUP", values, request_id=root.id)
        keep.append(row.id)
    for row in ctx.find("PHOTO_GROUP", request_id=root.id):
        if row.id not in keep:
            ctx.db.delete(row)
    ctx.invalidate_sources(root)
    return root
