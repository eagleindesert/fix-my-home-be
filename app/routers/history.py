"""History API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from starlette.responses import Response

from app.contracts import validate_type
from app.errors import require
from app.http import EndpointInput, run_endpoint
from app.media import normalize_image
from app.routers.helpers import media_response
from app.services import requests, views
from app.services.context import Context


router = APIRouter(tags=["History"])


@router.post(
    "/requests/{requestId}/photos",
    summary="추가 사진 업로드",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 파일과 촬영일·설명·항목 연결을 입력받아 추가 사진을 반환한다."
    ),
    status_code=201,
    operation_id="api_21_v1_requests__requestId__photos_post",
)
async def upload_photos(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=True)
        requests.add_photos(ctx, root, inputs.files, inputs.body["metadata"])
        return views.photos(ctx, root)

    return await run_endpoint(request, operation)


@router.put(
    "/photos/{photoId}",
    summary="사진·촬영일·설명 정정",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 선택한 파일 교체와 현재 사진 메타정보를 저장한다."
    ),
    status_code=200,
    operation_id="api_22_v1_photos__photoId__put",
)
async def update_photo(request: Request, photoId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.own(photoId, "PHOTO", writable=True)
        ctx.check_revision(row, inputs.body["expectedRevision"])
        validate_type(inputs.body["metadata"], "PhotoUpdateInputDTO", "metadata")
        root = ctx.get(row.request_id)
        previous_items = row.data["workItemIds"]
        requests.check_photo_metadata(ctx, root, inputs.body["metadata"])
        if inputs.files:
            data, width, height, suggested = normalize_image(inputs.files[0]["bytes"])
            old = ctx.file_for(row)
            ctx.obsolete_files.append(old.key)
            ctx.db.delete(old)
            ctx.store_file(row, data, "image/jpeg", width, height)
            ctx.save(row, suggestedCapturedOn=suggested)
        ctx.save(row, **inputs.body["metadata"])
        current_items = row.data["workItemIds"]
        ctx.invalidate_sources(
            root,
            set(previous_items + current_items) if previous_items and current_items else None,
        )
        return views.photo(ctx, row)

    return await run_endpoint(request, operation)


@router.get(
    "/media/{mediaId}",
    summary="권한 있는 이미지 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 자료 종류·관계 권한\n"
        "- **설명**: 현재 권한으로 조회 가능한 원본·전달본·포트폴리오 이미지 바이트를 반환한다."
    ),
    status_code=200,
    operation_id="api_23_v1_media__mediaId__get",
)
async def get_media(request: Request, mediaId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return media_response(ctx, mediaId)

    return await run_endpoint(request, operation)


@router.post(
    "/requests/{requestId}/records",
    summary="경과·보완 기록 추가",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 경과·조치·보완 설명을 날짜·사진·작업 항목과 연결하여 저장한다."
    ),
    status_code=201,
    operation_id="api_24_v1_requests__requestId__records_post",
)
async def create_record(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=True)
        return views.record(ctx, requests.add_record(ctx, root, inputs.body))

    return await run_endpoint(request, operation)


@router.patch(
    "/records/{recordId}",
    summary="본인 경과 기록 정정",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 기존 기록 종류에 맞는 `record` 또는 `outcome`을 입력받아 현재 기록을 반환한다."
    ),
    status_code=200,
    operation_id="api_25_v1_records__recordId__patch",
)
async def update_record(request: Request, recordId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        row = ctx.own(recordId, "RECORD", writable=True)
        ctx.check_revision(row, inputs.body["expectedRevision"])
        is_outcome = row.data.get("outcome") is not None
        require(
            ("outcome" in inputs.body) == is_outcome and ("record" in inputs.body) != is_outcome,
            "VALIDATION_ERROR",
            "기록 종류에 맞는 내용 하나를 전송하세요.",
            422,
        )
        content = inputs.body["outcome"] if is_outcome else inputs.body["record"]
        ctx.validate_references(content["photoIds"], "PHOTO", row.request_id)
        data = {
            "description": content["description"],
            "occurredOn": content.get("occurredOn"),
            "photoIds": content["photoIds"],
            "workItemIds": [row.item_id],
        } if is_outcome else content
        for item_id in data["workItemIds"]:
            require(
                ctx.get(item_id, "WORK_ITEM").request_id == row.request_id,
                "INVALID_REFERENCE",
                "다른 요청의 항목입니다.",
                422,
            )
        ctx.save(row, record=data, outcome=content if is_outcome else None)
        ctx.invalidate_sources(ctx.get(row.request_id))
        return views.record(ctx, row)

    return await run_endpoint(request, operation)


@router.get(
    "/requests/{requestId}/timeline",
    summary="날짜별 경과·비교쌍 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 촬영일별 사진·날짜 미확인 사진·기록·동일 부위 묶음을 반환한다."
    ),
    status_code=200,
    operation_id="api_26_v1_requests__requestId__timeline_get",
)
async def get_timeline(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=False)
        return views.timeline(ctx, root)

    return await run_endpoint(request, operation)


@router.put(
    "/requests/{requestId}/photo-groups",
    summary="동일 부위 묶음·비교쌍 설정",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 본인\n"
        "- **설명**: 사진 묶음 전체 구성과 기본·수동 비교쌍 선택을 저장한다."
    ),
    status_code=200,
    operation_id="api_27_v1_requests__requestId__photo_groups_put",
)
async def update_photo_groups(request: Request, requestId: str) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        root = ctx.own(requestId, "REQUEST", writable=True)
        return views.timeline(ctx, requests.set_groups(ctx, root, inputs.body))

    return await run_endpoint(request, operation)
