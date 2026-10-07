"""One persisted live programme run from discovery through report commit."""

from __future__ import annotations

import hashlib
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
from app.services.registry import (
    ARBITRARY_LINK_PROGRAMME,
    ARBITRARY_LINK_PROGRAMME_ID,
    load_registry,
)
from app.services.reporting import REPORT_SCHEMA_VERSION, build_report
from app.services.retrieval import (
    RetrievedSource,
    SourceRequestBudget,
    retrieve_arbitrary_source,
    retrieve_source,
)
from app.services.rules.types import SourcedRecord
from app.services.search import search_programme

DEADLINE_SCOPE_MARKERS = (
    "deadline",
    "last date",
    "closing date",
    "open till",
    "closed on",
    "submission of application",
    "submission of applications",
    "applications extended",
    "application extended",
    "inviting of applications",
    "portal for first round",
    "portal for second round",
)
# Groq's free tier currently allows 8K tokens per minute for the configured
# model.  Fourteen thousand source characters leaves room for the extraction
# schema, instructions, and response instead of making long official PDFs fail
# with a provider-side rate-limit response.
EXTRACTION_TEXT_BUDGET = 14_000


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


def _programme_markers(programme: dict[str, Any]) -> set[str]:
    return {
        programme["id"].lower(),
        programme["id"].lower().replace("-", " "),
        _normalize_scope_text(programme["name"]),
        *(
            _normalize_scope_text(marker)
            for marker in programme.get("search_terms", [])
            if isinstance(marker, str)
        ),
    }


def _has_requested_deadline_scope(
    blocks: list[Block], programme: dict[str, Any], academic_year: str
) -> bool:
    text = _normalize_scope_text("\n".join(block.text for block in blocks))
    return (
        _normalize_scope_text(academic_year) in text
        and any(marker and marker in text for marker in _programme_markers(programme))
        and any(marker in text for marker in DEADLINE_SCOPE_MARKERS)
    )


def _has_arbitrary_deadline_scope(
    blocks: list[Block], programme_name: str, academic_year: str
) -> bool:
    text = _normalize_scope_text("\n".join(block.text for block in blocks))
    programme_text = _normalize_scope_text(programme_name)
    ignored = {"scholarship", "scheme", "programme", "program", "the", "for", "and"}
    name_tokens = {
        token for token in programme_text.split() if len(token) >= 3 and token not in ignored
    }
    token_matches = sum(token in text.split() for token in name_tokens)
    programme_matches = programme_text in text or (
        bool(name_tokens) and token_matches >= min(2, len(name_tokens))
    )
    return (
        _normalize_scope_text(academic_year) in text
        and programme_matches
        and any(marker in text for marker in DEADLINE_SCOPE_MARKERS)
    )


def _blocks_for_extraction(
    blocks: list[Block], programme: dict[str, Any], academic_year: str
) -> list[Block]:
    """Keep exact evidence blocks while bounding programme-specific model input."""

    text_budget = min(
        int(programme.get("extraction_text_budget", EXTRACTION_TEXT_BUDGET)),
        EXTRACTION_TEXT_BUDGET,
    )
    markers = _programme_markers(programme)
    normalized_cycle = _normalize_scope_text(academic_year)
    scheme_cards = [block for block in blocks if block.kind == "scheme_card"]
    if scheme_cards:
        preferred_marker = _normalize_scope_text(programme["name"])
        matching_cards = [
            block for block in scheme_cards if preferred_marker in _normalize_scope_text(block.text)
        ]
        if not matching_cards:
            matching_cards = [
                block
                for block in scheme_cards
                if any(marker and marker in _normalize_scope_text(block.text) for marker in markers)
            ]
        matching_ids = {block.block_id for block in matching_cards}
        candidates = [
            block
            for block in blocks
            if normalized_cycle in _normalize_scope_text(block.text)
            or block.block_id in matching_ids
        ]
    else:

        def priority(item: tuple[int, Block]) -> tuple[int, int]:
            index, block = item
            text = _normalize_scope_text(block.text)
            score = 0
            if normalized_cycle in text:
                score += 4
            if any(marker and marker in text for marker in markers):
                score += 4
            if any(marker in text for marker in DEADLINE_SCOPE_MARKERS):
                score += 5
            if any(
                marker in text
                for marker in (
                    "list of document required",
                    "documents required",
                    "required documents",
                    "application procedure",
                )
            ):
                score += 3
            if any(marker in text for marker in ("eligibility", "eligible", "apply")):
                score += 1
            return (-score, index)

        candidates = [block for _, block in sorted(enumerate(blocks), key=priority)]

    selected: list[Block] = []
    selected_ids: set[str] = set()
    used = 0
    for block in candidates:
        rendered_size = len(block.block_id) + len(block.location) + len(block.text) + 8
        if block.block_id in selected_ids or used + rendered_size > text_budget:
            continue
        selected.append(block)
        selected_ids.add(block.block_id)
        used += rendered_size
    order = {block.block_id: index for index, block in enumerate(blocks)}
    return sorted(selected, key=lambda block: order[block.block_id])


