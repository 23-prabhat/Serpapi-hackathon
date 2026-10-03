"""Persisted check creation and history routes."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Check, Run
from app.db.session import get_session
from app.errors import APIError
from app.schemas.checks import CheckAccepted, CheckCreate, CheckRead
from app.schemas.runs import RunRead
from app.services.registry import require_supported_programme, validate_notice_url

router = APIRouter()


def _run_read(run: Run) -> RunRead:
    return RunRead(
        id=run.id,
        check_id=run.check_id,
        status=run.status,
        stage=run.stage,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        heartbeat_at=run.heartbeat_at,
        error=run.error_json,
    )


@router.post("", response_model=CheckAccepted, status_code=202)
async def create_check(
    payload: CheckCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CheckAccepted:
    if not idempotency_key or len(idempotency_key) > 200:
        raise APIError(422, "INVALID_IDEMPOTENCY_KEY", "Provide a valid Idempotency-Key.")
    if not settings.live_search_enabled or not settings.live_extraction_enabled:
        raise APIError(
            503,
            "LIVE_INTEGRATIONS_DISABLED",
            "Live SerpApi and Groq credentials are required for this check.",
            retryable=True,
        )

    request_json = payload.model_dump(mode="json")
    request_hash = hashlib.sha256(
        json.dumps(request_json, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = session.scalar(
        select(Run).where(
            Run.operation_scope == "check:create", Run.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise APIError(
                409,
                "IDEMPOTENCY_CONFLICT",
                "This Idempotency-Key was already used with different inputs.",
            )
        response.status_code = 200
        return CheckAccepted(check_id=existing.check_id, run_id=existing.id, status=existing.status)

    programme = require_supported_programme(
        payload.programme_id, payload.academic_year, payload.application_type.value
    )
    notice_url = str(payload.notice_url) if payload.notice_url else None
    validate_notice_url(programme, notice_url)

    queued_count = session.scalar(
        select(func.count()).select_from(Run).where(Run.status == "queued")
    )
    if (queued_count or 0) >= settings.max_waiting_runs:
        raise APIError(
            429,
            "QUEUE_FULL",
            "The local worker queue is full. Try again after the current checks finish.",
            retryable=True,
        )

    now = datetime.now(UTC)
    check_id = str(uuid4())
    run_id = str(uuid4())
    check = Check(
        id=check_id,
        programme_id=payload.programme_id,
        requested_scope_json={
            "academic_year": payload.academic_year,
            "application_type": payload.application_type.value,
            "applicant_group": payload.applicant_group,
        },
        profile_json=payload.profile.model_dump(mode="json") if payload.profile else None,
        notice_url=notice_url,
        saved_at=now if payload.save else None,
        created_at=now,
        expires_at=now + timedelta(days=30 if payload.save else 1),
    )
    run = Run(
        id=run_id,
        check_id=check_id,
        kind="live",
        status="queued",
        stage="queued",
        operation_scope="check:create",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        reference_time=now,
        created_at=now,
    )
    session.add_all([check, run])
    session.commit()
    return CheckAccepted(check_id=check_id, run_id=run_id)


@router.get("/{check_id}", response_model=CheckRead)
async def read_check(check_id: str, session: Annotated[Session, Depends(get_session)]) -> CheckRead:
    check = session.get(Check, check_id)
    if check is None:
        raise APIError(404, "CHECK_NOT_FOUND", "The requested check does not exist.")
    return CheckRead(
        id=check.id,
        programme_id=check.programme_id,
        academic_year=check.requested_scope_json["academic_year"],
        application_type=check.requested_scope_json["application_type"],
        notice_url=check.notice_url,
        saved_at=check.saved_at,
        created_at=check.created_at,
        runs=[_run_read(run) for run in check.runs],
    )
