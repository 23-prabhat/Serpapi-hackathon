"""Code-controlled report construction."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.extraction import prompt_hash
from app.services.rules.deadlines import record_matches_scope, resolve_deadlines
from app.services.rules.eligibility import evaluate_conditions
from app.services.rules.types import SourcedRecord

REPORT_SCHEMA_VERSION = "4"


def build_report(
    *,
    run_id: str,
    reference_time: datetime,
    programme: dict[str, Any],
    academic_year: str,
    application_type: str,
    sources: list[SourcedRecord],
    applicant_group: str | None,
    profile: dict[str, Any] | None,
    incomplete_source_attempts: bool,
    model_id: str,
    extraction_prompt_hash: str | None = None,
) -> dict[str, Any]:
    resolved = resolve_deadlines(
        sources,
        reference_time,
        programme["locale"]["comparison_timezone"],
        academic_year,
        application_type,
        applicant_group,
    )
    applicable = [
        source
        for source in sources
        if record_matches_scope(source, academic_year, application_type, applicant_group)
    ]
    limitations = list(
        dict.fromkeys(
            item
            for source in applicable
            for item in (
                *source.record.unresolved_items,
                *source.document_unresolved_items,
            )
        )
    )
    parse_statuses = {source.parse_status for source in applicable}
    if any(status != "parsed" for status in parse_statuses):
        limitations.append("The source document was only partially parsed.")
    if incomplete_source_attempts:
        limitations.append("One or more candidate sources could not be used.")
    extracted_years = {source.record.academic_year for source in sources}
    if not applicable and extracted_years and academic_year not in extracted_years:
        limitations.append("The source academic year does not match the requested cycle.")
    if resolved.get("scope_limitation"):
        limitations.append(resolved["scope_limitation"])
    if resolved["resolution"] == "insufficient":
        limitations.append("No exact student submission date was established.")

    eligibility, conditions = evaluate_conditions(applicable, profile)
    if profile is not None and limitations and eligibility == "meets_checked_conditions":
        eligibility = "more_information_needed"
        limitations.append(
            "Unresolved source conditions prevent a complete eligibility comparison."
        )

    summary = _report_summary(resolved)
    required_documents = _sourced_items(applicable, "required_documents")
    application_links = _sourced_items(applicable, "application_links")

    return {
        "run_id": run_id,
        "mode": "live",
        "reference_time": reference_time.isoformat(),
        "coverage": (
            "complete_for_attempted_scope"
            if applicable and parse_statuses == {"parsed"} and not incomplete_source_attempts
            else "partial"
        ),
        "scope": {
            "programme_id": programme["id"],
            "programme_name": programme["name"],
            "academic_year": academic_year,
            "application_type": application_type,
            "applicant_group": applicant_group,
        },
        "deadline_resolution": resolved["resolution"],
        "student_deadline": resolved["selected"],
        "summary": summary,
        "portal_status": "not_checked",
        "eligibility": eligibility,
        "conditions": conditions,
        "other_deadlines": resolved["other"],
        "conflicts": resolved["conflicts"],
        "amendments": resolved["amendments"],
        "required_documents": required_documents,
        "application_links": application_links,
        "limitations": limitations,
        "provenance": {
            "rules_version": "phase3-2",
            "schema_version": REPORT_SCHEMA_VERSION,
            "input_mode": "live_search_and_retrieval",
            "model_id": model_id,
            "prompt_hash": extraction_prompt_hash or prompt_hash(),
        },
    }


def _sourced_items(sources: list[SourcedRecord], field: str) -> list[dict[str, Any]]:
    rendered: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        for item in getattr(source.record, field):
            identity = (getattr(item, "url", ""), item.source_text)
            if identity in seen:
                continue
            seen.add(identity)
            value = {
                "source_text": item.source_text,
                "evidence_refs": [
                    {"version_id": source.version_id, "block_id": block_id}
                    for block_id in item.evidence_block_ids
                ],
            }
            if field == "application_links":
                value["url"] = item.url
            rendered.append(value)
    return rendered


def _report_summary(resolved: dict[str, Any]) -> str:
    selected = resolved["selected"]
    if resolved["resolution"] == "conflicting":
        return "Applicable student submission dates conflict; no definitive date was selected."
    if selected is None:
        return "A student submission deadline was not established for the requested scope."
    summary = f"The student submission date in this notice is {selected['date']}."
    if resolved["other"]:
        other = resolved["other"][0]
        summary += f" The {other['date']} date applies to {other['actor']} {other['action']}."
    if resolved["amendments"]:
        amendment = resolved["amendments"][0]
        summary += (
            f" An explicit amendment replaces {amendment['previous_date']} with "
            f"{amendment['revised_date']}."
        )
    return summary
