"""Bounded search fallback regression tests."""

from collections.abc import Iterator

import httpx
import pytest

from app.config import Settings
from app.services import search
from app.services.registry import load_registry


def fake_client(responses: list[httpx.Response]):
    class FakeClient:
        parameters: list[dict[str, object]] = []

        def __init__(self, **_kwargs: object) -> None:
            self.responses: Iterator[httpx.Response] = iter(responses)

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get(self, _url: str, *, params: dict[str, object]) -> httpx.Response:
            self.parameters.append(params)
            return next(self.responses)

    return FakeClient


def test_search_continues_after_unreviewed_results_and_soft_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    responses = [
        httpx.Response(
            200,
            json={
                "search_metadata": {"id": "one", "status": "Success"},
                "organic_results": [{"link": "https://example.com/not-reviewed"}],
            },
        ),
        httpx.Response(
            200,
            json={
                "search_metadata": {"id": "two", "status": "Success"},
                "error": "Google hasn't returned any results for this query.",
            },
        ),
        httpx.Response(
            200,
            json={
                "search_metadata": {"id": "three", "status": "Success"},
                "organic_results": [
                    {
                        "title": "NMMSS deadline extended",
                        "link": "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2317657",
                        "snippet": "Applications for 2026-27 close on October 31.",
                    }
                ],
            },
        ),
    ]
    client = fake_client(responses)
    monkeypatch.setattr(search.httpx, "Client", client)
    settings = Settings(
        serpapi_api_key="test-key",
        data_dir=tmp_path,
        max_search_attempts=4,
    )

    outcome = search.search_nmmss(
        settings,
        load_registry()["nmmss"],
        "2026-27",
        "search-regression",
    )

    assert outcome.metadata["attempt_count"] == 3
    assert outcome.metadata["discovery_mode"] == "search"
    assert outcome.urls == ["https://www.pib.gov.in/PressReleasePage.aspx?PRID=2317657"]
    assert all(item["as_sitesearch"] == "pib.gov.in" for item in client.parameters)


def test_search_uses_reviewed_cycle_fallback_after_bounded_attempts(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    responses = [
        httpx.Response(
            200,
            json={
                "search_metadata": {"id": "one", "status": "Success"},
                "organic_results": [],
            },
        ),
        httpx.Response(
            200,
            json={
                "search_metadata": {"id": "two", "status": "Success"},
                "error": "Google hasn't returned any results for this query.",
            },
        ),
    ]
    monkeypatch.setattr(search.httpx, "Client", fake_client(responses))
    settings = Settings(
        serpapi_api_key="test-key",
        data_dir=tmp_path,
        max_search_attempts=2,
    )

    outcome = search.search_nmmss(
        settings,
        load_registry()["nmmss"],
        "2026-27",
        "registry-fallback",
    )

    assert outcome.metadata["attempt_count"] == 2
    assert outcome.metadata["discovery_mode"] == "registry_fallback"
    assert outcome.urls == [
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2317657&lang=2&reg=48"
    ]


def test_search_rejects_allowlisted_but_irrelevant_programme_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    response = httpx.Response(
        200,
        json={
            "search_metadata": {"id": "workshop", "status": "Success"},
            "organic_results": [
                {
                    "title": (
                        "Ministry of Education organises one-day workshop on "
                        "National Means-cum-Merit Scholarship Scheme"
                    ),
                    "link": "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2238858",
                    "snippet": "Workshop held in Delhi on 10 March 2026.",
                }
            ],
        },
    )
    monkeypatch.setattr(search.httpx, "Client", fake_client([response]))
    settings = Settings(
        serpapi_api_key="test-key",
        data_dir=tmp_path,
        max_search_attempts=1,
    )

    outcome = search.search_nmmss(
        settings,
        load_registry()["nmmss"],
        "2026-27",
        "irrelevant-reviewed-result",
    )

    assert outcome.metadata["discovery_mode"] == "registry_fallback"
    assert outcome.metadata["reviewed_result_count"] == 0
    assert outcome.urls == [
        "https://www.pib.gov.in/PressReleasePage.aspx?PRID=2317657&lang=2&reg=48"
    ]
