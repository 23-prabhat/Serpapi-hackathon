"""Persisted run lifecycle contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.extraction import EvidenceReference


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
    kind: str
    status: RunStatus
    stage: RunStage
    reference_time: datetime
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    heartbeat_at: datetime | None = None
    retry_of_run_id: str | None = None
    report_available: bool = False
    error: dict[str, Any] | None = None


class FactChangeRead(BaseModel):
    kind: str
    fact_key: str
    before: Any | None = None
    after: Any | None = None
    before_evidence: list[EvidenceReference] = Field(default_factory=list)
    after_evidence: list[EvidenceReference] = Field(default_factory=list)


class RunComparisonRead(BaseModel):
    run_id: str
    previous_run_id: str | None
    classification: str
    summary: str
    outcome_changed: bool
    source_versions_changed: bool
    profile_changed: bool
    software_versions_changed: bool
    changes: list[FactChangeRead] = Field(default_factory=list)
