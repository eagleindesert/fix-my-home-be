"""상담과 견적. 견적 전제는 확인된 전달본의 버전에 묶는다."""

import copy
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from app.db import Resource, now, uid
from app.errors import require
from app.services import reference, scheduling
from app.services.context import ACTIVE_CONSULTATIONS, ACTIVE_RESERVATIONS
from app.time_rules import as_utc, iso, quarter


def price(cost):
    require(type(cost["minimumVisitFee"]) is int and cost["minimumVisitFee"] >= 0 and
            type(cost["minimumDiagnosticFee"]) is int and cost["minimumDiagnosticFee"] >= 0,
            "INVALID_COST", "최소 비용은 0 이상의 원 단위 정수여야 합니다.", 422)
    before, after = 0, 0
    categories = {"VISIT": 0, "DIAGNOSIS": 0}
    for line in cost["lines"]:
        if line["confirmed"]:
            b, a = line["beforeAmount"], line["afterAmount"]
            require(type(a) is int and type(b) is int and 0 <= a <= b,
                    "INVALID_COST", "확정 비용과 동일 항목 할인 금액을 확인하세요.", 422)
            before, after = before+b, after+a
            if line["category"] in categories:
                categories[line["category"]] += a
        else:
            require(line.get("beforeAmount") is None and line.get("afterAmount") is None and line.get("condition"),
                    "INVALID_COST", "미확정 비용은 금액 대신 발생 조건을 입력하세요.", 422)
    require(categories["VISIT"] >= cost["minimumVisitFee"] and categories["DIAGNOSIS"] >= cost["minimumDiagnosticFee"],
            "INVALID_COST", "최소 출장·진단비를 확정 비용에 포함해야 합니다.", 422)
    rate = float((Decimal(before-after)*100/Decimal(before)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)) if before else None
    return {"beforeTotal": before, "afterTotal": after, "discountAmount": before-after,
            "discountRate": rate, "minimumTotal": cost["minimumVisitFee"]+cost["minimumDiagnosticFee"]}


def create(ctx, item, body):
    root = ctx.open_request(item)
    tech = ctx.no_self(item, body["technicianId"])
    reference.require_supported(ctx, root, item)
    require(item.data["reviewStatus"] == "CONFIRMED" and item.data["facts"].get("visitPreference"),
            "INVALID_STATE", "요약·분야·방문 조건을 확인해야 합니다.")
    require(not item.data["activeReservationId"], "ACTIVE_RESERVATION_EXISTS", "항목에 활성 예약이 있습니다.")
    require(not any(r.technician_id == tech.id and r.status in ACTIVE_CONSULTATIONS for r in ctx.find("CONSULTATION", item_id=item.id)),
            "INVALID_STATE", "이미 활성 상담이 있습니다.")
    from app.services.handover import usable_delivery
    delivery = usable_delivery(ctx, body["deliveryId"], item, "CONSULTATION", tech.id)
    relation = ctx.create("CONSULTATION", {"deliveryIds": [delivery.id], "events": []}, request_id=root.id,
                          item_id=item.id, technician_id=tech.id, status="PENDING")
    scope = copy.deepcopy(delivery.data["scope"])
    scope["consultationId"] = relation.id
    ctx.save(delivery, scope=scope)
    ctx.relation_event(relation, "PENDING")
    return relation


def change(ctx, relation, body):
    ctx.check_revision(relation, body["expectedRevision"])
    action = body["action"]
    require(relation.status in ACTIVE_CONSULTATIONS, "INVALID_STATE", "종료된 상담입니다.")
    if action in ("ACCEPT", "REJECT"):
        require(ctx.actor.role == "TECHNICIAN" and relation.status == "PENDING", "ROLE_FORBIDDEN", "대기 상담의 담당 기사만 처리할 수 있습니다.", 403)
        relation.status = "ACCEPTED" if action == "ACCEPT" else "REJECTED"
    else:
        if action == "DESELECT":
            require(ctx.actor.role == "USER", "ROLE_FORBIDDEN", "선택 해제는 사용자만 할 수 있습니다.", 403)
        require(not any(r.parent_id == relation.id and r.status in ACTIVE_RESERVATIONS for r in ctx.find("RESERVATION", item_id=relation.item_id)),
                "ACTIVE_RESERVATION_EXISTS", "예약 취소·중단·완료 절차를 먼저 진행하세요.")
        relation.status = "CLOSED"
    ctx.relation_event(relation, relation.status, body.get("reason"))
    if relation.status in ("CLOSED", "REJECTED"):
        close_quotes(ctx, relation)
    return relation


def close_quotes(ctx, relation, selected=None):
    for quote in ctx.find("QUOTE", parent_id=relation.id):
        if quote.id != selected and quote.status == "ACTIVE":
            quote.status = "UNSELECTABLE"
            ctx.save(quote)


def quote_reasons(ctx, quote):
    if quote.status != "ACTIVE":
        return ["견적이 활성 상태가 아닙니다."]
    relation = ctx.get(quote.parent_id, "CONSULTATION")
    item = ctx.get(quote.item_id, "WORK_ITEM")
    root = ctx.get(quote.request_id, "REQUEST")
    versions = quote.data["terms"]["versions"]
    reasons = []
    if relation.status != "ACCEPTED":
        reasons.append("수락된 활성 상담이 아닙니다.")
    if versions["commonVersion"] != root.data["commonVersion"] or versions["itemVersion"] != item.data["itemVersion"]:
        reasons.append("작업 전제가 변경되어 재발행이 필요합니다.")
    if as_utc(quote.data["terms"]["expiresAt"]) <= now():
        reasons.append("견적이 만료되었습니다.")
    if item.data["activeReservationId"]:
        reasons.append("항목에 활성 예약이 있습니다.")
    from app.services.handover import current
    delivery = ctx.db.get(Resource, quote.data["contextDeliveryId"])
    if item.data["reviewStatus"] != "CONFIRMED" or not delivery or delivery.deleting or not current(ctx, delivery):
        reasons.append("확인한 최신 작업 전제 전달본이 필요합니다.")
    return reasons


