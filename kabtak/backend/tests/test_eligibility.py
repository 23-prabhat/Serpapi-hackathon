"""Closed-operator and three-valued eligibility tests."""

import pytest
from pydantic import ValidationError

from app.services.extraction import EligibilityRule, ExtractedFacts
from app.services.rules.eligibility import evaluate_conditions, evaluate_rule
from app.services.rules.types import SourcedRecord


def rule(
    operator: str,
    field: str | None = None,
    value: object = None,
    unit: str | None = None,
    children: list[EligibilityRule] | None = None,
) -> EligibilityRule:
    return EligibilityRule(
        operator=operator,
        field=field,
        value=value,
        unit=unit,
        children=children or [],
        source_text="Supported source condition",
        evidence_block_ids=["block_1"],
    )


def source(*rules: EligibilityRule) -> SourcedRecord:
    return SourcedRecord(
        ExtractedFacts(
            academic_year="2026-27",
            application_types=["fresh"],
            applicant_group=None,
            applies_to_all_groups=True,
            scope_evidence_block_ids=["block_1"],
            notice_type="original",
            deadlines=[],
            conditions=list(rules),
            required_documents=[],
            application_links=[],
            unresolved_items=[],
        ),
        "version_1",
        frozenset({"eligibility"}),
    )


@pytest.mark.parametrize(
    ("item", "profile", "expected"),
    [
        (rule("eq", "study_level", "secondary"), {"study_level": "Secondary"}, "true"),
        (rule("in", "domicile_state", ["Delhi", "Goa"]), {"domicile_state": "goa"}, "true"),
        (rule("lt", "study_year", 3, "year_of_study"), {"study_year": 2}, "true"),
        (rule("lte", "study_year", 2, "year_of_study"), {"study_year": 2}, "true"),
        (rule("gt", "study_year", 1, "year_of_study"), {"study_year": 2}, "true"),
        (rule("gte", "study_year", 2, "year_of_study"), {"study_year": 2}, "true"),
    ],
)
def test_supported_leaf_operators(item: EligibilityRule, profile: dict, expected: str) -> None:
    assert evaluate_rule(item, profile)["result"] == expected


def test_missing_income_is_unknown_and_needs_more_information() -> None:
    income = rule("lte", "annual_family_income_inr", 350000, "INR_per_year")

    overall, results = evaluate_conditions([source(income)], {})

    assert overall == "more_information_needed"
    assert results[0]["result"] == "unknown"
    assert results[0]["reason"] == "profile_value_missing"


def test_or_true_with_unknown_is_true() -> None:
    condition = rule(
        "or",
        children=[
            rule("eq", "domicile_state", "Delhi"),
            rule("lte", "annual_family_income_inr", 350000, "INR_per_year"),
        ],
    )

    assert evaluate_rule(condition, {"domicile_state": "Delhi"})["result"] == "true"


def test_unsupported_exception_is_unknown() -> None:
    exception = rule("unsupported")

    overall, results = evaluate_conditions([source(exception)], {"study_year": 2})

    assert overall == "more_information_needed"
    assert results[0]["reason"] == "unsupported_condition"


def test_failed_necessary_condition_controls_overall_result() -> None:
    rules = [
        rule("lte", "annual_family_income_inr", 350000, "INR_per_year"),
        rule("eq", "domicile_state", "Delhi"),
    ]

    overall, _ = evaluate_conditions([source(*rules)], {"annual_family_income_inr": 400000})

    assert overall == "condition_not_met"


def test_wrong_unit_is_unknown() -> None:
    income = rule("lte", "annual_family_income_inr", 350000, "INR_per_month")

    result = evaluate_rule(income, {"annual_family_income_inr": 200000})

    assert result["result"] == "unknown"
    assert result["reason"] == "incompatible_or_unknown_unit"


def test_no_profile_keeps_conditions_visible_but_not_assessed() -> None:
    income = rule("lte", "annual_family_income_inr", 350000, "INR_per_year")

    overall, results = evaluate_conditions([source(income)], None)

    assert overall == "not_assessed"
    assert len(results) == 1
    assert results[0]["result"] == "unknown"


def test_empty_group_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least one child"):
        rule("and")


def test_rule_tree_deeper_than_five_is_rejected() -> None:
    nested = rule("eq", "study_level", "secondary")
    for _ in range(5):
        nested = rule("and", children=[nested])

    with pytest.raises(ValidationError, match="depth"):
        ExtractedFacts(
            academic_year="2026-27",
            application_types=["fresh"],
            applicant_group=None,
            applies_to_all_groups=True,
            scope_evidence_block_ids=["block_1"],
            notice_type="original",
            deadlines=[],
            conditions=[nested],
            required_documents=[],
            application_links=[],
            unresolved_items=[],
        )
