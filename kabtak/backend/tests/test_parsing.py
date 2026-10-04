"""Structured and immutable source parsing tests."""

import hashlib
import io
import json
from pathlib import Path

import pytest

from app.services.failures import ParsingFailedError, UnsupportedPDFError
from app.services.parsing import Block, parse_html, parse_pdf, persist_source_files


def test_html_table_preserves_headers_rows_locations_and_hashes() -> None:
    blocks = parse_html(
        b"""
        <!doctype html><html><body><main>
          <h1>NMMSS notice</h1>
          <table>
            <tr><th>Actor</th><th>Deadline</th></tr>
            <tr><td>Student</td><td>31 October 2026</td></tr>
          </table>
        </main></body></html>
        """
    )

    table = next(block for block in blocks if block.kind == "table")
    assert table.location == "section NMMSS notice, table 1"
    assert table.metadata["headers"] == ["Actor", "Deadline"]
    assert table.metadata["rows"][1] == ["Student", "31 October 2026"]
    assert table.text_sha256 == hashlib.sha256(table.text.encode()).hexdigest()


def test_html_table_preserves_visual_header_rows_without_th_tags() -> None:
    blocks = parse_html(
        b"""
        <!doctype html><html><body><table>
          <tr><td>Process</td><td>Last Date</td></tr>
          <tr><td>Submission of Application</td><td>October 31, 2026</td></tr>
        </table></body></html>
        """
    )

    assert blocks[0].metadata["headers"] == ["Process", "Last Date"]


def test_nsp_scheme_card_preserves_title_cycle_and_every_schedule_row() -> None:
    blocks = parse_html(
        b"""
        <html><body>
          <nav><h6>Academic Year 2026-27</h6></nav>
          <main>
            <div class="row border-bottom">
              <h6>AICTE - Pragati Scholarship Scheme For Girl Students</h6>
              <span>Scheme Open from : 01-06-2026</span>
              <span>Student Application Open till : 31-10-2026</span>
              <span>Institute Verification Open till:15-11-2026</span>
            </div>
          </main>
        </body></html>
        """
    )

    assert blocks[0].kind == "document_context"
    assert blocks[0].text == "Academic Year 2026-27"
    card = next(block for block in blocks if block.kind == "scheme_card")
    assert "AICTE - Pragati Scholarship Scheme" in card.text
    assert "Student Application Open till : 31-10-2026" in card.text
    assert "Institute Verification Open till:15-11-2026" in card.text
    assert not any(block.kind == "heading" for block in blocks)


def test_source_files_are_versioned_and_never_overwritten(tmp_path) -> None:
    content = b"<!doctype html><html><body>notice</body></html>"
    digest = hashlib.sha256(content).hexdigest()
    block = Block(
        block_id="block_1",
        kind="p",
        location="document",
        text="Deadline: 31 October 2026",
        text_sha256=hashlib.sha256(b"Deadline: 31 October 2026").hexdigest(),
    )

    original_path, blocks_path = persist_source_files(
        tmp_path, "pib", digest, content, "html", [block]
    )
    repeated_paths = persist_source_files(tmp_path, "pib", digest, content, "html", [block])

    assert repeated_paths == (original_path, blocks_path)
    assert Path(original_path).read_bytes() == content
    assert json.loads(Path(blocks_path).read_text(encoding="utf-8"))[0]["block_id"] == "block_1"

    changed = Block(
        block_id="block_1",
        kind="p",
        location="document",
        text="different",
        text_sha256=hashlib.sha256(b"different").hexdigest(),
    )
    with pytest.raises(ParsingFailedError, match="Immutable evidence"):
        persist_source_files(tmp_path, "pib", digest, content, "html", [changed])


def test_scanned_or_empty_pdf_is_an_explicit_unsupported_state() -> None:
    import pypdfium2

    document = pypdfium2.PdfDocument.new()
    document.new_page(595, 842)
    output = io.BytesIO()
    document.save(output)

    with pytest.raises(UnsupportedPDFError, match="no extractable text"):
        parse_pdf(output.getvalue())
