"""Run status, report, and evidence routes."""

import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Document, DocumentVersion, Report, Run, RunDocument
from app.db.session import get_session
from app.errors import APIError
from app.schemas.reports import EvidenceRead, ReportRead
from app.schemas.runs import RunRead

router = APIRouter()


@router.get("/{run_id}", response_model=RunRead)
async def read_run(run_id: str, session: Annotated[Session, Depends(get_session)]) -> RunRead:
    run = session.get(Run, run_id)
    if run is None:
        raise APIError(404, "RUN_NOT_FOUND", "The requested run does not exist.")
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

    blocks = json.loads(Path(version.parsed_blocks_path).read_text(encoding="utf-8"))
    block = next((item for item in blocks if item["block_id"] == block_id), None)
    if block is None:
        raise APIError(404, "EVIDENCE_NOT_FOUND", "The source block is unavailable.")
    return EvidenceRead(
        version_id=version.id,
        block_id=block_id,
        location=block["location"],
        text=block["text"],
        source_url=document.canonical_url,
        publisher_role=document.publisher_role,
    )
