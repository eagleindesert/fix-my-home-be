"""별도 PostgreSQL 서비스가 있을 때 실행하는 실제 경합·부분 인덱스 검증."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db import Account, Resource, lock, uid
from app.schema import alembic_config, validate_schema


@pytest.fixture
def postgres():
    url = os.environ.get("FMH_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("FMH_TEST_POSTGRES_URL이 없어 실제 PostgreSQL 경합 검증 미실행")
    schema = "test_"+uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            validate_schema(connection)
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def resources(factory):
    with factory() as db, db.begin():
        account = Account(id=uid(), login_id="concurrency", password_hash="test-not-used", roles=["USER"])
        db.add(account)
        db.flush()
        item = Resource(id=uid(), kind="WORK_ITEM", owner_id=account.id)
        tech = Resource(id=uid(), kind="TECHNICIAN", owner_id=account.id)
        db.add_all([item, tech])
        db.flush()
        return account.id, item.id, tech.id


def test_postgres_transaction_gate_serializes_competing_confirmations(postgres):
    account, item, tech = resources(postgres)
    barrier = Barrier(2)
    def reserve(_):
        with postgres() as db, db.begin():
            barrier.wait(timeout=10)
            lock(db, item, tech)
            active = db.scalar(select(Resource).where(Resource.kind == "RESERVATION", Resource.item_id == item))
            if active:
                return "conflict"
            db.add(Resource(kind="RESERVATION", owner_id=account, item_id=item, technician_id=tech, status="CONFIRMED"))
            db.flush()
            return "created"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(reserve, range(2))) == ["conflict", "created"]


def test_postgres_unique_index_guards_bypassed_application_check(postgres):
    account, item, tech = resources(postgres)
    with postgres() as db, db.begin():
        db.add(Resource(kind="RESERVATION", owner_id=account, item_id=item, technician_id=tech, status="CONFIRMED"))
    with pytest.raises(IntegrityError), postgres() as db, db.begin():
        db.add(Resource(kind="RESERVATION", owner_id=account, item_id=item, technician_id=tech, status="CONFIRMED"))


def test_postgres_changed_partial_predicate_is_rejected(postgres):
    with postgres() as db, db.begin():
        db.execute(text("DROP INDEX one_running_work_per_technician"))
        db.execute(text("CREATE UNIQUE INDEX one_running_work_per_technician ON resources (technician_id) WHERE kind = 'RESERVATION' AND status = 'IN_PROGRESS'"))
        with pytest.raises(RuntimeError):
            validate_schema(db.connection())
