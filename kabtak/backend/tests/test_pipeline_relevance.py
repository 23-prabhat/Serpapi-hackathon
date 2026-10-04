"""Pipeline source-scope selection regressions."""

import hashlib

import pytest

from app.services.parsing import Block, parse_html
from app.services.pipeline import (
    EXTRACTION_TEXT_BUDGET,
    _blocks_for_extraction,
    _extraction_scope_hash,
    _has_requested_deadline_scope,
)
from app.services.registry import load_registry


def block(text: str) -> Block:
    return Block(
        block_id="block_1",
        kind="p",
        location="document",
        text=text,
        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def test_workshop_page_is_not_accepted_as_deadline_evidence() -> None:
    blocks = [
        block(
            "Ministry of Education organises one-day workshop on National "
            "Means-cum-Merit Scholarship Scheme (NMMSS) on 10 March 2026. "
            "Officials discussed timely verification and scheme implementation."
        )
    ]

    assert not _has_requested_deadline_scope(blocks, load_registry()["nmmss"], "2026-27")


def test_cycle_specific_deadline_notice_is_accepted() -> None:
    blocks = [
        block(
            "The last date for submission of applications under the National "
            "Means-cum-Merit Scholarship Scheme (NMMSS) for 2026-27 is "
            "31 October 2026."
        )
    ]

    assert _has_requested_deadline_scope(blocks, load_registry()["nmmss"], "2026-27")


@pytest.mark.parametrize(
    "programme_id",
    ["pm-usp-csss", "aicte-pragati", "top-class-st"],
)
def test_nsp_catalogue_cards_are_accepted_and_isolated_by_programme(
    programme_id: str,
) -> None:
    blocks = parse_html(
        b"""
        <html><body>
          <nav><h6>Academic Year 2026-27</h6></nav>
          <main>
            <div class="row border-bottom">
              <h6>AICTE - Pragati Scholarship Scheme For Girl Students (Technical Degree)</h6>
              <span>Student Application Open till : 31-10-2026</span>
            </div>
            <div class="row border-bottom">
              <h6>
                PM-USP Central Sector Scheme of Scholarship for College and University Students
              </h6>
              <span>Student Application Closed on : 30-09-2026</span>
            </div>
            <div class="row border-bottom">
              <h6>National Fellowship and Scholarship for Higher Education of ST Students</h6>
              <span>Student Application Open till : 31-10-2026</span>
            </div>
          </main>
        </body></html>
        """
    )
    programme = load_registry()[programme_id]

    assert _has_requested_deadline_scope(blocks, programme, "2026-27")
    selected = _blocks_for_extraction(blocks, programme, "2026-27")
    assert [block.kind for block in selected] == ["document_context", "scheme_card"]
    assert any(marker.lower() in selected[1].text.lower() for marker in programme["search_terms"])


def test_nos_application_window_without_exact_day_is_kept_for_unresolved_report() -> None:
    programme = load_registry()["national-overseas-scholarship"]
    blocks = [
        block(
            "National Overseas Scholarship Scheme applicable from 2026-27. "
            "The portal for second round will be opened in September/October 2026 "
            "for a period of 40 days for inviting of applications."
        )
    ]

    assert _has_requested_deadline_scope(blocks, programme, "2026-27")


def test_long_single_programme_document_is_bounded_without_changing_blocks() -> None:
    programme = load_registry()["national-overseas-scholarship"]
    blocks = [
        block(
            "National Overseas Scholarship 2026-27 eligibility and inviting of applications "
            + ("evidence " * 300)
        ),
        *[
            Block(
                block_id=f"block_{index}",
                kind="page_text",
                location=f"page {index}",
                text="eligibility evidence " * 1_000,
                text_sha256=hashlib.sha256(("eligibility evidence " * 1_000).encode()).hexdigest(),
            )
            for index in range(2, 8)
        ],
    ]

    selected = _blocks_for_extraction(blocks, programme, "2026-27")
    rendered_size = sum(
        len(item.block_id) + len(item.location) + len(item.text) + 8 for item in selected
    )
    assert selected
    assert rendered_size <= EXTRACTION_TEXT_BUDGET
    assert rendered_size <= programme["extraction_text_budget"]
    assert blocks[0] in selected


def test_long_pdf_prioritizes_deadline_and_document_sections() -> None:
    programme = load_registry()["national-overseas-scholarship"]
    blocks = [
        Block(
            block_id="block_1",
            kind="page_text",
            location="page 1",
            text="National Overseas Scholarship applicable from 2026-27. Eligibility.",
            text_sha256="1",
        ),
        *[
            Block(
                block_id=f"block_{index}",
                kind="page_text",
                location=f"page {index}",
                text=("General eligibility material. " * 120),
                text_sha256=str(index),
            )
            for index in range(2, 8)
        ],
        Block(
            block_id="block_8",
            kind="page_text",
            location="page 8",
            text=(
                "Application procedure: the portal for second round will be opened "
                "for inviting of applications. " + "Details. " * 80
            ),
            text_sha256="8",
        ),
        Block(
            block_id="block_9",
            kind="page_text",
            location="page 9",
            text="List of Document Required at the Application Stage. " + "Certificate. " * 80,
            text_sha256="9",
        ),
    ]

    selected = _blocks_for_extraction(blocks, programme, "2026-27")

    assert blocks[0] in selected
    assert blocks[-2] in selected
    assert blocks[-1] in selected


def test_extraction_cache_identity_includes_programme_and_scope() -> None:
    registry = load_registry()
    pragati = _extraction_scope_hash(registry["aicte-pragati"], "2026-27", "fresh")
    pm_usp = _extraction_scope_hash(registry["pm-usp-csss"], "2026-27", "renewal")

    assert pragati != pm_usp
    assert len(pragati) == 64
