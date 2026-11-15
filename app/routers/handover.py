"""Handover API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.errors import require
from app.http import EndpointInput, run_endpoint
from app.pagination import page
from app.routers.helpers import default_key, filtered
from app.services import handover
from app.services.context import Context


router = APIRouter(tags=["Handover"])


@router.post(
    "/work-items/{workItemId}/deliveries",
    summary="가림·공개 범위 전달본 준비",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 근거·공개 범위·가림 입력으로 전달본 준비 작업을 접수한다."
    ),
    status_code=202,
    operation_id="api_66_v1_work_items__workItemId__deliveries_post",
)
async def create_delivery(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=True)
        ctx.get(item.request_id, "REQUEST")
        return handover.view(ctx, handover.create(ctx, item, inputs.body))

    return await run_endpoint(request, operation)


@router.get(
    "/work-items/{workItemId}/deliveries",
    summary="본인 전달본·준비본 목록 복구",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 상담 전 준비본·외부 PDF용을 포함한 현존 본인 전달본을 반환한다."
    ),
    status_code=200,
    operation_id="api_67_v1_work_items__workItemId__deliveries_get",
)
async def list_deliveries(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=False)
        ctx.get(item.request_id, "REQUEST")
        purpose = inputs.query.get("purpose")
        status = inputs.query.get("status")
        rows = [
            handover.view(ctx, row)
            for row in ctx.find("DELIVERY", item_id=item.id)
            if (not purpose or row.data["scope"]["purpose"] == purpose)
            and (not status or row.status == status)
        ]
        return page(ctx, rows, inputs.query, "/work-items/{workItemId}/deliveries", default_key)

    return await run_endpoint(request, operation)


@router.get(
    "/deliveries/{deliveryId}",
    summary="전달본 처리 상태·미리보기·열람",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 소유자 또는 허용 수신자\n"
        "- **설명**: 소유자의 처리 상태·허용 미리보기 또는 수신자의 최신 확인본을 반환한다."
    ),
    status_code=200,
    operation_id="api_68_v1_deliveries__deliveryId__get",
)
async def get_delivery(request: Request, deliveryId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.get(deliveryId, "DELIVERY")
        return handover.view(ctx, row)

    return await run_endpoint(request, operation)


@router.put(
    "/deliveries/{deliveryId}/confirmation",
    summary="처리 결과·공개 범위 확인",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 전달본 버전·근거·공개 범위의 사용자 확인을 저장한다."
    ),
    status_code=200,
    operation_id="api_69_v1_deliveries__deliveryId__confirmation_put",
)
async def confirm_delivery(request: Request, deliveryId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.get(deliveryId, "DELIVERY")
        ctx.own(row.id, "DELIVERY")
        handover.confirm(ctx, row, inputs.body)
        return handover.view(ctx, row)

    return await run_endpoint(request, operation)


@router.put(
    "/work-items/{workItemId}/report",
    summary="보고서 직접 작성·수정 초안",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 보고서·근거 버전과 본문을 입력받아 현재 초안을 반환한다."
    ),
    status_code=200,
    operation_id="api_70_v1_work_items__workItemId__report_put",
)
async def update_report(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=True)
        ctx.get(item.request_id, "REQUEST")
        return handover.edit_report(ctx, item, inputs.body)

    return await run_endpoint(request, operation)


@router.get(
    "/work-items/{workItemId}/report",
    summary="본인 보고서·초안 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 본인 보고서의 초안·현재본·확인 상태를 반환한다."
    ),
    status_code=200,
    operation_id="api_71_v1_work_items__workItemId__report_get",
)
async def get_report(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=False)
        ctx.get(item.request_id, "REQUEST")
        return handover.report_view(ctx, item)

    return await run_endpoint(request, operation)


@router.put(
    "/work-items/{workItemId}/report/confirmation",
    summary="최신 보고서 본문 확인",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 보고서 버전·근거에 대한 확인 결과와 현재 보고서를 반환한다."
    ),
    status_code=200,
    operation_id="api_72_v1_work_items__workItemId__report_confirmation_put",
)
async def confirm_report(request: Request, workItemId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        item = ctx.own(workItemId, "WORK_ITEM", writable=True)
        ctx.get(item.request_id, "REQUEST")
        return handover.confirm_report(ctx, item, inputs.body)

    return await run_endpoint(request, operation)


@router.post(
    "/deliveries/{deliveryId}/pdf-jobs",
    summary="사진 포함 PDF 생성",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 확인 전달본 버전으로 PDF 생성 작업을 접수한다."
    ),
    status_code=202,
    operation_id="api_73_v1_deliveries__deliveryId__pdf_jobs_post",
)
async def create_pdf_job(request: Request, deliveryId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.get(deliveryId, "DELIVERY")
        ctx.own(row.id, "DELIVERY")
        return handover.pdf_view(ctx, handover.create_pdf(ctx, row, inputs.body))

    return await run_endpoint(request, operation)


@router.get(
    "/deliveries/{deliveryId}/pdf-jobs",
    summary="본인 PDF 작업 목록 복구",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 전달본별 현존 PDF 작업의 ID·처리 상태·오류를 반환한다."
    ),
    status_code=200,
    operation_id="api_74_v1_deliveries__deliveryId__pdf_jobs_get",
)
async def list_pdf_jobs(request: Request, deliveryId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.get(deliveryId, "DELIVERY")
        ctx.own(row.id, "DELIVERY")
        return page(
            ctx,
            filtered(
                [handover.pdf_view(ctx, r) for r in ctx.find("PDF_JOB", parent_id=row.id)],
                inputs.query,
            ),
            inputs.query,
            "/deliveries/{deliveryId}/pdf-jobs",
            default_key,
        )

    return await run_endpoint(request, operation)


@router.get(
    "/pdf-jobs/{jobId}",
    summary="PDF 생성 상태 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: PDF 작업 상태·오류·현재 다운로드 가능 여부를 반환한다."
    ),
    status_code=200,
    operation_id="api_75_v1_pdf_jobs__jobId__get",
)
async def get_pdf_job(request: Request, jobId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.own(jobId, "PDF_JOB")
        value = handover.pdf_view(ctx, row)
        return value

    return await run_endpoint(request, operation)


@router.get(
    "/pdf-jobs/{jobId}/content",
    summary="확인된 PDF 다운로드",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 권한과 최신성이 유효한 PDF 바이트를 첨부 파일로 반환한다."
    ),
    status_code=200,
    operation_id="api_76_v1_pdf_jobs__jobId__content_get",
)
async def download_pdf(request: Request, jobId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.own(jobId, "PDF_JOB")
        value = handover.pdf_view(ctx, row)
        require(value["downloadAvailable"], "CONFIRMATION_REQUIRED", "현재 다운로드할 수 없는 PDF입니다.")
        return Response(
            ctx.files.read(ctx.file_for(row).key),
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=\"report.pdf\""},
        )

    return await run_endpoint(request, operation)
