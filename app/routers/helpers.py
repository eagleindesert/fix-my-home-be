"""라우터에서 함께 사용하는 목록 정렬·조회와 이미지 응답."""

from starlette.responses import Response

from app.db import StoredFile
from app.errors import require
from app.security import require_actor
from app.services import handover
from app.time_rules import as_utc


def default_key(row):
    for field in ("createdAt", "receivedAt", "updatedAt", "issuedAt"):
        if field in row:
            instant = -as_utc(row[field]).timestamp()
            break
    else:
        instant = 0
    identifier_fields = (
        "jobId",
        "reservationId",
        "consultationId",
        "deliveryId",
        "requestId",
        "technicianId",
        "candidateId",
    )
    identifier = next((row[field] for field in identifier_fields if field in row), "")
    return [instant, [-ord(c) for c in identifier]]


def own_rows(ctx, kind):
    require_actor(ctx.actor, "USER")
    return ctx.find(kind, owner_id=ctx.actor.account_id)


def parties(ctx, kind):
    require_actor(ctx.actor)
    if ctx.actor.role == "USER":
        return ctx.find(kind, owner_id=ctx.actor.account_id)
    return ctx.find(kind, technician_id=ctx.technician().id)


def filtered(rows, query):
    return [
        row for row in rows
        if all(key in ("cursor", "limit") or value == row.get(key) for key, value in query.items())
    ]


def media_response(ctx, media_id):
    file = ctx.db.get(StoredFile, media_id)
    require(file, "RESOURCE_NOT_FOUND", "파일을 찾을 수 없습니다.", 404)
    row = ctx.get(file.resource_id)
    if row.kind == "PHOTO":
        ctx.own(row.id, "PHOTO")
    elif row.kind == "PORTFOLIO_PHOTO":
        require_actor(ctx.actor)
    elif row.kind == "DELIVERY":
        require(
            handover.can_read_delivery(ctx, row) and row.status == "READY",
            "ACCESS_DENIED",
            "전달본 이미지 접근 권한이 없습니다.",
            403,
        )
        if ctx.actor.role == "TECHNICIAN" and row.data.get("endedContent"):
            require(
                any(photo["media"]["mediaId"] == media_id for photo in row.data["endedContent"]["photos"]),
                "ACCESS_DENIED",
                "종료 관계에서 비공개인 이미지입니다.",
                403,
            )
    else:
        require(False, "ACCESS_DENIED", "이미지 조회 대상이 아닙니다.", 403)
    extension = "png" if file.mime == "image/png" else "jpg"
    return Response(
        ctx.files.read(file.key),
        media_type=file.mime,
        headers={"Content-Disposition": f'inline; filename="image.{extension}"'},
    )
