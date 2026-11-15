"""배포 전용 진입점. 운영 자동 downgrade와 create_all을 사용하지 않는다."""

from alembic import command
from sqlalchemy import text

from app.db import engine
from app.schema import alembic_config, validate_schema


def main():
    from app.runtime import validate_runtime
    validate_runtime()
    with engine().connect() as connection:
        postgres = connection.dialect.name == "postgresql"
        if postgres:
            connection.execute(text("SELECT pg_advisory_lock(618102474)"))
            connection.commit()
        try:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()
            validate_schema(connection)
        finally:
            if postgres:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(618102474)"))
                connection.commit()


if __name__ == "__main__":
    main()
