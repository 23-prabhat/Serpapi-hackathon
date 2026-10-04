"""Reproducibility and ground-truth checks for the Phase 5 evaluation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

PHASE5_DIR = Path(__file__).resolve().parents[1]


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "phase5_run_evaluation", PHASE5_DIR / "run_evaluation.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_has_frozen_twelve_development_and_eight_held_out_cases() -> None:
    manifest = yaml.safe_load((PHASE5_DIR / "cases.yaml").read_text(encoding="utf-8"))
    cases = manifest["cases"]

    assert manifest["held_out_frozen_before_first_run"] is True
    assert len(cases) == 20
    assert sum(case["split"] == "development" for case in cases) == 12
    assert sum(case["split"] == "held_out" for case in cases) == 8
    assert len({case["id"] for case in cases}) == 20
    assert all("answerable" in case["expected"] for case in cases)


def test_source_families_do_not_cross_splits() -> None:
    manifest = yaml.safe_load((PHASE5_DIR / "cases.yaml").read_text(encoding="utf-8"))
    by_source: dict[str, set[str]] = {}
    for case in manifest["cases"]:
        for source_id in case["source_ids"]:
            by_source.setdefault(source_id, set()).add(case["split"])

    assert all(len(splits) == 1 for splits in by_source.values())


def test_every_case_uses_reviewed_bounded_official_evidence() -> None:
    cases, sources = load_runner().load_inputs()
    source_ids = set(sources)

    assert all(set(case["source_ids"]).issubset(source_ids) for case in cases)
    assert all(source["url"].startswith("https://") for source in sources.values())
    assert all(source["blocks"] for source in sources.values())
    assert all(
        len(block["text"]) <= 4_000 for source in sources.values() for block in source["blocks"]
    )


def test_summary_keeps_unanswered_cases_in_the_denominator() -> None:
    runner = load_runner()
    summary = runner.summarize(
        [
            {
                "outcome": "correct",
                "answerable": True,
                "ground_truth_match": True,
            },
            {
                "outcome": "incorrect",
                "answerable": True,
                "ground_truth_match": False,
            },
            {
                "outcome": "unresolved",
                "answerable": True,
                "ground_truth_match": False,
            },
            {
                "outcome": "unresolved",
                "answerable": False,
                "ground_truth_match": True,
            },
        ]
    )

    assert summary["case_count"] == 4
    assert summary["answered_accuracy"] == 0.5
    assert summary["answerable_coverage"] == 0.6667
    assert summary["ground_truth_matches"] == 2
