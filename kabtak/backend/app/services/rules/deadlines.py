"""Scope-first deadline resolution for the Phase 1 NMMSS path."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.services.extraction import CandidateDeadline, ExtractedFacts


def deadline_timing(date_iso: str, reference_time: datetime, timezone: str) -> str:
    comparison_date = reference_time.astimezone(ZoneInfo(timezone)).date()
    deadline_date = date.fromisoformat(date_iso)
    if deadline_date > comparison_date:
        return "date_ahead"
    if deadline_date == comparison_date:
        return "due_today_time_unknown"
    return "date_passed"


def resolve_deadlines(
    facts: ExtractedFacts,
    version_id: str,
    reference_time: datetime,
    comparison_timezone: str,
) -> dict[str, Any]:
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)
    submissions = [
        item for item in facts.deadlines if item.actor == "student" and item.action == "submit"
    ]
    distinct_dates = sorted({item.date_iso for item in submissions})
    resolution = (
        "supported"
        if len(distinct_dates) == 1
        else "conflicting"
        if distinct_dates
        else "insufficient"
    )
    selected = submissions[0] if resolution == "supported" else None
    other = [item for item in facts.deadlines if item is not selected]

    return {
        "resolution": resolution,
        "selected": (
            _deadline_json(selected, version_id, reference_time, comparison_timezone)
            if selected
            else None
        ),
        "other": [
            _deadline_json(item, version_id, reference_time, comparison_timezone) for item in other
        ],
        "conflicts": (
            [
                {
                    "kind": "student_submission_date",
                    "candidate_dates": distinct_dates,
                    "message": "The supplied evidence contains conflicting student deadlines.",
                }
            ]
            if resolution == "conflicting"
            else []
        ),
    }


def _deadline_json(
    deadline: CandidateDeadline,
    version_id: str,
    reference_time: datetime,
    comparison_timezone: str,
) -> dict[str, Any]:
    return {
        "actor": deadline.actor,
        "action": deadline.action,
        "date": deadline.date_iso,
        "time": None,
        "timezone": None,
        "comparison_timezone": comparison_timezone,
        "timing": deadline_timing(deadline.date_iso, reference_time, comparison_timezone),
        "evidence_refs": [
            {"version_id": version_id, "block_id": block_id}
            for block_id in deadline.evidence_block_ids
        ],
    }
