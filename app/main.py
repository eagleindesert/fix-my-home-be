"""FastAPI 전송 경계: 세션, 입력 계약, 멱등성 및 원자적 업무 처리."""

import hashlib
import json
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response

from app import api
from app.config import get_settings
from app.contract_data import ENDPOINTS
from app.contracts import load_json, project_output, validate_object
from app.db import Idempotency, lock, session_factory
from app.errors import DomainError, require
from app.observability import AccessLogMiddleware, configure_logging
from app.openapi import API_DESCRIPTION, SWAGGER_UI_PARAMETERS, enrich_openapi
from app.security import authenticate, require_actor
from app.services.context import Context


def error_response(error):
    return JSONResponse(error.body(), status_code=error.status)


def fingerprint(body, files, query):
    value = {"body": body, "query": query, "files": [
        {"part": f["part"], "filename": f["filename"], "digest": hashlib.sha256(f["bytes"]).hexdigest()}
        for f in files]}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def parse(request, endpoint):
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
        require(request.headers.get("content-type", "").startswith("multipart/form-data"), "UNSUPPORTED_MEDIA_TYPE", "multipart/form-data가 필요합니다.", 415)
        async with request.form(max_files=5, max_fields=4) as form:
            for key, value in form.multi_items():
                if isinstance(value, UploadFile):
                    require(key in ("file", "files"), "BAD_REQUEST", "정의되지 않은 파일 파트입니다.", 400)
                    require(key == "files" or not files, "BAD_REQUEST", "단일 파일 파트가 중복되었습니다.", 400)
                    data = await value.read(10_000_001)
                    require(len(data) <= 10_000_000, "FILE_TOO_LARGE", "사진은 10,000,000 Byte 이하여야 합니다.", 413)
                    files.append({"part": key, "filename": value.filename, "bytes": data})
                else:
                    require(key not in body and len(value) <= 1_000_000, "BAD_REQUEST", "Form 필드가 중복되었거나 너무 큽니다.", 400)
                    body[key] = value
            present = {f["part"] for f in files} | set(body)
            required = {f["name"] for f in endpoint["body"] if f["required"]}
            known = {f["name"] for f in endpoint["body"]}
            require(required <= present <= known, "VALIDATION_ERROR", "필수 파트 또는 파트 이름을 확인하세요.", 422)
            for key in ("metadata", "source"):
                if key in body:
                    body[key] = load_json(body[key])
    elif endpoint["body"]:
        require(request.headers.get("content-type", "").split(";", 1)[0].strip() == "application/json", "UNSUPPORTED_MEDIA_TYPE", "application/json이 필요합니다.", 415)
        data = await request.body()
        require(len(data) <= 1_000_000, "PAYLOAD_TOO_LARGE", "JSON 본문이 너무 큽니다.", 413)
        body = load_json(data)
        validate_object(body, endpoint["body"])
    return body, files, query


def process(request, endpoint, body, files, query, settings, factory):
    ctx = None
    try:
        with factory() as db, db.begin():
            if endpoint["method"] != "GET":
                lock(db, request.url.path)
            actor = authenticate(db, request.cookies.get(settings.session_cookie))
            request.state.user_id = actor.account_id if actor else None
            if endpoint["authenticated"]:
                require_actor(actor)
            ctx = Context(db, actor, settings)
            ctx.path_params = request.path_params
            idem = None
            if endpoint["idempotent"]:
                key = request.headers.get("idempotency-key", "")
                require(len(key) <= 256 and re.fullmatch(r'"[\x20-\x21\x23-\x7e]+"', key), "INVALID_IDEMPOTENCY_KEY", "큰따옴표로 감싼 ASCII 멱등 키가 필요합니다.", 400)
                digest = fingerprint(body, files, query)
                idem = db.scalar(select(Idempotency).where(Idempotency.account_id == actor.account_id,
                    Idempotency.method == endpoint["method"], Idempotency.path == request.url.path, Idempotency.key == key))
                if idem:
                    require(idem.fingerprint == digest, "IDEMPOTENCY_KEY_REUSED", "다른 요청 내용에 같은 키를 재사용할 수 없습니다.")
                    require(idem.result is not None, "IDEMPOTENCY_IN_PROGRESS", "처리 결과 확인 중입니다.", retryable=True)
                    result = api.replay(ctx, endpoint, idem.result, request.path_params)
                    return result if isinstance(result, Response) else JSONResponse({"data": project_output(result, endpoint["response"])}, endpoint["status"])
                idem = Idempotency(account_id=actor.account_id, method=endpoint["method"], path=request.url.path,
                                   key=key, fingerprint=digest, result=None)
                db.add(idem)
                db.flush()
            headers = Response()
            try:
                with db.begin_nested():
                    result = api.dispatch(ctx, endpoint, request.path_params, query, body, files, headers)
                    if endpoint["response"] and not isinstance(result, Response):
                        result = project_output(result, endpoint["response"])
                    if ctx.obsolete_files:
                        cleanup = ctx.create("FILE_CLEANUP", {"error": None}, status="QUEUED")
                        ctx.enqueue(cleanup, "DELETE", {"resourceIds": [], "fileKeys": ctx.obsolete_files,
                                                        "photoCount": 0})
                    db.flush()
            except DomainError as error:
                for key in ctx.new_files:
                    ctx.files.delete(key)
                ctx.new_files.clear()
                ctx.obsolete_files.clear()
                if idem and error.status in (409, 422):
                    idem.result = {"role": actor.role, "error": error.body(), "status": error.status}
                    return error_response(error)
                raise
            if idem:
                idem.result = ({"role": actor.role, "error": json.loads(result.body), "status": result.status_code}
                               if isinstance(result, Response) and result.status_code >= 400 else
                               {"role": actor.role, **api.replay_locator(endpoint["response"], result, request.path_params)})
            if ctx.actor:
                request.state.user_id = ctx.actor.account_id
            response = result if isinstance(result, Response) else Response(status_code=204) if endpoint["status"] == 204 else JSONResponse({"data": result}, endpoint["status"])
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
            if (headers.get("origin") and headers["origin"] != self.settings.public_origin) or headers.get("sec-fetch-site") == "cross-site":
                return await error_response(DomainError("ORIGIN_FORBIDDEN", "허용되지 않은 요청 출처입니다.", 403))(scope, receive, send)
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > 51_000_000:
                raise DomainError("PAYLOAD_TOO_LARGE", "요청 크기 제한을 초과했습니다.", 413)
            return message
        await self.app(scope, bounded_receive, send)


