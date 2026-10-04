"""Live programme registry completeness tests."""

import pytest

from app.errors import APIError
from app.services.registry import (
    is_live_supported,
    load_registry,
    match_source_policy,
    public_programmes,
    require_supported_programme,
)

LIVE_PROGRAMME_IDS = {
    "nmmss",
    "pm-usp-csss",
    "aicte-pragati",
    "national-overseas-scholarship",
    "top-class-st",
}


def test_exactly_five_reviewed_programmes_are_live() -> None:
    registry = load_registry()
    assert {item["id"] for item in registry.values() if is_live_supported(item)} == (
        LIVE_PROGRAMME_IDS
    )
    assert {
        item["id"] for item in public_programmes() if item["support_status"] == "live_supported"
    } == LIVE_PROGRAMME_IDS


@pytest.mark.parametrize("programme_id", sorted(LIVE_PROGRAMME_IDS))
def test_live_programme_scope_and_fallbacks_are_admissible(programme_id: str) -> None:
    programme = load_registry()[programme_id]
    assert programme["supported_cycles"]
    assert programme["application_types"]
    for cycle in programme["supported_cycles"]:
        admitted = require_supported_programme(
            programme_id,
            cycle,
            programme["application_types"][0],
        )
        assert admitted["id"] == programme_id
        urls = programme.get("reviewed_discovery_urls", {}).get(cycle, [])
        assert urls, f"{programme_id} {cycle} has no reviewed discovery fallback"
        assert all(match_source_policy(programme, url) for url in urls)


def test_deferred_programme_is_not_live() -> None:
    with pytest.raises(APIError) as exc_info:
        require_supported_programme("azim-premji-scholarship", "2026-27", "fresh")
    assert exc_info.value.code == "UNSUPPORTED_PROGRAMME"
