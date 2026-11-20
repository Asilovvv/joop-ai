"""Database engine and sessions."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(get_settings().database_url)
    return _engine


def set_engine(engine: Engine) -> None:
    """Swap the engine (used by tests)."""
    global _engine
    _engine = engine


def init_db() -> None:
    """Create or upgrade the schema through migrations (joop/migrations)."""
    from .migrate import upgrade

    upgrade()


def free(session: Session) -> None:
    """Commit what is decided so far, before waiting for anyone else: the model, a messenger, a booking system.

    SQLite lets one connection write at a time, from its first write until commit. A network call inside that stops
    every other writer on the server (every business's customers, the panel, the scheduler) for as long as the other
    side takes to answer, and after 15 seconds they fail with «database is locked». So: store, then send. It also
    means a failure later in the same job cannot undo the mark of a message that already went out.
    A session that must stay one unit, rolled back whole by its caller, sets session.info["atomic"] (joop/pitch.py)."""
    if not session.info.get("atomic"):
        session.commit()


def new_session() -> Session:
    # Objects stay usable after commit; we pass them to background delivery code.
    return Session(get_engine(), expire_on_commit=False)