def _extraction_scope_hash(
    programme: dict[str, Any], academic_year: str, application_type: str
) -> str:
    cache_identity = "\n".join(
        (
            prompt_hash(),
            programme["id"],
            programme["name"],
            academic_year,
            application_type,
            str(programme.get("extraction_focus", "full")),
        )
    )
    return hashlib.sha256(cache_identity.encode()).hexdigest()


def process_run(run_id: str, owner_token: str, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    run = _require_owned_run(run_id, owner_token)
    with SessionLocal() as session:
        persisted_run = session.get(Run, run_id)
        if persisted_run is None:
            raise RuntimeError("Run disappeared")
        check = persisted_run.check
        session.expunge(check)

    scope = check.requested_scope_json
    is_link_check = check.programme_id == ARBITRARY_LINK_PROGRAMME_ID
    if is_link_check:
        programme = {
            **ARBITRARY_LINK_PROGRAMME,
            "name": scope["programme_name"],
            "provider": scope["source_host"],
            "search_terms": [scope["programme_name"]],
        }
    else:
        programme = load_registry()[check.programme_id]
    academic_year = scope["academic_year"]
    application_type = scope["application_type"]
    extraction_scope_hash = _extraction_scope_hash(programme, academic_year, application_type)
    usage: dict[str, Any] = {"search_calls": 0, "source_requests": 0, "model": {}}

    _set_stage(run_id, owner_token, "searching")
    search_urls: list[str] = []
    if not is_link_check:
        search = search_programme(settings, programme, academic_year, run_id)
        search_urls = search.urls
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
    candidate_urls.extend(search_urls)
    if not is_link_check:
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
            candidate = (
                retrieve_arbitrary_source(settings, url, request_budget)
                if is_link_check
                else retrieve_source(settings, programme, url, request_budget)
            )
            parsed_blocks, parsed_format, parsed_status = parse_source_bounded(
                candidate.content,
                candidate.content_type,
                candidate.resolved_url,
                max_pages=settings.max_pdf_pages,
                timeout_seconds=max(
                    settings.source_parse_timeout_seconds,
                    settings.ocr_timeout_seconds + 5 if settings.ocr_enabled else 0,
                ),
                ocr_enabled=settings.ocr_enabled,
                ocr_timeout_seconds=settings.ocr_timeout_seconds,
                max_ocr_pages=settings.max_ocr_pages,
            )
            scope_matches = (
                _has_arbitrary_deadline_scope(parsed_blocks, programme["name"], academic_year)
                if is_link_check
                else _has_requested_deadline_scope(parsed_blocks, programme, academic_year)
            )
            if not scope_matches:
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
                        Extraction.prompt_hash == extraction_scope_hash,
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
                    extraction_blocks = _blocks_for_extraction(
                        prepared.blocks, programme, academic_year
                    )
                    extracted, document_usage = extract_facts(
                        settings,
                        programme["name"],
                        academic_year,
                        application_type,
                        extraction_blocks,
                        deadline_only=programme.get("extraction_focus") == "deadline_only",
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
                            prompt_hash=extraction_scope_hash,
                            schema_version=SCHEMA_VERSION,
                            facts_json=extracted.model_dump(mode="json"),
                            validation_json={
                                "status": "valid",
                                "validated_at": _utcnow().isoformat(),
                                "evidence_ids": "valid",
                                "dates": "supported_in_actor_action_context",
                                "block_count": len(extraction_blocks),
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
    link_roles = {item.retrieved.source_policy["role"] for item in prepared_documents}
    authority_established = bool(link_roles & {"government_publisher"})
    link_limitations = []
    if is_link_check:
        link_limitations.append(
            "This mode checked only the supplied source and did not search for amendments."
        )
        if not authority_established:
            link_limitations.append(
                "Publisher authority was not independently established for this host. "
                "Confirm the notice with the scholarship issuer."
            )
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
        extraction_prompt_hash=extraction_scope_hash,
        mode="link" if is_link_check else "live",
        input_mode=("arbitrary_official_link" if is_link_check else "live_search_and_retrieval"),
        additional_limitations=link_limitations,
    )
    if is_link_check:
        report_json["coverage"] = "partial"
    if is_link_check and not authority_established and report_json["student_deadline"]:
        candidate_deadline = report_json["student_deadline"]
        report_json["student_deadline"] = None
        report_json["deadline_resolution"] = "insufficient"
        report_json["summary"] = (
            "A student date was extracted, but the source host's authority was not established; "
            "no definitive deadline was selected."
        )
        report_json["conflicts"].append(
            {
                "kind": "publisher_authority",
                "message": "The supplied host could not be verified as the scholarship issuer.",
                "candidates": [candidate_deadline],
            }
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
            "prompt": extraction_scope_hash,
        }
