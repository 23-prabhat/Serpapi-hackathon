"""One persisted live NMMSS run from discovery through report commit."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from app.config import Settings, get_settings
from app.db.models import (
    Document,
    DocumentVersion,
    Extraction,
    Report,
    Run,
    RunDocument,
    SearchRequest,
)
from app.db.session import SessionLocal
from app.schemas.reports import ReportRead
from app.services.evidence import validate_report_evidence
from app.services.extraction import (
    SCHEMA_VERSION,
    ExtractedDocument,
    extract_facts,
    prompt_hash,
    validate_evidence,
)
from app.services.failures import (
    InvalidExtractionError,
    IrrelevantSourceError,
    ParsingFailedError,
    ProcessingError,
    SourceUnavailableError,
)
from app.services.parsing import PARSER_VERSION, Block, parse_source_bounded, persist_source_files
from app.services.registry import load_registry
from app.services.reporting import REPORT_SCHEMA_VERSION, build_report
from app.services.retrieval import RetrievedSource, SourceRequestBudget, retrieve_source
from app.services.rules.types import SourcedRecord
from app.services.search import search_nmmss


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class PreparedDocument:
    retrieved: RetrievedSource
    blocks: list[Block]
    parse_status: str
    version_id: str


def _require_owned_run(run_id: str, owner_token: str) -> Run:
    with SessionLocal() as session:
        run = session.scalar(
            select(Run).where(
                Run.id == run_id,
                Run.owner_token == owner_token,
                Run.status == "running",
            )
        )
        if run is None:
            raise RuntimeError("Worker no longer owns this run")
        session.expunge(run)
        return run


def _set_stage(run_id: str, owner_token: str, stage: str) -> None:
    with SessionLocal.begin() as session:
        result = session.execute(
            update(Run)
            .where(
                Run.id == run_id,
                Run.owner_token == owner_token,
                Run.status == "running",
            )
            .values(stage=stage, heartbeat_at=_utcnow())
        )
        if result.rowcount != 1:
            raise RuntimeError("Worker lost run ownership")


def _record_document_failure(
    run_id: str,
    requested_url: str,
    error: ProcessingError,
    *,
    resolved_url: str | None = None,
    checked_at: datetime | None = None,
) -> None:
    with SessionLocal.begin() as session:
        session.add(
            RunDocument(
                id=str(uuid4()),
                run_id=run_id,
                requested_url=requested_url,
                resolved_url=resolved_url,
                document_version_id=None,
                extraction_id=None,
                checked_at=checked_at or _utcnow(),
                cache_provenance="live",
                fetch_status="unsupported" if not error.retryable else "failed",
                error_code=error.code,
            )
        )


def _normalize_scope_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _has_requested_deadline_scope(
    blocks: list[Block], programme: dict[str, Any], academic_year: str
) -> bool:
    text = _normalize_scope_text("\n".join(block.text for block in blocks))
    programme_markers = {
        programme["id"].lower(),
        programme["id"].lower().replace("-", " "),
        _normalize_scope_text(programme["name"]),
    }
    deadline_markers = (
        "deadline",
        "last date",
        "open till",
        "submission of application",
        "submission of applications",
        "applications extended",
        "application extended",
    )
    return (
        _normalize_scope_text(academic_year) in text
        and any(marker and marker in text for marker in programme_markers)
        and any(marker in text for marker in deadline_markers)
    )


def process_run(run_id: str, owner_token: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    run = _require_owned_run(run_id, owner_token)
    with SessionLocal() as session:
        persisted_run = session.get(Run, run_id)
        if persisted_run is None:
            raise RuntimeError("Run disappeared")
        check = persisted_run.check
        session.expunge(check)

    programme = load_registry()[check.programme_id]
    scope = check.requested_scope_json
    academic_year = scope["academic_year"]
    application_type = scope["application_type"]
    usage: dict[str, Any] = {"search_calls": 0, "source_requests": 0, "model": {}}

    _set_stage(run_id, owner_token, "searching")
    search = search_nmmss(settings, programme, academic_year, run_id)
    usage["search_calls"] = search.metadata["attempt_count"]
    with SessionLocal.begin() as session:
        session.add(
            SearchRequest(
                id=str(uuid4()),
                run_id=run_id,
                query=search.query,
                parameters_json=search.metadata["parameters"],
                requested_at=_utcnow(),
                result_created_at=search.result_created_at,
                provider_search_id=search.provider_search_id,
                response_path=search.response_path,
                local_cache_hit=False,
                outcome="success",
                usage_json=search.metadata,
            )
        )

    _set_stage(run_id, owner_token, "fetching")
    candidate_urls: list[str] = []
    if check.notice_url:
        candidate_urls.append(check.notice_url)
    candidate_urls.extend(search.urls)
    candidate_urls.extend(programme.get("reviewed_discovery_urls", {}).get(academic_year, []))
    candidate_urls = list(dict.fromkeys(candidate_urls))

    prepared_documents: list[PreparedDocument] = []
    seen_versions: set[str] = set()
    last_failure: ProcessingError | None = None
    request_budget = SourceRequestBudget(settings.max_source_requests)
    for url in candidate_urls[: settings.max_source_documents]:
        candidate = None
        _require_owned_run(run_id, owner_token)
        try:
            candidate = retrieve_source(settings, programme, url, request_budget)
            parsed_blocks, parsed_format, parsed_status = parse_source_bounded(
                candidate.content,
                candidate.content_type,
                candidate.resolved_url,
                max_pages=settings.max_pdf_pages,
                timeout_seconds=settings.source_parse_timeout_seconds,
            )
            if not _has_requested_deadline_scope(parsed_blocks, programme, academic_year):
                raise IrrelevantSourceError(
                    "Parsed source lacked programme, cycle, or deadline markers"
                )
            candidate_original_path, candidate_blocks_path = persist_source_files(
                Path(settings.data_dir),
                candidate.source_policy["id"],
                candidate.sha256,
                candidate.content,
                parsed_format,
                parsed_blocks,
            )
            with SessionLocal.begin() as session:
                document = session.scalar(
                    select(Document).where(Document.canonical_url == candidate.resolved_url)
                )
                if document is None:
                    document = Document(
                        id=str(uuid4()),
                        canonical_url=candidate.resolved_url,
                        source_policy_id=candidate.source_policy["id"],
                        publisher_role=candidate.source_policy["role"],
                    )
                    session.add(document)
                    session.flush()
                version = session.scalar(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == document.id,
                        DocumentVersion.sha256 == candidate.sha256,
                        DocumentVersion.parser_version == PARSER_VERSION,
                    )
                )
                version_reused = version is not None
                if version is None:
                    version = DocumentVersion(
                        id=str(uuid4()),
                        document_id=document.id,
                        sha256=candidate.sha256,
                        original_path=candidate_original_path,
                        parsed_blocks_path=candidate_blocks_path,
                        parser_version=PARSER_VERSION,
                        first_seen_at=candidate.retrieved_at,
                        parse_status=parsed_status,
                    )
                    session.add(version)
                    session.flush()
                association = RunDocument(
                    id=str(uuid4()),
                    run_id=run_id,
                    requested_url=candidate.requested_url,
                    resolved_url=candidate.resolved_url,
                    document_version_id=version.id,
                    extraction_id=None,
                    checked_at=candidate.retrieved_at,
                    cache_provenance="version_reused" if version_reused else "new_version",
                    fetch_status="success",
                    error_code=None,
                )
                session.add(association)
                session.flush()
                version_id = version.id
            if version_id not in seen_versions:
                seen_versions.add(version_id)
                prepared_documents.append(
                    PreparedDocument(
                        retrieved=candidate,
                        blocks=parsed_blocks,
                        parse_status=parsed_status,
                        version_id=version_id,
                    )
                )
        except ProcessingError as exc:
            last_failure = exc
            _record_document_failure(
                run_id,
                url,
                exc,
                resolved_url=(
                    candidate.resolved_url if candidate and candidate.requested_url == url else None
                ),
                checked_at=(
                    candidate.retrieved_at if candidate and candidate.requested_url == url else None
                ),
            )
        except Exception as exc:  # noqa: BLE001 - convert to a stable source state.
            last_failure = ParsingFailedError(type(exc).__name__)
            _record_document_failure(run_id, url, last_failure)
    usage["source_requests"] = request_budget.used
    if not prepared_documents:
        raise last_failure or SourceUnavailableError("All reviewed sources failed")

    _set_stage(run_id, owner_token, "extracting")
    sourced_records: list[SourcedRecord] = []
    model_usage: list[dict[str, Any]] = []
    last_extraction_failure: ProcessingError | None = None
    for prepared in prepared_documents:
        _require_owned_run(run_id, owner_token)
        try:
            with SessionLocal() as session:
                cached = session.scalar(
                    select(Extraction).where(
                        Extraction.document_version_id == prepared.version_id,
                        Extraction.model_id == settings.llm_model,
                        Extraction.prompt_hash == prompt_hash(),
                        Extraction.schema_version == SCHEMA_VERSION,
                    )
                )
                if cached is not None:
                    extracted = ExtractedDocument.model_validate(cached.facts_json)
                    for record in extracted.records:
                        validate_evidence(record, prepared.blocks)
                    extraction_id = cached.id
                    model_usage.append({"version_id": prepared.version_id, "cache_hit": True})
                else:
                    extracted, document_usage = extract_facts(
                        settings,
                        programme["name"],
                        academic_year,
                        application_type,
                        prepared.blocks,
                    )
                    model_usage.append(
                        {
                            "version_id": prepared.version_id,
                            "cache_hit": False,
                            **document_usage,
                        }
                    )
                    extraction_id = str(uuid4())
            if cached is None:
                with SessionLocal.begin() as write_session:
                    write_session.add(
                        Extraction(
                            id=extraction_id,
                            document_version_id=prepared.version_id,
                            model_id=settings.llm_model or "unknown",
                            prompt_hash=prompt_hash(),
                            schema_version=SCHEMA_VERSION,
                            facts_json=extracted.model_dump(mode="json"),
                            validation_json={
                                "status": "valid",
                                "validated_at": _utcnow().isoformat(),
                                "evidence_ids": "valid",
                                "dates": "supported_in_actor_action_context",
                                "block_count": len(prepared.blocks),
                            },
                            created_at=_utcnow(),
                        )
                    )
            with SessionLocal.begin() as write_session:
                result = write_session.execute(
                    update(RunDocument)
                    .where(
                        RunDocument.run_id == run_id,
                        RunDocument.document_version_id == prepared.version_id,
                    )
                    .values(extraction_id=extraction_id)
                )
                if result.rowcount < 1:
                    raise RuntimeError("Run document association disappeared")
            for record in extracted.records:
                sourced_records.append(
                    SourcedRecord(
                        record=record,
                        version_id=prepared.version_id,
                        source_capabilities=frozenset(
                            prepared.retrieved.source_policy.get("may_establish", [])
                        ),
                        parse_status=prepared.parse_status,
                        document_unresolved_items=tuple(extracted.document_unresolved_items),
                    )
                )
        except ProcessingError as exc:
            last_extraction_failure = exc
            with SessionLocal.begin() as session:
                session.execute(
                    update(RunDocument)
                    .where(
                        RunDocument.run_id == run_id,
                        RunDocument.document_version_id == prepared.version_id,
                    )
                    .values(error_code=exc.code, fetch_status="extraction_failed")
                )
        except Exception as exc:  # noqa: BLE001 - one bad document can yield partial coverage.
            last_extraction_failure = InvalidExtractionError(type(exc).__name__)
            with SessionLocal.begin() as session:
                session.execute(
                    update(RunDocument)
                    .where(
                        RunDocument.run_id == run_id,
                        RunDocument.document_version_id == prepared.version_id,
                    )
                    .values(
                        error_code="INVALID_EXTRACTION",
                        fetch_status="extraction_failed",
                    )
                )
    usage["model"] = model_usage
    if not sourced_records:
        raise last_extraction_failure or InvalidExtractionError("No valid extraction remained")

    _set_stage(run_id, owner_token, "checking")
    report_json = build_report(
        run_id=run_id,
        reference_time=run.reference_time,
        programme=programme,
        academic_year=academic_year,
        application_type=application_type,
        sources=sourced_records,
        applicant_group=scope.get("applicant_group"),
        profile=check.profile_json,
        incomplete_source_attempts=bool(last_failure or last_extraction_failure),
        model_id=settings.llm_model or "unknown",
    )
    ReportRead.model_validate(report_json)

    _set_stage(run_id, owner_token, "finalizing")
    with SessionLocal.begin() as session:
        owned_run = session.scalar(
            select(Run).where(
                Run.id == run_id,
                Run.owner_token == owner_token,
                Run.status == "running",
            )
        )
        if owned_run is None:
            raise RuntimeError("Worker lost ownership before report commit")
        validate_report_evidence(session, run_id, report_json)
        session.add(
            Report(
                id=str(uuid4()),
                run_id=run_id,
                report_schema_version=REPORT_SCHEMA_VERSION,
                decisions_json=report_json,
                created_at=_utcnow(),
            )
        )
        owned_run.status = "completed"
        owned_run.stage = "finished"
        owned_run.finished_at = _utcnow()
        owned_run.heartbeat_at = _utcnow()
        owned_run.usage_json = usage
        owned_run.version_manifest_json = {
            "registry": str(programme["schema_version"]),
            "parser": PARSER_VERSION,
            "rules": "phase3-2",
            "schema": REPORT_SCHEMA_VERSION,
            "model": settings.llm_model,
            "prompt": prompt_hash(),
        }
