"""Short SQLite write transactions used for run admission."""

from sqlalchemy.orm import Session


def begin_immediate(session: Session) -> None:
    """Serialize admission checks with their insert on the local SQLite database."""
    bind = session.get_bind()
    if bind.dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
