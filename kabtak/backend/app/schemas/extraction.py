"""Profile-independent structured extraction contracts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: str
    block_id: str


class DeadlineActor(StrEnum):
    STUDENT = "student"
    INSTITUTION = "institution"
    ADMINISTRATOR = "administrator"
    UNKNOWN = "unknown"


class DeadlineAction(StrEnum):
    SUBMIT = "submit"
    CORRECT = "correct"
    VERIFY = "verify"
    OTHER = "other"
    UNKNOWN = "unknown"


class ExtractedDeadline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: DeadlineActor
    action: DeadlineAction
    date_raw: str
    date_iso: str | None = None
    time: str | None = None
    timezone: str | None = None
    applies_to: str | None = None
    evidence_refs: list[EvidenceReference] = Field(min_length=1)
