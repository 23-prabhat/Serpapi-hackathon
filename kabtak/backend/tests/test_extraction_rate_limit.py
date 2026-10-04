"""Bounded retry behavior for provider rate limits."""

from unittest.mock import Mock, patch

from app.config import Settings
from app.services.extraction import ExtractedDocument, extract_facts
from app.services.parsing import Block


def test_groq_rate_limit_honours_bounded_retry_after() -> None:
    limited = Mock(status_code=429, is_success=False, headers={})
    limited.json.return_value = {
        "error": {"message": "Token limit reached. Please try again in 40.5s."}
    }
    success = Mock(
        status_code=200,
        is_success=True,
        json=lambda: {
            "choices": [
                {
                    "message": {
                        "content": ExtractedDocument(
                            records=[
                                {
                                    "academic_year": None,
                                    "application_types": ["unknown"],
                                    "applicant_group": None,
                                    "applies_to_all_groups": True,
                                    "scope_evidence_block_ids": ["block_1"],
                                    "notice_type": "unknown",
                                    "deadlines": [],
                                    "conditions": [],
                                    "required_documents": [],
                                    "application_links": [],
                                    "unresolved_items": [],
                                }
                            ],
                            document_unresolved_items=[],
                        ).model_dump_json()
                    }
                }
            ],
            "usage": {"total_tokens": 10},
        },
    )
    client = Mock()
    client.post.side_effect = [limited, success]
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    block = Block("block_1", "p", "body", "No exact facts.", "hash")

    with (
        patch("app.services.extraction.httpx.Client", return_value=context),
        patch("app.services.extraction.sleep") as wait,
    ):
        _, usage = extract_facts(
            Settings(
                llm_provider="groq",
                llm_model="test-model",
                llm_api_key="test-key",
                max_llm_attempts=2,
            ),
            "Test programme",
            "2026-27",
            "fresh",
            [block],
        )

    wait.assert_called_once_with(30)
    assert usage["attempt_count"] == 2


def test_groq_strict_generation_failure_gets_a_bounded_correction() -> None:
    invalid = Mock(status_code=400, is_success=False, headers={})
    invalid.json.return_value = {
        "error": {
            "message": "Generated JSON does not match the expected schema.",
            "failed_generation": '{"date_iso":null}',
        }
    }
    success = Mock(
        status_code=200,
        is_success=True,
        json=lambda: {
            "choices": [
                {
                    "message": {
                        "content": ExtractedDocument(
                            records=[
                                {
                                    "academic_year": None,
                                    "application_types": ["unknown"],
                                    "applicant_group": None,
                                    "applies_to_all_groups": True,
                                    "scope_evidence_block_ids": ["block_1"],
                                    "notice_type": "unknown",
                                    "deadlines": [],
                                    "conditions": [],
                                    "required_documents": [],
                                    "application_links": [],
                                    "unresolved_items": ["No exact calendar date."],
                                }
                            ],
                            document_unresolved_items=[],
                        ).model_dump_json()
                    }
                }
            ],
            "usage": {"total_tokens": 10},
        },
    )
    client = Mock()
    client.post.side_effect = [invalid, success]
    context = Mock()
    context.__enter__ = Mock(return_value=client)
    context.__exit__ = Mock(return_value=False)
    block = Block("block_1", "p", "body", "No exact facts.", "hash")

    with (
        patch("app.services.extraction.httpx.Client", return_value=context),
        patch("app.services.extraction.sleep") as wait,
    ):
        document, usage = extract_facts(
            Settings(
                llm_provider="groq",
                llm_model="test-model",
                llm_api_key="test-key",
                max_llm_attempts=2,
            ),
            "Test programme",
            "2026-27",
            "fresh",
            [block],
        )

    wait.assert_called_once_with(5)
    assert document.records[0].deadlines == []
    assert usage["attempt_count"] == 2
    correction = client.post.call_args_list[1].kwargs["json"]["messages"][-1]["content"]
    assert "never put null" in correction
