import csv
from dataclasses import replace

import pytest

from scripts import compare_intent
from scripts.evaluate_intent import INDEPENDENT_DATASET, INTENTS, Result, prepare_questions, summarize, write_report

MODEL = "gemini-decision-1"
LEGACY_HASH = "sha256:e9533ccec1a693b4b8a09cf4e850aa1e8f6715cfc2e606c606f533d0ef509a76"


@pytest.mark.skipif(
    not INDEPENDENT_DATASET.is_file(), reason="independent evaluation dataset is local",
)
def test_independent_dataset_balanced_and_missing_evidence_retains_route():
    questions, review = prepare_questions(INDEPENDENT_DATASET, None)

    assert not review
    assert len(questions) == 30
    assert all(sum(q.expected_intent == intent for q in questions) == 5 for intent in INTENTS)
    assert any(q.expected_intent == "graph" and q.evidence_status == "missing" for q in questions)


@pytest.fixture
def reports(tmp_path):
    v1 = tmp_path / "baseline"
    v2 = tmp_path / "new"
    before = [
        Result("Q1", "Find linked titles.", "graph", "rag", 0.8, is_correct=False, latency_ms=600),
        Result("Q2", "Read the policy.", "rag", "rag", 0.8, is_correct=True, latency_ms=600),
        Result("Q3", "Count enterprise metrics.", "kpi", "kpi", 0.8, is_correct=True, latency_ms=600),
        Result("Q4", "Tell a joke.", "other", "rag", 0.8, is_correct=False, latency_ms=600),
    ]
    after = [
        replace(before[0], predicted_intent="graph", is_correct=True, confidence=0.9, latency_ms=700),
        replace(before[1], predicted_intent="graph", is_correct=False, confidence=0.7, latency_ms=700),
        replace(before[2], confidence=0.9, latency_ms=700),
        Result("Q4", "Tell a joke.", "other", error="HTTP 504", latency_ms=2000),
    ]

    legacy = summarize(before, MODEL, 0)
    assert legacy["criteria_version"] == LEGACY_HASH
    for name in ("prompt_version", "instructions_version", "instructions", "criteria"):
        del legacy[name]
    write_report(v1, before, legacy, [])
    write_report(v2, after, summarize(after, MODEL, 0, "v2"), [])
    return v1, v2


def test_compare_legacy_baseline_and_v2_on_paired_successes(reports):
    report = compare_intent.compare_runs(*reports)

    assert report["compared"] == 3
    assert report["metrics"]["accuracy"] == {"v1": 2 / 3, "v2": 2 / 3, "delta": 0}
    assert report["metrics"]["average_confidence"]["delta"] == pytest.approx(1 / 30)
    assert report["metrics"]["average_latency_ms"]["delta"] == 100
    assert report["per_intent"]["graph"]["recall"]["delta"] == 1
    assert report["per_intent"]["rag"]["precision"]["v2"] is None
    assert [item["question_id"] for item in report["fixed"]] == ["Q1"]
    assert [item["question_id"] for item in report["regressions"]] == ["Q2"]
    assert [item["question_id"] for item in report["excluded_api_errors"]] == ["Q4"]


@pytest.mark.parametrize(("field", "value", "message"), [
    ("question_id", "Q99", "same attempted question IDs"),
    ("question", "Different wording", "text or expected intent differs"),
    ("expected_intent", "other", "text or expected intent differs"),
])
def test_compare_rejects_mismatched_questions(reports, field, value, message):
    path = reports[1] / "results.csv"
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        fields = reader.fieldnames
    rows[0][field] = value
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fields)
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match=message):
        compare_intent.compare_runs(*reports)
