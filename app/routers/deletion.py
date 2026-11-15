"""Deletion API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

import copy

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse, Response

from app.http import EndpointInput, run_endpoint
from app.pagination import page
from app.routers.helpers import default_key, filtered, own_rows
from app.services import deletion
from app.services.context import Context


router = APIRouter(tags=["Deletion"])


@router.post(
    "/deletion-jobs",
    summary="사진·일반 기록·요청 전체 삭제",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 삭제 대상·참조 정리 확인을 입력받아 삭제 작업을 접수한다."
    ),
    status_code=202,
    operation_id="api_77_v1_deletion_jobs_post",
)
async def create_deletion_job(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = deletion.create(ctx, inputs.body)
        if row.status == "REJECTED":
            error = copy.deepcopy(row.data["error"])
            error["currentState"] = {
                "resourceType": "DELETION_JOB",
                "resourceId": row.id,
                "status": row.status,
                "revision": str(row.revision),
            }
            return JSONResponse(error, 409)
        return deletion.view(row)

    return await run_endpoint(request, operation)


@router.get(
    "/deletion-jobs",
    summary="삭제 작업 목록·재시도 대상 복구",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 원래 요청의 삭제 여부와 관계없이 본인 삭제 작업 ID·상태를 반환한다.\n"
        "\n"
        "**정렬**\n"
        "\n"
        "`createdAt` 내림차순 → 동률 `jobId` 내림차순. 재시도는 최초 작업 생성 시각을 바꾸지 않는다."
    ),
    status_code=200,
    operation_id="api_78_v1_deletion_jobs_get",
)
async def list_deletion_jobs(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return page(
            ctx,
            filtered([deletion.view(r) for r in own_rows(ctx, "DELETION_JOB")], inputs.query),
            inputs.query,
            "/deletion-jobs",
            default_key,
        )

    return await run_endpoint(request, operation)


@router.get(
    "/deletion-jobs/{jobId}",
    summary="삭제 처리 상태 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 삭제 작업 상태·영향 범위·접근 차단·회복 사진 수를 반환한다."
    ),
    status_code=200,
    operation_id="api_79_v1_deletion_jobs__jobId__get",
)
async def get_deletion_job(request: Request, jobId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.own(jobId, "DELETION_JOB")
        return deletion.view(row)

    return await run_endpoint(request, operation)


@router.post(
    "/deletion-jobs/{jobId}/retry",
    summary="삭제 미완료 정리 재시도",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 실패한 삭제 작업을 기존 작업 ID로 재접수한다. 요청 본문은 없다."
    ),
    status_code=202,
    operation_id="api_80_v1_deletion_jobs__jobId__retry_post",
)
async def retry_deletion_job(request: Request, jobId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.own(jobId, "DELETION_JOB")
        return deletion.view(deletion.retry(ctx, row))

    return await run_endpoint(request, operation)
