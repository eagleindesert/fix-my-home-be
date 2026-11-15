"""Reservations API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.http import EndpointInput, run_endpoint
from app.pagination import page
from app.routers.helpers import filtered, parties
from app.services import reservations
from app.services.context import Context
from app.time_rules import as_utc


router = APIRouter(tags=["Reservations"])


@router.post(
    "/reservation-checks",
    summary="예약·변경·시작 조건 사전 검사",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 소유자 또는 관련 기사\n"
        "- **설명**: 처리 종류별 사전 검사 결과·확인 식별값·허용 중복 정보를 반환한다."
    ),
    status_code=200,
    operation_id="api_54_v1_reservation_checks_post",
)
async def create_reservation_check(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return reservations.check_view(reservations.examine(ctx, inputs.body))

    return await run_endpoint(request, operation)


@router.put(
    "/reservation-checks/{checkId}/confirmation",
    summary="다른 기사 방문 중복 확인",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 해당 요청 소유자\n"
        "- **설명**: 표시한 방문 중복에 대한 사용자 확인을 저장한다."
    ),
    status_code=200,
    operation_id="api_55_v1_reservation_checks__checkId__confirmation_put",
)
async def confirm_reservation_check(request: Request, checkId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return reservations.check_view(reservations.confirm_check(
            ctx,
            ctx.own(checkId, "CHECK"),
            inputs.body,
        ))

    return await run_endpoint(request, operation)


@router.post(
    "/work-items/{workItemId}/reservations",
    summary="견적 선택·예약 확정",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 소유자; 최신 견적·방문 정보 확인\n"
        "- **설명**: 견적·방문 정보·전제 버전·중복 확인을 입력받아 확정 예약을 반환한다."
    ),
    status_code=201,
    operation_id="api_56_v1_work_items__workItemId__reservations_post",
)
async def create_reservation(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=True)
        ctx.get(item.request_id, "REQUEST")
        return reservations.view(ctx, reservations.create(ctx, item, inputs.body))

    return await run_endpoint(request, operation)


@router.get(
    "/reservations",
    summary="당사자 예약 목록",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 현재 역할의 당사자\n"
        "- **설명**: 현재 역할의 예약·실제 작업 상태를 페이지로 반환한다.\n"
        "\n"
        "**정렬**\n"
        "\n"
        "현재 `agreement.terms.startAt` 오름차순 → 동률 `reservationId` 오름차순. 상태 필터를 적용한 뒤 같은 순서로 "
        "반환한다."
    ),
    status_code=200,
    operation_id="api_57_v1_reservations_get",
)
async def list_reservations(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return page(
            ctx,
            filtered(
                [reservations.view(ctx, r) for r in parties(ctx, "RESERVATION")],
                inputs.query,
            ),
            inputs.query,
            "/reservations",
            lambda r: [as_utc(r["agreement"]["terms"]["startAt"]).timestamp(), r["reservationId"]],
        )

    return await run_endpoint(request, operation)


@router.get(
    "/reservations/{reservationId}",
    summary="예약·작업·인계 상세",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 예약 당사자\n"
        "- **설명**: 당사자에게 허용된 합의·변경안·실제 작업·인계 정보를 반환한다."
    ),
    status_code=200,
    operation_id="api_58_v1_reservations__reservationId__get",
)
async def get_reservation(request: Request, reservationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(reservationId, "RESERVATION")
        return reservations.view(ctx, row)

    return await run_endpoint(request, operation)


@router.post(
    "/reservations/{reservationId}/cancellation",
    summary="시작 전 예약 취소",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 예약 당사자; 실제 시작 전\n"
        "- **설명**: 합의 버전과 취소 사유를 입력받아 취소 결과를 반환한다."
    ),
    status_code=200,
    operation_id="api_59_v1_reservations__reservationId__cancellation_post",
)
async def cancel_reservation(request: Request, reservationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(reservationId, "RESERVATION")
        reservations.cancel(ctx, row, inputs.body)
        return reservations.view(ctx, row)

    return await run_endpoint(request, operation)


@router.post(
    "/reservations/{reservationId}/changes",
    summary="시작 전·진행 중 변경안 제안",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 예약 당사자\n"
        "- **설명**: 변경 조건과 기준 합의 버전으로 새 변경안을 생성한다."
    ),
    status_code=201,
    operation_id="api_60_v1_reservations__reservationId__changes_post",
)
async def propose_reservation_change(request: Request, reservationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(reservationId, "RESERVATION")
        return reservations.change_view(ctx, reservations.propose_change(ctx, row, inputs.body))

    return await run_endpoint(request, operation)


@router.patch(
    "/reservation-changes/{changeId}",
    summary="변경안 수락·거절·철회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 예약 당사자; 동일 변경 버전\n"
        "- **설명**: 동일 변경안 버전에 대한 수락·거절·철회 결과를 반환한다."
    ),
    status_code=200,
    operation_id="api_61_v1_reservation_changes__changeId__patch",
)
async def respond_reservation_change(request: Request, changeId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(changeId, "CHANGE")
        return reservations.change_view(ctx, reservations.respond_change(ctx, row, inputs.body))

    return await run_endpoint(request, operation)
