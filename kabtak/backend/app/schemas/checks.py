"""Check request and response contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

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


class LinkCheckCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    programme_name: str = Field(min_length=3, max_length=300)
    academic_year: str = Field(pattern=r"^\d{4}-\d{2}$")
    application_type: ApplicationType
    notice_url: HttpUrl
    applicant_group: str | None = Field(default=None, max_length=200)
    profile: ApplicantProfile | None = None
    save: bool = False
    official_source_confirmed: bool

    @field_validator("programme_name")
    @classmethod
    def normalize_programme_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("application_type")
    @classmethod
    def require_known_application_type(cls, value: ApplicationType) -> ApplicationType:
        if value == ApplicationType.UNKNOWN:
            raise ValueError("select fresh or renewal")
        return value

    @field_validator("official_source_confirmed")
    @classmethod
    def require_source_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("confirm that the link is from the publisher or institution")
        return value


class CheckAccepted(BaseModel):
    check_id: str
    run_id: str
    status: str = "queued"
    poll_after_ms: int = 2_000


class CheckUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    save: bool


class CheckRead(BaseModel):
    id: str
    programme_id: str
    programme_name: str
    academic_year: str
    application_type: ApplicationType
    applicant_group: str | None
    profile: ApplicantProfile | None
    notice_url: str | None
    saved_at: datetime | None
    created_at: datetime
    expires_at: datetime | None
    latest_completed_run_id: str | None
    runs: list[RunRead]
