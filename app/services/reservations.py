"""예약 합의와 실제 수행. 모든 갱신은 동일 DB 잠금 아래에서 재검사한다."""

import copy

from app.db import now, uid
from app.errors import DomainError, require
from app.services import consultations, scheduling
from app.services.context import ACTIVE_RESERVATIONS
from app.time_rules import as_utc, iso, lead_time, quarter


def agreement_matches(row, version):
    require(row.data["agreement"]["agreementVersion"] == version,
            "VERSION_CONFLICT", "현재 합의 버전을 다시 조회하세요.")


def check_view(row):
    return {"checkId": row.id, **copy.deepcopy(row.data["view"])}


def inputs(ctx, body):
    operation = body["operation"]
    require(operation == "START_WORK" or "proposedStartAt" not in body,
            "VALIDATION_ERROR", "예상 시작 시각은 시작 검사에만 사용합니다.", 422)
    row = change = None
    if operation == "CREATE":
        require(body.get("quoteId") and not body.get("reservationId") and not body.get("changeId"),
                "VALIDATION_ERROR", "신규 예약에는 견적을 지정하세요.", 422)
        quote = ctx.own(body["quoteId"], "QUOTE")
        item = ctx.get(quote.item_id, "WORK_ITEM")
        root = ctx.get(quote.request_id, "REQUEST")
        terms = quote.data["terms"]
        start, end = as_utc(terms["startAt"]), as_utc(quote.data["endAt"])
        tech = ctx.get(quote.technician_id, "TECHNICIAN")
        preference, region = item.data["facts"]["visitPreference"], root.data["region"]
        version = terms["versions"]
    else:
        require(body.get("reservationId") and not body.get("quoteId"), "VALIDATION_ERROR", "예약을 지정하세요.", 422)
        row = ctx.party(body["reservationId"], "RESERVATION")
        require(row.status in ACTIVE_RESERVATIONS, "INVALID_STATE", "종료된 예약입니다.")
        item, root = ctx.get(row.item_id, "WORK_ITEM"), ctx.get(row.request_id, "REQUEST")
        tech = ctx.get(row.technician_id, "TECHNICIAN")
        terms = row.data["agreement"]["terms"]
        version = row.data["agreement"]["agreementVersion"]
        if operation in ("CHANGE_BEFORE_START", "CHANGE_IN_PROGRESS"):
            require(body.get("changeId"), "VALIDATION_ERROR", "변경안을 지정하세요.", 422)
            change = ctx.party(body["changeId"], "CHANGE")
            require(change.parent_id == row.id and change.status == "PROPOSED", "INVALID_STATE", "유효한 변경안이 아닙니다.")
            agreement_matches(row, change.data["baseAgreementVersion"])
            require(operation == ("CHANGE_BEFORE_START" if change.data["type"] == "BEFORE_START" else "CHANGE_IN_PROGRESS"),
                    "INVALID_STATE", "변경 유형과 검사 유형이 다릅니다.")
            terms = change.data["terms"]
        else:
            require(not body.get("changeId") and row.status == "CONFIRMED", "INVALID_STATE", "시작 전 예약만 시작 검사할 수 있습니다.")
        start = as_utc(row.data["actualStartedAt"] or terms["startAt"])
        end = as_utc(terms["expectedEndAt"])
        if operation == "START_WORK":
            start = as_utc(body["proposedStartAt"]) if body.get("proposedStartAt") else now()
            if body.get("proposedStartAt"):
                require(start < as_utc(terms["startAt"]), "VALIDATION_ERROR", "예상 조기 시작은 합의 시작보다 빨라야 합니다.", 422)
            end = as_utc(row.data["currentExpectedEndAt"])
        preference, region = terms["visitPreference"], terms["region"]
    return row, change, item, root, tech, start, end, preference, region, version


