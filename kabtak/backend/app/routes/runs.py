"""Run status, report, and evidence routes."""

import hashlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import Document, DocumentVersion, Report, Run, RunDocument
from app.db.session import get_session
from app.errors import APIError
from app.schemas.checks import CheckAccepted
from app.schemas.reports import EvidenceRead, ReportRead
from app.schemas.runs import FactChangeRead, RunComparisonRead, RunRead
from app.services.admission import begin_immediate
from app.services.evidence import load_version_blocks
from app.services.failures import InvalidExtractionError
from app.services.registry import ARBITRARY_LINK_PROGRAMME_ID

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


@router.get("/{run_id}", response_model=RunRead)
async def read_run(run_id: str, session: Annotated[Session, Depends(get_session)]) -> RunRead:
    run = session.get(Run, run_id)
    if run is None:
        raise APIError(404, "RUN_NOT_FOUND", "The requested run does not exist.")
    return _run_read(run)


@router.post("/{run_id}/retry", response_model=CheckAccepted, status_code=202)
async def retry_run(
    run_id: str,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CheckAccepted:
    if not idempotency_key or len(idempotency_key) > 200:
        raise APIError(422, "INVALID_IDEMPOTENCY_KEY", "Provide a valid Idempotency-Key.")
    begin_immediate(session)
    parent = session.get(Run, run_id)
    if parent is None:
        raise APIError(404, "RUN_NOT_FOUND", "The requested run does not exist.")
    operation_scope = f"run:{run_id}:retry"
    request_hash = hashlib.sha256(run_id.encode()).hexdigest()
    existing = session.scalar(
        select(Run).where(
            Run.operation_scope == operation_scope,
            Run.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise APIError(409, "IDEMPOTENCY_CONFLICT", "The key was used for another retry.")
        response.status_code = 200
        return CheckAccepted(check_id=existing.check_id, run_id=existing.id, status=existing.status)
    if parent.status not in {"failed", "interrupted"}:
        raise APIError(409, "RUN_NOT_RETRYABLE", "Only failed or interrupted runs can be retried.")
    if parent.kind == "replay":
        raise APIError(
            409,
            "REPLAY_RETRY_UNSUPPORTED",
            "Start the offline historical example again instead.",
        )
    needs_search = parent.check.programme_id != ARBITRARY_LINK_PROGRAMME_ID
    if not settings.live_extraction_enabled or (needs_search and not settings.live_search_enabled):
        raise APIError(
            503,
            "LIVE_INTEGRATIONS_DISABLED",
            (
                "The configured extraction model is required for this retry."
                if not needs_search
                else "Live SerpApi and Groq credentials are required for this retry."
            ),
            retryable=True,
        )
    active = session.scalar(
        select(Run).where(
            Run.check_id == parent.check_id,
            Run.status.in_(["queued", "running"]),
        )
    )
    if active is not None:
        raise APIError(409, "RUN_ACTIVE", "This check already has an active run.")
    queued_count = session.scalar(
        select(func.count()).select_from(Run).where(Run.status == "queued")
    )
    if (queued_count or 0) >= settings.max_waiting_runs:
        raise APIError(429, "QUEUE_FULL", "The local worker queue is full.", retryable=True)
    now = datetime.now(UTC)
    retry = Run(
        id=str(uuid4()),
        check_id=parent.check_id,
        kind="retry",
        status="queued",
        stage="queued",
        operation_scope=operation_scope,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        reference_time=now,
        created_at=now,
        retry_of_run_id=parent.id,
    )
    session.add(retry)
    session.commit()
    return CheckAccepted(check_id=parent.check_id, run_id=retry.id)


@router.get("/{run_id}/changes", response_model=RunComparisonRead)
async def compare_run(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> RunComparisonRead:
    current = session.get(Run, run_id)
    if current is None:
        raise APIError(404, "RUN_NOT_FOUND", "The requested run does not exist.")
    if current.report is None:
        raise APIError(409, "REPORT_NOT_READY", "A completed report is required for comparison.")
    previous = session.scalar(
        select(Run)
        .join(Report, Report.run_id == Run.id)
        .where(
            Run.check_id == current.check_id,
            Run.created_at < current.created_at,
        )
        .order_by(Run.created_at.desc())
        .limit(1)
    )
    if previous is None or previous.report is None:
        return RunComparisonRead(
            run_id=current.id,
            previous_run_id=None,
            classification="initial_report",
            summary="This is the first completed report for this check.",
            outcome_changed=False,
            source_versions_changed=False,
            profile_changed=False,
            software_versions_changed=False,
        )

    current_sources = {
        item.document_version_id for item in current.run_documents if item.document_version_id
    }
    previous_sources = {
        item.document_version_id for item in previous.run_documents if item.document_version_id
    }
    source_changed = current_sources != previous_sources
    software_changed = current.version_manifest_json != previous.version_manifest_json
    profile_changed = current.check.profile_json != previous.check.profile_json
    current_outcome = _decision_signature(current.report.decisions_json)
    previous_outcome = _decision_signature(previous.report.decisions_json)
    outcome_changed = current_outcome != previous_outcome
    changes = _fact_changes(previous.report.decisions_json, current.report.decisions_json)
    incomplete = any(
        item.fetch_status not in {"success"}
        for item in [*current.run_documents, *previous.run_documents]
    )
    if outcome_changed and incomplete:
        classification = "coverage_uncertain"
        summary = (
            "The result differs, but one run had unavailable evidence; a removed fact "
            "cannot be established as a source change."
        )
    elif outcome_changed and source_changed:
        classification = "source_change"
        summary = "The structured result changed alongside the preserved source versions."
    elif outcome_changed and profile_changed:
        classification = "profile_change"
        summary = "The result changed with different profile inputs, not source evidence."
    elif outcome_changed and software_changed:
        classification = "software_interpretation_change"
        summary = "The same source set produced a different result under changed software versions."
    elif outcome_changed:
        classification = "unexplained_interpretation_change"
        summary = "The structured result changed without a recorded source or profile change."
    elif source_changed:
        classification = "source_changed_result_stable"
        summary = "The preserved source set changed, but the structured result stayed the same."
    elif software_changed:
        classification = "software_changed_result_stable"
        summary = "Software versions changed, but the structured result stayed the same."
    else:
        classification = "no_change"
        summary = "No structured result, source, profile, or software-version change was detected."
    return RunComparisonRead(
        run_id=current.id,
        previous_run_id=previous.id,
        classification=classification,
        summary=summary,
        outcome_changed=outcome_changed,
        source_versions_changed=source_changed,
        profile_changed=profile_changed,
        software_versions_changed=software_changed,
        changes=changes,
    )


def _decision_signature(report: dict) -> dict:
    return {key: value[0] for key, value in _fact_index(report).items()}


def _fact_changes(previous: dict, current: dict) -> list[FactChangeRead]:
    before = _fact_index(previous)
    after = _fact_index(current)
    changes: list[FactChangeRead] = []
    for key in sorted(before.keys() | after.keys()):
        old = before.get(key)
        new = after.get(key)
        if old is None:
            changes.append(
                FactChangeRead(
                    kind="added",
                    fact_key=key,
                    after=new[0],
                    after_evidence=new[1],
                )
            )
        elif new is None:
            changes.append(
                FactChangeRead(
                    kind="removed",
                    fact_key=key,
                    before=old[0],
                    before_evidence=old[1],
                )
            )
        elif old[0] != new[0]:
            changes.append(
                FactChangeRead(
                    kind="changed",
                    fact_key=key,
                    before=old[0],
                    after=new[0],
                    before_evidence=old[1],
                    after_evidence=new[1],
                )
            )
    return changes


def _fact_index(report: dict) -> dict[str, tuple[object, list[dict[str, str]]]]:
    scope = report.get("scope") or {}
    prefix = ":".join(
        str(scope.get(key) or "any")
        for key in ("programme_id", "academic_year", "application_type", "applicant_group")
    )
    facts: dict[str, tuple[object, list[dict[str, str]]]] = {}
    for key in ("deadline_resolution", "portal_status", "eligibility"):
        facts[f"{prefix}:{key}"] = (report.get(key), [])

    deadlines = []
    if report.get("student_deadline"):
        deadlines.append(report["student_deadline"])
    deadlines.extend(report.get("other_deadlines", []))
    for item in deadlines:
        base = f"{prefix}:deadline:{item.get('actor', 'unknown')}:{item.get('action', 'unknown')}"
        key = _unique_key(facts, base)
        facts[key] = (_without_evidence(item), _evidence_references(item))

    for index, item in enumerate(report.get("conditions", []), start=1):
        identity = str(item.get("source_text") or item.get("field") or index)
        key = _unique_key(facts, f"{prefix}:condition:{identity}")
        facts[key] = (_without_evidence(item), _evidence_references(item))

    for section in ("conflicts", "amendments", "required_documents", "application_links"):
        for index, item in enumerate(report.get(section, []), start=1):
            identity = str(
                item.get("url")
                or item.get("source_text")
                or item.get("previous_date")
                or item.get("message")
                or index
            )
            key = _unique_key(facts, f"{prefix}:{section}:{identity}")
            facts[key] = (_without_evidence(item), _evidence_references(item))
    return facts


def _unique_key(facts: dict, base: str) -> str:
    if base not in facts:
        return base
    suffix = 2
    while f"{base}:{suffix}" in facts:
        suffix += 1
    return f"{base}:{suffix}"


def _without_evidence(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_evidence(item)
            for key, item in value.items()
            if key not in {"evidence_refs", "previous_evidence_refs", "revised_evidence_refs"}
        }
    if isinstance(value, list):
        return [_without_evidence(item) for item in value]
    return value


def _evidence_references(value: object) -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("evidence_refs") and isinstance(item, list):
                for reference in item:
                    if (
                        isinstance(reference, dict)
                        and isinstance(reference.get("version_id"), str)
                        and isinstance(reference.get("block_id"), str)
                        and reference not in references
                    ):
                        references.append(reference)
            else:
                for reference in _evidence_references(item):
                    if reference not in references:
                        references.append(reference)
    elif isinstance(value, list):
        for item in value:
            for reference in _evidence_references(item):
                if reference not in references:
                    references.append(reference)
    return references


@router.get("/{run_id}/report", response_model=ReportRead)
async def read_report(run_id: str, session: Annotated[Session, Depends(get_session)]) -> ReportRead:
    run = session.get(Run, run_id)
    if run is None:
        raise APIError(404, "RUN_NOT_FOUND", "The requested run does not exist.")
    report = session.scalar(select(Report).where(Report.run_id == run_id))
    if report is None:
        raise APIError(
            409,
            "REPORT_NOT_READY",
            "The report is not available yet.",
            retryable=run.status in {"queued", "running"},
            run_id=run_id,
        )
    return ReportRead.model_validate(report.decisions_json)


@router.get(
    "/{run_id}/evidence/{version_id}/{block_id}",
    response_model=EvidenceRead,
)
async def read_evidence(
    run_id: str,
    version_id: str,
    block_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> EvidenceRead:
    association = session.scalar(
        select(RunDocument).where(
            RunDocument.run_id == run_id,
            RunDocument.document_version_id == version_id,
        )
    )
    if association is None:
        raise APIError(404, "EVIDENCE_NOT_FOUND", "This evidence is not part of the run.")
    version = session.get(DocumentVersion, version_id)
    if version is None:
        raise APIError(404, "EVIDENCE_NOT_FOUND", "The evidence version is unavailable.")
    document = session.get(Document, version.document_id)
    if document is None:
        raise APIError(404, "EVIDENCE_NOT_FOUND", "The source document is unavailable.")

    try:
        blocks = load_version_blocks(version)
    except InvalidExtractionError:
        raise APIError(
            503,
            "EVIDENCE_INTEGRITY_FAILED",
            "The preserved evidence failed its integrity check.",
            retryable=False,
            run_id=run_id,
        ) from None
    block = next((item for item in blocks if item["block_id"] == block_id), None)
    if block is None:
        raise APIError(404, "EVIDENCE_NOT_FOUND", "The source block is unavailable.")
    return EvidenceRead(
        version_id=version.id,
        block_id=block_id,
        kind=block["kind"],
        location=block["location"],
        text=block["text"],
        metadata=block.get("metadata", {}),
        content_sha256=version.sha256,
        block_sha256=block.get("text_sha256") or hashlib.sha256(block["text"].encode()).hexdigest(),
        retrieved_at=association.checked_at,
        parse_status=version.parse_status,
        parser_version=version.parser_version,
        source_url=document.canonical_url,
        publisher_role=document.publisher_role,
    )
