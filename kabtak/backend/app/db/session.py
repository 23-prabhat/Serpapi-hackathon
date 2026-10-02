"""Shared SQLAlchemy engine and session factory."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(Engine, "connect")
def set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