def examine(ctx, body, persist=True):
    row, change, item, root, tech, start, end, preference, region, version = inputs(ctx, body)
    operation = body["operation"]
    checks = []
    try:
        require(end > start, "SCHEDULE_RECHECK_REQUIRED", "종료 예상을 다시 확인하세요.")
        if operation in ("CREATE", "CHANGE_BEFORE_START"):
            lead_time(start, now())
        if operation == "CREATE":
            quote = ctx.get(body["quoteId"], "QUOTE")
            require(not consultations.quote_reasons(ctx, quote), "QUOTE_UNAVAILABLE", "선택할 수 없는 견적입니다.")
        scheduling.check_schedule(ctx, tech, start, end, region,
                                  preference if operation != "START_WORK" else None,
                                  exclude=row.id if row else None,
                                  operation=operation)
    except DomainError as error:
        checks.append({"status": "RECHECK_REQUIRED", "code": error.code, "reason": error.message,
                       "reservationIds": [row.id] if row else []})
    overlaps = scheduling.visit_overlaps(ctx, root.id, item.id, tech.id, start, end)
    fingerprint = {"operation": operation, "quoteId": body.get("quoteId"), "reservationId": row.id if row else None,
                   "version": version, "changeId": change.id if change else None,
                   "changeRevision": str(change.revision) if change else None,
                   "start": iso(start), "end": iso(end), "overlaps": overlaps}
    view = {"operation": operation, "reservationId": row.id if row else None,
            "agreementVersion": version if isinstance(version, str) else None,
            "changeId": change.id if change else None, "changeRevision": str(change.revision) if change else None,
            "proposedStartAt": body.get("proposedStartAt"), "allowed": not checks,
            "checks": checks, "overlaps": overlaps if ctx.actor.role == "USER" else None,
            "overlapConfirmationRequired": bool(overlaps), "overlapConfirmed": not overlaps,
            "checkedAt": iso(now())}
    if not persist:
        return fingerprint, view
    return ctx.create("CHECK", {"input": body, "fingerprint": fingerprint, "view": view,
                      "confirmed": False}, request_id=root.id, item_id=item.id,
                      owner_id=root.owner_id, technician_id=tech.id)


def confirm_check(ctx, row, body):
    require(body["confirmed"] is True, "VALIDATION_ERROR", "확인이 필요합니다.", 422)
    current, view = examine(ctx, row.data["input"], persist=False)
    require(current == row.data["fingerprint"], "VERSION_CONFLICT", "중복 조건이 변경되었습니다.")
    require(view["allowed"], "TECHNICIAN_CONFLICT", "기사 일정 조건을 먼저 해결하세요.")
    view["overlapConfirmed"] = True
    ctx.save(row, confirmed=True, view=view)
    return row


def enforce(ctx, body, confirmation=None):
    fingerprint, view = examine(ctx, body, persist=False)
    if not view["allowed"]:
        first = view["checks"][0]
        raise DomainError(first["code"], first["reason"], checks=view["checks"])
    if not fingerprint["overlaps"]:
        return
    candidates = ctx.find("CHECK", request_id=ctx.get(body.get("reservationId") or body.get("quoteId")).request_id)
    if confirmation:
        require(ctx.actor.role == "USER" and confirmation["confirmed"], "ROLE_FORBIDDEN", "중복은 사용자만 확인합니다.", 403)
        check = ctx.own(confirmation["checkId"], "CHECK")
        confirm_check(ctx, check, {"confirmed": True})
        candidates = [check]
    def matches(check):
        old = copy.deepcopy(check.data["fingerprint"])
        current = copy.deepcopy(fingerprint)
        if body["operation"] == "START_WORK":
            return check.data["confirmed"] and covers_start_check(old, current)
        return check.data["confirmed"] and old == current
    require(any(matches(check) for check in candidates), "OVERLAP_CONFIRMATION_REQUIRED", "최신 방문 중복을 사용자가 확인해야 합니다.")


def covers_start_check(previous, current):
    """실제 시작이 늦어 중복이 줄면 기존 확인을 사용하고 새로 겹치는 시간은 거절한다."""
    previous, current = copy.deepcopy(previous), copy.deepcopy(current)
    old_overlaps = {v["reservationId"]: v for v in previous.pop("overlaps")}
    for actual in current.pop("overlaps"):
        approved = old_overlaps.get(actual["reservationId"])
        if not approved or any(approved[k] != actual[k] for k in ("workItemId", "technicianId", "agreementVersion")):
            return False
        if not (as_utc(approved["range"]["startAt"]) <= as_utc(actual["range"]["startAt"]) and
                as_utc(actual["range"]["endAt"]) <= as_utc(approved["range"]["endAt"])):
            return False
    previous.pop("start", None)
    current.pop("start", None)
    return previous == current


