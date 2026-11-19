import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep
from typing import get_args

from app.core.config import IntentCriteriaVersion, Settings
from app.schemas.gemini import Intent
from app.services.decision_service import classify_question
from app.services.gemini_client import GeminiServiceError
from app.services.intent_criteria import INTENT_PROMPTS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = (
    PROJECT_ROOT / "data" / "synthetic_enterprise_v2" / "evaluation" / "golden_questions.json"
)
OTHER_DATASET = PROJECT_ROOT / "data" / "intent_other_questions.json"
INDEPENDENT_DATASET = PROJECT_ROOT / "data" / "intent_independent_questions.json"
RESULTS_ROOT = PROJECT_ROOT / "evaluation_results"
INTENTS = get_args(Intent)
REVIEW_ROUTE = "insufficient_evidence"


@dataclass(frozen=True)
class Question:
    question_id: str
    question: str
    expected_intent: str
    evidence_status: str | None = None


@dataclass
class Result:
    question_id: str
    question: str
    expected_intent: str
    predicted_intent: str | None = None
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    is_correct: bool | None = None
    latency_ms: float | None = None
    error: str | None = None
    evidence_status: str | None = None


def load_questions(path: Path) -> list[Question]:
    records = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(records, list) or not records:
        raise ValueError(f"{path}: expected a nonempty JSON list")

    questions = []
    for index, record in enumerate(records, start=1):
        values = []
        for field in ("question_id", "question", "route"):
            value = record.get(field) if isinstance(record, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{path}: row {index} needs a nonempty {field}")
            values.append(value.strip())

        evidence_status = record.get("evidence_status")
        if evidence_status not in (None, "sufficient", "missing", "unverified", "not_applicable"):
            raise ValueError(f"{path}: row {index} has an invalid evidence_status")
        question = Question(*values, evidence_status=evidence_status)
        if question.expected_intent not in (*INTENTS, REVIEW_ROUTE):
            raise ValueError(f"{path}: row {index} has an invalid route")
        questions.append(question)
    return questions


def prepare_questions(dataset: Path, other_dataset: Path | None) -> tuple[list[Question], list[Question]]:
    questions = load_questions(dataset)
    if other_dataset is not None:
        questions.extend(load_questions(other_dataset))
    if len({question.question_id for question in questions}) != len(questions):
        raise ValueError("Duplicate question_id across evaluation data")

    groups = {intent: [] for intent in INTENTS}
    review = []
    for question in questions:
        if question.expected_intent == REVIEW_ROUTE:
            review.append(question)
        else:
            groups[question.expected_intent].append(question)

    # Alternate labels so a short run covers several routes.
    selected = []
    for index in range(max(map(len, groups.values()))):
        selected.extend(group[index] for group in groups.values() if index < len(group))
    return selected, review


def evaluate(questions: list[Question], settings: Settings, rpm: int) -> list[Result]:
    results = []
    next_request_at = perf_counter()
    for index, question in enumerate(questions, start=1):
        print(f"[{index}/{len(questions)}] {question.question_id}", flush=True)
        wait = next_request_at - perf_counter()
        if wait > 0:
            sleep(wait)

        started = perf_counter()
        next_request_at = started + 60 / rpm
        result = Result(**asdict(question))
        stop = False
        try:
            response = classify_question(question.question, settings)
            result.predicted_intent = response.choice
            result.confidence = response.confidence
            result.probabilities = response.probabilities
            result.is_correct = response.choice == question.expected_intent
        except GeminiServiceError as error:
            result.error = f"HTTP {error.status_code}: {error.detail}"
            stop = error.status_code == 429
        result.latency_ms = round((perf_counter() - started) * 1000, 2)
        results.append(result)
        outcome = result.error or f"{result.predicted_intent} ({'correct' if result.is_correct else 'incorrect'})"
        print(f"  {outcome} | {result.latency_ms:.2f} ms", flush=True)
        if stop:
            print("Quota or rate limit reached. Stopping without retry.", flush=True)
            break
    return results


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize(
    results: list[Result], model: str, skipped_count: int, version: IntentCriteriaVersion = "v1",
) -> dict:
    confusion = {expected: dict.fromkeys(INTENTS, 0) for expected in INTENTS}
    valid = [result for result in results if result.is_correct is not None]
    for result in valid:
        confusion[result.expected_intent][result.predicted_intent] += 1

    per_intent = {}
    for intent in INTENTS:
        true_positive = confusion[intent][intent]
        support = sum(confusion[intent].values())
        predicted = sum(row[intent] for row in confusion.values())
        per_intent[intent] = {
            "support": support,
            "precision": ratio(true_positive, predicted),
            "recall": ratio(true_positive, support),
            "f1": ratio(2 * true_positive, predicted + support),
        }

    instructions, criteria = INTENT_PROMPTS[version]
    correct = sum(result.is_correct is True for result in valid)
    return {
        "model": model,
        "prompt_version": version,
        "criteria_version": "sha256:" + hashlib.sha256(
            json.dumps(criteria, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "instructions_version": "sha256:" + hashlib.sha256(instructions.encode("utf-8")).hexdigest(),
        "criteria": criteria,
        "instructions": instructions,
        "attempted": len(results),
        "evaluated": len(valid),
        "correct": correct,
        "incorrect": len(valid) - correct,
        "api_errors": len(results) - len(valid),
        "skipped": skipped_count,
        "accuracy": ratio(correct, len(valid)),
        "per_intent": per_intent,
        "confusion_matrix": confusion,
        "average_confidence": sum(result.confidence for result in valid) / len(valid) if valid else None,
        "average_latency_ms": (
            round(sum(result.latency_ms for result in results) / len(results), 2)
            if results else None
        ),
    }


def write_csv(path: Path, results: list[Result]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(Result.__dataclass_fields__))
        writer.writeheader()
        for result in results:
            row = asdict(result)
            if result.probabilities is not None:
                row["probabilities"] = json.dumps(result.probabilities)
            writer.writerow(row)


def write_report(
    output: Path,
    results: list[Result],
    summary: dict,
    review: list[Question],
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "results.csv", results)
    write_csv(output / "misclassified.csv", [result for result in results if result.is_correct is False])
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    review_data = json.dumps([asdict(question) for question in review], ensure_ascii=False, indent=2)
    (output / "insufficient_evidence.json").write_text(review_data + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the Gemini Decision intent baseline.")
    datasets = parser.add_mutually_exclusive_group()
    datasets.add_argument("--dataset", type=Path, help="Custom golden JSON with the supplemental other set.")
    datasets.add_argument("--independent", action="store_true", help="Use only the independent 30 questions.")
    parser.add_argument("--criteria", choices=INTENT_PROMPTS, default="v1")
    parser.add_argument("--limit", type=int, help="Maximum number of eligible questions to send.")
    parser.add_argument("--rpm", type=int, default=30, help="Requests per minute (default: 30, maximum: 200).")
    parser.add_argument("--dry-run", action="store_true", help="Validate data without calling Gemini.")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if not 1 <= args.rpm <= 200:
        parser.error("--rpm must be between 1 and 200")

    dataset = INDEPENDENT_DATASET if args.independent else args.dataset or DEFAULT_DATASET
    supplemental = None if args.independent else OTHER_DATASET
    try:
        eligible, review = prepare_questions(dataset, supplemental)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    selected = eligible[:args.limit]
    excluded_by_limit = len(eligible) - len(selected)
    counts = Counter(question.expected_intent for question in selected)
    print(f"Dataset: {dataset} | Criteria: {args.criteria}")
    print(f"Selected: {len(selected)}/{len(eligible)} eligible | " + ", ".join(
        f"{intent}={counts[intent]}" for intent in INTENTS
    ))
    print(f"Insufficient evidence: {len(review)} | " + ", ".join(q.question_id for q in review))
    if not selected:
        parser.error("No eligible questions to evaluate")
    if args.dry_run:
        print("Dry run complete. No API requests sent.")
        return 0

    settings = Settings(intent_criteria_version=args.criteria)
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value().strip():
        parser.error("GEMINI_API_KEY is required for an API run")

    results = evaluate(selected, settings, args.rpm)
    stopped_early = len(selected) - len(results)
    summary = summarize(
        results, settings.gemini_decision_model, len(review) + excluded_by_limit + stopped_early, args.criteria,
    )
    summary["skipped_by_reason"] = {
        "insufficient_evidence": len(review),
        "limit": excluded_by_limit,
        "quota_stop": stopped_early,
    }
    summary["dataset"] = str(dataset.resolve())
    summary["supplemental_dataset"] = str(supplemental) if supplemental else None
    summary["rpm"] = args.rpm

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = RESULTS_ROOT / run_id
    write_report(output, results, summary, review)
    accuracy = summary["accuracy"]
    score = f"{accuracy:.2%}" if accuracy is not None else "n/a"
    print(f"Accuracy: {score} | API errors: {summary['api_errors']} | Reports: {output}")
    return 1 if summary["api_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