def issue_quote(ctx, relation, body):
    tech = ctx.technician()
    item = ctx.get(relation.item_id, "WORK_ITEM")
    root = ctx.open_request(item)
    require(relation.technician_id == tech.id and relation.status == "ACCEPTED", "CONSULTATION_NOT_ACTIVE", "수락된 활성 상담에서만 견적을 발행할 수 있습니다.")
    ctx.no_self(item, tech.id)
    from app.services.handover import usable_delivery
    delivery = usable_delivery(ctx, body["contextDeliveryId"], item, "CONSULTATION", tech.id)
    require(delivery.data["scope"].get("consultationId") == relation.id, "INVALID_REFERENCE", "다른 상담의 전달본입니다.", 422)
    terms = copy.deepcopy(body["terms"])
    versions = terms["versions"]
    require(versions["commonVersion"] == root.data["commonVersion"] and versions["itemVersion"] == item.data["itemVersion"], "VERSION_CONFLICT", "견적 전제가 변경되었습니다.")
    previous = ctx.get(body["replacesQuoteId"], "QUOTE") if body.get("replacesQuoteId") else None
    if previous:
        require(previous.parent_id == relation.id and previous.status not in ("SELECTED", "REPLACED"), "QUOTE_UNAVAILABLE", "수정할 수 없는 견적입니다.")
        require(versions["proposalVersion"] == previous.data["terms"]["versions"]["proposalVersion"], "VERSION_CONFLICT", "이전 제안 버전이 다릅니다.")
    else:
        require(versions.get("proposalVersion") is None, "VERSION_CONFLICT", "신규 견적의 제안 버전은 null이어야 합니다.")
    duration = terms["durationMinutes"]
    require(duration > 0 and duration % 15 == 0, "VALIDATION_ERROR", "소요 시간은 양수인 15분 배수여야 합니다.", 422)
    start = quarter(terms["startAt"])
    end = start + timedelta(minutes=duration)
    require(now() < as_utc(terms["expiresAt"]) <= start, "VALIDATION_ERROR", "견적 유효 종료를 확인하세요.", 422)
    require(terms["quantity"] > 0 and terms["fields"] and set(terms["fields"]) <= set(tech.data["profile"]["fields"]), "VALIDATION_ERROR", "기사의 작업 분야와 수량을 확인하세요.", 422)
    reference.require_supported(ctx, root, item)
    scheduling.check_schedule(ctx, tech, start, end, root.data["region"], item.data["facts"]["visitPreference"])
    summary = price(terms["cost"])
    terms["versions"]["proposalVersion"] = uid()
    if previous:
        previous.status = "REPLACED"
        ctx.save(previous)
    return ctx.create("QUOTE", {"terms": terms, "endAt": iso(end), "price": summary,
                      "contextDeliveryId": delivery.id}, request_id=root.id, item_id=item.id,
                      technician_id=tech.id, parent_id=relation.id, owner_id=item.owner_id, status="ACTIVE")


def quote_view(ctx, row):
    reasons = quote_reasons(ctx, row)
    status = "EXPIRED" if row.status == "ACTIVE" and as_utc(row.data["terms"]["expiresAt"]) <= now() else row.status
    return {"quoteId": row.id, "consultationId": row.parent_id, "workItemId": row.item_id,
            "technicianId": row.technician_id, "revision": str(row.revision), "issuedAt": iso(row.created_at),
            "status": status, "terms": copy.deepcopy(row.data["terms"]), "endAt": row.data["endAt"],
            "price": row.data["price"], "durationEstimate": reference.duration(ctx, ctx.get(row.item_id, "WORK_ITEM")),
            "selectable": not reasons, "reasons": reasons, "checks": []}


def consultation_view(ctx, row):
    from app.services.handover import can_read_delivery
    deliveries = [d for d in ctx.find("DELIVERY", item_id=row.item_id) if
                  d.data["scope"].get("consultationId") == row.id and can_read_delivery(ctx, d)]
    contexts = [d.data.get("content", {}).get("quoteContext") for d in deliveries if d.status == "READY" and d.data["reviewStatus"] == "CONFIRMED" and d.data.get("content")]
    quote_context = contexts[-1] if contexts and row.status in ACTIVE_CONSULTATIONS else None
    value = {"consultationId": row.id, "workItemId": row.item_id, "technicianId": row.technician_id,
            "revision": str(row.revision), "status": row.status, "createdAt": iso(row.created_at),
            "deliveryIds": [d.id for d in deliveries], "quoteContext": quote_context,
            "quoteContextUnavailableReason": None if quote_context else "최신 확인 전달본이 없거나 상담이 종료되었습니다.",
            "quotes": [quote_view(ctx, q) for q in ctx.find("QUOTE", parent_id=row.id)], "events": row.data["events"]}
    if ctx.actor.role == "TECHNICIAN" and row.status not in ACTIVE_CONSULTATIONS:
        from app.services.handover import scrub_visit_details
        value = scrub_visit_details(ctx, row, value)
    return value
