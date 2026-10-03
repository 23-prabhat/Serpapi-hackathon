"""Database-backed multi-document Phase 3 pipeline integration test."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.base import Base
from app.db.models import Check, Programme, Report, Run, RunDocument
from app.services import pipeline
from app.services.extraction import CandidateDeadline, ExtractedDocument, ExtractedFacts
from app.services.parsing import Block
from app.services.retrieval import RetrievedSource
from app.services.search import SearchOutcome


def test_pipeline_combines_original_and_separate_amendment(tmp_path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'pipeline.db'}")
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(pipeline, "SessionLocal", test_sessions)

    now = datetime(2026, 10, 2, tzinfo=UTC)
    check_id = str(uuid4())
    run_id = str(uuid4())
    with test_sessions.begin() as session:
        session.add(
            Programme(
                id="nmmss",
                name="NMMSS",
                provider="Ministry of Education",
                registry_version="1",
                support_status="phase1_supported",
            )
        )
        session.add(
            Check(
                id=check_id,
                programme_id="nmmss",
                requested_scope_json={
                    "academic_year": "2026-27",
                    "application_type": "fresh",
                    "applicant_group": None,
                },
                profile_json=None,
                notice_url=None,
                saved_at=None,
                created_at=now,
                expires_at=now + timedelta(days=1),
            )
        )
        session.add(
            Run(
                id=run_id,
                check_id=check_id,
                kind="live",
                status="running",
                stage="searching",
                operation_scope=f"check:{check_id}:live",
                idempotency_key="phase3-multi-source",
                request_hash="0" * 64,
                reference_time=now,
                created_at=now,
                owner_token="owner",
            )
        )

    urls = [
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=original",
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=original-alias",
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=amendment",
    ]

    def fake_search(*_args, **_kwargs) -> SearchOutcome:
        return SearchOutcome(
            query="NMMSS 2026-27 deadline extension",
            urls=urls,
            provider_search_id="search_1",
            result_created_at=now,
            response_path=str(tmp_path / "search.json"),
            metadata={"attempt_count": 1, "parameters": {"q": "test"}},
        )

    def fake_retrieve(_settings, _programme, url, _budget) -> RetrievedSource:
        label = "amendment" if "amendment" in url else "original"
        resolved_url = urls[0] if "original-alias" in url else url
        content = f"<!doctype html><html><body>{label}</body></html>".encode()
        return RetrievedSource(
            requested_url=url,
            resolved_url=resolved_url,
            content=content,
            content_type="text/html",
            sha256=hashlib.sha256(content).hexdigest(),
            retrieved_at=now,
            source_policy={
                "id": f"pib-{label}",
                "role": "issuer_release",
                "may_establish": ["deadline", "amendment", "eligibility"],
            },
        )

    def fake_parse(content, *_args, **_kwargs):
        amendment = b"amendment" in content
        date_text = "October 31, 2026" if amendment else "October 15, 2026"
        row_label = "Student submission extended" if amendment else "Student submission"
        text = (
            "National Means-cum-Merit Scholarship Scheme NMMSS 2026-27 fresh deadline\n"
            f"{row_label} | {date_text}"
        )
        return (
            [
                Block(
                    block_id="block_1",
                    kind="table",
                    location="table 1",
                    text=text,
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    metadata={"rows": [[row_label, date_text]]},
                )
            ],
            "html",
            "parsed",
        )

    def fake_extract(_settings, _programme, _year, _application_type, blocks):
        amendment = "extended" in blocks[0].text
        date_iso = "2026-10-31" if amendment else "2026-10-15"
        return (
            ExtractedDocument(
                records=[
                    ExtractedFacts(
                        academic_year="2026-27",
                        application_types=["fresh"],
                        applicant_group=None,
                        applies_to_all_groups=True,
                        scope_evidence_block_ids=["block_1"],
                        notice_type="amendment" if amendment else "original",
                        deadlines=[
                            CandidateDeadline(
                                actor="student",
                                action="submit",
                                date_raw=("October 31, 2026" if amendment else "October 15, 2026"),
                                date_iso=date_iso,
                                time=None,
                                timezone=None,
                                application_types=["fresh"],
                                applicant_group=None,
                                applies_to_all_groups=True,
                                explicitly_revises_deadline=amendment,
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

    monkeypatch.setattr(pipeline, "search_nmmss", fake_search)
    monkeypatch.setattr(pipeline, "retrieve_source", fake_retrieve)
    monkeypatch.setattr(pipeline, "parse_source_bounded", fake_parse)
    monkeypatch.setattr(pipeline, "extract_facts", fake_extract)

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'pipeline.db'}",
        data_dir=tmp_path / "data",
        serpapi_api_key="test",
        llm_provider="groq",
        llm_model="test-model",
        llm_api_key="test",
        max_source_documents=3,
    )
    pipeline.process_run(run_id, "owner", settings)

    with test_sessions() as session:
        stored_run = session.get(Run, run_id)
        report = session.scalar(select(Report).where(Report.run_id == run_id))
        documents = session.scalars(select(RunDocument).where(RunDocument.run_id == run_id)).all()
        assert stored_run is not None and stored_run.status == "completed"
        assert report is not None
        assert report.decisions_json["student_deadline"]["date"] == "2026-10-31"
        assert report.decisions_json["amendments"][0]["previous_date"] == "2026-10-15"
        assert len({item.document_version_id for item in documents}) == 2
        assert len(documents) == 3
        assert all(item.extraction_id for item in documents)

    engine.dispose()
