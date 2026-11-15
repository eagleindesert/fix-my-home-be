"""Authentication API: 경로·설명·업무 처리를 엔드포인트별로 정의한다."""

from fastapi import APIRouter, Request
from sqlalchemy import select
from starlette.responses import Response

from app.db import Account
from app.errors import require
from app.http import EndpointInput, run_endpoint
from app.security import Actor, new_session, session_dto, verify_password
from app.services import accounts
from app.services.context import Context


router = APIRouter(tags=["Authentication"])


@router.post(
    "/auth/signup",
    summary="일반 사용자 회원가입",
    description=(
        "- **인증 요구사항**: ❌\n"
        "- **선행 조건**: 사용하지 않은 로그인 ID\n"
        "- **설명**: 로그인 ID와 비밀번호로 일반 사용자 계정을 생성한다. 이메일·휴대전화 인증이나 운영자 승인 절차는 없다. 계정에는 `USER` "
        "역할만 부여하며 역할 입력은 허용하지 않는다. 가입 후 `POST /auth/login`으로 로그인한다. 가입 자체로 세션 쿠키를 발급하거나 기존 "
        "로그인 세션을 변경하지 않는다.\n"
        "\n"
        "**처리 규칙**\n"
        "\n"
        "`Idempotency-Key`는 필요하지 않다. 동일 ID로 다시 요청하면 비밀번호 일치 여부와 관계없이 `409 ACCOUNT_EXISTS`를 "
        "반환한다. 동시 가입 요청에서도 같은 ID의 계정은 하나만 생성된다."
    ),
    status_code=201,
    operation_id="api_01_v1_auth_signup_post",
)
async def signup(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        account = accounts.create_account(
            ctx.db,
            ctx.settings,
            inputs.body["loginId"],
            inputs.body["password"],
            ["USER"],
        )
        return {
            "accountId": account.id,
            "loginId": account.login_id,
            "availableRoles": account.roles,
        }

    return await run_endpoint(request, operation)


@router.post(
    "/auth/login",
    summary="계정 로그인",
    description=(
        "- **인증 요구사항**: ❌\n"
        "- **선행 조건**: 가입 또는 사전 발급한 계정\n"
        "- **설명**: 계정으로 로그인하고 세션 쿠키와 계정·역할 정보를 반환한다."
    ),
    status_code=200,
    operation_id="api_02_v1_auth_login_post",
)
async def login(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        account = ctx.db.scalar(select(Account).where(Account.login_id == inputs.body["loginId"]))
        require(
            account and verify_password(inputs.body["password"], account.password_hash),
            "INVALID_CREDENTIALS",
            "로그인 정보를 확인하세요.",
            401,
        )
        if ctx.actor:
            ctx.db.delete(ctx.actor.session)
        token, session = new_session(ctx.db, account, ctx.settings, account.roles[0])
        tech = next(iter(ctx.find("TECHNICIAN", owner_id=account.id)), None)
        ctx.actor = Actor(account.id, session.role, tech.id if tech else None, session)
        inputs.response.set_cookie(
            ctx.settings.session_cookie,
            token,
            max_age=ctx.settings.session_hours * 3600,
            httponly=True,
            secure=ctx.settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        return session_dto(ctx.db, ctx.actor)

    return await run_endpoint(request, operation)


@router.post(
    "/auth/logout",
    summary="로그아웃",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 계정 본인\n"
        "- **설명**: 현재 세션을 종료하고 로그인 쿠키를 만료시킨다. 요청 본문은 없다."
    ),
    status_code=204,
    operation_id="api_03_v1_auth_logout_post",
)
async def logout(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        ctx.db.delete(ctx.actor.session)
        inputs.response.delete_cookie(
            ctx.settings.session_cookie,
            path="/",
            secure=ctx.settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return None

    return await run_endpoint(request, operation)


@router.get(
    "/auth/me",
    summary="현재 계정·역할 조회",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 계정 본인\n"
        "- **설명**: 현재 계정·활성 역할·연결 기사 식별자를 반환한다."
    ),
    status_code=200,
    operation_id="api_04_v1_auth_me_get",
)
async def get_session(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        return session_dto(ctx.db, ctx.actor)

    return await run_endpoint(request, operation)


@router.patch(
    "/auth/role",
    summary="활성 역할 전환",
    description=(
        "- **인증 요구사항**: ✅\n"
        "- **선행 조건**: 계정 본인\n"
        "- **설명**: 허용 역할 중 선택한 활성 역할과 계정 정보를 반환한다."
    ),
    status_code=200,
    operation_id="api_05_v1_auth_role_patch",
)
async def switch_role(request: Request) -> Response:
    def operation(ctx: Context, inputs: EndpointInput):
        account = ctx.db.get(Account, ctx.actor.account_id)
        require(inputs.body["role"] in account.roles, "ROLE_FORBIDDEN", "계정에 허용되지 않은 역할입니다.", 403)
        ctx.actor.session.role = ctx.actor.role = inputs.body["role"]
        return session_dto(ctx.db, ctx.actor)

    return await run_endpoint(request, operation)
