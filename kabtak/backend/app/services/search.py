"""Bounded SerpApi search adapter for reviewed live programmes."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.services.registry import match_source_policy


@dataclass(frozen=True)
class SearchOutcome:
    query: str
    urls: list[str]
    provider_search_id: str | None
    result_created_at: datetime | None
    response_path: str
    metadata: dict[str, Any]


def _normalized_search_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def _is_deadline_result(
    programme: dict[str, Any], academic_year: str, title: str, snippet: str
) -> bool:
    searchable = _normalized_search_text(f"{title} {snippet}")
    programme_markers = {
        programme["id"].lower(),
        programme["id"].lower().replace("-", " "),
        _normalized_search_text(programme["name"]),
        *(
            _normalized_search_text(marker)
            for marker in programme.get("search_terms", [])
            if isinstance(marker, str)
        ),
    }
    deadline_markers = (
        "deadline",
        "last date",
        "closing date",
        "open till",
        "closed on",
        "submission of application",
        "submission of applications",
        "application deadline",
        "applications extended",
        "application extended",
        "inviting of applications",
    )
    normalized_cycle = _normalized_search_text(academic_year)
    has_programme = any(marker and marker in searchable for marker in programme_markers)
    has_cycle = normalized_cycle in searchable
    has_deadline_intent = any(marker in searchable for marker in deadline_markers)
    return has_programme and has_cycle and has_deadline_intent


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".search-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def search_programme(
    settings: Settings,
    programme: dict[str, Any],
    academic_year: str,
    run_id: str,
) -> SearchOutcome:
    if not settings.serpapi_api_key:
        raise RuntimeError("SERPAPI_API_KEY is not configured")

    year = academic_year.split("-")[0]
    search_terms = programme.get("search_terms") or [programme["name"]]
    primary_term = str(search_terms[0])
    reviewed_hosts = sorted({source["host"] for source in programme["sources"]})
    site_scope = " OR ".join(f"site:{host}" for host in reviewed_hosts)
    queries = [
        f'"{primary_term}" "{academic_year}" deadline ({site_scope})',
        f'"{primary_term}" "{academic_year}" extension amendment revised ({site_scope})',
        f'"{primary_term}" scholarship "last date" {year} ({site_scope})',
        f'"{primary_term}" application "open till" {year} ({site_scope})',
    ][: settings.max_search_attempts]
    requested_at = datetime.now(UTC)
    candidates: list[tuple[int, str]] = []
    sanitized_results: list[dict[str, str]] = []
    attempts: list[dict[str, Any]] = []
    result_search_metadata: dict[str, Any] = {}
    organic_result_count = 0
    # Search providers can take longer than a direct document fetch while a live
    # result is prepared, so give this bounded request its own modest allowance.
    with httpx.Client(timeout=max(30, settings.source_request_timeout_seconds)) as client:
        for query in queries:
            safe_parameters = {
                "engine": "google",
                "q": query,
                "num": 10,
                "hl": "en",
                "gl": "in",
            }
            attempt: dict[str, Any] = {
                "parameters": safe_parameters,
                "requested_at": datetime.now(UTC).isoformat(),
            }
            try:
                response = client.get(
                    "https://serpapi.com/search.json",
                    params={**safe_parameters, "api_key": settings.serpapi_api_key},
                )
            except httpx.TimeoutException:
                attempt.update(outcome="timeout", error_code="SEARCH_TIMEOUT")
                attempts.append(attempt)
                continue
            except httpx.RequestError:
                attempt.update(outcome="request_failed", error_code="SEARCH_REQUEST_FAILED")
                attempts.append(attempt)
                continue
            if response.status_code in {401, 403}:
                raise RuntimeError("SerpApi authentication failed")
            if response.status_code == 429:
                raise RuntimeError("SerpApi rate or quota limit reached")
            if not response.is_success:
                attempt.update(
                    outcome="provider_failed",
                    error_code=f"SEARCH_HTTP_{response.status_code}",
                )
                attempts.append(attempt)
                continue
            payload = response.json()
            result_search_metadata = payload.get("search_metadata", {})
            attempt["search_metadata"] = {
                "id": result_search_metadata.get("id"),
                "created_at": result_search_metadata.get("created_at"),
            }
            provider_error = payload.get("error")
            if provider_error:
                normalized_error = str(provider_error).lower()
                if any(
                    marker in normalized_error
                    for marker in ("invalid api key", "account", "quota", "rate limit")
                ):
                    raise RuntimeError("SerpApi account cannot perform this search")
                attempt.update(outcome="no_results", error_code="SEARCH_NO_RESULTS")
                attempts.append(attempt)
                continue
            organic_results = payload.get("organic_results", [])
            organic_result_count += len(organic_results)
            year_tokens = {academic_year, academic_year.replace("-", "–"), year}
            reviewed_before = len(candidates)
            for item in organic_results:
                url = item.get("link")
                if not isinstance(url, str) or match_source_policy(programme, url) is None:
                    continue
                title = str(item.get("title", ""))
                snippet = str(item.get("snippet", ""))
                if not _is_deadline_result(programme, academic_year, title, snippet):
                    continue
                searchable = f"{title} {snippet} {url}".lower()
                score = 0
                if any(token.lower() in searchable for token in year_tokens):
                    score += 5
                if "extend" in searchable or "deadline" in searchable or "last date" in searchable:
                    score += 3
                if urlparse(url).path.startswith("/PressReleasePage.aspx"):
                    score += 2
                candidates.append((score, url))
                sanitized_results.append({"title": title, "link": url, "snippet": snippet})
            reviewed_count = len(candidates) - reviewed_before
            attempt.update(
                outcome=("reviewed_results_found" if reviewed_count else "no_reviewed_results"),
                organic_result_count=len(organic_results),
                reviewed_result_count=reviewed_count,
            )
            attempts.append(attempt)

    ordered_urls: list[str] = []
    for _score, url in sorted(candidates, key=lambda item: item[0], reverse=True):
        if url not in ordered_urls:
            ordered_urls.append(url)
    discovery_mode = "search"
    if not ordered_urls:
        configured_urls = programme.get("reviewed_discovery_urls", {}).get(academic_year, [])
        ordered_urls = [
            url for url in configured_urls if match_source_policy(programme, url) is not None
        ]
        discovery_mode = "registry_fallback"
    if not ordered_urls:
        raise RuntimeError(
            f"SerpApi returned no reviewed source for {programme['name']} in {academic_year}"
        )

    created_at = None
    raw_created_at = result_search_metadata.get("created_at")
    if isinstance(raw_created_at, str):
        try:
            created_at = datetime.fromisoformat(raw_created_at.replace("Z", "+00:00"))
        except ValueError:
            created_at = None

    output_path = Path(settings.data_dir).resolve() / "search" / f"{run_id}.json"
    _atomic_json(
        output_path,
        {
            "requested_at": requested_at.isoformat(),
            "attempts": attempts,
            "discovery_mode": discovery_mode,
            "selected_urls": ordered_urls[: settings.max_source_documents],
            "organic_results": sanitized_results,
        },
    )
    return SearchOutcome(
        query=attempts[-1]["parameters"]["q"],
        urls=ordered_urls[: settings.max_source_documents],
        provider_search_id=result_search_metadata.get("id"),
        result_created_at=created_at,
        response_path=str(output_path),
        metadata={
            "parameters": attempts[-1]["parameters"],
            "organic_result_count": organic_result_count,
            "reviewed_result_count": len(sanitized_results),
            "attempt_count": len(attempts),
            "discovery_mode": discovery_mode,
        },
    )


# Compatibility for older imports and local scripts. New production code uses
# the programme-neutral name above.
search_nmmss = search_programme
