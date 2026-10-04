"""Readiness route for the frontend and local operator."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import WorkerState
from app.db.session import get_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database_ready: bool
    worker_ready: bool
    worker_heartbeat_at: datetime | None
    live_search_enabled: bool
    live_extraction_enabled: bool
    replay_enabled: bool


@router.get("/health", response_model=HealthResponse)
async def health(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    database_ready = True
    worker = None
    try:
        session.execute(text("SELECT 1"))
        worker = session.get(WorkerState, 1)
    except Exception:  # noqa: BLE001 - health must return a safe degraded response.
        session.rollback()
        database_ready = False

    heartbeat = worker.heartbeat_at if worker else None
    if heartbeat and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    worker_ready = bool(heartbeat and heartbeat >= datetime.now(UTC) - timedelta(seconds=15))
    status = "ok" if database_ready else "degraded"
    return HealthResponse(
        status=status,
        database_ready=database_ready,
        worker_ready=worker_ready,
        worker_heartbeat_at=heartbeat,
        live_search_enabled=settings.live_search_enabled,
        live_extraction_enabled=settings.live_extraction_enabled,
        replay_enabled=True,
    )