def create_app(settings=None, factory=None):
    from app.runtime import validate_runtime
    validate_runtime()
    settings, factory = settings or get_settings(), factory or session_factory()
    logger = configure_logging(settings)
    app = FastAPI(title="고쳐야집 Backend API", version="v1.0",
                  description=API_DESCRIPTION,
                  docs_url="/docs", openapi_url="/openapi.json", redoc_url=None,
                  redirect_slashes=False,
                  root_path=settings.root_path,
                  servers=[{"url": settings.root_path}] if settings.root_path else [],
                  swagger_ui_parameters=SWAGGER_UI_PARAMETERS)
    app.state.settings, app.state.factory = settings, factory

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return error_response(error)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(DomainError("RESOURCE_NOT_FOUND" if error.status_code == 404 else "HTTP_ERROR", "요청 경로·메서드·전송 형식을 확인하세요.", error.status_code))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(DomainError("VALIDATION_ERROR", "입력 형식을 확인하세요.", 422))

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        # Exception text/SQL parameters can contain request bodies or credentials.
        logger.error("request_failed", extra={"fields": {"errorType": type(error).__name__, "requestId": getattr(request.state, "request_id", None)}})
        if isinstance(error, IntegrityError):
            return error_response(DomainError("VERSION_CONFLICT", "동시 변경 또는 중복 예약을 확인하세요."))
        return error_response(DomainError("SERVICE_UNAVAILABLE" if isinstance(error, SQLAlchemyError) else "INTERNAL_ERROR",
                                         "처리를 완료하지 못했습니다.", 503 if isinstance(error, SQLAlchemyError) else 500, retryable=True))

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"status": "live"}

    @app.get("/health/ready", include_in_schema=False)
    def ready():
        from app.schema import validate_schema
        try:
            with factory() as db:
                validate_schema(db.connection())
            return {"status": "ready"}
        except Exception:
            return JSONResponse({"status": "not_ready"}, 503)

    def handler(endpoint):
        async def route(request: Request):
            def identify():
                with factory() as db:
                    actor = authenticate(db, request.cookies.get(settings.session_cookie))
                    request.state.user_id = actor.account_id if actor else None
                    if endpoint["authenticated"]:
                        require_actor(actor)
            if endpoint["authenticated"] or request.cookies.get(settings.session_cookie):
                await run_in_threadpool(identify)
            body, files, query = await parse(request, endpoint)
            return await run_in_threadpool(process, request, endpoint, body, files, query, settings, factory)
        return route

    for index, endpoint in enumerate(ENDPOINTS, 1):
        app.add_api_route("/v1"+endpoint["path"], handler(endpoint), methods=[endpoint["method"]],
                          name=f"api_{index:02d}", summary=endpoint["summary"], status_code=endpoint["status"])

    def openapi():
        if app.openapi_schema is None:
            app.openapi_schema = enrich_openapi(
                get_openapi(title=app.title, version=app.version,
                            description=app.description, routes=app.routes,
                            servers=app.servers), settings)
        return app.openapi_schema
    app.openapi = openapi
    app.add_middleware(RequestBoundary, settings=settings)
    app.add_middleware(AccessLogMiddleware, settings=settings, logger=logger, error_handler=unexpected_error)
    return app


app = create_app()
