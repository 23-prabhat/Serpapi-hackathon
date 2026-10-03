"""Strict extraction schema and evidence-reference tests."""

import hashlib

import pytest
from pydantic import ValidationError

from app.services.extraction import CandidateDeadline, ExtractedFacts, validate_evidence
from app.services.failures import InvalidExtractionError
from app.services.parsing import Block


def block(text: str) -> Block:
    return Block(
        block_id="block_1",
        kind="p",
        location="section Deadline",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def facts(date_iso: str, block_id: str = "block_1") -> ExtractedFacts:
    return ExtractedFacts(
        academic_year="2026-27",
        application_types=["fresh"],
        notice_type="amendment",
        deadlines=[
            CandidateDeadline(
                actor="student",
                action="submit",
                date_raw="31 October 2026",
                date_iso=date_iso,
                evidence_block_ids=[block_id],
            )
        ],
        unresolved_items=[],
    )


def test_unknown_evidence_block_is_rejected() -> None:
    with pytest.raises(InvalidExtractionError, match="unknown evidence block"):
        validate_evidence(facts("2026-10-31", "block_99"), [block("31 October 2026")])


def test_date_must_occur_in_the_cited_block() -> None:
    with pytest.raises(InvalidExtractionError, match="does not occur"):
        validate_evidence(facts("2026-10-31"), [block("Verification ends 15 November 2026")])


def test_date_must_be_a_real_calendar_date() -> None:
    with pytest.raises(ValidationError, match="real calendar date"):
        facts("2026-02-31")
