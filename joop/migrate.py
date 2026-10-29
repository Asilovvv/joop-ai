"""Database migrations (Alembic), run from code so no alembic.ini is needed.

    python -m joop migrate                     # bring the database to the latest schema
    python -m joop make-migration "add x"      # developers: generate a migration from model changes
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .db import get_engine

MIGRATIONS = Path(__file__).parent / "migrations"


def _config(connection=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def upgrade() -> None:
    """Apply pending migrations. A database created before migrations existed is marked as baseline."""
    engine = get_engine()
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        cfg = _config(conn)
        if "business" in tables and "alembic_version" not in tables:
            command.stamp(cfg, "0001")
        command.upgrade(cfg, "head")


def make_migration(message: str) -> None:
    with get_engine().begin() as conn:
        command.revision(_config(conn), message=message, autogenerate=True)
