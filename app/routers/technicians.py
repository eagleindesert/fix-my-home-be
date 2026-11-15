"""Technicians API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.contracts import validate_type
from app.http import EndpointInput, run_endpoint
from app.services import technicians, views
from app.services.context import Context


router = APIRouter(tags=["Technicians"])


@router.get(
    "/technicians/me",
    summary="본인 기사 자원 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 기사 본인\n"
        "- **설명**: 본인 프로필·공개 설정·포트폴리오를 반환한다."
    ),
    status_code=200,
    operation_id="api_32_v1_technicians_me_get",
)
async def get_my_technician(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        tech = ctx.technician()
        return views.technician(ctx, tech)

    return await run_endpoint(request, operation)


@router.put(
    "/technicians/me/profile",
    summary="프로필 등록·수정",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 기사 본인\n"
        "- **설명**: 기대 버전과 프로필 전체 내용을 입력받아 현재 프로필을 반환한다."
    ),
    status_code=200,
    operation_id="api_33_v1_technicians_me_profile_put",
)
async def update_profile(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        tech = ctx.technician()
        return views.technician(ctx, technicians.profile(ctx, tech, inputs.body))

    return await run_endpoint(request, operation)


@router.post(
    "/technicians/me/portfolio-photos",
    summary="본인 포트폴리오 사진 업로드",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 기사 본인\n"
        "- **설명**: 포트폴리오 사진과 출처 정보를 입력받아 미디어 목록을 반환한다."
    ),
    status_code=201,
    operation_id="api_34_v1_technicians_me_portfolio_photos_post",
)
async def upload_portfolio_photos(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        tech = ctx.technician()
        validate_type(inputs.body["source"], "SourceDTO", "source")
        return technicians.upload(ctx, tech, inputs.files, inputs.body["source"])

    return await run_endpoint(request, operation)


@router.get(
    "/technicians/{technicianId}/portfolio",
    summary="포트폴리오·사례 목록 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 로그인; 공개 검증 자료\n"
        "- **설명**: 본인 자료 또는 타인에게 공개 가능한 사진·사례 목록을 반환한다."
    ),
    status_code=200,
    operation_id="api_35_v1_technicians__technicianId__portfolio_get",
)
async def get_portfolio(request: Request, technicianId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return views.portfolio(ctx, ctx.get(technicianId, "TECHNICIAN"))

    return await run_endpoint(request, operation)


@router.post(
    "/technicians/me/cases",
    summary="준비된 시공 사례 등록",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 기사 본인\n"
        "- **설명**: 본인 자료에 연결한 시공 사례를 생성한다."
    ),
    status_code=201,
    operation_id="api_36_v1_technicians_me_cases_post",
)
async def create_case(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        tech = ctx.technician()
        return views.case(ctx, technicians.case(ctx, tech, inputs.body, None))

    return await run_endpoint(request, operation)


@router.patch(
    "/technicians/me/cases/{caseId}",
    summary="본인 사례 정정",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 기사 본인\n"
        "- **설명**: 기대 버전과 사례 내용을 입력받아 수정한 사례를 반환한다."
    ),
    status_code=200,
    operation_id="api_37_v1_technicians_me_cases__caseId__patch",
)
async def update_case(request: Request, caseId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        tech = ctx.technician()
        return views.case(ctx, technicians.case(ctx, tech, inputs.body, ctx.get(caseId, "CASE")))

    return await run_endpoint(request, operation)


@router.get(
    "/cases/{caseId}",
    summary="사례 상세 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 로그인; 공개 검증 자료\n"
        "- **설명**: 현재 권한으로 조회 가능한 사례 내용·출처·전후 사진을 반환한다."
    ),
    status_code=200,
    operation_id="api_38_v1_cases__caseId__get",
)
async def get_case(request: Request, caseId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return views.case(ctx, ctx.get(caseId, "CASE"))

    return await run_endpoint(request, operation)


@router.get(
    "/technicians/me/schedule",
    summary="본인 일정표 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 기사 본인\n"
        "- **설명**: 날짜 범위의 가능 시간·외부 일정·예약·이동 구간·검사 결과를 반환한다."
    ),
    status_code=200,
    operation_id="api_39_v1_technicians_me_schedule_get",
)
async def get_schedule(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        tech = ctx.technician()
        return technicians.schedule_view(ctx, tech, inputs.query)

    return await run_endpoint(request, operation)


@router.put(
    "/technicians/me/schedule",
    summary="가능 시간·외부 일정 변경",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 기사 본인\n"
        "- **설명**: 지정 날짜 범위의 편집 가능한 일정 전체를 입력받아 일정표를 반환한다."
    ),
    status_code=200,
    operation_id="api_40_v1_technicians_me_schedule_put",
)
async def update_schedule(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        tech = ctx.technician()
        return technicians.update_schedule(ctx, tech, inputs.body)

    return await run_endpoint(request, operation)
