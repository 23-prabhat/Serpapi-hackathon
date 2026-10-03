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
    BEFORE_CUTOFF = "before_cutoff"
    AFTER_CUTOFF = "after_cutoff"
    UNKNOWN = "unknown"


class EligibilityResolution(StrEnum):
    MEETS_CHECKED_CONDITIONS = "meets_checked_conditions"
    CONDITION_NOT_MET = "condition_not_met"
    MORE_INFORMATION_NEEDED = "more_information_needed"
    NOT_ASSESSED = "not_assessed"


class ScopeRead(BaseModel):
    programme_id: str
    programme_name: str
    academic_year: str
    application_type: str
    applicant_group: str | None = None


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


class RequiredDocumentRead(BaseModel):
    source_text: str
    evidence_refs: list[EvidenceReference] = Field(min_length=1)


class ApplicationLinkRead(BaseModel):
    url: str
    source_text: str
    evidence_refs: list[EvidenceReference] = Field(min_length=1)


class ReportRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: str
    reference_time: datetime
    coverage: Coverage
    scope: ScopeRead
    deadline_resolution: DeadlineResolution
    student_deadline: DeadlineRead | None
    summary: str
    portal_status: str
    eligibility: EligibilityResolution
    conditions: list[dict[str, object]] = Field(default_factory=list)
    other_deadlines: list[DeadlineRead] = Field(default_factory=list)
    conflicts: list[dict[str, object]] = Field(default_factory=list)
    amendments: list[dict[str, object]] = Field(default_factory=list)
    required_documents: list[RequiredDocumentRead] = Field(default_factory=list)
    application_links: list[ApplicationLinkRead] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance: ReportProvenance


class EvidenceRead(BaseModel):
    version_id: str
    block_id: str
    kind: str
    location: str
    text: str
    metadata: dict[str, object] = Field(default_factory=dict)
    content_sha256: str
    block_sha256: str
    retrieved_at: datetime
    parse_status: str
    parser_version: str
    source_url: str
    publisher_role: str
