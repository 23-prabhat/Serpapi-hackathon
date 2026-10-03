"""Public supported-programme catalogue contracts."""

from pydantic import BaseModel


class ProgrammeRead(BaseModel):
    id: str
    name: str
    provider: str
    supported_cycles: list[str]
    application_types: list[str]
    support_status: str
