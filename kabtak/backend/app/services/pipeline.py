"""One persisted live NMMSS run from discovery through report commit."""

from __future__ import annotations

import re
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
    ExtractedFacts,
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
from app.services.reporting import build_report
from app.services.retrieval import SourceRequestBudget, retrieve_source
from app.services.search import search_nmmss


def _utcnow() -> datetime:
    return datetime.now(UTC)


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

    retrieved = None
    blocks = []
    parse_status = ""
    original_path = ""
    blocks_path = ""
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
            retrieved = candidate
            blocks = parsed_blocks
            parse_status = parsed_status
            original_path = candidate_original_path
            blocks_path = candidate_blocks_path
            break
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
    if retrieved is None:
        raise last_failure or SourceUnavailableError("All reviewed sources failed")

    with SessionLocal.begin() as session:
        document = session.scalar(
            select(Document).where(Document.canonical_url == retrieved.resolved_url)
        )
        if document is None:
            document = Document(
                id=str(uuid4()),
                canonical_url=retrieved.resolved_url,
                source_policy_id=retrieved.source_policy["id"],
                publisher_role=retrieved.source_policy["role"],
            )
            session.add(document)
            session.flush()
        version = session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.sha256 == retrieved.sha256,
                DocumentVersion.parser_version == PARSER_VERSION,
            )
        )
        version_reused = version is not None
        if version is None:
            version = DocumentVersion(
                id=str(uuid4()),
                document_id=document.id,
                sha256=retrieved.sha256,
                original_path=original_path,
                parsed_blocks_path=blocks_path,
                parser_version=PARSER_VERSION,
                first_seen_at=retrieved.retrieved_at,
                parse_status=parse_status,
            )
            session.add(version)
            session.flush()
        association = RunDocument(
            id=str(uuid4()),
            run_id=run_id,
            requested_url=retrieved.requested_url,
            resolved_url=retrieved.resolved_url,
            document_version_id=version.id,
            extraction_id=None,
            checked_at=retrieved.retrieved_at,
            cache_provenance="version_reused" if version_reused else "new_version",
            fetch_status="success",
            error_code=None,
        )
        session.add(association)
        session.flush()
        version_id = version.id
        association_id = association.id

    _set_stage(run_id, owner_token, "extracting")
    try:
        with SessionLocal() as session:
            cached = session.scalar(
                select(Extraction).where(
                    Extraction.document_version_id == version_id,
                    Extraction.model_id == settings.llm_model,
                    Extraction.prompt_hash == prompt_hash(),
                    Extraction.schema_version == SCHEMA_VERSION,
                )
            )
            if cached is not None:
                facts = ExtractedFacts.model_validate(cached.facts_json)
                validate_evidence(facts, blocks)
                extraction_id = cached.id
                usage["model"] = {"cache_hit": True}
            else:
                facts, model_usage = extract_facts(
                    settings,
                    programme["name"],
                    academic_year,
                    application_type,
                    blocks,
                )
                usage["model"] = {"cache_hit": False, **model_usage}
                extraction_id = str(uuid4())
        if cached is None:
            with SessionLocal.begin() as write_session:
                write_session.add(
                    Extraction(
                        id=extraction_id,
                        document_version_id=version_id,
                        model_id=settings.llm_model or "unknown",
                        prompt_hash=prompt_hash(),
                        schema_version=SCHEMA_VERSION,
                        facts_json=facts.model_dump(mode="json"),
                        validation_json={
                            "status": "valid",
                            "validated_at": _utcnow().isoformat(),
                            "evidence_ids": "valid",
                            "dates": "supported",
                            "block_count": len(blocks),
                        },
                        created_at=_utcnow(),
                    )
                )
        with SessionLocal.begin() as write_session:
            run_document = write_session.get(RunDocument, association_id)
            if run_document is None:
                raise RuntimeError("Run document association disappeared")
            run_document.extraction_id = extraction_id
    except ProcessingError as exc:
        with SessionLocal.begin() as session:
            run_document = session.get(RunDocument, association_id)
            if run_document is not None:
                run_document.error_code = exc.code
                run_document.fetch_status = "extraction_failed"
        raise
    except Exception as exc:
        with SessionLocal.begin() as session:
            run_document = session.get(RunDocument, association_id)
            if run_document is not None:
                run_document.error_code = "INVALID_EXTRACTION"
                run_document.fetch_status = "extraction_failed"
        raise InvalidExtractionError(type(exc).__name__) from None

    _set_stage(run_id, owner_token, "checking")
    report_json = build_report(
        run_id=run_id,
        reference_time=run.reference_time,
        programme=programme,
        academic_year=academic_year,
        application_type=application_type,
        version_id=version_id,
        facts=facts,
        model_id=settings.llm_model or "unknown",
        parse_status=parse_status,
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
                report_schema_version="1",
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
            "rules": "phase1-1",
            "schema": "1",
            "model": settings.llm_model,
            "prompt": prompt_hash(),
        }
