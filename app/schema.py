"""마이그레이션 revision과 ORM 정의의 불일치를 기동 전에 차단한다."""

from pathlib import Path
import re

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from app.db import Base


def alembic_config():
    return Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))


def validate_schema(connection):
    migration = MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True})
    expected = set(ScriptDirectory.from_config(alembic_config()).get_heads())
    if set(migration.get_current_heads()) != expected or not expected:
        raise RuntimeError("DB 마이그레이션 revision이 실행 이미지와 일치하지 않습니다.")
    differences = compare_metadata(migration, Base.metadata)
    if differences:
        raise RuntimeError("DB 스키마와 ORM 정의가 일치하지 않습니다.")
    inspector = inspect(connection)
    for name, table in Base.metadata.tables.items():
        present = {check["name"]: check["sqltext"] for check in inspector.get_check_constraints(name)}
        for constraint in table.constraints:
            if constraint.__class__.__name__ == "CheckConstraint":
                normalize = lambda value: re.sub(r'[\s()"]', '', str(value)).lower()
                if constraint.name not in present or normalize(present[constraint.name]) != normalize(constraint.sqltext):
                    raise RuntimeError(f"DB CHECK 제약이 누락되었거나 변경되었습니다: {name}")
    if connection.dialect.name == "postgresql":
        indexes = {i["name"]: i for i in inspector.get_indexes("resources")}
        for name in ("one_active_reservation_per_item", "one_running_work_per_technician"):
            index = indexes.get(name, {})
            if not index.get("unique") or not index.get("dialect_options", {}).get("postgresql_where"):
                raise RuntimeError(f"활성 예약 부분 유일 인덱스가 잘못되었습니다: {name}")
            expected_index = next(i for i in Base.metadata.tables["resources"].indexes if i.name == name)
            expected_values = set(re.findall(r"'([^']+)'", str(expected_index.dialect_options["postgresql"]["where"])))
            actual_values = set(re.findall(r"'([^']+)'", index["dialect_options"]["postgresql_where"]))
            if actual_values != expected_values:
                raise RuntimeError(f"활성 예약 인덱스 조건이 변경되었습니다: {name}")