def create(ctx, item, body):
    root = ctx.open_request(item)
    quote = ctx.own(body["quoteId"], "QUOTE")
    require(quote.item_id == item.id, "INVALID_REFERENCE", "다른 항목의 견적입니다.", 422)
    require(body["versions"] == quote.data["terms"]["versions"], "VERSION_CONFLICT", "견적 버전이 변경되었습니다.")
    require(root.data.get("visitDetailsConfirmed") and body["visitDetailsRevision"] == root.data.get("visitDetailsRevision"),
            "VISIT_DETAILS_REQUIRED", "최신 방문 주소와 연락처를 확인하세요.")
    enforce(ctx, {"operation": "CREATE", "quoteId": quote.id}, body.get("overlapConfirmation"))
    terms = quote.data["terms"]
    agreement = {"agreementVersion": uid(), "agreedAt": iso(now()), "terms": {
        "fields": terms["fields"], "scope": terms["scope"], "quantity": terms["quantity"], "cost": terms["cost"],
        "startAt": terms["startAt"], "expectedEndAt": quote.data["endAt"],
        "visitPreference": item.data["facts"]["visitPreference"], "region": root.data["region"],
        "visitDetails": root.data["visitDetails"]}}
    row = ctx.create("RESERVATION", {"quoteId": quote.id, "quoteVersions": body["versions"],
                     "agreement": agreement, "agreementHistory": [agreement], "actualStartedAt": None,
                     "actualEndedAt": None, "currentExpectedEndAt": quote.data["endAt"],
                     "endEstimateSource": "AGREEMENT", "endEstimateRevision": uid(), "earlyStartConsent": None,
                     "reason": None, "performance": None, "endLocationRevision": uid(), "preparation": None},
                     request_id=root.id, item_id=item.id, parent_id=quote.parent_id,
                     technician_id=quote.technician_id, status="CONFIRMED")
    quote.status = "SELECTED"
    ctx.save(quote)
    item.status = "RESERVED"
    ctx.save(item, activeReservationId=row.id)
    for relation in ctx.find("CONSULTATION", item_id=item.id):
        if relation.id != row.parent_id and relation.status in ("PENDING", "ACCEPTED"):
            relation.status = "CLOSED"
            ctx.relation_event(relation, "CLOSED", "다른 견적 선택")
        consultations.close_quotes(ctx, relation, selected=quote.id)
    return row


def close(ctx, row, status, reason=None, performance=None):
    row.status = status
    values = {"reason": reason, "earlyStartConsent": None}
    if performance is not None:
        validate_location(ctx, performance.get("endLocationId"))
        values.update(performance=performance, actualEndedAt=iso(now()), endLocationRevision=uid())
    ctx.save(row, **values)
    item = ctx.get(row.item_id, "WORK_ITEM")
    item.status = "RESOLVED" if status == "COMPLETED" else "EXPLORING"
    ctx.save(item, activeReservationId=None)
    relation = ctx.get(row.parent_id, "CONSULTATION")
    relation.status = "CLOSED"
    ctx.relation_event(relation, "CLOSED", reason)
    consultations.close_quotes(ctx, relation)
    for change in ctx.find("CHANGE", parent_id=row.id):
        if change.status == "PROPOSED":
            change.status = "INVALIDATED"
            ctx.save(change)
    from app.services.handover import end_relationship
    frozen = end_relationship(ctx, row)
    ctx.invalidate_sources(ctx.get(row.request_id, "REQUEST"), [row.item_id])
    for delivery_id in frozen:
        delivery = ctx.get(delivery_id, "DELIVERY")
        delivery.status = "READY"
        ctx.save(delivery, reviewStatus="CONFIRMED", endedSourceRevision=item.data["sourceRevision"])
    return row


def cancel(ctx, row, body):
    agreement_matches(row, body["agreementVersion"])
    require(row.status == "CONFIRMED" and not row.data["actualStartedAt"], "INVALID_STATE", "시작 전 예약만 취소할 수 있습니다.")
    require(ctx.actor.role != "TECHNICIAN" or body.get("reason"), "VALIDATION_ERROR", "기사 취소 사유가 필요합니다.", 422)
    return close(ctx, row, "CANCELLED", body.get("reason"))


