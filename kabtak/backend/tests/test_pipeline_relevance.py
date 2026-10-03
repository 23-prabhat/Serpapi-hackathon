"""Pipeline source-scope selection regressions."""

import hashlib

from app.services.parsing import Block
from app.services.pipeline import _has_requested_deadline_scope
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
