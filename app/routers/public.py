"""Public API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.http import EndpointInput, run_endpoint
from app.pagination import page
from app.services import reference, views
from app.services.context import Context


router = APIRouter(tags=["Public"])


@router.get(
    "/public/service-info",
    summary="소개·지원 범위 조회",
    description=(
        "- **인증 요구사항**: ❌\n"
        "- **설명**: 소개·지원 분야·지원 지역·기준 자료 버전·재촬영 안내를 반환한다."
    ),
    status_code=200,
    operation_id="api_06_v1_public_service_info_get",
)
async def get_service_info(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return reference.service_info(ctx)

    return await run_endpoint(request, operation)


@router.get(
    "/public/technicians",
    summary="공개 기사 연락 목록",
    description=(
        "- **인증 요구사항**: ❌\n"
        "- **설명**: 공개 연락수단이 있는 기사의 공개 프로필을 페이지로 반환한다.\n"
        "\n"
        "**정렬**\n"
        "\n"
        "`technicianId` 오름차순. 기사 ID는 목록에서 유일하며 표시명 변경으로 순서를 바꾸지 않는다."
    ),
    status_code=200,
    operation_id="api_07_v1_public_technicians_get",
)
async def list_public_technicians(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        field = inputs.query.get("field")
        region_id = inputs.query.get("regionId")
        rows = [
            views.public_technician(ctx, row)
            for row in ctx.find("TECHNICIAN")
            if (not field or field in row.data["profile"]["fields"])
            and (not region_id or region_id in row.data["profile"]["regionIds"])
        ]
        return page(ctx, rows, inputs.query, "/public/technicians", lambda r: [r["technicianId"]])

    return await run_endpoint(request, operation)


@router.get(
    "/public/technicians/{technicianId}",
    summary="공개 기사 프로필 조회",
    description=(
        "- **인증 요구사항**: ❌\n"
        "- **설명**: 표시명·분야·지역·공개 중인 업무 연락수단을 반환한다."
    ),
    status_code=200,
    operation_id="api_08_v1_public_technicians__technicianId__get",
)
async def get_public_technician(request: Request, technicianId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return views.public_technician(ctx, ctx.get(technicianId, "TECHNICIAN"))

    return await run_endpoint(request, operation)


@router.get(
    "/public/guidance",
    summary="긴급·공식 안내 조회",
    description=(
        "- **인증 요구사항**: ❌\n"
        "- **설명**: 검증 가이드와 공식 경로를 각각 상태·보완 입력·사유와 함께 반환한다."
    ),
    status_code=200,
    operation_id="api_09_v1_public_guidance_get",
)
async def get_guidance(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return reference.guidance(ctx, inputs.query["type"], inputs.query)

    return await run_endpoint(request, operation)
