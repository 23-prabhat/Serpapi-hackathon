"""Load and materialize deterministic, offline historical replays."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    Check,
    Document,
    DocumentVersion,
    Extraction,
    Report,
    Run,
    RunDocument,
)
from app.schemas.reports import ReportRead
from app.services.evidence import validate_report_evidence
from app.services.extraction import SCHEMA_VERSION, ExtractedDocument, validate_evidence
from app.services.parsing import Block
from app.services.registry import load_registry
from app.services.reporting import REPORT_SCHEMA_VERSION, build_report
from app.services.rules.types import SourcedRecord

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"
FIXTURE_PARSER_VERSION = "historical-fixture-1"


@lru_cache
def load_examples() -> dict[str, dict[str, Any]]:
    examples: dict[str, dict[str, Any]] = {}
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            examples[value["id"]] = value
    return examples


def public_examples() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "description": item["description"],
            "programme_name": item["programme_name"],
            "academic_year": item["academic_year"],
            "application_type": item["application_type"],
            "reference_time": item["reference_time"],
            "expected_student_deadline": item["report"]["student_deadline"]["date"],
            "source_url": item["source_url"],
        }
        for item in load_examples().values()
    ]


def materialize_replay(
    session: Session,
    settings: Settings,
    fixture: dict[str, Any],
    idempotency_key: str,
) -> Run:
    now = datetime.now(UTC)
    content = fixture["source_text"].encode()
    content_hash = hashlib.sha256(content).hexdigest()
    blocks = deepcopy(fixture["blocks"])
    for block in blocks:
        block["text_sha256"] = hashlib.sha256(block["text"].encode()).hexdigest()

    fixture_dir = Path(settings.data_dir) / "examples" / fixture["id"]
    fixture_dir.mkdir(parents=True, exist_ok=True)
    original_path = fixture_dir / f"{content_hash}.txt"
    blocks_path = fixture_dir / f"{content_hash}.blocks.json"
    _write_once(original_path, content)
    _write_once(
        blocks_path,
        json.dumps(blocks, ensure_ascii=False, indent=2).encode(),
    )

    document = session.scalar(
        select(Document).where(Document.canonical_url == fixture["source_url"])
    )
    if document is None:
        document = Document(
            id=str(uuid4()),
            canonical_url=fixture["source_url"],
            source_policy_id=f"fixture-{fixture['id']}",
            publisher_role=fixture["publisher_role"],
        )
        session.add(document)
        session.flush()
    version = session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document.id,
            DocumentVersion.sha256 == content_hash,
            DocumentVersion.parser_version == FIXTURE_PARSER_VERSION,
        )
    )
    if version is None:
        version = DocumentVersion(
            id=str(uuid4()),
            document_id=document.id,
            sha256=content_hash,
            original_path=str(original_path),
            parsed_blocks_path=str(blocks_path),
            parser_version=FIXTURE_PARSER_VERSION,
            first_seen_at=now,
            parse_status="parsed",
        )
        session.add(version)
        session.flush()
    extraction = session.scalar(
        select(Extraction).where(
            Extraction.document_version_id == version.id,
            Extraction.model_id == "packaged-fixture",
            Extraction.prompt_hash == "0" * 64,
            Extraction.schema_version == SCHEMA_VERSION,
        )
    )
    if extraction is None:
        extracted = ExtractedDocument.model_validate(fixture["extraction"])
        parsed_blocks = [Block(**block) for block in blocks]
        for record in extracted.records:
            validate_evidence(record, parsed_blocks)
        extraction = Extraction(
            id=str(uuid4()),
            document_version_id=version.id,
            model_id="packaged-fixture",
            prompt_hash="0" * 64,
            schema_version=SCHEMA_VERSION,
            facts_json=extracted.model_dump(mode="json"),
            validation_json={"status": "packaged_and_reviewed", "expected_report_match": None},
            created_at=now,
        )
        session.add(extraction)
        session.flush()

    check = Check(
        id=str(uuid4()),
        programme_id=fixture["programme_id"],
        requested_scope_json={
            "academic_year": fixture["academic_year"],
            "application_type": fixture["application_type"],
            "applicant_group": None,
        },
        profile_json=None,
        notice_url=fixture["source_url"],
        saved_at=None,
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    reference_time = datetime.fromisoformat(fixture["reference_time"])
    run = Run(
        id=str(uuid4()),
        check_id=check.id,
        kind="replay",
        status="completed",
        stage="finished",
        operation_scope=f"example:{fixture['id']}:replay",
        idempotency_key=idempotency_key,
        request_hash=hashlib.sha256(fixture["id"].encode()).hexdigest(),
        reference_time=reference_time,
        created_at=now,
        started_at=now,
        finished_at=now,
        heartbeat_at=now,
        version_manifest_json={
            "registry": "fixture",
            "parser": FIXTURE_PARSER_VERSION,
            "rules": "phase3-2",
            "schema": REPORT_SCHEMA_VERSION,
            "model": "packaged-fixture",
            "prompt": "0" * 64,
        },
        usage_json={"search_calls": 0, "source_requests": 0, "model": []},
    )
    session.add_all([check, run])
    session.flush()
    session.add(
        RunDocument(
            id=str(uuid4()),
            run_id=run.id,
            requested_url=fixture["source_url"],
            resolved_url=fixture["source_url"],
            document_version_id=version.id,
            extraction_id=extraction.id,
            checked_at=reference_time,
            cache_provenance="packaged_fixture",
            fetch_status="success",
            error_code=None,
        )
    )
    extracted = ExtractedDocument.model_validate(extraction.facts_json)
    programme = load_registry()[fixture["programme_id"]]
    capabilities = frozenset(
        fixture.get(
            "source_capabilities",
            ["deadline", "amendment", "eligibility", "portal_status_at_publication"],
        )
    )
    sourced_records = [
        SourcedRecord(
            record=record,
            version_id=version.id,
            source_capabilities=capabilities,
            document_unresolved_items=tuple(extracted.document_unresolved_items),
        )
        for record in extracted.records
    ]
    report_json = build_report(
        run_id=run.id,
        reference_time=reference_time,
        programme=programme,
        academic_year=fixture["academic_year"],
        application_type=fixture["application_type"],
        sources=sourced_records,
        applicant_group=None,
        profile=None,
        incomplete_source_attempts=False,
        model_id="packaged-fixture",
    )
    report_json["mode"] = "replay"
    report_json["provenance"] = {
        "rules_version": "phase3-2",
        "schema_version": REPORT_SCHEMA_VERSION,
        "input_mode": "packaged_fixture",
        "model_id": "packaged-fixture",
        "prompt_hash": "0" * 64,
    }
    report_json["limitations"] = [
        *report_json["limitations"],
        "Historical replay; this is not an open opportunity.",
        (
            "Replay uses packaged extraction and current deterministic rules; "
            "it does not repeat live search or AI extraction."
        ),
    ]
    expected = _replace_version(deepcopy(fixture["report"]), version.id)
    expected_match = _report_signature(report_json) == _report_signature(expected)
    extraction.validation_json = {
        **extraction.validation_json,
        "expected_report_match": expected_match,
    }
    if not expected_match:
        report_json["limitations"].append(
            "Replay regression: the current deterministic result differs from the "
            "reviewed expected report."
        )
    ReportRead.model_validate(report_json)
    session.flush()
    validate_report_evidence(session, run.id, report_json)
    session.add(
        Report(
            id=str(uuid4()),
            run_id=run.id,
            report_schema_version=REPORT_SCHEMA_VERSION,
            decisions_json=report_json,
            created_at=now,
        )
    )
    session.commit()
    return run


def _report_signature(report: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "scope",
        "deadline_resolution",
        "student_deadline",
        "portal_status",
        "eligibility",
        "conditions",
        "other_deadlines",
        "conflicts",
        "amendments",
        "required_documents",
        "application_links",
    )
    return {key: _without_evidence(report.get(key, [])) for key in keys}


def _without_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_evidence(item)
            for key, item in value.items()
            if key not in {"evidence_refs", "previous_evidence_refs", "revised_evidence_refs"}
        }
    if isinstance(value, list):
        return [_without_evidence(item) for item in value]
    return value


def _replace_version(value: Any, version_id: str) -> Any:
    if isinstance(value, dict):
        return {key: _replace_version(item, version_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_version(item, version_id) for item in value]
    return version_id if value == "__VERSION__" else value


def _write_once(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise RuntimeError("Historical fixture path contains different bytes")
        return
    temporary = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
