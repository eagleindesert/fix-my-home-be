"""공통 HTTP 처리: 입력 검증·세션·트랜잭션·멱등성·파일 정리."""

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy import select, text
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse, Response

from app.contracts import endpoint_contract, load_json, project_output, validate_object
from app.db import Idempotency, lock
from app.errors import DomainError, require
from app.idempotency import replay, replay_locator
from app.security import authenticate, require_actor
from app.services.context import Context


@dataclass
class EndpointInput:
    """검증된 입력과 세션 쿠키를 기록할 응답 헤더."""

    body: dict[str, Any]
    files: list[dict[str, Any]]
    query: dict[str, Any]
    response: Response


EndpointAction = Callable[[Context, EndpointInput], Any]


async def run_endpoint(request: Request, action: EndpointAction) -> Response:
    """선언된 엔드포인트의 업무 함수를 하나의 DB 트랜잭션에서 실행한다.

    인증을 본문 파싱보다 먼저 확인하고, 동기 DB·파일 작업은 스레드풀에서 실행한다.
    계약 데이터는 입력 검증과 응답 투영에만 사용하며 처리 함수는 라우터가 전달한다.
    """
    settings = request.app.state.settings
    factory = request.app.state.factory
    route = request.scope["route"]
    endpoint = endpoint_contract(request.method, route.path_format, route.status_code)

    def identify():
        with factory() as db:
            actor = authenticate(db, request.cookies.get(settings.session_cookie))
            request.state.user_id = actor.account_id if actor else None
            if endpoint["authenticated"]:
                require_actor(actor)

    if endpoint["authenticated"] or request.cookies.get(settings.session_cookie):
        await run_in_threadpool(identify)
    body, files, query = await parse_request(request, endpoint)
    return await run_in_threadpool(
        process_request, request, endpoint, body, files, query, settings, factory, action,
    )


def error_response(error):
    return JSONResponse(error.body(), status_code=error.status)


def fingerprint(body, files, query):
    value = {
        "body": body,
        "query": query,
        "files": [
            {
                "part": file["part"],
                "filename": file["filename"],
                "digest": hashlib.sha256(file["bytes"]).hexdigest(),
            }
            for file in files
        ],
    }
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


async def parse_request(request, endpoint):
    query = {}
    for key, value in request.query_params.multi_items():
        require(key not in query, "BAD_REQUEST", "쿼리 키가 중복되었습니다.", 400)
        field = next((f for f in endpoint["query"] if f["name"] == key), None)
        require(field, "VALIDATION_ERROR", "정의되지 않은 쿼리입니다.", 422)
        if field["type"] == "integer":
            require(re.fullmatch(r"[0-9]+", value), "VALIDATION_ERROR", "정수 쿼리가 필요합니다.", 422)
            value = int(value)
        query[key] = value
    validate_object(query, endpoint["query"])
    files, body = [], {}
    if endpoint["multipart"]:
        require(
            request.headers.get("content-type", "").startswith("multipart/form-data"),
            "UNSUPPORTED_MEDIA_TYPE",
            "multipart/form-data가 필요합니다.",
            415,
        )
        async with request.form(max_files=5, max_fields=4) as form:
            for key, value in form.multi_items():
                if isinstance(value, UploadFile):
                    require(key in ("file", "files"), "BAD_REQUEST", "정의되지 않은 파일 파트입니다.", 400)
                    require(key == "files" or not files, "BAD_REQUEST", "단일 파일 파트가 중복되었습니다.", 400)
                    data = await value.read(10_000_001)
                    require(
                        len(data) <= 10_000_000,
                        "FILE_TOO_LARGE",
                        "사진은 10,000,000 Byte 이하여야 합니다.",
                        413,
                    )
                    files.append({"part": key, "filename": value.filename, "bytes": data})
                else:
                    require(
                        key not in body and len(value) <= 1_000_000,
                        "BAD_REQUEST",
                        "Form 필드가 중복되었거나 너무 큽니다.",
                        400,
                    )
                    body[key] = value
            present = {f["part"] for f in files} | set(body)
            required = {f["name"] for f in endpoint["body"] if f["required"]}
            known = {f["name"] for f in endpoint["body"]}
            require(required <= present <= known, "VALIDATION_ERROR", "필수 파트 또는 파트 이름을 확인하세요.", 422)
            for key in ("metadata", "source"):
                if key in body:
                    body[key] = load_json(body[key])
    elif endpoint["body"]:
        require(
            request.headers.get("content-type", "").split(";", 1)[0].strip() == "application/json",
            "UNSUPPORTED_MEDIA_TYPE",
            "application/json이 필요합니다.",
            415,
        )
        data = await request.body()
        require(len(data) <= 1_000_000, "PAYLOAD_TOO_LARGE", "JSON 본문이 너무 큽니다.", 413)
        body = load_json(data)
        validate_object(body, endpoint["body"])
    return body, files, query


