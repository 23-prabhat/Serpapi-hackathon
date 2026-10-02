"""Tests for the Phase 0 block-preserving parser."""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_probe_module():
    path = Path(__file__).parents[1] / "probe_sources.py"
    spec = spec_from_file_location("phase0_probe_sources", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_html_parser_keeps_deadline_actor_with_table_date() -> None:
    probe = load_probe_module()
    content = b"""
    <main>
      <h2>Revised schedule</h2>
      <table>
        <tr><th>Process</th><th>Last date</th></tr>
        <tr><td>Submission of application</td><td>October 31, 2026</td></tr>
        <tr><td>Institute verification</td><td>November 15, 2026</td></tr>
      </table>
    </main>
    """

    blocks = probe.parse_html(content)

    table = next(block for block in blocks if block.kind == "table")
    assert "Submission of application | October 31, 2026" in table.text
    assert "Institute verification | November 15, 2026" in table.text
    assert table.location == "section Revised schedule, table 1"


def test_excerpt_is_bounded_without_changing_short_text() -> None:
    probe = load_probe_module()

    assert probe.bounded_excerpt("  student   deadline  ", limit=40) == "student deadline"
    assert probe.bounded_excerpt("x" * 20, limit=10) == "xxxxxxxxx…"


def test_html_parser_keeps_scheme_card_scope_with_all_dates() -> None:
    probe = load_probe_module()
    content = b"""
    <main>
      <div class="row mb-4 border-bottom">
        <div><h6>Example Scholarship</h6>
          <span>Student Application Open till: 31-10-2026</span>
          <span>Institute Verification Open till: 15-11-2026</span>
        </div>
      </div>
    </main>
    """

    blocks = probe.parse_html(content)

    assert len(blocks) == 1
    assert blocks[0].kind == "scheme_card"
    assert "Example Scholarship" in blocks[0].text
    assert "Student Application Open till: 31-10-2026" in blocks[0].text
    assert "Institute Verification Open till: 15-11-2026" in blocks[0].text
