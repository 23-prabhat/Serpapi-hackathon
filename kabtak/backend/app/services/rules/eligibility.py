"""Closed-operator, three-valued eligibility evaluation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.services.extraction import EligibilityRule
from app.services.rules.types import SourcedRecord


class TruthValue(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


EXPECTED_UNITS: dict[str, str | None] = {
    "study_level": None,
    "study_year": "year_of_study",
    "course": None,
    "domicile_state": None,
    "annual_family_income_inr": "INR_per_year",
}


def evaluate_rule(rule: EligibilityRule, profile: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a validated rule without executing source-provided code."""
    child_results = [evaluate_rule(child, profile) for child in rule.children]
    if rule.operator == "and":
        result = _and([TruthValue(item["result"]) for item in child_results])
        reason = "all_children_true" if result == TruthValue.TRUE else "group_not_settled"
        if result == TruthValue.FALSE:
            reason = "at_least_one_child_false"
    elif rule.operator == "or":
        result = _or([TruthValue(item["result"]) for item in child_results])
        reason = "at_least_one_child_true" if result == TruthValue.TRUE else "group_not_settled"
        if result == TruthValue.FALSE:
            reason = "all_children_false"
    elif rule.operator == "unsupported":
        result = TruthValue.UNKNOWN
        reason = "unsupported_condition"
    else:
        result, reason = _evaluate_leaf(rule, profile)

    return {
        "result": result.value,
        "reason": reason,
        "operator": rule.operator,
        "field": rule.field,
        "profile_value": profile.get(rule.field) if rule.field else None,
        "expected_value": rule.value,
        "unit": rule.unit,
        "source_text": rule.source_text,
        "evidence_block_ids": rule.evidence_block_ids,
        "children": child_results,
    }


def evaluate_conditions(
    sources: list[SourcedRecord], profile: dict[str, Any] | None
) -> tuple[str, list[dict[str, Any]]]:
    rules = [(rule, source.version_id) for source in sources for rule in source.record.conditions]
    if profile is None:
        evaluated = [evaluate_rule(rule, {}) for rule, _ in rules]
        rendered = [
            _render_result(item, version_id)
            for item, (_, version_id) in zip(evaluated, rules, strict=True)
        ]
        return "not_assessed", rendered
    evaluated = [evaluate_rule(rule, profile) for rule, _ in rules]
    rendered = [
        _render_result(item, version_id)
        for item, (_, version_id) in zip(evaluated, rules, strict=True)
    ]
    results = {item["result"] for item in evaluated}
    if "false" in results:
        return "condition_not_met", rendered
    if not evaluated or "unknown" in results:
        return "more_information_needed", rendered
    return "meets_checked_conditions", rendered


def _evaluate_leaf(rule: EligibilityRule, profile: dict[str, Any]) -> tuple[TruthValue, str]:
    assert rule.field is not None
    actual = profile.get(rule.field)
    if actual is None:
        return TruthValue.UNKNOWN, "profile_value_missing"
    expected_unit = EXPECTED_UNITS[rule.field]
    if rule.unit != expected_unit:
        return TruthValue.UNKNOWN, "incompatible_or_unknown_unit"
    expected = rule.value
    try:
        if rule.operator == "eq":
            matches = _normalized(actual) == _normalized(expected)
        elif rule.operator == "in":
            if not isinstance(expected, list) or not expected:
                return TruthValue.UNKNOWN, "invalid_membership_values"
            matches = _normalized(actual) in {_normalized(item) for item in expected}
        elif rule.operator in {"lt", "lte", "gt", "gte"}:
            if not _numeric(actual) or not _numeric(expected):
                return TruthValue.UNKNOWN, "non_numeric_comparison"
            comparisons = {
                "lt": actual < expected,
                "lte": actual <= expected,
                "gt": actual > expected,
                "gte": actual >= expected,
            }
            matches = comparisons[rule.operator]
        else:  # Schema validation makes this unreachable, kept fail-closed.
            return TruthValue.UNKNOWN, "unsupported_operator"
    except (TypeError, ValueError):
        return TruthValue.UNKNOWN, "incompatible_values"
    return (
        (TruthValue.TRUE, "condition_met")
        if matches
        else (
            TruthValue.FALSE,
            "condition_not_met",
        )
    )


def _and(values: list[TruthValue]) -> TruthValue:
    if TruthValue.FALSE in values:
        return TruthValue.FALSE
    if values and all(value == TruthValue.TRUE for value in values):
        return TruthValue.TRUE
    return TruthValue.UNKNOWN


def _or(values: list[TruthValue]) -> TruthValue:
    if TruthValue.TRUE in values:
        return TruthValue.TRUE
    if values and all(value == TruthValue.FALSE for value in values):
        return TruthValue.FALSE
    return TruthValue.UNKNOWN


def _numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalized(value: object) -> object:
    return value.casefold().strip() if isinstance(value, str) else value


def _render_result(item: dict[str, Any], version_id: str) -> dict[str, Any]:
    rendered = dict(item)
    rendered["evidence_refs"] = [
        {"version_id": version_id, "block_id": block_id}
        for block_id in rendered.pop("evidence_block_ids")
    ]
    rendered["children"] = [_render_result(child, version_id) for child in rendered["children"]]
    return rendered
