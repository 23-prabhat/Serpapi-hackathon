"""Historical replay fixture contracts."""

from datetime import datetime

from pydantic import BaseModel


class ExampleRead(BaseModel):
    id: str
    title: str
    description: str
    programme_name: str
    academic_year: str
    application_type: str
    reference_time: datetime
    expected_student_deadline: str | None
    source_url: str