def consent(ctx, row, body):
    agreement_matches(row, body["agreementVersion"])
    require(row.status == "CONFIRMED", "INVALID_STATE", "시작 전 예약만 동의할 수 있습니다.")
    previous = row.data["earlyStartConsent"]
    require(body["expectedConsentRevision"] == (previous["revision"] if previous else None), "VERSION_CONFLICT", "동의 상태가 변경되었습니다.")
    active = body["action"] == "GRANT"
    if not active and previous and not previous["active"]:
        return row
    if active:
        require(body.get("proposedStartAt"), "VALIDATION_ERROR", "예상 조기 시작 시각이 필요합니다.", 422)
        enforce(ctx, {"operation": "START_WORK", "reservationId": row.id,
                      "proposedStartAt": body["proposedStartAt"]}, body.get("overlapConfirmation"))
    return ctx.save(row, earlyStartConsent={"revision": uid(), "agreementVersion": body["agreementVersion"],
                    "proposedStartAt": body.get("proposedStartAt") if active else None,
                    "active": active, "confirmedAt": iso(now())})


def validate_location(ctx, location):
    require(location is None or any(r.data.get("representativeLocationId") == location for r in ctx.references("REGION")),
            "INVALID_REFERENCE", "확인된 동 대표 위치가 아닙니다.", 422)


def work_event(ctx, row, body):
    agreement_matches(row, body["agreementVersion"])
    event = body["event"]
    require((ctx.actor.role == "USER") == (event == "REQUEST_STOP"), "ROLE_FORBIDDEN", "해당 역할에서 처리할 수 없는 작업 이벤트입니다.", 403)
    require(event == "UPDATE_EXPECTED_END" or "expectedEndEstimateRevision" not in body,
            "VALIDATION_ERROR", "종료 예상 갱신에서만 변경 식별값을 전송하세요.", 422)
    if event == "START":
        require(row.status == "CONFIRMED", "INVALID_STATE", "시작 전 예약만 시작할 수 있습니다.")
        actual = now()
        if actual < as_utc(row.data["agreement"]["terms"]["startAt"]):
            current = row.data["earlyStartConsent"]
            require(current and current["active"] and current["agreementVersion"] == body["agreementVersion"],
                    "EARLY_START_CONSENT_REQUIRED", "현재 합의에 대한 조기 시작 동의가 필요합니다.")
        enforce(ctx, {"operation": "START_WORK", "reservationId": row.id})
        row.status = "IN_PROGRESS"
        ctx.save(row, actualStartedAt=iso(actual))
        item = ctx.get(row.item_id, "WORK_ITEM")
        item.status = "IN_PROGRESS"
        ctx.save(item)
    elif event == "REQUEST_STOP":
        require(row.status == "IN_PROGRESS", "INVALID_STATE", "진행 중인 작업만 중단 요청할 수 있습니다.")
        require(body.get("reason"), "VALIDATION_ERROR", "중단 요청 사유가 필요합니다.", 422)
        row.status = "STOP_REQUESTED"
        ctx.save(row, reason=body["reason"])
        item = ctx.get(row.item_id, "WORK_ITEM")
        item.status = "STOP_REQUESTED"
        ctx.save(item)
    elif event in ("STOP", "COMPLETE"):
        require(row.status in (("IN_PROGRESS", "STOP_REQUESTED") if event == "STOP" else ("IN_PROGRESS",)),
                "INVALID_STATE", "현재 상태에서 종료할 수 없습니다.")
        require(body.get("performance") is not None, "VALIDATION_ERROR", "수행 결과가 필요합니다.", 422)
        reason = body.get("reason") or row.data["reason"]
        require(event != "STOP" or reason, "VALIDATION_ERROR", "직접 중단 사유가 필요합니다.", 422)
        close(ctx, row, "STOPPED" if event == "STOP" else "COMPLETED", reason, body["performance"])
    else:
        require(row.status in ("IN_PROGRESS", "STOP_REQUESTED"), "INVALID_STATE", "실제 작업 중에만 종료 예상을 갱신합니다.")
        require(body.get("expectedEndAt") and body.get("expectedEndEstimateRevision"), "VALIDATION_ERROR", "종료 예상과 변경 식별값이 필요합니다.", 422)
        require(body["expectedEndEstimateRevision"] == row.data["endEstimateRevision"], "VERSION_CONFLICT", "종료 예상이 변경되었습니다.")
        require(quarter(body["expectedEndAt"]) > now(), "VALIDATION_ERROR", "종료 예상은 미래여야 합니다.", 422)
        if row.data["currentExpectedEndAt"] != body["expectedEndAt"] or row.data["endEstimateSource"] != "OPERATIONS":
            ctx.save(row, currentExpectedEndAt=body["expectedEndAt"], endEstimateSource="OPERATIONS", endEstimateRevision=uid())
    return row


