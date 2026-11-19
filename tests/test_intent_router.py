from pathlib import Path
from unittest.mock import Mock

import pytest

from app.core.config import Settings
from app.services.gemini_client import GeminiServiceError
from app.services import intent_router
from scripts import evaluate_fallback as evaluation
from scripts.evaluate_intent import Result


@pytest.mark.parametrize(("confidence", "enabled", "expected_calls"), [
    (0.9, True, 0),
    (0.7, True, 0),
    (0.69, False, 0),
    (0.69, True, 1),
])
def test_threshold_and_toggle(monkeypatch, confidence, enabled, expected_calls):
    fallback = Mock(return_value="hybrid_graph_rag")
    monkeypatch.setattr(intent_router, "classify_with_flash_lite", fallback)
    settings = Settings(_env_file=None, intent_confidence_threshold=0.7, intent_fallback_enabled=enabled)
    outcome = intent_router.resolve_intent("question only", "graph", confidence, settings)

    assert fallback.call_count == expected_calls
    assert outcome.fallback_used is bool(expected_calls)
    if expected_calls:
        fallback.assert_called_once_with("question only", settings)
        assert outcome.final_intent == "hybrid_graph_rag"
    elif confidence < 0.7:
        assert outcome.final_intent is None
        assert outcome.routing_status == "unconfirmed"
    else:
        assert outcome.final_intent == "graph"
        assert outcome.routing_status == "accepted"


@pytest.mark.parametrize("status", [502, 504, 429])
def test_error_leaves_low_confidence_unconfirmed_without_retry(monkeypatch, status):
    fallback = Mock(side_effect=GeminiServiceError(status, "mock failure"))
    monkeypatch.setattr(intent_router, "classify_with_flash_lite", fallback)
    settings = Settings(_env_file=None, intent_confidence_threshold=0.7, intent_fallback_enabled=True)

    outcome = intent_router.resolve_intent("question only", "graph", 0.5, settings)

    fallback.assert_called_once_with("question only", settings)
    assert outcome.fallback_used
    assert outcome.final_intent is None
    assert outcome.routing_status == "unconfirmed"
    assert outcome.fallback_error_status == status


def test_analysis_counts_correct_and_wrong_in_strict_threshold():
    rows = [
        Result("1", "q", "rag", "rag", 0.6, is_correct=True),
        Result("2", "q", "rag", "graph", 0.65, is_correct=False),
        Result("3", "q", "rag", "rag", 0.7, is_correct=True),
        Result("4", "q", "rag", error="HTTP 504"),
    ]
    assert evaluation.analyze_thresholds(rows, (0.7,)) == [{
        "threshold": 0.7, "eligible": 2, "initially_correct": 1, "initially_wrong": 1, "total_rows": 4,
    }]


def test_saved_evaluation_does_not_recall_decision_and_keeps_abstentions(monkeypatch):
    rows = [
        Result("1", "fix", "rag", "graph", 0.6, latency_ms=500),
        Result("2", "regression", "rag", "rag", 0.6, latency_ms=500),
        Result("3", "quota", "rag", "rag", 0.6, latency_ms=500),
        Result("4", "skip for quota", "rag", "rag", 0.6, latency_ms=500),
        Result("5", "accepted", "rag", "rag", 0.7, latency_ms=500),
        Result("6", "decision error", "rag", latency_ms=500, error="HTTP 504"),
    ]
    fallback = Mock(side_effect=["rag", "graph", GeminiServiceError(429, "quota")])
    monkeypatch.setattr(intent_router, "classify_with_flash_lite", fallback)
    monkeypatch.setattr(intent_router, "classify_question", Mock(side_effect=AssertionError))
    monkeypatch.setattr(evaluation, "sleep", Mock())
    settings = Settings(_env_file=None, intent_confidence_threshold=0.7, intent_fallback_enabled=True)

    results = evaluation.evaluate_fallback({Path("fixture-v2"): rows}, settings, rpm=10)
    summary = evaluation.summarize_fallback(results)

    assert [call.args[0] for call in fallback.call_args_list] == ["fix", "regression", "quota"]
    assert summary["before"]["accuracy"] == pytest.approx(4 / 6)
    assert summary["after"]["accuracy"] == pytest.approx(2 / 6)
    assert summary["after"]["per_intent"]["rag"]["recall"] == pytest.approx(2 / 6)
    assert summary["fixed_question_ids"] == ["1"]
    assert summary["regression_question_ids"] == ["2"]
    assert summary["initially_correct_unconfirmed_ids"] == ["3", "4"]
    assert summary["fallback_attempts"] == 3
    assert summary["api_errors"] == 2
    assert summary["unconfirmed_by_reason"] == {
        "fallback_error": 1, "quota_stop": 1, "decision_error": 1,
    }
