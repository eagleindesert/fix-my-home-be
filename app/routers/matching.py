"""Matching API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.errors import require
from app.http import EndpointInput, run_endpoint
from app.pagination import page
from app.services import ai, reference, technicians, views
from app.services.context import Context
from app.time_rules import iso


router = APIRouter(tags=["Matching"])


@router.get(
    "/work-items/{workItemId}/case-recommendations",
    summary="사례 기반 기사 추천 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 사례 평가 상태·추천 기사·점수·근거·미완료 사유를 반환한다."
    ),
    status_code=200,
    operation_id="api_41_v1_work_items__workItemId__case_recommendations_get",
)
async def get_case_recommendations(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=False)
        ctx.get(item.request_id, "REQUEST")
        rows = [r for r in ctx.find("AI_JOB", item_id=item.id) if r.data["type"] == "CASE_MATCHING"]
        if rows:
            latest = ai.view(ctx, rows[-1])
            if latest["result"]:
                return latest["result"]["caseRecommendations"]
            status = "RUNNING" if latest["status"] in ("QUEUED", "RUNNING") else "INCOMPLETE"
        else:
            status = "NOT_REQUESTED"
        return {
            "evaluationStatus": status,
            "sourceRevision": item.data["sourceRevision"],
            "stale": bool(rows and (not ai.source_current(ctx, rows[-1]))),
            "recommendations": [],
            "reason": "명시적으로 실행한 최신 사례 평가 결과가 없습니다.",
        }

    return await run_endpoint(request, operation)


@router.get(
    "/work-items/{workItemId}/general-candidates",
    summary="일반 기사 후보 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 분야·지역·시간 적합성과 미확인 사유를 포함한 일반 기사 후보를 반환한다.\n"
        "\n"
        "**정렬**\n"
        "\n"
        "`technician.technicianId` 오름차순. 사례 점수나 시간 적합성으로 순서를 바꾸지 않는다."
    ),
    status_code=200,
    operation_id="api_42_v1_work_items__workItemId__general_candidates_get",
)
async def list_general_candidates(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=False)
        ctx.get(item.request_id, "REQUEST")
        return page(
            ctx,
            technicians.candidates(ctx, item),
            inputs.query,
            "/work-items/{workItemId}/general-candidates",
            lambda r: [r["technician"]["technicianId"]],
        )

    return await run_endpoint(request, operation)


@router.put(
    "/work-items/{workItemId}/route-exploration",
    summary="동선 탐색 공개·중단",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 최소 공개 확인과 동선 탐색 활성 여부를 저장한다.\n"
        "\n"
        "**재전송 응답**\n"
        "\n"
        "성공 후 이전 `expectedRevision`으로 재전송하면 `409 VERSION_CONFLICT`이다. 상위 `GET "
        "/requests/{requestId}`의 `workItems`에서 해당 항목의 활성 여부·버전을 확인한다. 기대값만 바꾼 자동 재제출은 하지 않는다."
    ),
    status_code=200,
    operation_id="api_43_v1_work_items__workItemId__route_exploration_put",
)
async def update_route_exploration(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=True)
        root = ctx.get(item.request_id, "REQUEST")
        ctx.check_revision(item, inputs.body["expectedRevision"])
        if inputs.body["enabled"]:
            reference.require_supported(ctx, root, item)
            require(
                inputs.body.get("confirmed")
                and item.data["reviewStatus"] == "CONFIRMED"
                and item.data["facts"].get("visitPreference")
                and reference.duration(ctx, item)["minutes"]
                and not item.data["activeReservationId"],
                "CONFIRMATION_REQUIRED",
                "분야·동·방문 조건·추정 시간을 확인하세요.",
            )
        return views.work_item(ctx, ctx.save(item, routeExplorationEnabled=inputs.body["enabled"]))

    return await run_endpoint(request, operation)


@router.get(
    "/technicians/me/route-candidates",
    summary="기사 동선 추천 작업 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 기사 본인\n"
        "- **설명**: 공개 확인된 최소 작업 정보·시간 적합성·동선 계산 근거를 반환한다.\n"
        "\n"
        "**정렬**\n"
        "\n"
        "아래 그룹 순서로 반환하며, 각 그룹 안에서 명시한 키를 왼쪽부터 적용한다. 조회한 `date`에서 삽입 가능한 구간이 여러 개이면 추가 이동 시간이 "
        "가장 작은 구간의 `route.additionalMinutes`를 사용한다.\n"
        "\n"
        "| 순서 | 응답 조건 | 그룹 내 정렬 |\n"
        "| --- | --- | --- |\n"
        "| 1 | `timeFit=MATCHED`, `route != null` | `route.additionalMinutes` 오름차순 → 요청 접수 시각"
        " 오름차순 → `candidateId` 오름차순 |\n"
        "| 2 | `timeFit=MATCHED`, `route=null`; 효율만 미산정 | 요청 접수 시각 오름차순 → `candidateId` 오름차순 "
        "|\n"
        "| 3 | `timeFit=UNKNOWN`; 작업·이동 검사 보완 필요 | 요청 접수 시각 오름차순 → `candidateId` 오름차순 |\n"
        "\n"
        "`NOT_MATCHED` 항목은 목록에서 제외한다. 미산정은 0분으로 취급하지 않으며, 요청 접수 시각은 서버 정렬용 값으로 응답에 추가하지 않는다. "
        "정렬 근거는 [요구사항 §6.4](요구사항명세서(기능들).md#64-동선-추천의-비교-기준)를 따른다."
    ),
    status_code=200,
    operation_id="api_44_v1_technicians_me_route_candidates_get",
)
async def list_route_candidates(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        tech = ctx.technician()
        return page(
            ctx,
            technicians.route_candidates(ctx, tech, inputs.query),
            inputs.query,
            "/technicians/me/route-candidates",
            lambda r: technicians.route_sort_key(ctx, r),
        )

    return await run_endpoint(request, operation)


@router.post(
    "/route-candidates/{candidateId}/interests",
    summary="상담 참여 의사 표시",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 기사 본인; 탐색 공개 중\n"
        "- **설명**: 추천 작업에 대한 본인의 참여 의사를 저장한다. 요청 본문은 없다."
    ),
    status_code=201,
    operation_id="api_45_v1_route_candidates__candidateId__interests_post",
)
async def create_interest(request: Request, candidateId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return technicians.interest(ctx, candidateId)

    return await run_endpoint(request, operation)


@router.get(
    "/work-items/{workItemId}/interests",
    summary="참여 기사 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 항목에 참여 의사를 표시한 기사의 공개 정보를 반환한다."
    ),
    status_code=200,
    operation_id="api_46_v1_work_items__workItemId__interests_get",
)
async def list_interests(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=False)
        ctx.get(item.request_id, "REQUEST")
        return [
            {
                "interestId": row.id,
                "candidateId": row.data["candidateId"],
                "technician": views.public_technician(ctx, ctx.get(row.technician_id)),
                "createdAt": iso(row.created_at),
            }
            for row in ctx.find("INTEREST", item_id=item.id)
        ]

    return await run_endpoint(request, operation)
