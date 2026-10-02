"""Persisted run lifecycle contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RunStage(StrEnum):
    QUEUED = "queued"
    SEARCHING = "searching"
    FETCHING = "fetching"
    EXTRACTING = "extracting"
    CHECKING = "checking"
    FINALIZING = "finalizing"
    FINISHED = "finished"


class RunRead(BaseModel):
    id: str
    check_id: str
    status: RunStatus
    stage: RunStage
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
