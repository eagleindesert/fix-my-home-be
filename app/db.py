"""관계·상태는 검색 가능한 열로, 계약 본문은 JSON으로 보관한다.

요청 aggregate와 기사 자원을 트랜잭션 잠금으로 직렬화한다. 부분 유일
인덱스는 애플리케이션 검사를 우회한 활성 예약 중복도 차단한다.
"""

from datetime import UTC, datetime
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, create_engine, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import get_settings


def now():
    return datetime.now(UTC)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


json_type = JSON().with_variant(JSONB(), "postgresql")


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    login_id: Mapped[str] = mapped_column(String(128), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    roles: Mapped[list] = mapped_column(json_type, default=lambda: ["USER"])


class LoginSession(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    request_id: Mapped[str | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[str | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    technician_id: Mapped[str | None] = mapped_column(
        ForeignKey("resources.id"), index=True
    )
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("resources.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    data: Mapped[dict] = mapped_column(json_type, default=dict)
    deleting: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    __table_args__ = (
        CheckConstraint("revision > 0", name="resource_revision_positive"),
        Index("one_active_reservation_per_item", "item_id", unique=True,
              postgresql_where=text("kind = 'RESERVATION' AND status IN ('CONFIRMED', 'IN_PROGRESS', 'STOP_REQUESTED')"),
              sqlite_where=text("kind = 'RESERVATION' AND status IN ('CONFIRMED', 'IN_PROGRESS', 'STOP_REQUESTED')")),
        Index("one_running_work_per_technician", "technician_id", unique=True,
              postgresql_where=text("kind = 'RESERVATION' AND status IN ('IN_PROGRESS', 'STOP_REQUESTED')"),
              sqlite_where=text("kind = 'RESERVATION' AND status IN ('IN_PROGRESS', 'STOP_REQUESTED')")),
    )


class StoredFile(Base):
    __tablename__ = "stored_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    resource_id: Mapped[str] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    mime: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str] = mapped_column(String(16), default="QUEUED", index=True)
    payload: Mapped[dict] = mapped_column(json_type, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Idempotency(Base):
    __tablename__ = "idempotency_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(512))
    key: Mapped[str] = mapped_column(String(256))
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict | None] = mapped_column(json_type)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint("account_id", "method", "path", "key"),)


class ReferenceData(Base):
    __tablename__ = "reference_data"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    version: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict] = mapped_column(json_type)


@lru_cache
def engine():
    url = get_settings().database_url.get_secret_value()
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **options)


def session_factory():
    return sessionmaker(engine(), expire_on_commit=False)


def lock(db, *keys):
    """모든 쓰기를 짧은 트랜잭션으로 직렬화하여 교차 요청 경합도 막는다."""
    if db.bind.dialect.name == "postgresql":
        # A global transaction gate also covers cross-request schedule/overlap races.
        # Short DB transactions never include external AI calls or PDF rendering.
        db.execute(text("SELECT pg_advisory_xact_lock(618102473)"))
