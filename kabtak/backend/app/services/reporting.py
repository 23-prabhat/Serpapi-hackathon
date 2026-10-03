"""Code-controlled report construction."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.extraction import ExtractedFacts, prompt_hash
from app.services.rules.deadlines import resolve_deadlines


def build_report(
    *,
    run_id: str,
    reference_time: datetime,
    programme: dict[str, Any],
    academic_year: str,
    application_type: str,
    version_id: str,
    facts: ExtractedFacts,
    model_id: str,
    parse_status: str,
) -> dict[str, Any]:
    resolved = resolve_deadlines(
        facts,
        version_id,
        reference_time,
        programme["locale"]["comparison_timezone"],
    )
    limitations = list(facts.unresolved_items)
    if parse_status != "parsed":
        limitations.append("The source document was only partially parsed.")
    if facts.academic_year and facts.academic_year != academic_year:
        limitations.append("The source academic year does not match the requested cycle.")
        resolved = {"resolution": "insufficient", "selected": None, "other": [], "conflicts": []}
    if resolved["resolution"] == "insufficient":
        limitations.append("No exact student submission date was established.")

    return {
        "run_id": run_id,
        "mode": "live",
        "reference_time": reference_time.isoformat(),
        "coverage": ("complete_for_attempted_scope" if parse_status == "parsed" else "partial"),
        "scope": {
            "programme_id": programme["id"],
            "programme_name": programme["name"],
            "academic_year": academic_year,
            "application_type": application_type,
        },
        "deadline_resolution": resolved["resolution"],
        "student_deadline": resolved["selected"],
        "portal_status": "not_checked",
        "eligibility": "not_assessed",
        "conditions": [],
        "other_deadlines": resolved["other"],
        "conflicts": resolved["conflicts"],
        "limitations": limitations,
        "provenance": {
            "rules_version": "phase1-1",
            "schema_version": "1",
            "input_mode": "live_search_and_retrieval",
            "model_id": model_id,
            "prompt_hash": prompt_hash(),
        },
    }
