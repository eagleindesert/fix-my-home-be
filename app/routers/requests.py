"""Requests API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.http import EndpointInput, run_endpoint
from app.pagination import page
from app.routers.helpers import default_key, filtered, own_rows
from app.security import require_actor
from app.services import reference, requests, views
from app.services.context import Context


router = APIRouter(tags=["Requests"])


@router.post(
    "/requests",
    summary="사진·증상 최초 접수",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 사진·증상으로 요청과 기본 작업 항목 하나를 생성하여 반환한다."
    ),
    status_code=201,
    operation_id="api_10_v1_requests_post",
)
async def create_request(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        require_actor(ctx.actor, "USER")
        return views.request_view(
            ctx,
            requests.create_request(ctx, inputs.body["metadata"], inputs.files),
        )

    return await run_endpoint(request, operation)


@router.get(
    "/requests",
    summary="본인 요청 목록",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 본인 요청과 항목별 상태의 요약 목록을 반환한다.\n"
        "\n"
        "**정렬**\n"
        "\n"
        "`updatedAt` 내림차순 → 동률 `requestId` 내림차순."
    ),
    status_code=200,
    operation_id="api_11_v1_requests_get",
)
async def list_requests(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return page(
            ctx,
            filtered([views.request_list(ctx, r) for r in own_rows(ctx, "REQUEST")], inputs.query),
            inputs.query,
            "/requests",
            default_key,
        )

    return await run_endpoint(request, operation)


@router.get(
    "/requests/{requestId}",
    summary="요청 상세·이력 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 공통 자료·작업 항목·연결 이력을 반환한다."
    ),
    status_code=200,
    operation_id="api_12_v1_requests__requestId__get",
)
async def get_request(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=False)
        return views.request_view(ctx, root)

    return await run_endpoint(request, operation)


@router.patch(
    "/requests/{requestId}",
    summary="공통 증상·지역 정정",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 공통 증상·지역을 수정하고 현재 요청을 반환한다."
    ),
    status_code=200,
    operation_id="api_13_v1_requests__requestId__patch",
)
async def update_request(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=True)
        return views.request_view(ctx, requests.patch_request(ctx, root, inputs.body))

    return await run_endpoint(request, operation)


@router.put(
    "/requests/{requestId}/visit-details",
    summary="상세 방문 정보 확인",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 확인한 상세 방문 정보와 확인 버전을 반환한다.\n"
        "\n"
        "**재전송 응답**\n"
        "\n"
        "성공 후 이전 `expectedRevision`으로 재전송하면 `409 VERSION_CONFLICT`이다. `GET "
        "/requests/{requestId}`로 현재 방문 정보·버전을 확인한다. 기대값만 바꾼 자동 재제출은 하지 않는다."
    ),
    status_code=200,
    operation_id="api_14_v1_requests__requestId__visit_details_put",
)
async def confirm_visit_details(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=True)
        return views.request_view(ctx, requests.visit_details(ctx, root, inputs.body))

    return await run_endpoint(request, operation)


@router.post(
    "/requests/{requestId}/closure",
    summary="요청 전체 종료",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 항목별 종료 선택을 입력받아 요청의 종료 결과를 반환한다."
    ),
    status_code=200,
    operation_id="api_15_v1_requests__requestId__closure_post",
)
async def close_request(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=True)
        return views.request_view(ctx, requests.close_request(ctx, root, inputs.body))

    return await run_endpoint(request, operation)


@router.post(
    "/requests/{requestId}/work-items",
    summary="독립 작업 항목 추가",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 확인한 작업 사실로 독립 작업 항목을 추가한다."
    ),
    status_code=201,
    operation_id="api_16_v1_requests__requestId__work_items_post",
)
async def create_work_item(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=True)
        ctx.check_revision(root, inputs.body["expectedRevision"])
        row = requests.new_item(ctx, root, inputs.body["facts"])
        ctx.save(root)
        return views.work_item(ctx, row)

    return await run_endpoint(request, operation)


@router.patch(
    "/work-items/{workItemId}",
    summary="작업 사실·해결 경로 변경",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 작업 사실·방문 조건·해결 경로를 부분 수정한다."
    ),
    status_code=200,
    operation_id="api_17_v1_work_items__workItemId__patch",
)
async def update_work_item(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=True)
        ctx.get(item.request_id, "REQUEST")
        return views.work_item(ctx, requests.patch_item(ctx, item, inputs.body))

    return await run_endpoint(request, operation)


@router.put(
    "/work-items/{workItemId}/confirmation",
    summary="요약·분야 사용자 확인",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 요약·분야·근거 버전의 사용자 확인 결과를 저장한다."
    ),
    status_code=200,
    operation_id="api_18_v1_work_items__workItemId__confirmation_put",
)
async def confirm_work_item(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=True)
        ctx.get(item.request_id, "REQUEST")
        return views.work_item(ctx, requests.confirm_item(ctx, item, inputs.body))

    return await run_endpoint(request, operation)


@router.get(
    "/work-items/{workItemId}/solutions",
    summary="항목별 해결 안내",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 자가 해결과 공식 AS 각각의 상태·안내·보완 입력 및 선택 경로를 반환한다."
    ),
    status_code=200,
    operation_id="api_19_v1_work_items__workItemId__solutions_get",
)
async def get_solutions(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=False)
        ctx.get(item.request_id, "REQUEST")
        guide = reference.guidance(ctx, "SELF_HELP", item.data["facts"]["product"])
        official = reference.guidance(ctx, "MANUFACTURER_AS", item.data["facts"]["product"])
        paths = ["TECHNICIAN", "DIRECT_CONTACT", "MANUFACTURER_AS"]
        for value in (guide["guide"], official["officialService"]):
            value["missingFields"] = ["facts.product." + f for f in value["missingFields"]]
        if any((g["applicable"] for g in guide["guide"]["guides"])):
            paths.insert(0, "SELF_HELP")
        return {
            "availablePaths": paths,
            "selfHelp": guide["guide"],
            "officialService": official["officialService"],
            "selectedPath": item.data["resolutionPath"],
        }

    return await run_endpoint(request, operation)


@router.post(
    "/work-items/{workItemId}/outcomes",
    summary="자가 조치·외부 해결 결과 기록",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 자가 조치·외부 해결 결과를 사용자 기록으로 저장한다."
    ),
    status_code=201,
    operation_id="api_20_v1_work_items__workItemId__outcomes_post",
)
async def create_outcome(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=True)
        root = ctx.get(item.request_id, "REQUEST")
        return views.record(ctx, requests.add_record(ctx, root, inputs.body, item))

    return await run_endpoint(request, operation)
