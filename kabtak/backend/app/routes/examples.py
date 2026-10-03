"""Offline historical example and replay routes."""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Run
from app.db.session import get_session
from app.errors import APIError
from app.schemas.checks import CheckAccepted
from app.schemas.examples import ExampleRead
from app.services.admission import begin_immediate
from app.services.examples import load_examples, materialize_replay, public_examples

router = APIRouter()


@router.get("", response_model=list[ExampleRead])
async def list_examples() -> list[ExampleRead]:
    return [ExampleRead.model_validate(item) for item in public_examples()]


@router.post("/{example_id}/replay", response_model=CheckAccepted, status_code=202)
async def replay_example(
    example_id: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CheckAccepted:
    if not idempotency_key or len(idempotency_key) > 200:
        raise APIError(422, "INVALID_IDEMPOTENCY_KEY", "Provide a valid Idempotency-Key.")
    fixture = load_examples().get(example_id)
    if fixture is None:
        raise APIError(404, "EXAMPLE_NOT_FOUND", "The historical example does not exist.")
    begin_immediate(session)
    operation_scope = f"example:{example_id}:replay"
    request_hash = hashlib.sha256(example_id.encode()).hexdigest()
    existing = session.scalar(
        select(Run).where(
            Run.operation_scope == operation_scope,
            Run.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise APIError(409, "IDEMPOTENCY_CONFLICT", "The key was used for another replay.")
        response.status_code = 200
        return CheckAccepted(check_id=existing.check_id, run_id=existing.id, status=existing.status)
    run = materialize_replay(session, settings, fixture, idempotency_key)
    return CheckAccepted(check_id=run.check_id, run_id=run.id, status=run.status)
