"""Deterministic report contracts."""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.schemas.extraction import EvidenceReference


class Coverage(StrEnum):
    COMPLETE_FOR_ATTEMPTED_SCOPE = "complete_for_attempted_scope"
    PARTIAL = "partial"


class DeadlineResolution(StrEnum):
    SUPPORTED = "supported"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient"


class ReportProvenance(BaseModel):
    rules_version: str
    schema_version: str
    input_mode: str


class ReportRead(BaseModel):
    run_id: str
    coverage: Coverage
    deadline_resolution: DeadlineResolution
    evidence_refs: list[EvidenceReference] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    provenance: ReportProvenance
