"""FastAPI 앱 구성: 업무별 라우터·예외 처리·상태 확인·미들웨어."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.config import get_settings
from app.db import session_factory
from app.errors import DomainError
from app.http import RequestBoundary, error_response
from app.observability import AccessLogMiddleware, configure_logging
from app.openapi import API_DESCRIPTION, SWAGGER_UI_PARAMETERS, enrich_openapi
from app.routers import api_router
from app.runtime import validate_runtime
from app.schema import validate_schema


def create_app(settings=None, factory=None):
    validate_runtime()
    settings, factory = settings or get_settings(), factory or session_factory()
    logger = configure_logging(settings)
    app = FastAPI(
        title="고쳐야집 Backend API",
        version="v1.1",
        description=API_DESCRIPTION,
        docs_url="/docs",
        openapi_url="/openapi.json",
        redoc_url=None,
        redirect_slashes=False,
        root_path=settings.root_path,
        servers=[{"url": settings.root_path}] if settings.root_path else [],
        swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
    )
    app.state.settings, app.state.factory = settings, factory

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return error_response(error)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return error_response(
            DomainError(
                "RESOURCE_NOT_FOUND" if error.status_code == 404 else "HTTP_ERROR",
                "요청 경로·메서드·전송 형식을 확인하세요.",
                error.status_code,
            )
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return error_response(DomainError("VALIDATION_ERROR", "입력 형식을 확인하세요.", 422))

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        # Exception text/SQL parameters can contain request bodies or credentials.
        logger.error(
            "request_failed",
            extra={
                "fields": {
                    "errorType": type(error).__name__,
                    "requestId": getattr(request.state, "request_id", None),
                }
            },
        )
        if isinstance(error, IntegrityError):
            return error_response(DomainError("VERSION_CONFLICT", "동시 변경 또는 중복 예약을 확인하세요."))
        database_error = isinstance(error, SQLAlchemyError)
        return error_response(
            DomainError(
                "SERVICE_UNAVAILABLE" if database_error else "INTERNAL_ERROR",
                "처리를 완료하지 못했습니다.",
                503 if database_error else 500,
                retryable=True,
            )
        )

    @app.get("/health/live", include_in_schema=False)
    def live():
        return {"status": "live"}

    @app.get("/health/ready", include_in_schema=False)
    def ready():
        try:
            with factory() as db:
                validate_schema(db.connection())
            return {"status": "ready"}
        except Exception:
            return JSONResponse({"status": "not_ready"}, 503)

    app.include_router(api_router)

    def openapi():
        if app.openapi_schema is None:
            app.openapi_schema = enrich_openapi(
                get_openapi(
                    title=app.title,
                    version=app.version,
                    description=app.description,
                    routes=app.routes,
                    servers=app.servers,
                ),
                settings,
                app.routes,
            )
        return app.openapi_schema

    app.openapi = openapi
    app.add_middleware(RequestBoundary, settings=settings)
    app.add_middleware(
        AccessLogMiddleware,
        settings=settings,
        logger=logger,
        error_handler=unexpected_error,
    )
    return app


app = create_app()
