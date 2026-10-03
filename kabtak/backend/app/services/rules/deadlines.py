"""Scope-first, multi-source deadline and amendment resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.extraction import CandidateDeadline
from app.services.rules.types import SourcedRecord


@dataclass(frozen=True)
class SourcedDeadline:
    deadline: CandidateDeadline
    source: SourcedRecord


def deadline_timing(
    date_iso: str,
    reference_time: datetime,
    comparison_timezone: str,
    cutoff_time: str | None = None,
    cutoff_timezone: str | None = None,
) -> str:
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)
    deadline_date = date.fromisoformat(date_iso)
    if cutoff_time is not None and cutoff_timezone is not None:
        try:
            deadline_zone = ZoneInfo(cutoff_timezone)
        except ZoneInfoNotFoundError:
            return "unknown"
        cutoff = datetime.combine(deadline_date, time.fromisoformat(cutoff_time), deadline_zone)
        return "before_cutoff" if reference_time < cutoff else "after_cutoff"
    comparison_zone = ZoneInfo(comparison_timezone)
    comparison_date = reference_time.astimezone(comparison_zone).date()
    if deadline_date > comparison_date:
        return "date_ahead"
    if deadline_date < comparison_date:
        return "date_passed"
    if cutoff_time is None:
        return "due_today_time_unknown"
    return "unknown"


def resolve_deadlines(
    sources: list[SourcedRecord],
    reference_time: datetime,
    comparison_timezone: str,
    requested_academic_year: str,
    requested_application_type: str,
    requested_applicant_group: str | None = None,
) -> dict[str, Any]:
    applicable_sources = [
        source
        for source in sources
        if _record_matches(
            source,
            requested_academic_year,
            requested_application_type,
            requested_applicant_group,
        )
    ]
    if not applicable_sources:
        return _insufficient("No document record established the complete requested scope.")

    scoped = [
        SourcedDeadline(item, source)
        for source in applicable_sources
        for item in source.record.deadlines
        if _deadline_scope_matches(
            item,
            requested_application_type,
            requested_applicant_group,
        )
    ]
    submissions = [
        item
        for item in scoped
        if item.deadline.actor == "student" and item.deadline.action == "submit"
    ]
    other = _merge_other_deadlines(
        [
            item
            for item in scoped
            if item.deadline.actor != "student" or item.deadline.action != "submit"
        ],
        reference_time,
        comparison_timezone,
    )

    active = list(submissions)
    amendments: list[dict[str, Any]] = []
    revisions = [
        item
        for item in submissions
        if item.deadline.explicitly_revises_deadline
        and "amendment" in item.source.source_capabilities
    ]
    for revision in revisions:
        if revision.deadline.supersedes_date_iso is not None:
            targets = [
                item
                for item in active
                if item is not revision
                and item.deadline.date_iso == revision.deadline.supersedes_date_iso
            ]
        else:
            # A targetless extension can replace an original same-scope deadline,
            # but it cannot establish ordering between multiple amendments.
            targets = [
                item
                for item in active
                if item is not revision and not item.deadline.explicitly_revises_deadline
            ]
        for target in targets:
            active.remove(target)
            old_refs = _evidence_refs(target)
            new_refs = _evidence_refs(revision)
            amendments.append(
                {
                    "actor": revision.deadline.actor,
                    "action": revision.deadline.action,
                    "previous_date": target.deadline.date_iso,
                    "revised_date": revision.deadline.date_iso,
                    "previous_evidence_refs": old_refs,
                    "revised_evidence_refs": new_refs,
                    "evidence_refs": old_refs + [ref for ref in new_refs if ref not in old_refs],
                }
            )

    grouped = _group_by_cutoff(active)
    if len(grouped) == 1:
        selected = _merged_deadline_json(
            next(iter(grouped.values())), reference_time, comparison_timezone
        )
        resolution = "supported"
        conflicts: list[dict[str, Any]] = []
    elif len(grouped) > 1:
        selected = None
        resolution = "conflicting"
        conflicts = [
            {
                "kind": "student_submission_date",
                "candidate_dates": sorted({key[0] for key in grouped}),
                "candidates": [
                    _merged_deadline_json(items, reference_time, comparison_timezone)
                    for _, items in sorted(grouped.items(), key=lambda entry: repr(entry[0]))
                ],
                "message": (
                    "Applicable student submission dates disagree and no explicit "
                    "same-scope amendment resolves them."
                ),
            }
        ]
    else:
        selected = None
        resolution = "insufficient"
        conflicts = []

    return {
        "resolution": resolution,
        "selected": selected,
        "other": other,
        "conflicts": conflicts,
        "amendments": amendments,
        "scope_limitation": (
            "No student submission date matched the requested scope."
            if resolution == "insufficient"
            else None
        ),
    }


def record_matches_scope(
    source: SourcedRecord,
    academic_year: str,
    application_type: str,
    applicant_group: str | None,
) -> bool:
    return _record_matches(source, academic_year, application_type, applicant_group)


def _record_matches(
    source: SourcedRecord,
    academic_year: str,
    application_type: str,
    applicant_group: str | None,
) -> bool:
    record = source.record
    return (
        record.academic_year == academic_year
        and _application_matches(record.application_types, application_type)
        and _group_matches(record.applicant_group, record.applies_to_all_groups, applicant_group)
    )


def _deadline_scope_matches(
    item: CandidateDeadline,
    application_type: str,
    applicant_group: str | None,
) -> bool:
    return _application_matches(item.application_types, application_type) and _group_matches(
        item.applicant_group,
        item.applies_to_all_groups,
        applicant_group,
    )


def _insufficient(message: str) -> dict[str, Any]:
    return {
        "resolution": "insufficient",
        "selected": None,
        "other": [],
        "conflicts": [],
        "amendments": [],
        "scope_limitation": message,
    }


def _application_matches(scopes: list[str], requested: str) -> bool:
    if requested == "unknown":
        return False
    return requested in scopes or "all" in scopes


def _group_matches(
    fact_group: str | None, applies_to_all_groups: bool, requested_group: str | None
) -> bool:
    if applies_to_all_groups:
        return True
    if fact_group is None or requested_group is None:
        return False
    return _normalize_group(fact_group) == _normalize_group(requested_group)


def _normalize_group(value: str) -> str:
    return " ".join(value.casefold().split())


def _group_by_cutoff(
    items: list[SourcedDeadline],
) -> dict[tuple[str, str | None, str | None], list[SourcedDeadline]]:
    grouped: dict[tuple[str, str | None, str | None], list[SourcedDeadline]] = {}
    for item in items:
        deadline = item.deadline
        grouped.setdefault((deadline.date_iso, deadline.time, deadline.timezone), []).append(item)
    return grouped


def _merge_other_deadlines(
    items: list[SourcedDeadline],
    reference_time: datetime,
    comparison_timezone: str,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str | None, str | None], list[SourcedDeadline]] = {}
    for item in items:
        deadline = item.deadline
        key = (deadline.actor, deadline.action, deadline.date_iso, deadline.time, deadline.timezone)
        grouped.setdefault(key, []).append(item)
    return [
        _merged_deadline_json(group, reference_time, comparison_timezone)
        for group in grouped.values()
    ]


def _merged_deadline_json(
    deadlines: list[SourcedDeadline],
    reference_time: datetime,
    comparison_timezone: str,
) -> dict[str, Any]:
    rendered = _deadline_json(deadlines[0], reference_time, comparison_timezone)
    rendered["evidence_refs"] = list(
        {
            (reference["version_id"], reference["block_id"]): reference
            for item in deadlines
            for reference in _evidence_refs(item)
        }.values()
    )
    return rendered


def _evidence_refs(item: SourcedDeadline) -> list[dict[str, str]]:
    return [
        {"version_id": item.source.version_id, "block_id": block_id}
        for block_id in item.deadline.evidence_block_ids
    ]


def _deadline_json(
    item: SourcedDeadline,
    reference_time: datetime,
    comparison_timezone: str,
) -> dict[str, Any]:
    deadline = item.deadline
    return {
        "actor": deadline.actor,
        "action": deadline.action,
        "date": deadline.date_iso,
        "time": deadline.time,
        "timezone": deadline.timezone,
        "comparison_timezone": comparison_timezone,
        "timing": deadline_timing(
            deadline.date_iso,
            reference_time,
            comparison_timezone,
            deadline.time,
            deadline.timezone,
        ),
        "evidence_refs": _evidence_refs(item),
    }
