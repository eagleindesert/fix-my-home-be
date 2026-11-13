"""세션 토큰은 해시만 저장하고 계정과 활성 역할을 독립적으로 검사한다."""

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from app.db import Account, LoginSession, Resource, now
from app.errors import require


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return "scrypt$" + base64.b64encode(salt + digest).decode()


def verify_password(password: str, encoded: str) -> bool:
    try:
        raw = base64.b64decode(encoded.split("$", 1)[1], validate=True)
        digest = hashlib.scrypt(password.encode(), salt=raw[:16], n=16384, r=8, p=1)
        return hmac.compare_digest(raw[16:], digest)
    except (ValueError, IndexError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Actor:
    account_id: str
    role: str
    technician_id: str | None
    session: LoginSession


def authenticate(db, token):
    session = db.get(LoginSession, token_hash(token)) if token else None
    if session is None:
        return None
    from app.time_rules import as_utc
    if as_utc(session.expires_at) <= now():
        return None
    technician = db.scalar(select(Resource).where(
        Resource.kind == "TECHNICIAN", Resource.owner_id == session.account_id
    ))
    return Actor(session.account_id, session.role, technician.id if technician else None, session)


def new_session(db, account: Account, settings, role="USER"):
    token = secrets.token_urlsafe(48)
    session = LoginSession(token_hash=token_hash(token), account_id=account.id,
                           role=role, expires_at=now() + timedelta(hours=settings.session_hours))
    db.add(session)
    return token, session


def require_actor(actor, role=None):
    require(actor is not None, "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.", 401)
    if role:
        require(actor.role == role, "ROLE_FORBIDDEN", "현재 역할로 실행할 수 없습니다.", 403)


def session_dto(db, actor):
    account = db.get(Account, actor.account_id)
    return {"accountId": account.id, "activeRole": actor.role,
            "availableRoles": account.roles, "technicianId": actor.technician_id}
