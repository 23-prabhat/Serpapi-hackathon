"""Reviewed programme registry loading and live support policy."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from sqlalchemy.orm import Session

from app.db.models import Programme
from app.errors import APIError

REGISTRY_DIR = Path(__file__).resolve().parents[3] / "config" / "programmes"
LIVE_ONBOARDING_STATUS = "phase0_selected"


def is_live_supported(programme: dict[str, Any]) -> bool:
    """Return whether a reviewed registry entry passed the live onboarding gate."""

    return programme.get("onboarding_status") == LIVE_ONBOARDING_STATUS


@lru_cache
def load_registry() -> dict[str, dict[str, Any]]:
    programmes: dict[str, dict[str, Any]] = {}
    for path in sorted(REGISTRY_DIR.glob("*.yaml")):
        item = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(item, dict) and item.get("id"):
            programmes[item["id"]] = item
    return programmes


def public_programmes() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "provider": item["provider"],
            "supported_cycles": item["supported_cycles"],
            "application_types": item["application_types"],
            "support_status": "live_supported" if is_live_supported(item) else "coming_soon",
        }
        for item in load_registry().values()
    ]


def require_supported_programme(
    programme_id: str, academic_year: str, application_type: str
) -> dict[str, Any]:
    item = load_registry().get(programme_id)
    if item is None or not is_live_supported(item):
        raise APIError(
            422,
            "UNSUPPORTED_PROGRAMME",
            "Select one of Kabtak's reviewed live scholarship programmes.",
        )
    if academic_year not in item["supported_cycles"]:
        raise APIError(422, "UNSUPPORTED_CYCLE", "Select a reviewed academic cycle.")
    if application_type not in item["application_types"]:
        raise APIError(422, "UNSUPPORTED_APPLICATION_TYPE", "Select fresh or renewal.")
    return item


def match_source_policy(programme: dict[str, Any], url: str) -> dict[str, Any] | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return None
    if parsed.port not in {None, 80, 443}:
        return None
    hostname = (parsed.hostname or "").lower().removeprefix("www.")
    for policy in programme["sources"]:
        if hostname != policy["host"].lower().removeprefix("www."):
            continue
        if any(parsed.path.startswith(prefix) for prefix in policy["path_prefixes"]):
            return policy
    return None


def validate_notice_url(programme: dict[str, Any], url: str | None) -> None:
    if url and match_source_policy(programme, url) is None:
        raise APIError(
            422,
            "UNSUPPORTED_SOURCE",
            "This URL is outside the reviewed source list for the selected programme.",
        )


def seed_programmes(session: Session) -> None:
    for item in load_registry().values():
        support_status = "live_supported" if is_live_supported(item) else "coming_soon"
        programme = session.get(Programme, item["id"])
        if programme is None:
            session.add(
                Programme(
                    id=item["id"],
                    name=item["name"],
                    provider=item["provider"],
                    registry_version=str(item["schema_version"]),
                    support_status=support_status,
                )
            )
        else:
            programme.name = item["name"]
            programme.provider = item["provider"]
            programme.registry_version = str(item["schema_version"])
            programme.support_status = support_status
    session.commit()
