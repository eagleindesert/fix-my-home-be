"""사례 매칭에 사용하는 기사 포트폴리오 사진 관찰을 보관한다."""

from io import BytesIO

from PIL import Image
from sqlalchemy import select

from app.db import Resource, StoredFile
from app.errors import DomainError


ANALYSIS_VERSION = 1
MAX_PHOTOS_PER_MATCH = 8
MAX_IMAGE_SIDE = 1536


def _verified_sources(ctx):
    return {
        (row.data.get("reference"), row.data.get("title"), row.version)
        for row in ctx.references("SOURCE")
        if row.data.get("identifiersRemoved")
    }


def _is_verified(photo, sources):
    source = photo.data.get("source") or {}
    key = source.get("reference"), source.get("title"), source.get("version")
    return source.get("verified") is True and bool(source.get("usageBasis")) and key in sources


def _analysis_basis(settings, file):
    return {"version": ANALYSIS_VERSION, "fileKey": file.key, "model": settings.openai_model}


def _current_analysis(photo, basis):
    analysis = photo.data.get("visualAnalysis")
    if analysis and analysis.get("basis") == basis:
        return analysis


def _add_observation(observations, photo, file, text):
    if text:
        observations.setdefault(photo.technician_id, []).append({"mediaId": file.id, "text": text})


def _image_for_analysis(ctx, file):
    content = ctx.files.read(file.key)
    if max(file.width or 0, file.height or 0) <= MAX_IMAGE_SIDE:
        return content
    with Image.open(BytesIO(content)) as image:
        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        output = BytesIO()
        image.save(output, "JPEG", quality=90)
        return output.getvalue()


def snapshot(ctx, prompt, *, analyze_missing):
    """추천 가능한 기사의 사진 관찰과 새로 분석할 사진을 준비한다."""
    technician_ids = {
        candidate["technician"]["technicianId"]
        for candidate in prompt["candidates"]
        if candidate["timeFit"] != "NOT_MATCHED"
    }
    cases = [case for case in prompt["cases"] if case["technicianId"] in technician_ids]
    if not cases:
        return {}, []
    case_media_ids = {
        media_id
        for case in cases
        for key in ("beforeMediaIds", "afterMediaIds")
        for media_id in case["content"][key]
    }
    rows = ctx.db.execute(
        select(Resource, StoredFile)
        .join(StoredFile, StoredFile.resource_id == Resource.id)
        .where(
            Resource.kind == "PORTFOLIO_PHOTO",
            Resource.deleting.is_(False),
            Resource.technician_id.in_({case["technicianId"] for case in cases}),
        )
        .order_by(Resource.created_at, StoredFile.id)
    ).all()
    sources = _verified_sources(ctx)
    observations, pending = {}, []
    for photo, file in sorted(rows, key=lambda row: row[1].id not in case_media_ids):
        if not _is_verified(photo, sources):
            continue
        basis = _analysis_basis(ctx.settings, file)
        analysis = _current_analysis(photo, basis)
        if analysis is not None:
            _add_observation(observations, photo, file, analysis["text"])
            continue
        if not analyze_missing or len(pending) >= MAX_PHOTOS_PER_MATCH:
            continue
        try:
            content = _image_for_analysis(ctx, file)
        except DomainError as error:
            if error.code != "RESOURCE_NOT_FOUND":
                raise
            continue
        except OSError:
            continue
        pending.append({"photoId": file.id, "basis": basis, "bytes": content})
    return observations, pending


def store(ctx, pending, descriptions):
    """분석 중 교체되거나 검증이 해제된 사진의 결과는 사용하지 않는다."""
    sources = _verified_sources(ctx)
    for entry in pending:
        file = ctx.db.get(StoredFile, entry["photoId"])
        if file is None or _analysis_basis(ctx.settings, file) != entry["basis"]:
            continue
        photo = ctx.db.get(Resource, file.resource_id)
        if photo is None or photo.deleting or photo.kind != "PORTFOLIO_PHOTO":
            continue
        if not _is_verified(photo, sources) or _current_analysis(photo, entry["basis"]) is not None:
            continue
        ctx.save(photo, visualAnalysis={"basis": entry["basis"], "text": descriptions[file.id]})
