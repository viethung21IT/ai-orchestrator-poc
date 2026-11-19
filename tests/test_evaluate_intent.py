import csv
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import SecretStr

from app.schemas.gemini import ClassificationResponse
from app.services.gemini_client import GeminiServiceError
from scripts import evaluate_intent as evaluation

KPI = evaluation.Question("Q1", "Tính doanh thu giả lập.", "kpi")
RAG = evaluation.Question("Q2", "Tìm chính sách giả lập.", "rag")
REVIEW = evaluation.Question("Q3", "Dữ liệu giả lập có tồn tại không?", "insufficient_evidence")
OTHER = evaluation.Question("OTHER1", "Kể chuyện cười.", "other")


def write_dataset(path, *questions):
    records = [
        {"question_id": q.question_id, "question": q.question, "route": q.expected_intent,
         "expected_answer": "Do not send this answer"}
        for q in questions
    ]
    path.write_text(json.dumps(records), encoding="utf-8")


def mock_prediction(choice):
    return ClassificationResponse(
        choice=choice,
        confidence=0.75,
        probabilities={intent: 0.75 if intent == choice else 0.05 for intent in evaluation.INTENTS},
    )


def test_summary_metrics_exclude_api_errors():
    results = [
        evaluation.Result("Q1", "q", "kpi", "kpi", 0.9, is_correct=True, latency_ms=100),
        evaluation.Result("Q2", "q", "rag", "kpi", 0.7, is_correct=False, latency_ms=200),
        evaluation.Result("Q3", "q", "rag", "rag", 0.8, is_correct=True, latency_ms=300),
        evaluation.Result("Q4", "q", "kpi", latency_ms=400, error="HTTP 504"),
    ]
    summary = evaluation.summarize(results, "gemini-decision-1", skipped_count=3)

    assert (summary["evaluated"], summary["correct"], summary["incorrect"]) == (3, 2, 1)
    assert summary["api_errors"] == 1
    assert summary["skipped"] == 3
    assert summary["accuracy"] == pytest.approx(2 / 3)
    assert summary["per_intent"]["kpi"] == {
        "support": 1, "precision": 0.5, "recall": 1.0, "f1": pytest.approx(2 / 3),
    }
    assert summary["per_intent"]["rag"]["recall"] == 0.5
    assert summary["per_intent"]["other"]["f1"] is None
    assert summary["confusion_matrix"]["rag"]["kpi"] == 1
    assert summary["average_confidence"] == pytest.approx(0.8)
    assert summary["average_latency_ms"] == 250


def test_summary_when_all_requests_fail():
    results = [evaluation.Result("Q1", "q", "kpi", latency_ms=100, error="HTTP 504")]
    summary = evaluation.summarize(results, "model", 0)

    assert summary["accuracy"] is None
    assert summary["average_confidence"] is None
    assert summary["average_latency_ms"] == 100
    assert summary["incorrect"] == 0


@pytest.mark.parametrize(("record", "message"), [
    ({"question_id": "Q1", "route": "kpi"}, "nonempty question"),
    ({"question_id": "Q1", "question": "q"}, "nonempty route"),
    ({"question_id": "Q1", "question": "q", "route": "unknown"}, "invalid route"),
])
def test_load_questions_rejects_invalid_rows(tmp_path, record, message):
    dataset = tmp_path / "golden.json"
    dataset.write_text(json.dumps([record]), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        evaluation.load_questions(dataset)


def test_load_questions_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        evaluation.load_questions(tmp_path / "missing.json")


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    dataset = tmp_path / "golden.json"
    other_dataset = tmp_path / "other.json"
    write_dataset(dataset, KPI, RAG, REVIEW)
    write_dataset(other_dataset, OTHER)
    output = tmp_path / "reports"
    monkeypatch.setattr(evaluation, "OTHER_DATASET", other_dataset)
    monkeypatch.setattr(evaluation, "RESULTS_ROOT", output)
    monkeypatch.setattr(sys, "argv", ["evaluate_intent", "--dataset", str(dataset)])
    monkeypatch.setattr(evaluation, "sleep", Mock())
    return output


def test_dry_run_validates_labels_without_settings_or_api(jobs, monkeypatch, capsys):
    monkeypatch.setattr(evaluation, "Settings", Mock(side_effect=AssertionError))
    monkeypatch.setattr(evaluation, "classify_question", Mock(side_effect=AssertionError))
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--limit", "2", "--dry-run"])

    assert evaluation.main() == 0
    stdout = capsys.readouterr().out
    assert "Selected: 2/3 eligible" in stdout
    assert "Insufficient evidence: 1 | Q3" in stdout
    assert not jobs.exists()


def test_run_writes_correct_error_and_review_reports(jobs, monkeypatch):
    settings = SimpleNamespace(gemini_api_key=SecretStr("mock-key"), gemini_decision_model="gemini-decision-1")
    monkeypatch.setattr(evaluation, "Settings", lambda **kwargs: settings)
    classify = Mock(side_effect=[mock_prediction("kpi"), GeminiServiceError(504, "timeout"), mock_prediction("rag")])
    monkeypatch.setattr(evaluation, "classify_question", classify)

    assert evaluation.main() == 1
    assert [call.args for call in classify.call_args_list] == [
        (KPI.question, settings), (RAG.question, settings), (OTHER.question, settings),
    ]
    run, = jobs.iterdir()
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert summary["accuracy"] == 0.5
    assert summary["api_errors"] == 1
    assert summary["skipped_by_reason"]["insufficient_evidence"] == 1
    assert summary["criteria_version"].startswith("sha256:")
    with (run / "results.csv").open(encoding="utf-8-sig", newline="") as file:
        correct, error, incorrect = csv.DictReader(file)
    assert json.loads(correct["probabilities"])["kpi"] == 0.75
    assert (error["predicted_intent"], error["is_correct"], error["error"]) == ("", "", "HTTP 504: timeout")
    assert incorrect["is_correct"] == "False"
    with (run / "misclassified.csv").open(encoding="utf-8-sig", newline="") as file:
        misclassified, = csv.DictReader(file)
    assert misclassified["question_id"] == OTHER.question_id
    review, = json.loads((run / "insufficient_evidence.json").read_text(encoding="utf-8"))
    assert review["question_id"] == REVIEW.question_id


def test_quota_stops_without_retry_and_records_skipped(jobs, monkeypatch):
    settings = SimpleNamespace(gemini_api_key=SecretStr("mock-key"), gemini_decision_model="gemini-decision-1")
    monkeypatch.setattr(evaluation, "Settings", lambda **kwargs: settings)
    classify = Mock(side_effect=GeminiServiceError(429, "quota"))
    monkeypatch.setattr(evaluation, "classify_question", classify)

    assert evaluation.main() == 1
    classify.assert_called_once_with(KPI.question, settings)
    run, = jobs.iterdir()
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    assert summary["api_errors"] == 1
    assert summary["skipped_by_reason"] == {"insufficient_evidence": 1, "limit": 0, "quota_stop": 2}
