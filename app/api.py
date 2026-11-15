"""API 계약을 서비스에 연결한다. 전송 처리·트랜잭션은 main에서 공통 적용한다."""

import copy
import re

from sqlalchemy import select
from starlette.responses import JSONResponse, Response

from app.admin import create_account
from app.contracts import validate_type
from app.db import Account, StoredFile, uid
from app.errors import invalid, require
from app.media import normalize_image
from app.pagination import page
from app.security import Actor, new_session, require_actor, session_dto, verify_password
from app.services import ai, consultations, deletion, handover, reference, requests, reservations, technicians, views
from app.services.context import ACTIVE_RESERVATIONS
from app.time_rules import as_utc, iso


def default_key(row):
    for field in ("createdAt", "receivedAt", "updatedAt", "issuedAt"):
        if field in row:
            instant = -as_utc(row[field]).timestamp()
            break
    else:
        instant = 0
    identifier = next((row[k] for k in ("jobId", "reservationId", "consultationId", "deliveryId", "requestId", "technicianId", "candidateId") if k in row), "")
    return [instant, [-ord(c) for c in identifier]]


def own_rows(ctx, kind):
    require_actor(ctx.actor, "USER")
    return ctx.find(kind, owner_id=ctx.actor.account_id)


def parties(ctx, kind):
    require_actor(ctx.actor)
    return ctx.find(kind, **({"owner_id": ctx.actor.account_id} if ctx.actor.role == "USER" else {"technician_id": ctx.technician().id}))


def filtered(rows, query):
    return [r for r in rows if all(k in ("cursor", "limit") or v == r.get(k) for k, v in query.items())]


def media_response(ctx, media_id):
    file = ctx.db.get(StoredFile, media_id)
    require(file, "RESOURCE_NOT_FOUND", "파일을 찾을 수 없습니다.", 404)
    row = ctx.get(file.resource_id)
    if row.kind == "PHOTO":
        ctx.own(row.id, "PHOTO")
    elif row.kind == "PORTFOLIO_PHOTO":
        require_actor(ctx.actor)
    elif row.kind == "DELIVERY":
        require(handover.can_read_delivery(ctx, row) and row.status == "READY", "ACCESS_DENIED", "전달본 이미지 접근 권한이 없습니다.", 403)
        if ctx.actor.role == "TECHNICIAN" and row.data.get("endedContent"):
            require(any(p["media"]["mediaId"] == media_id for p in row.data["endedContent"]["photos"]), "ACCESS_DENIED", "종료 관계에서 비공개인 이미지입니다.", 403)
    else:
        require(False, "ACCESS_DENIED", "이미지 조회 대상이 아닙니다.", 403)
    return Response(ctx.files.read(file.key), media_type=file.mime, headers={"Content-Disposition": 'inline; filename="image.'+("png" if file.mime == "image/png" else "jpg")+'"'})


def signup_account(ctx, body):
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,128}", body["loginId"]):
        invalid("로그인 ID는 영문·숫자·마침표·밑줄·하이픈으로 3~128자여야 합니다.", "loginId")
    if not 12 <= len(body["password"]) <= 128:
        invalid("비밀번호는 12~128자여야 합니다.", "password")

    region = None
    if "regionId" in body:
        if body["role"] != "TECHNICIAN":
            invalid("활동 지역은 기사 가입에서만 지정할 수 있습니다.", "regionId")
        region = next((row for row in ctx.references("REGION") if row.id == body["regionId"]), None)
        require(region and region.data.get("representativeLocationId"), "INVALID_REFERENCE",
                "공개 서비스 정보에 등록된 활동 지역을 선택하세요.", 422)

    roles = ["USER", "TECHNICIAN"] if body["role"] == "TECHNICIAN" else ["USER"]
    account = create_account(ctx.db, ctx.settings, body["loginId"], body["password"], roles)
    if region:
        tech = next(iter(ctx.find("TECHNICIAN", owner_id=account.id)))
        ctx.save(tech, profile={**tech.data["profile"], "regionIds": [region.id]})
        location = region.data["representativeLocationId"]
        ctx.create("SCHEDULE", {
            "availability": [], "externalVisits": [],
            "departureLocationId": location, "returnLocationId": location,
        }, owner_id=account.id, technician_id=tech.id)
    return account


