"""Alembic environment: uses the app's engine and the SQLModel metadata."""

from alembic import context
from sqlmodel import SQLModel

from joop import models  # noqa: F401  (register tables)
from joop.db import get_engine

target_metadata = SQLModel.metadata


def run() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _configure(connection)
        return
    with get_engine().connect() as conn:
        _configure(conn)


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite cannot ALTER most columns
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run()
