"""공개 회원가입과 운영자 계정 발급에 공통으로 사용하는 계정 생성 규칙."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import Account, uid
from app.errors import DomainError, invalid, require
from app.security import Actor, hash_password
from app.services.context import Context


def create_account(db, settings, login_id, password, roles):
    if not isinstance(login_id, str) or not 1 <= len(login_id) <= 128:
        invalid("로그인 ID는 1~128자여야 합니다.", "loginId")
    if login_id != login_id.strip():
        invalid("로그인 ID 앞뒤에 공백을 넣을 수 없습니다.", "loginId")
    if not isinstance(password, str) or not password.strip() or len(password) < 12:
        invalid("비밀번호는 12자 이상이어야 합니다.", "password")
    require(roles and set(roles) <= {"USER", "TECHNICIAN"},
            "VALIDATION_ERROR", "계정 역할을 확인하세요.", 422)

    existing = select(Account.id).where(Account.login_id == login_id)
    require(db.scalar(existing) is None, "ACCOUNT_EXISTS", "이미 사용 중인 로그인 ID입니다.")
    account = Account(
        id=uid(), login_id=login_id, password_hash=hash_password(password), roles=roles,
    )
    try:
        # 사전 검사 이후 경쟁 삽입도 DB 유일 제약으로 막고 같은 중복 오류로 반환한다.
        with db.begin_nested():
            db.add(account)
            db.flush()
    except IntegrityError:
        if db.scalar(existing) is not None:
            raise DomainError("ACCOUNT_EXISTS", "이미 사용 중인 로그인 ID입니다.") from None
        raise

    if "TECHNICIAN" in roles:
        ctx = Context(db, Actor(account.id, "TECHNICIAN", None, None), settings)
        ctx.create("TECHNICIAN", {
            "profile": {
                "displayName": login_id, "fields": [], "regionIds": [],
                "contacts": [], "representativeMediaIds": [],
            },
        })
    return account
