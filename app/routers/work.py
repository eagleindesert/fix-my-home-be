"""Work API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.db import uid
from app.errors import require
from app.http import EndpointInput, run_endpoint
from app.security import require_actor
from app.services import reservations
from app.services.context import ACTIVE_RESERVATIONS, Context


router = APIRouter(tags=["Work"])


@router.put(
    "/reservations/{reservationId}/early-start-consent",
    summary="조기 시작 동의·철회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 요청 소유자; 시작 전\n"
        "- **설명**: 현재 예약의 조기 시작 동의·철회와 동의 변경 식별값을 반환한다.\n"
        "\n"
        "**동의 버전·재전송 응답**\n"
        "\n"
        "| 입력·조회 조건 | 응답 |\n"
        "| --- | --- |\n"
        "| 동의 기록 없음 | `earlyStartConsent=null`; 최초 변경의 기대값은 명시적 `null` |\n"
        "| 최초 `REVOKE(null)` | `active=false`인 동의 객체와 새 `revision`; 이후 기대값은 이 값 사용 |\n"
        "| 비활성 기록에 최신 기대값으로 `REVOKE` | 변경 없이 `200`; 같은 `revision` 유지 |\n"
        "| 변경 성공 후 이전 기대값 재전송 | `409 VERSION_CONFLICT`; 현재 예약을 재조회 |"
    ),
    status_code=200,
    operation_id="api_62_v1_reservations__reservationId__early_start_consent_put",
)
async def update_early_start_consent(request: Request, reservationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(reservationId, "RESERVATION")
        ctx.own(row.id, "RESERVATION")
        reservations.consent(ctx, row, inputs.body)
        return reservations.view(ctx, row)

    return await run_endpoint(request, operation)


@router.post(
    "/reservations/{reservationId}/work-events",
    summary="시작·중단 요청·중단·완료·종료 예상 갱신",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 액션별 사용자 또는 담당 기사\n"
        "- **설명**: 작업 이벤트와 조건부 입력을 저장하고 현재 예약·수행·검사 결과를 반환한다.\n"
        "\n"
        "**이벤트별 출력**\n"
        "\n"
        "| 이벤트 | ReservationDTO의 출력 |\n"
        "| --- | --- |\n"
        "| `START` | `actualStartedAt`은 처리 서버 시각; `proposedStartAt`을 복사하거나 15분 단위로 반올림하지 않음 |\n"
        "| `COMPLETE`, `STOP` | `actualEndedAt`은 처리 서버 시각; 종료 위치가 `null`이어도 종료 결과 반환, 위치·이동 "
        "미확인은 `checks`에 표시 |\n"
        "| `UPDATE_EXPECTED_END` | 갱신된 종료 예상·출처·변경 식별값; 충돌은 `checks`로 반환, 오래된 기대값은 `409 "
        "VERSION_CONFLICT`; 최신 기대값의 동일 값·출처는 변경 없이 `200` |"
    ),
    status_code=200,
    operation_id="api_63_v1_reservations__reservationId__work_events_post",
)
async def create_work_event(request: Request, reservationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(reservationId, "RESERVATION")
        reservations.work_event(ctx, row, inputs.body)
        return reservations.view(ctx, row)

    return await run_endpoint(request, operation)


@router.put(
    "/reservations/{reservationId}/end-location",
    summary="완료·중단 후 종료 위치 보완·정정",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 해당 완료·중단 예약의 담당 기사\n"
        "- **설명**: 종료 위치를 보완·정정하고 기존 종료 시각·상태를 유지한 예약을 반환한다.\n"
        "\n"
        "**저장·재전송 응답**\n"
        "\n"
        "| 조건 | 응답 |\n"
        "| --- | --- |\n"
        "| 최신 기대값·같은 위치 | 변경 없이 `200` |\n"
        "| 이전 기대값 | `409 VERSION_CONFLICT`; 예약 상세로 반영 여부 확인 |\n"
        "| 위치 저장 후 이동 검사 미완료 | `200`, 종료 상태·시각 유지, `checks[].status=RECHECK_REQUIRED` |"
    ),
    status_code=200,
    operation_id="api_64_v1_reservations__reservationId__end_location_put",
)
async def update_end_location(request: Request, reservationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(reservationId, "RESERVATION")
        require_actor(ctx.actor, "TECHNICIAN")
        require(row.status in ("COMPLETED", "STOPPED"), "INVALID_STATE", "종료 후 위치만 정정할 수 있습니다.")
        require(
            inputs.body["expectedEndLocationRevision"] == row.data["endLocationRevision"],
            "VERSION_CONFLICT",
            "종료 위치가 변경되었습니다.",
        )
        reservations.validate_location(ctx, inputs.body["endLocationId"])
        if row.data["performance"]["endLocationId"] != inputs.body["endLocationId"]:
            ctx.save(
                row,
                performance={
                    **row.data["performance"],
                    "endLocationId": inputs.body["endLocationId"],
                },
                endLocationRevision=uid(),
            )
            ctx.invalidate_sources(ctx.get(row.request_id, "REQUEST"), [row.item_id])
        return reservations.view(ctx, row)

    return await run_endpoint(request, operation)


@router.put(
    "/reservations/{reservationId}/preparation-notes",
    summary="방문 준비사항 등록·수정",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 해당 활성 예약 담당 기사\n"
        "- **설명**: 장비·부품·현장 점검 준비사항을 저장한다."
    ),
    status_code=200,
    operation_id="api_65_v1_reservations__reservationId__preparation_notes_put",
)
async def update_preparation_notes(request: Request, reservationId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.party(reservationId, "RESERVATION")
        require_actor(ctx.actor, "TECHNICIAN")
        require(row.status in ACTIVE_RESERVATIONS, "INVALID_STATE", "활성 예약만 준비사항을 수정합니다.")
        ctx.save(row, preparation=inputs.body["preparation"])
        return row.data["preparation"]

    return await run_endpoint(request, operation)
