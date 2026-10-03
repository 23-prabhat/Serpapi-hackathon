"""Strict extraction schema and evidence-reference tests."""

import hashlib

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services import extraction
from app.services.extraction import (
    CandidateDeadline,
    EligibilityRule,
    ExtractedApplicationLink,
    ExtractedDocument,
    ExtractedFacts,
    ExtractedRequiredDocument,
    extract_facts,
    validate_evidence,
)
from app.services.failures import InvalidExtractionError
from app.services.parsing import Block


def block(text: str, block_id: str = "block_1") -> Block:
    text = f"2026-27 fresh {text}"
    return Block(
        block_id=block_id,
        kind="p",
        location="section Deadline",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def facts(date_iso: str, block_id: str = "block_1") -> ExtractedFacts:
    return ExtractedFacts(
        academic_year="2026-27",
        application_types=["fresh"],
        applicant_group=None,
        applies_to_all_groups=True,
        scope_evidence_block_ids=["block_1"],
        notice_type="amendment",
        deadlines=[
            CandidateDeadline(
                actor="student",
                action="submit",
                date_raw="31 October 2026",
                date_iso=date_iso,
                time=None,
                timezone=None,
                application_types=["fresh"],
                applicant_group=None,
                applies_to_all_groups=True,
                explicitly_revises_deadline=False,
                supersedes_date_iso=None,
                evidence_block_ids=[block_id],
            )
        ],
        conditions=[],
        required_documents=[],
        application_links=[],
        unresolved_items=[],
    )


def test_unknown_evidence_block_is_rejected() -> None:
    with pytest.raises(InvalidExtractionError, match="unknown evidence block"):
        validate_evidence(facts("2026-10-31", "block_99"), [block("31 October 2026")])


def test_date_must_occur_in_the_cited_block() -> None:
    with pytest.raises(InvalidExtractionError, match="actor/action row"):
        validate_evidence(facts("2026-10-31"), [block("Verification ends 15 November 2026")])


def test_date_must_be_a_real_calendar_date() -> None:
    with pytest.raises(ValidationError, match="real calendar date"):
        facts("2026-02-31")


def test_eligibility_value_must_occur_in_cited_context() -> None:
    value = facts("2026-10-31")
    value.conditions = [
        EligibilityRule(
            operator="lte",
            field="annual_family_income_inr",
            value=350000,
            unit="INR_per_year",
            children=[],
            source_text="Annual family income applies",
            evidence_block_ids=["block_1"],
        )
    ]
    source = block(
        "Applications close 31 October 2026. Annual family income applies: INR 2,50,000."
    )

    with pytest.raises(InvalidExtractionError, match="Eligibility value"):
        validate_evidence(value, [source])


def test_indian_lakh_value_is_validated_without_string_matching() -> None:
    value = facts("2026-10-31")
    value.conditions = [
        EligibilityRule(
            operator="lte",
            field="annual_family_income_inr",
            value=350000,
            unit="INR_per_year",
            children=[],
            source_text="Income must not exceed ₹3.50 lakh per annum.",
            evidence_block_ids=["block_1"],
        )
    ]

    validate_evidence(
        value,
        [block("Applications close 31 October 2026. Income must not exceed ₹3.50 lakh per annum.")],
    )


def test_application_type_requires_a_cited_scope_marker() -> None:
    value = facts("2026-10-31")
    value.application_types = ["renewal"]

    with pytest.raises(InvalidExtractionError, match="Application type"):
        validate_evidence(value, [block("Applications close 31 October 2026.")])


def test_date_from_wrong_table_row_is_rejected() -> None:
    value = facts("2026-04-22")
    text = (
        "2026-27 fresh\nStudent submission | March 31, 2026\n"
        "Administrator verification | April 22, 2026"
    )
    table = Block(
        block_id="block_1",
        kind="table",
        location="table 1",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        metadata={
            "rows": [
                ["Student submission", "March 31, 2026"],
                ["Administrator verification", "April 22, 2026"],
            ]
        },
    )

    with pytest.raises(InvalidExtractionError, match="actor/action row"):
        validate_evidence(value, [table])


def test_explicit_time_and_timezone_must_occur_in_evidence() -> None:
    value = facts("2026-10-31")
    value.deadlines[0].time = "23:59"
    value.deadlines[0].timezone = "Asia/Kolkata"

    validate_evidence(
        value,
        [block("Applications close October 31, 2026 at 11:59 PM IST.")],
    )

    value.deadlines[0].time = "22:00"
    with pytest.raises(InvalidExtractionError, match="time does not occur"):
        validate_evidence(
            value,
            [block("Applications close October 31, 2026 at 11:59 PM IST.")],
        )


def test_inclusive_income_language_rejects_strict_less_than_operator() -> None:
    value = facts("2026-10-31")
    value.conditions = [
        EligibilityRule(
            operator="lt",
            field="annual_family_income_inr",
            value=350000,
            unit="INR_per_year",
            children=[],
            source_text="Income must not exceed ₹3.50 lakh per annum.",
            evidence_block_ids=["block_1"],
        )
    ]

    with pytest.raises(InvalidExtractionError, match="lte operator"):
        validate_evidence(
            value,
            [
                block(
                    "Applications close 31 October 2026. "
                    "Income must not exceed ₹3.50 lakh per annum."
                )
            ],
        )


def test_next_steps_must_be_present_in_their_cited_evidence() -> None:
    value = facts("2026-10-31")
    value.required_documents = [
        ExtractedRequiredDocument(
            source_text="Upload the income certificate.",
            evidence_block_ids=["block_1"],
        )
    ]
    value.application_links = [
        ExtractedApplicationLink(
            url="https://scholarships.gov.in/apply",
            source_text="Apply at https://scholarships.gov.in/apply",
            evidence_block_ids=["block_1"],
        )
    ]
    source = block(
        "Applications close 31 October 2026. Upload the income certificate. "
        "Apply at https://scholarships.gov.in/apply"
    )

    validate_evidence(value, [source])

    value.application_links[0].url = "https://example.invalid/apply"
    with pytest.raises(InvalidExtractionError, match="Application link"):
        validate_evidence(value, [source])

    with pytest.raises(ValidationError, match="public HTTP"):
        ExtractedApplicationLink(
            url="javascript:alert(1)",
            source_text="Apply here",
            evidence_block_ids=["block_1"],
        )


def test_extraction_retries_when_structured_output_fails_evidence_validation(
    monkeypatch,
) -> None:
    scope_block = Block(
        block_id="block_1",
        kind="p",
        location="paragraph 1",
        text="NMMSS 2026-27. Student submission closes October 31, 2026.",
        text_sha256="1" * 64,
    )
    type_block = Block(
        block_id="block_2",
        kind="p",
        location="paragraph 2",
        text="This schedule applies to fresh applications.",
        text_sha256="2" * 64,
    )
    invalid = ExtractedDocument(
        records=[facts("2026-10-31")],
        document_unresolved_items=[],
    )
    corrected_record = facts("2026-10-31")
    corrected_record.scope_evidence_block_ids = ["block_1", "block_2"]
    corrected = ExtractedDocument(
        records=[corrected_record],
        document_unresolved_items=[],
    )
    responses = iter([invalid.model_dump_json(), corrected.model_dump_json()])
    requests: list[dict] = []

    class FakeResponse:
        is_success = True
        status_code = 200

        def __init__(self, content: str) -> None:
            self.content = content

        def json(self) -> dict:
            return {
                "choices": [{"message": {"content": self.content}}],
                "usage": {"total_tokens": 10},
            }

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, _url, **kwargs) -> FakeResponse:
            requests.append(kwargs["json"])
            return FakeResponse(next(responses))

    monkeypatch.setattr(extraction.httpx, "Client", FakeClient)
    settings = Settings(
        _env_file=None,
        llm_provider="groq",
        llm_model="test-model",
        llm_api_key="test-key",
        max_llm_attempts=2,
    )

    result, usage = extract_facts(
        settings,
        "NMMSS",
        "2026-27",
        "fresh",
        [scope_block, type_block],
    )

    assert result == corrected
    assert usage["attempt_count"] == 2
    assert usage["total_tokens"] == 20
    assert len(requests) == 2
    assert "Validation failed" in requests[1]["messages"][-1]["content"]
