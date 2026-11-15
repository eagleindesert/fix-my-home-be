"""서명된 정렬 키 커서. 계정·역할·경로·필터를 함께 검증한다."""

import base64
import hashlib
import hmac
import json

from app.errors import DomainError, require


def page(ctx, rows, query, path, key):
    limit = query.get("limit", 20)
    require(type(limit) is int and 1 <= limit <= 100, "VALIDATION_ERROR", "limit은 1~100이어야 합니다.", 422)
    scope = {"path": path.format(**ctx.path_params), "filters": {k: v for k, v in query.items() if k not in ("cursor", "limit")},
             "account": ctx.actor.account_id if ctx.actor else None, "role": ctx.actor.role if ctx.actor else None}
    secret = ctx.settings.session_secret.get_secret_value().encode()
    ordered = sorted(rows, key=key)
    if query.get("cursor"):
        try:
            payload, signature = query["cursor"].split(".")
            expected = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            value = json.loads(base64.urlsafe_b64decode(payload+"="*(-len(payload) % 4)))
            if value["scope"] != scope:
                raise ValueError()
            ordered = [row for row in ordered if key(row) > value["last"]]
        except (ValueError, KeyError, TypeError):
            raise DomainError("VALIDATION_ERROR", "커서 없이 다시 조회하세요.", 422,
                              fields=[{"field": "cursor", "fileIndex": None, "code": "INVALID_CURSOR", "message": "조회 조건과 커서가 일치하지 않습니다."}],
                              actions=["커서 없이 다시 조회하세요."])
    selected = ordered[:limit]
    cursor = None
    if len(ordered) > limit:
        payload = base64.urlsafe_b64encode(json.dumps({"scope": scope, "last": key(selected[-1])},
                                                     ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")
        cursor = payload+"."+hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
    return {"items": selected, "nextCursor": cursor}
