"""멱등 요청의 결과 식별자 저장과 현재 권한을 적용한 재조회."""

import copy
import json

from starlette.responses import Response

from app.db import StoredFile
from app.errors import require
from app.services import ai, consultations, deletion, handover, reservations, views
from app.time_rules import iso


def replay(ctx, endpoint, result, params):
    """재전송은 현재 권한으로 기존 식별자를 재투영한다. 오래된 본문을 반환하지 않는다."""
    require(not result.get("deleted"), "RESOURCE_NOT_FOUND", "삭제된 처리 결과입니다.", 404)
    require(result["role"] == ctx.actor.role, "ROLE_FORBIDDEN", "처리 당시 역할로 전환하세요.", 403)
    if "error" in result:
        return Response(
            json.dumps(result["error"], ensure_ascii=False),
            result["status"],
            media_type="application/json",
        )
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
        require(
            ctx.get(row.item_id).data["routeExplorationEnabled"],
            "ACCESS_DENIED",
            "종료된 탐색 결과입니다.",
            403,
        )
        return {
            "interestId": row.id,
            "candidateId": row.data["candidateId"],
            "technician": views.public_technician(ctx, ctx.get(row.technician_id)),
            "createdAt": iso(row.created_at),
        }
    if response_type == "MediaDTO[]":
        tech = ctx.technician()
        output = []
        for value in data:
            file = ctx.db.get(StoredFile, value["mediaId"])
            require(file, "RESOURCE_NOT_FOUND", "파일을 찾을 수 없습니다.", 404)
            resource = ctx.get(file.resource_id, "PORTFOLIO_PHOTO")
            require(
                resource.technician_id == tech.id,
                "ACCESS_DENIED",
                "본인 업로드 결과만 조회할 수 있습니다.",
                403,
            )
            output.append(views.media(file))
        return output
    return copy.deepcopy(data)


def replay_locator(response_type, value, params):
    """멱등 저장소에는 개인정보가 포함된 응답 사본 대신 현재 자원 ID만 저장한다."""
    identifiers = {
        "RequestDTO": "requestId",
        "WorkItemDTO": "workItemId",
        "RecordDTO": "recordId",
        "CaseDTO": "caseId",
        "ConsultationDTO": "consultationId",
        "QuoteDTO": "quoteId",
        "ReservationDTO": "reservationId",
        "ReservationChangeDTO": "changeId",
        "DeliveryDTO": "deliveryId",
        "AiJobDTO": "jobId",
        "PdfJobDTO": "jobId",
        "DeletionJobDTO": "jobId",
        "ReservationCheckDTO": "checkId",
        "InterestDTO": "interestId",
    }
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
