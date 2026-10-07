"""End-to-end worker rules for guarded arbitrary-link checks."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.base import Base
from app.db.models import Check, Report, Run
from app.services import pipeline
from app.services.extraction import CandidateDeadline, ExtractedDocument, ExtractedFacts
from app.services.parsing import Block
from app.services.registry import ARBITRARY_LINK_PROGRAMME_ID, seed_programmes
from app.services.retrieval import RetrievedSource


@pytest.mark.parametrize(
    ("publisher_role", "expected_resolution"),
    [
        ("government_publisher", "supported"),
        ("unverified_publisher", "insufficient"),
    ],
)
def test_link_pipeline_skips_search_and_requires_publisher_authority(
    publisher_role: str,
    expected_resolution: str,
    tmp_path,
    monkeypatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'link.db'}")
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", test_sessions)
    now = datetime(2026, 10, 7, tzinfo=UTC)
    check_id = str(uuid4())
    run_id = str(uuid4())
    source_url = "https://education.gov.in/scholarships/merit-notice"
    with test_sessions() as session:
        seed_programmes(session)
        session.add(
            Check(
                id=check_id,
                programme_id=ARBITRARY_LINK_PROGRAMME_ID,
                requested_scope_json={
                    "input_mode": "arbitrary_official_link",
                    "programme_name": "National Merit Scholarship",
                    "source_host": "education.gov.in",
                    "academic_year": "2026-27",
                    "application_type": "fresh",
                    "applicant_group": None,
                },
                profile_json=None,
                notice_url=source_url,
                saved_at=None,
                created_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
        session.add(
            Run(
                id=run_id,
                check_id=check_id,
                kind="link",
                status="running",
                stage="searching",
                operation_scope="check:link:create",
                idempotency_key=f"link-{publisher_role}",
                request_hash="0" * 64,
                reference_time=now,
                created_at=now,
                owner_token="owner",
            )
        )
        session.commit()

    block_text = (
        "National Merit Scholarship 2026-27 fresh applications\n"
        "Student submission deadline | 31 October 2026"
    )
    block = Block(
        block_id="block_1",
        kind="table",
        location="deadline table",
        text=block_text,
        text_sha256=hashlib.sha256(block_text.encode()).hexdigest(),
        metadata={"headers": ["Action", "Deadline"]},
    )

    def reject_search(*_args, **_kwargs):
        raise AssertionError("arbitrary-link mode must not spend a search request")

    def fake_retrieve(_settings, url, _budget):
        content = b"<!doctype html><html><body>notice</body></html>"
        return RetrievedSource(
            requested_url=url,
            resolved_url=url,
            content=content,
            content_type="text/html",
            sha256=hashlib.sha256(content).hexdigest(),
            retrieved_at=now,
            source_policy={
                "id": "link-test",
                "role": publisher_role,
                "may_establish": ["deadline", "eligibility", "amendment"],
            },
        )

    def fake_extract(*_args, **_kwargs):
        return (
            ExtractedDocument(
                records=[
                    ExtractedFacts(
                        academic_year="2026-27",
                        application_types=["fresh"],
                        applicant_group=None,
                        applies_to_all_groups=True,
                        scope_evidence_block_ids=["block_1"],
                        notice_type="original",
                        deadlines=[
                            CandidateDeadline(
                                actor="student",
                                action="submit",
                                date_raw="31 October 2026",
                                date_iso="2026-10-31",
                                time=None,
                                timezone=None,
                                application_types=["fresh"],
                                applicant_group=None,
                                applies_to_all_groups=True,
                                explicitly_revises_deadline=False,
                                supersedes_date_iso=None,
                                evidence_block_ids=["block_1"],
                            )
                        ],
                        conditions=[],
                        required_documents=[],
                        application_links=[],
                        unresolved_items=[],
                    )
                ],
                document_unresolved_items=[],
            ),
            {"total_tokens": 10},
        )

    monkeypatch.setattr(pipeline, "search_programme", reject_search)
    monkeypatch.setattr(pipeline, "retrieve_arbitrary_source", fake_retrieve)
    monkeypatch.setattr(
        pipeline,
        "parse_source_bounded",
        lambda *_args, **_kwargs: ([block], "html", "parsed"),
    )
    monkeypatch.setattr(pipeline, "extract_facts", fake_extract)

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'link.db'}",
        data_dir=tmp_path / "data",
        llm_provider="groq",
        llm_model="test-model",
        llm_api_key="test-key",
    )
    pipeline.process_run(run_id, "owner", settings)

    with test_sessions() as session:
        stored = session.scalar(select(Report).where(Report.run_id == run_id))
        assert stored is not None
        report = stored.decisions_json
        assert report["mode"] == "link"
        assert report["provenance"]["input_mode"] == "arbitrary_official_link"
        assert report["deadline_resolution"] == expected_resolution
        assert report["coverage"] == "partial"
        if expected_resolution == "insufficient":
            assert report["student_deadline"] is None
        else:
            assert report["student_deadline"]["date"] == "2026-10-31"
        assert any("did not search for amendments" in item for item in report["limitations"])
        if expected_resolution == "insufficient":
            assert report["conflicts"][0]["kind"] == "publisher_authority"

    engine.dispose()