def start_session(ctx, account, response):
    if ctx.actor:
        ctx.db.delete(ctx.actor.session)
    token, session = new_session(ctx.db, account, ctx.settings, account.roles[0])
    tech = next(iter(ctx.find("TECHNICIAN", owner_id=account.id)), None)
    ctx.actor = Actor(account.id, session.role, tech.id if tech else None, session)
    response.set_cookie(ctx.settings.session_cookie, token, max_age=ctx.settings.session_hours*3600,
                        httponly=True, secure=ctx.settings.cookie_secure, samesite="lax", path="/")
    return session_dto(ctx.db, ctx.actor)


def dispatch(ctx, endpoint, params, query, body, files, response):
    method, path = endpoint["method"], endpoint["path"]
    if path == "/auth/signup":
        return start_session(ctx, signup_account(ctx, body), response)
    if path == "/auth/login":
        account = ctx.db.scalar(select(Account).where(Account.login_id == body["loginId"]))
        require(account and verify_password(body["password"], account.password_hash), "INVALID_CREDENTIALS", "로그인 정보를 확인하세요.", 401)
        return start_session(ctx, account, response)
    if path == "/auth/logout":
        ctx.db.delete(ctx.actor.session)
        response.delete_cookie(ctx.settings.session_cookie, path="/", secure=ctx.settings.cookie_secure, httponly=True, samesite="lax")
        return None
    if path == "/auth/me":
        return session_dto(ctx.db, ctx.actor)
    if path == "/auth/role":
        account = ctx.db.get(Account, ctx.actor.account_id)
        require(body["role"] in account.roles, "ROLE_FORBIDDEN", "계정에 허용되지 않은 역할입니다.", 403)
        ctx.actor.session.role = ctx.actor.role = body["role"]
        return session_dto(ctx.db, ctx.actor)
    if path == "/public/service-info":
        return reference.service_info(ctx)
    if path == "/public/technicians":
        rows = [views.public_technician(ctx, r) for r in ctx.find("TECHNICIAN") if
                (not query.get("field") or query["field"] in r.data["profile"]["fields"]) and
                (not query.get("regionId") or query["regionId"] in r.data["profile"]["regionIds"])]
        return page(ctx, rows, query, path, lambda r: [r["technicianId"]])
    if path == "/public/technicians/{technicianId}":
        return views.public_technician(ctx, ctx.get(params["technicianId"], "TECHNICIAN"))
    if path == "/public/guidance":
        return reference.guidance(ctx, query["type"], query)
    if path == "/requests":
        if method == "POST":
            require_actor(ctx.actor, "USER")
            return views.request_view(ctx, requests.create_request(ctx, body["metadata"], files))
        return page(ctx, filtered([views.request_list(ctx, r) for r in own_rows(ctx, "REQUEST")], query), query, path, default_key)
    if "requestId" in params:
        root = ctx.own(params["requestId"], "REQUEST", writable=method != "GET")
        if path.endswith("/visit-details"):
            return views.request_view(ctx, requests.visit_details(ctx, root, body))
        if path.endswith("/closure"):
            return views.request_view(ctx, requests.close_request(ctx, root, body))
        if path.endswith("/work-items"):
            ctx.check_revision(root, body["expectedRevision"])
            row = requests.new_item(ctx, root, body["facts"])
            ctx.save(root)
            return views.work_item(ctx, row)
        if path.endswith("/photos"):
            requests.add_photos(ctx, root, files, body["metadata"])
            return views.photos(ctx, root)
        if path.endswith("/records"):
            return views.record(ctx, requests.add_record(ctx, root, body))
        if path.endswith("/timeline"):
            return views.timeline(ctx, root)
        if path.endswith("/photo-groups"):
            return views.timeline(ctx, requests.set_groups(ctx, root, body))
        if path.endswith("/ai-jobs"):
            if method == "POST":
                return ai.view(ctx, ai.create(ctx, root, body))
            return page(ctx, filtered([ai.view(ctx, r) for r in ctx.find("AI_JOB", request_id=root.id)], query), query, path, default_key)
        if path.endswith("/ai-dialogue"):
            return ai.dialogue(ctx, root, body)
        return views.request_view(ctx, requests.patch_request(ctx, root, body) if method == "PATCH" else root)
    if "workItemId" in params:
        item = ctx.own(params["workItemId"], "WORK_ITEM", writable=method != "GET")
        root = ctx.get(item.request_id, "REQUEST")
        if path.endswith("/solutions"):
            guide = reference.guidance(ctx, "SELF_HELP", item.data["facts"]["product"])
            official = reference.guidance(ctx, "MANUFACTURER_AS", item.data["facts"]["product"])
            paths = ["TECHNICIAN", "DIRECT_CONTACT", "MANUFACTURER_AS"]
            for value in (guide["guide"], official["officialService"]):
                value["missingFields"] = ["facts.product."+f for f in value["missingFields"]]
            if any(g["applicable"] for g in guide["guide"]["guides"]):
                paths.insert(0, "SELF_HELP")
            return {"availablePaths": paths, "selfHelp": guide["guide"], "officialService": official["officialService"], "selectedPath": item.data["resolutionPath"]}
        if path.endswith("/outcomes"):
            return views.record(ctx, requests.add_record(ctx, root, body, item))
        if path.endswith("/general-candidates"):
            return page(ctx, technicians.candidates(ctx, item), query, path,
                        lambda r: [r["technician"]["technicianId"]])
        if path.endswith("/case-recommendations"):
            rows = [r for r in ctx.find("AI_JOB", item_id=item.id) if r.data["type"] == "CASE_MATCHING"]
            if rows:
                latest = ai.view(ctx, rows[-1])
                if latest["result"]:
                    return latest["result"]["caseRecommendations"]
                status = "RUNNING" if latest["status"] in ("QUEUED", "RUNNING") else "INCOMPLETE"
            else:
                status = "NOT_REQUESTED"
            return {"evaluationStatus": status, "sourceRevision": item.data["sourceRevision"], "stale": bool(rows and not ai.source_current(ctx, rows[-1])),
                    "recommendations": [], "reason": "명시적으로 실행한 최신 사례 평가 결과가 없습니다."}
        if path.endswith("/route-exploration"):
            ctx.check_revision(item, body["expectedRevision"])
            if body["enabled"]:
                reference.require_supported(ctx, root, item)
                require(body.get("confirmed") and item.data["reviewStatus"] == "CONFIRMED" and item.data["facts"].get("visitPreference") and
                        reference.duration(ctx, item)["minutes"] and not item.data["activeReservationId"], "CONFIRMATION_REQUIRED", "분야·동·방문 조건·추정 시간을 확인하세요.")
            return views.work_item(ctx, ctx.save(item, routeExplorationEnabled=body["enabled"]))
        if path.endswith("/interests"):
            return [{"interestId": r.id, "candidateId": r.data["candidateId"], "technician": views.public_technician(ctx, ctx.get(r.technician_id)),
                     "createdAt": iso(r.created_at)} for r in ctx.find("INTEREST", item_id=item.id)]
        if path.endswith("/consultations"):
            return consultations.consultation_view(ctx, consultations.create(ctx, item, body))
        if path.endswith("/quotes"):
            return sorted([consultations.quote_view(ctx, r) for r in ctx.find("QUOTE", item_id=item.id)], key=lambda r: [-as_utc(r["issuedAt"]).timestamp(), r["quoteId"]])
        if path.endswith("/reservations"):
            return reservations.view(ctx, reservations.create(ctx, item, body))
        if path.endswith("/deliveries"):
            if method == "POST":
                return handover.view(ctx, handover.create(ctx, item, body))
            rows = [handover.view(ctx, r) for r in ctx.find("DELIVERY", item_id=item.id) if
                    (not query.get("purpose") or r.data["scope"]["purpose"] == query["purpose"]) and
                    (not query.get("status") or r.status == query["status"])]
            return page(ctx, rows, query, path, default_key)
        if path.endswith("/report/confirmation"):
            return handover.confirm_report(ctx, item, body)
        if path.endswith("/report"):
            return handover.edit_report(ctx, item, body) if method == "PUT" else handover.report_view(ctx, item)
        if path.endswith("/confirmation"):
            return views.work_item(ctx, requests.confirm_item(ctx, item, body))
        return views.work_item(ctx, requests.patch_item(ctx, item, body))
    if "photoId" in params:
        row = ctx.own(params["photoId"], "PHOTO", writable=True)
        ctx.check_revision(row, body["expectedRevision"])
        validate_type(body["metadata"], "PhotoUpdateInputDTO", "metadata")
        root = ctx.get(row.request_id)
        previous_items = row.data["workItemIds"]
        requests.check_photo_metadata(ctx, root, body["metadata"])
        if files:
            data, width, height, suggested = normalize_image(files[0]["bytes"])
            old = ctx.file_for(row)
            ctx.obsolete_files.append(old.key)
            ctx.db.delete(old)
            ctx.store_file(row, data, "image/jpeg", width, height)
            ctx.save(row, suggestedCapturedOn=suggested)
        ctx.save(row, **body["metadata"])
        current_items = row.data["workItemIds"]
        ctx.invalidate_sources(root, set(previous_items+current_items) if previous_items and current_items else None)
        return views.photo(ctx, row)
    if "recordId" in params:
        row = ctx.own(params["recordId"], "RECORD", writable=True)
        ctx.check_revision(row, body["expectedRevision"])
        is_outcome = row.data.get("outcome") is not None
        require(("outcome" in body) == is_outcome and ("record" in body) != is_outcome, "VALIDATION_ERROR", "기록 종류에 맞는 내용 하나를 전송하세요.", 422)
        content = body["outcome"] if is_outcome else body["record"]
        ctx.validate_references(content["photoIds"], "PHOTO", row.request_id)
        data = {"description": content["description"], "occurredOn": content.get("occurredOn"), "photoIds": content["photoIds"], "workItemIds": [row.item_id]} if is_outcome else content
        for item_id in data["workItemIds"]:
            require(ctx.get(item_id, "WORK_ITEM").request_id == row.request_id, "INVALID_REFERENCE", "다른 요청의 항목입니다.", 422)
        ctx.save(row, record=data, outcome=content if is_outcome else None)
        ctx.invalidate_sources(ctx.get(row.request_id))
        return views.record(ctx, row)
    if "mediaId" in params:
        return media_response(ctx, params["mediaId"])
    if path.startswith("/technicians/me"):
        tech = ctx.technician()
        if path.endswith("/profile"):
            return views.technician(ctx, technicians.profile(ctx, tech, body))
        if path.endswith("/portfolio-photos"):
            validate_type(body["source"], "SourceDTO", "source")
            return technicians.upload(ctx, tech, files, body["source"])
        if "/cases" in path:
            return views.case(ctx, technicians.case(ctx, tech, body, ctx.get(params["caseId"], "CASE") if "caseId" in params else None))
        if path.endswith("/schedule"):
            return technicians.update_schedule(ctx, tech, body) if method == "PUT" else technicians.schedule_view(ctx, tech, query)
        if path.endswith("/route-candidates"):
            return page(ctx, technicians.route_candidates(ctx, tech, query), query, path,
                        lambda r: technicians.route_sort_key(ctx, r))
        return views.technician(ctx, tech)
    if "technicianId" in params:
        return views.portfolio(ctx, ctx.get(params["technicianId"], "TECHNICIAN"))
    if "caseId" in params:
        return views.case(ctx, ctx.get(params["caseId"], "CASE"))
    if "candidateId" in params:
        return technicians.interest(ctx, params["candidateId"])
    if path == "/consultations":
        return page(ctx, filtered([consultations.consultation_view(ctx, r) for r in parties(ctx, "CONSULTATION")], query), query, path, default_key)
    if "consultationId" in params:
        row = ctx.party(params["consultationId"], "CONSULTATION")
        if path.endswith("/quotes"):
            return consultations.quote_view(ctx, consultations.issue_quote(ctx, row, body))
        return consultations.consultation_view(ctx, consultations.change(ctx, row, body) if method == "PATCH" else row)
    if "quoteId" in params:
        row = ctx.party(params["quoteId"], "QUOTE")
        ctx.check_revision(row, body["expectedRevision"])
        require((ctx.actor.role == "TECHNICIAN") == (body["action"] == "WITHDRAW"), "ROLE_FORBIDDEN", "견적 발행자는 철회, 소유자는 거절할 수 있습니다.", 403)
        require(row.status in ("ACTIVE", "RECONFIRMATION_REQUIRED"), "INVALID_STATE", "변경할 수 없는 견적입니다.")
        row.status = "WITHDRAWN" if body["action"] == "WITHDRAW" else "REJECTED"
        ctx.save(row)
        return consultations.quote_view(ctx, row)
    if path == "/reservation-checks":
        return reservations.check_view(reservations.examine(ctx, body))
    if "checkId" in params:
        return reservations.check_view(reservations.confirm_check(ctx, ctx.own(params["checkId"], "CHECK"), body))
    if path == "/reservations":
        return page(ctx, filtered([reservations.view(ctx, r) for r in parties(ctx, "RESERVATION")], query), query, path,
                    lambda r: [as_utc(r["agreement"]["terms"]["startAt"]).timestamp(), r["reservationId"]])
    if "reservationId" in params:
        row = ctx.party(params["reservationId"], "RESERVATION")
        if path.endswith("/cancellation"):
            reservations.cancel(ctx, row, body)
        elif path.endswith("/changes"):
            return reservations.change_view(ctx, reservations.propose_change(ctx, row, body))
        elif path.endswith("/early-start-consent"):
            ctx.own(row.id, "RESERVATION")
            reservations.consent(ctx, row, body)
        elif path.endswith("/work-events"):
            reservations.work_event(ctx, row, body)
        elif path.endswith("/end-location"):
            require_actor(ctx.actor, "TECHNICIAN")
            require(row.status in ("COMPLETED", "STOPPED"), "INVALID_STATE", "종료 후 위치만 정정할 수 있습니다.")
            require(body["expectedEndLocationRevision"] == row.data["endLocationRevision"], "VERSION_CONFLICT", "종료 위치가 변경되었습니다.")
            reservations.validate_location(ctx, body["endLocationId"])
            if row.data["performance"]["endLocationId"] != body["endLocationId"]:
                ctx.save(row, performance={**row.data["performance"], "endLocationId": body["endLocationId"]}, endLocationRevision=uid())
                ctx.invalidate_sources(ctx.get(row.request_id, "REQUEST"), [row.item_id])
        elif path.endswith("/preparation-notes"):
            require_actor(ctx.actor, "TECHNICIAN")
            require(row.status in ACTIVE_RESERVATIONS, "INVALID_STATE", "활성 예약만 준비사항을 수정합니다.")
            ctx.save(row, preparation=body["preparation"])
            return row.data["preparation"]
        return reservations.view(ctx, row)
    if "changeId" in params:
        row = ctx.party(params["changeId"], "CHANGE")
        return reservations.change_view(ctx, reservations.respond_change(ctx, row, body))
    if "deliveryId" in params:
        row = ctx.get(params["deliveryId"], "DELIVERY")
        if method != "GET" or path.endswith("/pdf-jobs"):
            ctx.own(row.id, "DELIVERY")
        if path.endswith("/confirmation"):
            handover.confirm(ctx, row, body)
        elif path.endswith("/pdf-jobs"):
            if method == "POST":
                return handover.pdf_view(ctx, handover.create_pdf(ctx, row, body))
            return page(ctx, filtered([handover.pdf_view(ctx, r) for r in ctx.find("PDF_JOB", parent_id=row.id)], query), query, path, default_key)
        return handover.view(ctx, row)
    if path == "/deletion-jobs":
        if method == "POST":
            row = deletion.create(ctx, body)
            if row.status == "REJECTED":
                error = copy.deepcopy(row.data["error"])
                error["currentState"] = {"resourceType": "DELETION_JOB", "resourceId": row.id, "status": row.status, "revision": str(row.revision)}
                return JSONResponse(error, 409)
            return deletion.view(row)
        return page(ctx, filtered([deletion.view(r) for r in own_rows(ctx, "DELETION_JOB")], query), query, path, default_key)
    if "jobId" in params:
        kind = "AI_JOB" if path.startswith("/ai-jobs") else "PDF_JOB" if path.startswith("/pdf-jobs") else "DELETION_JOB"
        row = ctx.own(params["jobId"], kind)
        if kind == "AI_JOB":
            return ai.view(ctx, row)
        if kind == "PDF_JOB":
            value = handover.pdf_view(ctx, row)
            if path.endswith("/content"):
                require(value["downloadAvailable"], "CONFIRMATION_REQUIRED", "현재 다운로드할 수 없는 PDF입니다.")
                return Response(ctx.files.read(ctx.file_for(row).key), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="report.pdf"'})
            return value
        return deletion.view(deletion.retry(ctx, row) if method == "POST" else row)
    raise RuntimeError(f"Unmapped endpoint: {method} {path}")


def replay(ctx, endpoint, result, params):
    """재전송은 현재 권한으로 기존 식별자를 재투영한다. 오래된 본문을 반환하지 않는다."""
    require(not result.get("deleted"), "RESOURCE_NOT_FOUND", "삭제된 처리 결과입니다.", 404)
    require(result["role"] == ctx.actor.role, "ROLE_FORBIDDEN", "처리 당시 역할로 전환하세요.", 403)
    if "error" in result:
        return Response(__import__("json").dumps(result["error"], ensure_ascii=False), result["status"], media_type="application/json")
    data, response_type = result["data"], endpoint["response"]
    projections = {
        "RequestDTO": ("requestId", "REQUEST", ctx.own, views.request_view),
        "WorkItemDTO": ("workItemId", "WORK_ITEM", ctx.own, views.work_item),
        "RecordDTO": ("recordId", "RECORD", ctx.own, views.record),
        "CaseDTO": ("caseId", "CASE", ctx.get, views.case),
        "ConsultationDTO": ("consultationId", "CONSULTATION", ctx.party, consultations.consultation_view),
        "QuoteDTO": ("quoteId", "QUOTE", ctx.party, consultations.quote_view),
        "ReservationDTO": ("reservationId", "RESERVATION", ctx.party, reservations.view),
        "ReservationChangeDTO": ("changeId", "CHANGE", ctx.party, reservations.change_view),
        "DeliveryDTO": ("deliveryId", "DELIVERY", ctx.get, handover.view),
        "AiJobDTO": ("jobId", "AI_JOB", ctx.own, ai.view),
        "PdfJobDTO": ("jobId", "PDF_JOB", ctx.own, handover.pdf_view),
        "DeletionJobDTO": ("jobId", "DELETION_JOB", ctx.own, lambda c, r: deletion.view(r)),
        "ReservationCheckDTO": ("checkId", "CHECK", ctx.own, lambda c, r: reservations.check_view(r)),
    }
    if response_type in projections:
        field, kind, getter, renderer = projections[response_type]
        return renderer(ctx, getter(data[field], kind))
    if response_type == "PhotoCollectionDTO":
        return views.photos(ctx, ctx.own(params["requestId"], "REQUEST"))
    if response_type == "ReportDTO":
        return handover.report_view(ctx, ctx.own(params["workItemId"], "WORK_ITEM"))
    if response_type == "InterestDTO":
        row = ctx.party(data["interestId"], "INTEREST")
        require(ctx.get(row.item_id).data["routeExplorationEnabled"], "ACCESS_DENIED", "종료된 탐색 결과입니다.", 403)
        return {"interestId": row.id, "candidateId": row.data["candidateId"],
                "technician": views.public_technician(ctx, ctx.get(row.technician_id)), "createdAt": iso(row.created_at)}
    if response_type == "MediaDTO[]":
        tech = ctx.technician()
        output = []
        for value in data:
            file = ctx.db.get(StoredFile, value["mediaId"])
            require(file, "RESOURCE_NOT_FOUND", "파일을 찾을 수 없습니다.", 404)
            resource = ctx.get(file.resource_id, "PORTFOLIO_PHOTO")
            require(resource.technician_id == tech.id, "ACCESS_DENIED", "본인 업로드 결과만 조회할 수 있습니다.", 403)
            output.append(views.media(file))
        return output
    return copy.deepcopy(data)


def replay_locator(response_type, value, params):
    """멱등 저장소에는 개인정보가 포함된 응답 사본 대신 현재 자원 ID만 저장한다."""
    identifiers = {"RequestDTO": "requestId", "WorkItemDTO": "workItemId", "RecordDTO": "recordId",
                   "CaseDTO": "caseId", "ConsultationDTO": "consultationId", "QuoteDTO": "quoteId",
                   "ReservationDTO": "reservationId", "ReservationChangeDTO": "changeId", "DeliveryDTO": "deliveryId",
                   "AiJobDTO": "jobId", "PdfJobDTO": "jobId", "DeletionJobDTO": "jobId",
                   "ReservationCheckDTO": "checkId", "InterestDTO": "interestId"}
    if response_type in identifiers:
        field = identifiers[response_type]
        return {"data": {field: value[field]}, "resourceIds": [value[field]]}
    if response_type == "PhotoCollectionDTO":
        return {"data": {}, "resourceIds": [params["requestId"]]}
    if response_type == "ReportDTO":
        return {"data": {}, "resourceIds": [params["workItemId"]]}
    if response_type == "MediaDTO[]":
        return {"data": [{"mediaId": v["mediaId"]} for v in value], "resourceIds": []}
    raise RuntimeError(f"Missing idempotency projection: {response_type}")