def propose_change(ctx, row, body):
    agreement_matches(row, body["agreementVersion"])
    before = body["type"] == "BEFORE_START"
    require(row.status == ("CONFIRMED" if before else "IN_PROGRESS"), "INVALID_STATE", "현재 작업 상태와 변경 유형이 다릅니다.")
    terms = copy.deepcopy(row.data["agreement"]["terms"])
    incoming = copy.deepcopy(body["terms"])
    require(("startAt" in incoming) == before, "VALIDATION_ERROR", "시작 시각은 시작 전 변경에만 필요합니다.", 422)
    revision = incoming.pop("visitDetailsRevision", None)
    if revision:
        require(ctx.actor.role == "USER" and before, "ROLE_FORBIDDEN", "시작 전 요청 소유자만 주소 변경을 제안할 수 있습니다.", 403)
        root = ctx.get(row.request_id, "REQUEST")
        require(root.data.get("visitDetailsConfirmed") and revision == root.data["visitDetailsRevision"], "VERSION_CONFLICT", "확인한 방문 정보가 변경되었습니다.")
        terms.update(visitDetails=root.data["visitDetails"], region=root.data["region"])
    terms.update(incoming)
    consultations.price(terms["cost"])
    require(terms["quantity"] > 0 and terms["fields"], "VALIDATION_ERROR", "작업 분야와 양수 수량이 필요합니다.", 422)
    end = quarter(terms["expectedEndAt"])
    if before:
        start = quarter(terms["startAt"])
        lead_time(start, now())
        require(end > start, "VALIDATION_ERROR", "종료는 시작 이후여야 합니다.", 422)
    else:
        require(end > now(), "VALIDATION_ERROR", "종료는 현재 이후여야 합니다.", 422)
    if body.get("replacesChangeId"):
        old = ctx.party(body["replacesChangeId"], "CHANGE")
        require(old.parent_id == row.id and old.status == "PROPOSED" and old.data["proposerRole"] == ctx.actor.role,
                "INVALID_STATE", "본인의 미반영 변경안만 교체할 수 있습니다.")
        old.status = "SUPERSEDED"
        ctx.save(old)
    return ctx.create("CHANGE", {"type": body["type"], "baseAgreementVersion": body["agreementVersion"],
                      "proposerRole": ctx.actor.role, "terms": terms, "visitDetailsRevision": revision,
                      "userAccepted": ctx.actor.role == "USER", "technicianAccepted": ctx.actor.role == "TECHNICIAN"},
                      request_id=row.request_id, item_id=row.item_id, parent_id=row.id,
                      technician_id=row.technician_id, owner_id=row.owner_id, status="PROPOSED")


