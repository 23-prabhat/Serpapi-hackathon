"""Report-level source-version integrity tests."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    Check,
    Document,
    DocumentVersion,
    Extraction,
    Programme,
    Run,
    RunDocument,
)
from app.services.evidence import validate_report_evidence
from app.services.failures import InvalidExtractionError


def populated_session(tmp_path) -> tuple[Session, str, str]:
    engine = create_engine(f"sqlite:///{tmp_path / 'evidence.db'}")
    Base.metadata.create_all(engine)
    session = Session(engine)
    now = datetime.now(UTC)
    run_id = str(uuid4())
    version_id = str(uuid4())
    content = b"<!doctype html><html><body>Student deadline: 31 October 2026</body></html>"
    digest = hashlib.sha256(content).hexdigest()
    original_path = tmp_path / "source.html"
    blocks_path = tmp_path / "source.blocks.json"
    original_path.write_bytes(content)
    block_text = "Student deadline: 31 October 2026. Income must not exceed INR 3,50,000."
    revised_text = "The student deadline is revised to 15 November 2026."
    blocks_path.write_text(
        json.dumps(
            [
                {
                    "block_id": "block_1",
                    "kind": "p",
                    "location": "section Deadline",
                    "text": block_text,
                    "text_sha256": hashlib.sha256(block_text.encode()).hexdigest(),
                    "metadata": {},
                },
                {
                    "block_id": "block_2",
                    "kind": "p",
                    "location": "section Amendment",
                    "text": revised_text,
                    "text_sha256": hashlib.sha256(revised_text.encode()).hexdigest(),
                    "metadata": {},
                },
            ]
        ),
        encoding="utf-8",
    )
    programme = Programme(
        id="nmmss",
        name="NMMSS",
        provider="Ministry of Education",
        registry_version="1",
        support_status="live_supported",
    )
    check = Check(
        id=str(uuid4()),
        programme_id=programme.id,
        requested_scope_json={},
        profile_json=None,
        notice_url=None,
        saved_at=None,
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    run = Run(
        id=run_id,
        check_id=check.id,
        kind="live",
        status="running",
        stage="checking",
        operation_scope=f"check:{check.id}:live",
        idempotency_key="evidence-test",
        request_hash="0" * 64,
        reference_time=now,
        created_at=now,
    )
    document = Document(
        id=str(uuid4()),
        canonical_url="https://pib.gov.in/PressReleasePage.aspx?PRID=test",
        source_policy_id="pib",
        publisher_role="authoritative_notice",
    )
    version = DocumentVersion(
        id=version_id,
        document_id=document.id,
        sha256=digest,
        original_path=str(original_path),
        parsed_blocks_path=str(blocks_path),
        parser_version="phase2-2",
        first_seen_at=now,
        parse_status="parsed",
    )
    extraction = Extraction(
        id=str(uuid4()),
        document_version_id=version_id,
        model_id="test-model",
        prompt_hash="1" * 64,
        schema_version="1",
        facts_json={},
        validation_json={"status": "valid"},
        created_at=now,
    )
    association = RunDocument(
        id=str(uuid4()),
        run_id=run_id,
        requested_url=document.canonical_url,
        resolved_url=document.canonical_url,
        document_version_id=version_id,
        extraction_id=extraction.id,
        checked_at=now,
        cache_provenance="new_version",
        fetch_status="success",
        error_code=None,
    )
    session.add_all([programme, check, run, document, version, extraction, association])
    session.commit()
    return session, run_id, version_id


def report(version_id: str, *, block_id: str = "block_1", date: str = "2026-10-31"):
    return {
        "student_deadline": {
            "date": date,
            "evidence_refs": [{"version_id": version_id, "block_id": block_id}],
        },
        "other_deadlines": [],
    }


def test_report_evidence_is_bound_to_the_run_and_exact_source_version(tmp_path) -> None:
    session, run_id, version_id = populated_session(tmp_path)
    try:
        index = validate_report_evidence(session, run_id, report(version_id))
        assert index[(version_id, "block_1")]["text"].startswith("Student deadline")

        with pytest.raises(InvalidExtractionError, match="outside"):
            validate_report_evidence(session, run_id, report(version_id, block_id="block_99"))
        with pytest.raises(InvalidExtractionError, match="does not occur"):
            validate_report_evidence(session, run_id, report(version_id, date="2026-11-15"))
    finally:
        session.close()


def test_report_condition_evidence_is_bound_to_the_run(tmp_path) -> None:
    session, run_id, version_id = populated_session(tmp_path)
    value = report(version_id)
    value["conditions"] = [
        {
            "source_text": "Income must not exceed INR 3,50,000.",
            "evidence_refs": [{"version_id": version_id, "block_id": "block_1"}],
            "children": [],
        }
    ]
    try:
        validate_report_evidence(session, run_id, value)
        value["conditions"][0]["source_text"] = "A fabricated condition"
        with pytest.raises(InvalidExtractionError, match="condition text"):
            validate_report_evidence(session, run_id, value)
    finally:
        session.close()


def test_amendment_dates_require_their_own_evidence_references(tmp_path) -> None:
    session, run_id, version_id = populated_session(tmp_path)
    value = report(version_id)
    value["amendments"] = [
        {
            "previous_date": "2026-10-31",
            "revised_date": "2026-11-15",
            "previous_evidence_refs": [{"version_id": version_id, "block_id": "block_1"}],
            "revised_evidence_refs": [{"version_id": version_id, "block_id": "block_2"}],
        }
    ]
    try:
        validate_report_evidence(session, run_id, value)
        value["amendments"][0]["revised_evidence_refs"] = [
            {"version_id": version_id, "block_id": "block_1"}
        ]
        with pytest.raises(InvalidExtractionError, match="revised amendment date"):
            validate_report_evidence(session, run_id, value)
    finally:
        session.close()
