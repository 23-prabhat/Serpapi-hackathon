"""Source policy and retrieval boundary tests."""

import pytest

from app.services.failures import (
    SourceUnavailableError,
    UnsafeSourceURLError,
    UnsupportedSourceError,
)
from app.services.registry import load_registry, match_source_policy
from app.services.retrieval import (
    SourceRequestBudget,
    _arbitrary_source_policy,
    _require_public_host,
    _validate_content_type,
    validate_arbitrary_url_syntax,
)


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


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user@example.gov.in/notice",
        "https://127.0.0.1/notice",
        "https://example.gov.in:8443/notice",
        "https://bit.ly/notice",
        "https://drive.google.com/file/notice",
    ],
)
def test_arbitrary_link_syntax_blocks_unsafe_and_indirect_targets(url: str) -> None:
    with pytest.raises(UnsafeSourceURLError):
        validate_arbitrary_url_syntax(url)


def test_arbitrary_link_policy_marks_authority_without_trusting_every_host() -> None:
    assert _arbitrary_source_policy("https://education.gov.in/notice")["role"] == (
        "government_publisher"
    )
    assert _arbitrary_source_policy("https://college.ac.in/notice")["role"] == (
        "education_publisher"
    )
    assert _arbitrary_source_policy("https://scholarship.example/notice")["role"] == (
        "unverified_publisher"
    )
    assert _arbitrary_source_policy("http://education.gov.in/notice")["role"] == (
        "unverified_publisher"
    )


def test_arbitrary_link_dns_cannot_resolve_to_a_private_address(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.retrieval.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )

    with pytest.raises(UnsupportedSourceError, match="non-public"):
        _require_public_host("https://official.example/notice")
