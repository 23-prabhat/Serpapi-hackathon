"""Persisted check creation and history routes."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Check, Run
from app.db.session import get_session
from app.errors import APIError
from app.schemas.checks import CheckAccepted, CheckCreate, CheckRead, CheckUpdate, LinkCheckCreate
from app.schemas.runs import RunRead
from app.services.admission import begin_immediate
from app.services.failures import ProcessingError
from app.services.registry import (
    ARBITRARY_LINK_PROGRAMME_ID,
    require_supported_programme,
    validate_notice_url,
)
from app.services.retrieval import validate_arbitrary_url_syntax

router = APIRouter()


def _run_read(run: Run) -> RunRead:
    return RunRead(
        id=run.id,
        check_id=run.check_id,
        kind=run.kind,
        status=run.status,
        stage=run.stage,
        reference_time=run.reference_time,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        heartbeat_at=run.heartbeat_at,
        retry_of_run_id=run.retry_of_run_id,
        report_available=run.report is not None,
        error=run.error_json,
    )


def _check_read(check: Check) -> CheckRead:
    completed = [run for run in check.runs if run.report is not None]
    scope = check.requested_scope_json
    return CheckRead(
        id=check.id,
        programme_id=check.programme_id,
        programme_name=scope.get("programme_name", check.programme.name),
        academic_year=scope["academic_year"],
        application_type=scope["application_type"],
        applicant_group=scope.get("applicant_group"),
        profile=check.profile_json,
        notice_url=check.notice_url,
        saved_at=check.saved_at,
        created_at=check.created_at,
        expires_at=check.expires_at,
        latest_completed_run_id=completed[-1].id if completed else None,
        runs=[_run_read(run) for run in reversed(check.runs)],
    )


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key or len(idempotency_key) > 200:
        raise APIError(422, "INVALID_IDEMPOTENCY_KEY", "Provide a valid Idempotency-Key.")
    return idempotency_key


def _ensure_live_integrations(settings: Settings) -> None:
    if not settings.live_search_enabled or not settings.live_extraction_enabled:
        raise APIError(
            503,
            "LIVE_INTEGRATIONS_DISABLED",
            "Live SerpApi and Groq credentials are required for this check.",
            retryable=True,
        )


def _ensure_link_integration(settings: Settings) -> None:
    if not settings.live_extraction_enabled:
        raise APIError(
            503,
            "LIVE_EXTRACTION_DISABLED",
            "The configured extraction model is required for an official-link check.",
            retryable=True,
        )


def _queue_has_capacity(session: Session, settings: Settings) -> None:
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


@router.post("", response_model=CheckAccepted, status_code=202)
async def create_check(
    payload: CheckCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CheckAccepted:
    idempotency_key = _require_idempotency_key(idempotency_key)
    request_json = payload.model_dump(mode="json")
    request_hash = hashlib.sha256(
        json.dumps(request_json, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    begin_immediate(session)
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

    _ensure_live_integrations(settings)

    programme = require_supported_programme(
        payload.programme_id, payload.academic_year, payload.application_type.value
    )
    notice_url = str(payload.notice_url) if payload.notice_url else None
    validate_notice_url(programme, notice_url)

    _queue_has_capacity(session, settings)

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
        expires_at=None if payload.save else now + timedelta(days=1),
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


@router.post("/link", response_model=CheckAccepted, status_code=202)
async def create_link_check(
    payload: LinkCheckCreate,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CheckAccepted:
    idempotency_key = _require_idempotency_key(idempotency_key)
    request_json = payload.model_dump(mode="json")
    request_hash = hashlib.sha256(
        json.dumps(request_json, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    begin_immediate(session)
    existing = session.scalar(
        select(Run).where(
            Run.operation_scope == "check:link:create", Run.idempotency_key == idempotency_key
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

    _ensure_link_integration(settings)
    notice_url = str(payload.notice_url)
    try:
        validate_arbitrary_url_syntax(notice_url)
    except ProcessingError as exc:
        raise APIError(422, "UNSAFE_SOURCE_URL", exc.public_message) from None
    _queue_has_capacity(session, settings)

    now = datetime.now(UTC)
    check_id = str(uuid4())
    run_id = str(uuid4())
    hostname = (urlparse(notice_url).hostname or "").rstrip(".").lower()
    check = Check(
        id=check_id,
        programme_id=ARBITRARY_LINK_PROGRAMME_ID,
        requested_scope_json={
            "input_mode": "arbitrary_official_link",
            "programme_name": payload.programme_name,
            "source_host": hostname,
            "academic_year": payload.academic_year,
            "application_type": payload.application_type.value,
            "applicant_group": payload.applicant_group,
        },
        profile_json=payload.profile.model_dump(mode="json") if payload.profile else None,
        notice_url=notice_url,
        saved_at=now if payload.save else None,
        created_at=now,
        expires_at=None if payload.save else now + timedelta(days=1),
    )
    run = Run(
        id=run_id,
        check_id=check_id,
        kind="link",
        status="queued",
        stage="queued",
        operation_scope="check:link:create",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        reference_time=now,
        created_at=now,
    )
    session.add_all([check, run])
    session.commit()
    return CheckAccepted(check_id=check_id, run_id=run_id)


@router.get("", response_model=list[CheckRead])
async def list_checks(
    session: Annotated[Session, Depends(get_session)],
    saved: bool | None = None,
) -> list[CheckRead]:
    statement = select(Check).order_by(Check.created_at.desc())
    if saved is True:
        statement = statement.where(Check.saved_at.is_not(None))
    elif saved is False:
        statement = statement.where(Check.saved_at.is_(None))
    return [_check_read(check) for check in session.scalars(statement).unique().all()]


@router.get("/{check_id}", response_model=CheckRead)
async def read_check(check_id: str, session: Annotated[Session, Depends(get_session)]) -> CheckRead:
    check = session.get(Check, check_id)
    if check is None:
        raise APIError(404, "CHECK_NOT_FOUND", "The requested check does not exist.")
    return _check_read(check)


@router.patch("/{check_id}", response_model=CheckRead)
async def update_check(
    check_id: str,
    payload: CheckUpdate,
    session: Annotated[Session, Depends(get_session)],
) -> CheckRead:
    check = session.get(Check, check_id)
    if check is None:
        raise APIError(404, "CHECK_NOT_FOUND", "The requested check does not exist.")
    now = datetime.now(UTC)
    check.saved_at = now if payload.save else None
    check.expires_at = None if payload.save else now + timedelta(days=1)
    session.commit()
    return _check_read(check)


@router.post("/{check_id}/refresh", response_model=CheckAccepted, status_code=202)
async def refresh_check(
    check_id: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CheckAccepted:
    idempotency_key = _require_idempotency_key(idempotency_key)
    begin_immediate(session)
    check = session.get(Check, check_id)
    if check is None:
        raise APIError(404, "CHECK_NOT_FOUND", "The requested check does not exist.")
    operation_scope = f"check:{check_id}:refresh"
    request_hash = hashlib.sha256(check_id.encode()).hexdigest()
    existing = session.scalar(
        select(Run).where(
            Run.operation_scope == operation_scope,
            Run.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise APIError(409, "IDEMPOTENCY_CONFLICT", "The key was used for another refresh.")
        response.status_code = 200
        return CheckAccepted(check_id=check.id, run_id=existing.id, status=existing.status)
    if any(run.status in {"queued", "running"} for run in check.runs):
        raise APIError(409, "RUN_ACTIVE", "This check already has an active run.")
    if any(run.kind == "replay" for run in check.runs):
        raise APIError(
            409,
            "REPLAY_REFRESH_UNSUPPORTED",
            "Historical replays cannot be refreshed as live checks.",
        )
    if check.programme_id == ARBITRARY_LINK_PROGRAMME_ID:
        _ensure_link_integration(settings)
    else:
        _ensure_live_integrations(settings)
    _queue_has_capacity(session, settings)
    now = datetime.now(UTC)
    run = Run(
        id=str(uuid4()),
        check_id=check.id,
        kind="refresh",
        status="queued",
        stage="queued",
        operation_scope=operation_scope,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        reference_time=now,
        created_at=now,
    )
    session.add(run)
    session.commit()
    return CheckAccepted(check_id=check.id, run_id=run.id)


@router.delete("/{check_id}", status_code=204)
async def delete_check(
    check_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    check = session.get(Check, check_id)
    if check is None:
        raise APIError(404, "CHECK_NOT_FOUND", "The requested check does not exist.")
    if any(run.status in {"queued", "running"} for run in check.runs):
        raise APIError(409, "RUN_ACTIVE", "Wait for the active run before deleting this check.")
    session.delete(check)
    session.commit()
    return Response(status_code=204)