def process_request(request, endpoint, body, files, query, settings, factory, action):
    ctx = None
    try:
        with factory() as db, db.begin():
            if endpoint["method"] != "GET":
                lock(db, request.url.path)
                if endpoint["path"] == "/auth/signup" and db.bind.dialect.name == "sqlite":
                    # 중복 조회 전에 쓰기 잠금을 확보해 동시 가입이 503 대신 409가 되도록 한다.
                    db.execute(text("BEGIN IMMEDIATE"))
            actor = authenticate(db, request.cookies.get(settings.session_cookie))
            request.state.user_id = actor.account_id if actor else None
            if endpoint["authenticated"]:
                require_actor(actor)
            ctx = Context(db, actor, settings)
            ctx.path_params = request.path_params
            idem = None
            if endpoint["idempotent"]:
                key = request.headers.get("idempotency-key", "")
                require(
                    len(key) <= 256 and re.fullmatch(r'"[\x20-\x21\x23-\x7e]+"', key),
                    "INVALID_IDEMPOTENCY_KEY",
                    "큰따옴표로 감싼 ASCII 멱등 키가 필요합니다.",
                    400,
                )
                digest = fingerprint(body, files, query)
                idem = db.scalar(
                    select(Idempotency).where(
                        Idempotency.account_id == actor.account_id,
                        Idempotency.method == endpoint["method"],
                        Idempotency.path == request.url.path,
                        Idempotency.key == key,
                    )
                )
                if idem:
                    require(
                        idem.fingerprint == digest,
                        "IDEMPOTENCY_KEY_REUSED",
                        "다른 요청 내용에 같은 키를 재사용할 수 없습니다.",
                    )
                    require(
                        idem.result is not None,
                        "IDEMPOTENCY_IN_PROGRESS",
                        "처리 결과 확인 중입니다.",
                        retryable=True,
                    )
                    result = replay(ctx, endpoint, idem.result, request.path_params)
                    if isinstance(result, Response):
                        return result
                    return JSONResponse(
                        {"data": project_output(result, endpoint["response"])},
                        endpoint["status"],
                    )
                idem = Idempotency(
                    account_id=actor.account_id,
                    method=endpoint["method"],
                    path=request.url.path,
                    key=key,
                    fingerprint=digest,
                    result=None,
                )
                db.add(idem)
                db.flush()
            headers = Response()
            try:
                with db.begin_nested():
                    result = action(
                        ctx,
                        EndpointInput(body=body, files=files, query=query, response=headers),
                    )
                    if endpoint["response"] and not isinstance(result, Response):
                        result = project_output(result, endpoint["response"])
                    if ctx.obsolete_files:
                        cleanup = ctx.create("FILE_CLEANUP", {"error": None}, status="QUEUED")
                        ctx.enqueue(
                            cleanup,
                            "DELETE",
                            {
                                "resourceIds": [],
                                "fileKeys": ctx.obsolete_files,
                                "photoCount": 0,
                            },
                        )
                    db.flush()
            except DomainError as error:
                for key in ctx.new_files:
                    ctx.files.delete(key)
                ctx.new_files.clear()
                ctx.obsolete_files.clear()
                if idem and error.status in (409, 422):
                    idem.result = {
                        "role": actor.role,
                        "error": error.body(),
                        "status": error.status,
                    }
                    return error_response(error)
                raise
            if idem:
                if isinstance(result, Response) and result.status_code >= 400:
                    idem.result = {
                        "role": actor.role,
                        "error": json.loads(result.body),
                        "status": result.status_code,
                    }
                else:
                    idem.result = {
                        "role": actor.role,
                        **replay_locator(endpoint["response"], result, request.path_params),
                    }
            if ctx.actor:
                request.state.user_id = ctx.actor.account_id
            if isinstance(result, Response):
                response = result
            elif endpoint["status"] == 204:
                response = Response(status_code=204)
            else:
                response = JSONResponse({"data": result}, endpoint["status"])
            for key, value in headers.raw_headers:
                if key == b"set-cookie":
                    response.raw_headers.append((key, value))
        # Old file cleanup is durable and retryable; committed new files survive
        # a later cleanup failure or response disconnect.
        ctx.new_files.clear()
        return response
    except Exception:
        if ctx:
            for key in ctx.new_files:
                ctx.files.delete(key)
        raise


class RequestBoundary:
    """본문 스트리밍 상한과 브라우저의 교차 출처 상태 변경 방지."""

    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode(): v.decode("latin-1") for k, v in scope["headers"]}
        if scope["method"] not in ("GET", "HEAD", "OPTIONS"):
            origin_mismatch = (
                headers.get("origin") and headers["origin"] != self.settings.public_origin
            )
            if origin_mismatch or headers.get("sec-fetch-site") == "cross-site":
                response = error_response(
                    DomainError("ORIGIN_FORBIDDEN", "허용되지 않은 요청 출처입니다.", 403)
                )
                return await response(scope, receive, send)
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > 51_000_000:
                raise DomainError("PAYLOAD_TOO_LARGE", "요청 크기 제한을 초과했습니다.", 413)
            return message

        await self.app(scope, bounded_receive, send)