def respond_change(ctx, change, body):
    ctx.check_revision(change, body["expectedRevision"])
    require(change.status == "PROPOSED", "INVALID_STATE", "미반영 변경안만 처리할 수 있습니다.")
    row = ctx.party(change.parent_id, "RESERVATION")
    agreement_matches(row, change.data["baseAgreementVersion"])
    proposer = change.data["proposerRole"] == ctx.actor.role
    require(proposer == (body["action"] == "WITHDRAW"), "ROLE_FORBIDDEN", "제안자는 철회, 상대방은 수락·거절할 수 있습니다.", 403)
    if body["action"] != "ACCEPT":
        change.status = "WITHDRAWN" if body["action"] == "WITHDRAW" else "REJECTED"
        return ctx.save(change)
    operation = "CHANGE_BEFORE_START" if change.data["type"] == "BEFORE_START" else "CHANGE_IN_PROGRESS"
    enforce(ctx, {"operation": operation, "reservationId": row.id, "changeId": change.id}, body.get("overlapConfirmation"))
    revision = change.data["visitDetailsRevision"]
    if revision:
        require(revision == ctx.get(row.request_id).data["visitDetailsRevision"], "VERSION_CONFLICT", "방문 정보가 변경되었습니다.")
    agreement = {"agreementVersion": uid(), "terms": change.data["terms"], "agreedAt": iso(now())}
    ctx.save(row, agreement=agreement, agreementHistory=[*row.data["agreementHistory"], agreement],
             currentExpectedEndAt=agreement["terms"]["expectedEndAt"], endEstimateSource="AGREEMENT",
             endEstimateRevision=uid(), earlyStartConsent=None)
    change.status = "APPLIED"
    ctx.save(change, userAccepted=True, technicianAccepted=True)
    for other in ctx.find("CHANGE", parent_id=row.id):
        if other.id != change.id and other.status == "PROPOSED":
            other.status = "INVALIDATED"
            ctx.save(other)
    return change


def checks(ctx, row):
    if row.status not in ACTIVE_RESERVATIONS:
        if row.status in ("COMPLETED", "STOPPED") and not (row.data["performance"] or {}).get("endLocationId"):
            return [{"status": "RECHECK_REQUIRED", "code": "END_LOCATION_REQUIRED", "reason": "종료 위치가 확인되지 않았습니다.", "reservationIds": [row.id]}]
        return []
    try:
        start, end = scheduling.reservation_range(row)
        if end <= now() and row.status in ("IN_PROGRESS", "STOP_REQUESTED"):
            raise DomainError("END_ESTIMATE_OVERDUE", "종료 예상을 갱신하세요.")
        terms = row.data["agreement"]["terms"]
        scheduling.check_schedule(ctx, ctx.get(row.technician_id), start, end, terms["region"], None, exclude=row.id)
        return []
    except DomainError as error:
        return [{"status": "RECHECK_REQUIRED", "code": error.code, "reason": error.message, "reservationIds": [row.id]}]


def change_view(ctx, row):
    data = copy.deepcopy(row.data)
    reservation = ctx.get(row.parent_id, "RESERVATION")
    if ctx.actor.role == "TECHNICIAN" and reservation.status not in ACTIVE_RESERVATIONS:
        from app.services.handover import scrub_visit_details
        data = scrub_visit_details(ctx, reservation, data)
    return {"changeId": row.id, "reservationId": row.parent_id, "revision": str(row.revision), **data,
            "status": row.status, "overlapConfirmationRequired": None, "checkedAt": iso(now()), "checks": checks(ctx, reservation)}


def view(ctx, row):
    data = copy.deepcopy(row.data)
    ended_technician = ctx.actor.role == "TECHNICIAN" and row.status not in ACTIVE_RESERVATIONS
    if ended_technician:
        from app.services.handover import scrub_visit_details
        data = scrub_visit_details(ctx, row, data)
        data["preparation"] = None
        data["reason"] = None
    start, end = scheduling.reservation_range(row)
    overlaps = scheduling.visit_overlaps(ctx, row.request_id, row.item_id, row.technician_id, start, end) if row.status in ACTIVE_RESERVATIONS else []
    from app.services.handover import can_read_delivery
    return {"reservationId": row.id, "workItemId": row.item_id, "consultationId": row.parent_id,
            "technicianId": row.technician_id, "status": row.status, **data,
            "changes": [change_view(ctx, c) for c in ctx.find("CHANGE", parent_id=row.id)],
            "overdue": row.status in ("IN_PROGRESS", "STOP_REQUESTED") and end <= now(),
            "overlaps": overlaps if ctx.actor.role == "USER" else None,
            "overlapConfirmationRequired": bool(overlaps), "checks": checks(ctx, row),
            "handoverDeliveryIds": [d.id for d in ctx.find("DELIVERY", item_id=row.item_id)
                                    if d.data["scope"].get("reservationId") == row.id and can_read_delivery(ctx, d)]}
