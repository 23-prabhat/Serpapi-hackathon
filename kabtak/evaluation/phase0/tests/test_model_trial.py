"""Offline tests for Phase 0 model-trial evidence validation."""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def load_trial_module():
    path = Path(__file__).parents[1] / "model_trial.py"
    spec = spec_from_file_location("phase0_model_trial", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_date_occurs_in_supported_source_formats() -> None:
    trial = load_trial_module()

    assert trial.date_occurs_in_text("2026-10-31", "Open till: 31-10-2026")
    assert trial.date_occurs_in_text("2026-10-31", "Extended to October 31, 2026")
    assert trial.date_occurs_in_text("2025-10-31", "DNO verification is 31.10.2025")
    assert trial.date_occurs_in_text("2025-09-30", "extended up to 30th September, 2025")
    assert not trial.date_occurs_in_text("2026-10-31", "Verify by November 15, 2026")


def test_evaluator_rejects_fabricated_evidence_id() -> None:
    trial = load_trial_module()
    case = {
        "expected": {
            "deadline_resolution": "supported",
            "selected_deadline": {
                "actor": "student",
                "action": "submit",
                "date": "2026-10-31",
            },
        }
    }
    output = {
        "deadline_resolution": "supported",
        "selected_deadline": {
            "actor": "student",
            "action": "submit",
            "date_iso": "2026-10-31",
            "evidence_refs": ["source:block_999"],
        },
        "other_deadlines": [],
        "candidate_deadlines": [],
        "duration_facts": [],
        "correction_allows_new_registration": None,
        "unresolved_items": [],
    }

    evaluation = trial.evaluate_case(case, output, {})

    assert not evaluation["passed"]
    assert not evaluation["checks"]["evidence_ids_exist"]
