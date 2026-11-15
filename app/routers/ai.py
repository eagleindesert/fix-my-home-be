"""AI API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.http import EndpointInput, run_endpoint
from app.pagination import page
from app.routers.helpers import default_key, filtered
from app.services import ai
from app.services.context import Context


router = APIRouter(tags=["AI"])


@router.post(
    "/requests/{requestId}/ai-jobs",
    summary="AI 작업 명시적 실행·재시도",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 종류·대상·근거 버전으로 AI 작업을 접수하여 작업 ID를 반환한다.\n"
        "\n"
        "**종류별 대상·근거 버전**\n"
        "\n"
        "| `AiJobType` | 처리 단위 | `workItemId` | `photoGroupId` | `guideId` | `sourceRevision`"
        " 기준 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| `DIAGNOSIS` | 작업 항목 | ✅ 필수 | 전송 금지 | 전송 금지 | 대상 `WorkItemDTO.sourceRevision` |\n"
        "| `QUESTION` | 요청 전체 | 전송 금지 | 전송 금지 | 전송 금지 | `RequestDTO.sourceRevision` |\n"
        "| `GUIDE_EXPLANATION` | 작업 항목·가이드 | ✅ 필수 | 전송 금지 | ✅ 필수 | 대상 "
        "`WorkItemDTO.sourceRevision`; 가이드 출처·버전도 서버가 함께 검사 |\n"
        "| `CASE_MATCHING` | 작업 항목 | ✅ 필수 | 전송 금지 | 전송 금지 | 대상 `WorkItemDTO.sourceRevision` |\n"
        "| `PHOTO_COMPARISON` | 요청의 사진 묶음 | 전송 금지 | ✅ 필수 | 전송 금지 | 대상 "
        "`PhotoGroupDTO.sourceRevision`; 해당 묶음의 비교 근거만 검사 |\n"
        "| `REPORT_DRAFT` | 작업 항목 | ✅ 필수 | 전송 금지 | 전송 금지 | 대상 `WorkItemDTO.sourceRevision` |"
    ),
    status_code=202,
    operation_id="api_28_v1_requests__requestId__ai_jobs_post",
)
async def create_ai_job(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=True)
        return ai.view(ctx, ai.create(ctx, root, inputs.body))

    return await run_endpoint(request, operation)


@router.get(
    "/requests/{requestId}/ai-jobs",
    summary="요청별 AI 작업·결과 이력 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 요청 소유자\n"
        "- **설명**: 종류·대상별 작업 ID·상태·결과·실패 및 재시도 이력을 반환한다."
    ),
    status_code=200,
    operation_id="api_29_v1_requests__requestId__ai_jobs_get",
)
async def list_ai_jobs(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=False)
        return page(
            ctx,
            filtered(
                [ai.view(ctx, r) for r in ctx.find("AI_JOB", request_id=root.id)],
                inputs.query,
            ),
            inputs.query,
            "/requests/{requestId}/ai-jobs",
            default_key,
        )

    return await run_endpoint(request, operation)


@router.get(
    "/ai-jobs/{jobId}",
    summary="AI 상태·결과·오류 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 저장된 AI 작업의 상태·종류별 결과·오류를 반환한다."
    ),
    status_code=200,
    operation_id="api_30_v1_ai_jobs__jobId__get",
)
async def get_ai_job(request: Request, jobId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.own(jobId, "AI_JOB")
        return ai.view(ctx, row)

    return await run_endpoint(request, operation)


@router.put(
    "/requests/{requestId}/ai-dialogue",
    summary="답변·건너뛰기·문답 종료",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 현재 질문의 답변·건너뛰기 또는 문답 종료 결과를 반환한다.\n"
        "\n"
        "**동일 입력 재전송 응답**\n"
        "\n"
        "| 입력 | 응답 |\n"
        "| --- | --- |\n"
        "| 이미 저장한 같은 질문·액션·답변 또는 종료된 문답의 `FINISH` | 현재 DialogueDTO, `200`; 해당 처리에 소비된 과거 "
        "기대값만으로 충돌 처리하지 않음 |\n"
        "| 처리한 질문에 다른 답변·액션 | `409 INVALID_STATE` |"
    ),
    status_code=200,
    operation_id="api_31_v1_requests__requestId__ai_dialogue_put",
)
async def update_ai_dialogue(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=True)
        return ai.dialogue(ctx, root, inputs.body)

    return await run_endpoint(request, operation)
