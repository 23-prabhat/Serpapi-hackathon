"""Check request and response contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.schemas.runs import RunRead


class ApplicationType(StrEnum):
    FRESH = "fresh"
    RENEWAL = "renewal"
    UNKNOWN = "unknown"


class ApplicantProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_level: str | None = None
    study_year: int | None = Field(default=None, ge=1)
    course: str | None = None
    domicile_state: str | None = None
    annual_family_income_inr: int | None = Field(default=None, ge=0)


class CheckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    programme_id: str = Field(min_length=1, max_length=100)
    academic_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    application_type: ApplicationType
    notice_url: HttpUrl | None = None
    applicant_group: str | None = Field(default=None, max_length=200)
    profile: ApplicantProfile | None = None
    save: bool = False


class CheckAccepted(BaseModel):
    check_id: str
    run_id: str
    status: str = "queued"
    poll_after_ms: int = 2_000


class CheckRead(BaseModel):
    id: str
    programme_id: str
    academic_year: str
    application_type: ApplicationType
    notice_url: str | None
    saved_at: datetime | None
    created_at: datetime
    runs: list[RunRead]
