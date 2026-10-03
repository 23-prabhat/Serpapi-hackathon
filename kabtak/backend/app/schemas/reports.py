"""Deterministic report and evidence contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.extraction import DeadlineAction, DeadlineActor, EvidenceReference


class Coverage(StrEnum):
    COMPLETE_FOR_ATTEMPTED_SCOPE = "complete_for_attempted_scope"
    PARTIAL = "partial"


class DeadlineResolution(StrEnum):
    SUPPORTED = "supported"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient"


class DeadlineTiming(StrEnum):
    DATE_AHEAD = "date_ahead"
    DUE_TODAY_TIME_UNKNOWN = "due_today_time_unknown"
    DATE_PASSED = "date_passed"
    UNKNOWN = "unknown"


class ScopeRead(BaseModel):
    programme_id: str
    programme_name: str
    academic_year: str
    application_type: str


class DeadlineRead(BaseModel):
    actor: DeadlineActor
    action: DeadlineAction
    date: str
    time: str | None = None
    timezone: str | None = None
    comparison_timezone: str
    timing: DeadlineTiming
    evidence_refs: list[EvidenceReference] = Field(min_length=1)


class ReportProvenance(BaseModel):
    rules_version: str
    schema_version: str
    input_mode: str
    model_id: str
    prompt_hash: str


class ReportRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: str
    reference_time: datetime
    coverage: Coverage
    scope: ScopeRead
    deadline_resolution: DeadlineResolution
    student_deadline: DeadlineRead | None
    portal_status: str
    eligibility: str
    conditions: list[dict[str, object]] = Field(default_factory=list)
    other_deadlines: list[DeadlineRead] = Field(default_factory=list)
    conflicts: list[dict[str, object]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance: ReportProvenance


class EvidenceRead(BaseModel):
    version_id: str
    block_id: str
    location: str
    text: str
    source_url: str
    publisher_role: str
