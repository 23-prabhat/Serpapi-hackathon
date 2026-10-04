"""Regression checks discovered by the Phase 5 held-out NSP cases."""

from app.services.extraction import CandidateDeadline, ExtractedFacts, validate_evidence
from app.services.parsing import parse_html


def test_academic_year_in_navigation_is_preserved_as_document_context() -> None:
    blocks = parse_html(
        b"""
        <html><body>
          <nav><h6>Academic Year 2026-27</h6></nav>
          <main><h2>Scholarship</h2><p>Student Application Open till: 31-10-2026</p></main>
        </body></html>
        """
    )

    assert blocks[0].kind == "document_context"
    assert blocks[0].location == "document metadata"
    assert blocks[0].text == "Academic Year 2026-27"
    assert all("navigation" not in block.text for block in blocks)


def test_nsp_unqualified_application_schedule_can_establish_fresh_scope() -> None:
    blocks = parse_html(
        b"""
        <html><body><main>
          <h6>Academic Year 2026-27</h6>
          <p>Student Application Open till: 31-10-2026</p>
        </main></body></html>
        """
    )
    scope_blocks = [block.block_id for block in blocks]
    facts = ExtractedFacts.model_validate(
        {
            "academic_year": "2026-27",
            "application_types": ["fresh"],
            "applicant_group": None,
            "applies_to_all_groups": True,
            "scope_evidence_block_ids": scope_blocks,
            "notice_type": "original",
            "deadlines": [],
            "conditions": [],
            "required_documents": [],
            "application_links": [],
            "unresolved_items": [],
        }
    )

    validate_evidence(facts, blocks)


def test_nsp_dno_sno_mno_deadline_is_valid_administrator_evidence() -> None:
    blocks = parse_html(
        b"""
        <html><body><main>
          <p>DNO/SNO/MNO Verification Open till:30-11-2026</p>
        </main></body></html>
        """
    )
    facts = ExtractedFacts.model_validate(
        {
            "academic_year": None,
            "application_types": ["unknown"],
            "applicant_group": None,
            "applies_to_all_groups": True,
            "scope_evidence_block_ids": ["block_1"],
            "notice_type": "original",
            "deadlines": [
                CandidateDeadline(
                    actor="administrator",
                    action="verify",
                    date_raw="30-11-2026",
                    date_iso="2026-11-30",
                    time=None,
                    timezone=None,
                    application_types=["unknown"],
                    applicant_group=None,
                    applies_to_all_groups=True,
                    explicitly_revises_deadline=False,
                    supersedes_date_iso=None,
                    evidence_block_ids=["block_1"],
                ).model_dump()
            ],
            "conditions": [],
            "required_documents": [],
            "application_links": [],
            "unresolved_items": [],
        }
    )

    validate_evidence(facts, blocks)


def test_nsp_defective_application_deadline_is_valid_student_correction_evidence() -> None:
    blocks = parse_html(
        b"""
        <html><body><main>
          <p>Defective Application Verification Open till:15-11-2026</p>
        </main></body></html>
        """
    )
    facts = ExtractedFacts.model_validate(
        {
            "academic_year": None,
            "application_types": ["unknown"],
            "applicant_group": None,
            "applies_to_all_groups": True,
            "scope_evidence_block_ids": ["block_1"],
            "notice_type": "original",
            "deadlines": [
                CandidateDeadline(
                    actor="student",
                    action="correct",
                    date_raw="15-11-2026",
                    date_iso="2026-11-15",
                    time=None,
                    timezone=None,
                    application_types=["unknown"],
                    applicant_group=None,
                    applies_to_all_groups=True,
                    explicitly_revises_deadline=False,
                    supersedes_date_iso=None,
                    evidence_block_ids=["block_1"],
                ).model_dump()
            ],
            "conditions": [],
            "required_documents": [],
            "application_links": [],
            "unresolved_items": [],
        }
    )

    validate_evidence(facts, blocks)
