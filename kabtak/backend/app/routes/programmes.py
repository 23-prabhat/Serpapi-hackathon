"""Supported-programme catalogue routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Check, Run
from app.db.session import get_session
from app.schemas.programmes import ProgrammeRead
from app.services.registry import public_programmes

router = APIRouter()


@router.get("", response_model=list[ProgrammeRead])
async def list_programmes(
    session: Annotated[Session, Depends(get_session)],
) -> list[ProgrammeRead]:
    latest_checks = dict(
        session.execute(
            select(Check.programme_id, func.max(Run.finished_at))
            .join(Run, Run.check_id == Check.id)
            .where(Run.status == "completed")
            .group_by(Check.programme_id)
        ).all()
    )
    return [
        ProgrammeRead.model_validate({**item, "last_checked_at": latest_checks.get(item["id"])})
        for item in public_programmes()
    ]
