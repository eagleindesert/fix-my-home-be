"""Consultations API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.errors import require
from app.http import EndpointInput, run_endpoint
from app.pagination import page
from app.routers.helpers import default_key, filtered, parties
from app.services import consultations
from app.services.context import Context
from app.time_rules import as_utc


router = APIRouter(tags=["Consultations"])


@router.post(
    "/work-items/{workItemId}/consultations",
    summary="기사 선택·상담 요청",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 소유자; 지역·방문 조건·요약 확인\n"
        "- **설명**: 선택 기사와 확인 전달본을 입력받아 상담 관계를 생성한다."
    ),
    status_code=201,
    operation_id="api_47_v1_work_items__workItemId__consultations_post",
)
async def create_consultation(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=True)
        ctx.get(item.request_id, "REQUEST")
        return consultations.consultation_view(ctx, consultations.create(ctx, item, inputs.body))

    return await run_endpoint(request, operation)


@router.get(
    "/consultations",
    summary="참여 상담 목록",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 현재 역할의 당사자\n"
        "- **설명**: 현재 역할로 참여한 상담과 허용된 자료를 페이지로 반환한다.\n"
        "\n"
        "**정렬**\n"
        "\n"
        "`createdAt` 내림차순 → 동률 `consultationId` 내림차순."
    ),
    status_code=200,
    operation_id="api_48_v1_consultations_get",
)
async def list_consultations(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return page(
            ctx,
            filtered(
                [consultations.consultation_view(ctx, r) for r in parties(ctx, "CONSULTATION")],
                inputs.query,
            ),
            inputs.query,
            "/consultations",
            default_key,
        )

    return await run_endpoint(request, operation)


@router.get(
    "/consultations/{consultationId}",
    summary="상담 상세·전달 이력 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 관계 당사자\n"
        "- **설명**: 해당 상담의 이벤트·견적·전달본 ID·공개 확인 견적 전제를 반환한다."
    ),
    status_code=200,
    operation_id="api_49_v1_consultations__consultationId__get",
)
async def get_consultation(request: Request, consultationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(consultationId, "CONSULTATION")
        return consultations.consultation_view(ctx, row)

    return await run_endpoint(request, operation)


@router.patch(
    "/consultations/{consultationId}",
    summary="상담 수락·거절·종료·해제",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 관계 당사자; 액션별 권한\n"
        "- **설명**: 역할별 상담 액션과 기대 버전을 입력받아 현재 상담 상태를 반환한다."
    ),
    status_code=200,
    operation_id="api_50_v1_consultations__consultationId__patch",
)
async def update_consultation(request: Request, consultationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(consultationId, "CONSULTATION")
        return consultations.consultation_view(ctx, consultations.change(ctx, row, inputs.body))

    return await run_endpoint(request, operation)


@router.post(
    "/consultations/{consultationId}/quotes",
    summary="견적 신규 발행·수정본 발행",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 수락된 활성 상담의 기사\n"
        "- **설명**: 공개 확인 전제와 기사 제안 조건으로 새 견적 버전을 발행한다."
    ),
    status_code=201,
    operation_id="api_51_v1_consultations__consultationId__quotes_post",
)
async def issue_quote(request: Request, consultationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(consultationId, "CONSULTATION")
        return consultations.quote_view(ctx, consultations.issue_quote(ctx, row, inputs.body))

    return await run_endpoint(request, operation)


@router.patch(
    "/quotes/{quoteId}",
    summary="견적 철회·거절",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 발행 기사 또는 요청 소유자\n"
        "- **설명**: 발행 기사의 철회 또는 사용자의 거절 결과를 반환한다."
    ),
    status_code=200,
    operation_id="api_52_v1_quotes__quoteId__patch",
)
async def update_quote(request: Request, quoteId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(quoteId, "QUOTE")
        ctx.check_revision(row, inputs.body["expectedRevision"])
        require(
            (ctx.actor.role == "TECHNICIAN") == (inputs.body["action"] == "WITHDRAW"),
            "ROLE_FORBIDDEN",
            "견적 발행자는 철회, 소유자는 거절할 수 있습니다.",
            403,
        )
        require(
            row.status in ("ACTIVE", "RECONFIRMATION_REQUIRED"),
            "INVALID_STATE",
            "변경할 수 없는 견적입니다.",
        )
        row.status = "WITHDRAWN" if inputs.body["action"] == "WITHDRAW" else "REJECTED"
        ctx.save(row)
        return consultations.quote_view(ctx, row)

    return await run_endpoint(request, operation)


@router.get(
    "/work-items/{workItemId}/quotes",
    summary="항목별 견적 비교",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 항목의 견적·선택 가능 여부·확정 및 미확정 비용을 반환한다."
    ),
    status_code=200,
    operation_id="api_53_v1_work_items__workItemId__quotes_get",
)
async def list_quotes(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=False)
        ctx.get(item.request_id, "REQUEST")
        return sorted(
            [consultations.quote_view(ctx, r) for r in ctx.find("QUOTE", item_id=item.id)],
            key=lambda r: [-as_utc(r["issuedAt"]).timestamp(), r["quoteId"]],
        )

    return await run_endpoint(request, operation)
