"""Code-controlled report and cross-cycle safety tests."""

from datetime import UTC, datetime

from app.schemas.reports import ReportRead
from app.services.extraction import (
    CandidateDeadline,
    EligibilityRule,
    ExtractedApplicationLink,
    ExtractedFacts,
    ExtractedRequiredDocument,
)
from app.services.reporting import build_report
from app.services.rules.types import SourcedRecord

PROGRAMME = {
    "id": "nmmss",
    "name": "National Means-cum-Merit Scholarship Scheme",
    "locale": {"comparison_timezone": "Asia/Kolkata"},
}


def extracted(academic_year: str | None = "2026-27") -> ExtractedFacts:
    return ExtractedFacts(
        academic_year=academic_year,
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
            ),
            CandidateDeadline(
                actor="administrator",
                action="verify",
                date_raw="30 November 2026",
                date_iso="2026-11-30",
                time=None,
                timezone=None,
                application_types=["fresh"],
                applicant_group=None,
                applies_to_all_groups=True,
                explicitly_revises_deadline=False,
                supersedes_date_iso=None,
                evidence_block_ids=["block_1"],
            ),
        ],
        conditions=[
            EligibilityRule(
                operator="lte",
                field="annual_family_income_inr",
                value=350000,
                unit="INR_per_year",
                children=[],
                source_text="Income must not exceed INR 3,50,000.",
                evidence_block_ids=["block_2"],
            )
        ],
        required_documents=[],
        application_links=[],
        unresolved_items=[],
    )


def report(facts: ExtractedFacts, profile: dict | None = None) -> dict:
    result = build_report(
        run_id="run_1",
        reference_time=datetime(2026, 10, 3, tzinfo=UTC),
        programme=PROGRAMME,
        academic_year="2026-27",
        application_type="fresh",
        sources=[
            SourcedRecord(
                facts,
                "version_1",
                frozenset({"deadline", "amendment", "eligibility"}),
            )
        ],
        applicant_group=None,
        profile=profile,
        incomplete_source_attempts=False,
        model_id="test-model",
    )
    ReportRead.model_validate(result)
    return result


def test_wrong_year_never_becomes_current_deadline() -> None:
    result = report(extracted("2025-26"))

    assert result["deadline_resolution"] == "insufficient"
    assert result["student_deadline"] is None
    assert "does not match" in " ".join(result["limitations"])


def test_future_deadline_does_not_claim_portal_is_open() -> None:
    result = report(extracted())

    assert result["student_deadline"]["timing"] == "date_ahead"
    assert result["portal_status"] == "not_checked"


def test_report_summary_is_code_controlled_and_separates_roles() -> None:
    result = report(extracted())

    assert result["summary"] == (
        "The student submission date in this notice is 2026-10-31. "
        "The 2026-11-30 date applies to administrator verify."
    )
    assert result["provenance"]["rules_version"] == "phase3-2"


def test_profile_drives_basic_eligibility_without_claiming_full_eligibility() -> None:
    result = report(extracted(), {"annual_family_income_inr": 300000})

    assert result["eligibility"] == "meets_checked_conditions"
    assert result["conditions"][0]["result"] == "true"
    assert "eligible" not in result["summary"].casefold()


def test_no_profile_preserves_published_conditions_as_not_assessed() -> None:
    result = report(extracted())

    assert result["eligibility"] == "not_assessed"
    assert len(result["conditions"]) == 1
    assert result["conditions"][0]["result"] == "unknown"


def test_multiple_records_from_one_document_do_not_mix_academic_years() -> None:
    previous = extracted("2025-26")
    current = extracted("2026-27")
    current.deadlines[0].date_iso = "2026-11-15"
    current.deadlines[0].date_raw = "15 November 2026"

    result = build_report(
        run_id="run_1",
        reference_time=datetime(2026, 10, 3, tzinfo=UTC),
        programme=PROGRAMME,
        academic_year="2026-27",
        application_type="fresh",
        sources=[
            SourcedRecord(previous, "version_shared", frozenset({"deadline"})),
            SourcedRecord(current, "version_shared", frozenset({"deadline"})),
        ],
        applicant_group=None,
        profile=None,
        incomplete_source_attempts=False,
        model_id="test-model",
    )

    assert result["deadline_resolution"] == "supported"
    assert result["student_deadline"]["date"] == "2026-11-15"


def test_failed_candidate_source_makes_coverage_partial() -> None:
    result = build_report(
        run_id="run_1",
        reference_time=datetime(2026, 10, 3, tzinfo=UTC),
        programme=PROGRAMME,
        academic_year="2026-27",
        application_type="fresh",
        sources=[SourcedRecord(extracted(), "version_1", frozenset({"deadline"}))],
        applicant_group=None,
        profile=None,
        incomplete_source_attempts=True,
        model_id="test-model",
    )

    assert result["coverage"] == "partial"
    assert "could not be used" in " ".join(result["limitations"])


def test_ocr_evidence_is_visible_as_partial_with_a_recognition_warning() -> None:
    result = build_report(
        run_id="run_1",
        reference_time=datetime(2026, 10, 3, tzinfo=UTC),
        programme=PROGRAMME,
        academic_year="2026-27",
        application_type="fresh",
        sources=[
            SourcedRecord(
                extracted(),
                "version_1",
                frozenset({"deadline"}),
                parse_status="ocr",
            )
        ],
        applicant_group=None,
        profile=None,
        incomplete_source_attempts=False,
        model_id="test-model",
    )

    assert result["coverage"] == "partial"
    assert "recognition errors" in " ".join(result["limitations"])
    assert "partially parsed" not in " ".join(result["limitations"])


def test_report_includes_source_backed_documents_and_application_links() -> None:
    facts = extracted()
    facts.required_documents = [
        ExtractedRequiredDocument(
            source_text="Upload the income certificate.",
            evidence_block_ids=["block_2"],
        )
    ]
    facts.application_links = [
        ExtractedApplicationLink(
            url="https://scholarships.gov.in/apply",
            source_text="Apply at https://scholarships.gov.in/apply",
            evidence_block_ids=["block_2"],
        )
    ]

    result = report(facts)

    assert result["required_documents"][0]["evidence_refs"] == [
        {"version_id": "version_1", "block_id": "block_2"}
    ]
    assert result["application_links"][0]["url"] == "https://scholarships.gov.in/apply"
