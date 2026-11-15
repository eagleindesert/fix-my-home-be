"""온라인 마이그레이션은 배포 CLI가 확보한 연결·잠금을 재사용한다."""

from alembic import context

from app.config import get_settings
from app.db import Base, engine

config = context.config


def migrate(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True,
                      compare_server_default=True, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=get_settings().database_url.get_secret_value(), target_metadata=Base.metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    migrate(config.attributes["connection"])
else:
    with engine().connect() as connection:
        migrate(connection)
