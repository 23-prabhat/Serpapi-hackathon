"""Deterministic deadline role tests."""

from datetime import UTC, datetime

from app.services.extraction import CandidateDeadline, ExtractedFacts
from app.services.rules.deadlines import resolve_deadlines


def test_student_deadline_does_not_use_later_verification_date() -> None:
    facts = ExtractedFacts(
        academic_year="2026-27",
        application_types=["fresh", "renewal"],
        notice_type="amendment",
        deadlines=[
            CandidateDeadline(
                actor="student",
                action="submit",
                date_raw="October 31, 2026",
                date_iso="2026-10-31",
                evidence_block_ids=["block_1"],
            ),
            CandidateDeadline(
                actor="institution",
                action="verify",
                date_raw="November 15, 2026",
                date_iso="2026-11-15",
                evidence_block_ids=["block_1"],
            ),
            CandidateDeadline(
                actor="administrator",
                action="verify",
                date_raw="November 30, 2026",
                date_iso="2026-11-30",
                evidence_block_ids=["block_1"],
            ),
        ],
        unresolved_items=[],
    )

    result = resolve_deadlines(
        facts,
        "version_1",
        datetime(2026, 10, 2, tzinfo=UTC),
        "Asia/Kolkata",
    )

    assert result["resolution"] == "supported"
    assert result["selected"]["date"] == "2026-10-31"
    assert [item["date"] for item in result["other"]] == [
        "2026-11-15",
        "2026-11-30",
    ]
