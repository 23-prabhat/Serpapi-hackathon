"""Source policy and retrieval boundary tests."""

import pytest

from app.services.failures import SourceUnavailableError, UnsupportedSourceError
from app.services.registry import load_registry, match_source_policy
from app.services.retrieval import SourceRequestBudget, _validate_content_type


def test_source_policy_rejects_credentials_ports_and_unreviewed_paths() -> None:
    programme = load_registry()["nmmss"]

    assert match_source_policy(programme, "https://pib.gov.in/PressReleasePage.aspx?id=1")
    assert match_source_policy(programme, "https://user@pib.gov.in/PressReleasePage.aspx") is None
    assert match_source_policy(programme, "https://pib.gov.in:8443/PressReleasePage.aspx") is None
    assert match_source_policy(programme, "https://pib.gov.in/private/report") is None


def test_content_type_must_match_document_signature() -> None:
    with pytest.raises(UnsupportedSourceError, match="PDF signature"):
        _validate_content_type("application/pdf", "https://example.gov/report.pdf", b"not pdf")
    with pytest.raises(UnsupportedSourceError, match="HTML document marker"):
        _validate_content_type("text/html", "https://example.gov/report", b"plain text")

    assert (
        _validate_content_type(
            "text/html; charset=utf-8",
            "https://example.gov/report",
            b"<!doctype html><html><body>notice</body></html>",
        )
        == "text/html"
    )


def test_source_request_budget_is_shared_and_exact() -> None:
    budget = SourceRequestBudget(limit=2)
    budget.consume()
    budget.consume()

    assert budget.used == 2
    with pytest.raises(SourceUnavailableError, match="budget"):
        budget.consume()
