"""Short API-side recovery and local-retention maintenance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import exists, or_, select, update

from app.config import get_settings
from app.db.models import Check, Document, DocumentVersion, Run, RunDocument
from app.db.session import SessionLocal
from app.services.admission import begin_immediate


def maintenance_sweep(
    *,
    session_factory: Any = SessionLocal,
    now: datetime | None = None,
    data_dir: Path | None = None,
) -> None:
    current = now or datetime.now(UTC)
    artifact_root = (data_dir or get_settings().data_dir).resolve()
    interrupted_error = {
        "code": "WORKER_INTERRUPTED",
        "message": "The worker stopped before this run completed.",
        "retryable": True,
    }
    queue_error = {
        "code": "QUEUE_EXPIRED",
        "message": "The queued run expired before a worker could claim it.",
        "retryable": True,
    }
    with session_factory() as session:
        begin_immediate(session)
        session.execute(
            update(Run)
            .where(
                Run.status == "running",
                or_(
                    Run.heartbeat_at < current - timedelta(seconds=60),
                    (
                        Run.heartbeat_at.is_(None)
                        & (Run.started_at < current - timedelta(seconds=60))
                    ),
                ),
            )
            .values(
                status="interrupted",
                stage="finished",
                owner_token=None,
                finished_at=current,
                error_json=interrupted_error,
            )
        )
        session.execute(
            update(Run)
            .where(
                Run.status == "queued",
                Run.created_at < current - timedelta(minutes=10),
            )
            .values(
                status="failed",
                stage="finished",
                finished_at=current,
                error_json=queue_error,
            )
        )
        expired = session.scalars(
            select(Check).where(
                Check.saved_at.is_(None),
                Check.expires_at.is_not(None),
                Check.expires_at < current,
            )
        ).all()
        for check in expired:
            if not any(run.status in {"queued", "running"} for run in check.runs):
                session.delete(check)
        session.flush()

        unreferenced_versions = session.scalars(
            select(DocumentVersion).where(
                ~exists().where(RunDocument.document_version_id == DocumentVersion.id)
            )
        ).all()
        for version in unreferenced_versions:
            paths = [Path(version.original_path), Path(version.parsed_blocks_path)]
            if all(_remove_artifact(path, artifact_root) for path in paths):
                session.delete(version)
        session.flush()

        orphaned_documents = session.scalars(
            select(Document).where(~exists().where(DocumentVersion.document_id == Document.id))
        ).all()
        for document in orphaned_documents:
            session.delete(document)
        session.commit()


def _remove_artifact(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            return False
        resolved.unlink(missing_ok=True)
    except OSError:
        return False
    return True
