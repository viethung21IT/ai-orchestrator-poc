import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from time import perf_counter, sleep

from app.core.config import Settings
from app.schemas.gemini import Intent
from app.services.intent_router import needs_fallback, resolve_intent
from scripts.compare_intent import load_run
from scripts.evaluate_intent import INTENTS, RESULTS_ROOT, Result, ratio

THRESHOLDS = (0.6, 0.7, 0.8, 0.9)


@dataclass
class FallbackResult:
    source_run: str
    question_id: str
    question: str
    expected_intent: str
    initial_intent: Intent | None
    initial_confidence: float | None
    decision_latency_ms: float
    final_intent: Intent | None = None
    fallback_used: bool = False
    fallback_latency_ms: float | None = None
    routing_status: str = "unconfirmed"
    fallback_error_status: int | None = None
    unconfirmed_reason: str | None = None


def analyze_thresholds(rows: list[Result], thresholds: tuple[float, ...] = THRESHOLDS) -> list[dict]:
    stats = []
    for threshold in thresholds:
        candidates = [
            row for row in rows
            if not row.error and needs_fallback(row.confidence, threshold)
        ]
        correct = sum(row.is_correct for row in candidates)
        stats.append({
            "threshold": threshold,
            "eligible": len(candidates),
            "initially_correct": correct,
            "initially_wrong": len(candidates) - correct,
            "total_rows": len(rows),
        })
    return stats


def evaluate_fallback(
    runs: dict[Path, list[Result]], settings: Settings, rpm: int,
) -> list[FallbackResult]:
    results = []
    next_request_at = 0.0
    quota_reached = False
    total = sum(len(rows) for rows in runs.values())
    for path, rows in runs.items():
        for row in rows:
            item = FallbackResult(
                path.name, row.question_id, row.question, row.expected_intent,
                row.predicted_intent, row.confidence, row.latency_ms,
            )
            results.append(item)
            print(f"[{len(results)}/{total}] {path.name}/{row.question_id}", flush=True)
            if row.error:
                item.unconfirmed_reason = "decision_error"
                continue

            attempt = needs_fallback(row.confidence, settings.intent_confidence_threshold)
            if attempt and quota_reached:
                item.unconfirmed_reason = "quota_stop"
                continue
            if attempt:
                sleep(max(0, next_request_at - perf_counter()))
            started = perf_counter()
            outcome = resolve_intent(row.question, row.predicted_intent, row.confidence, settings)
            item.final_intent = outcome.final_intent
            item.fallback_used = outcome.fallback_used
            item.routing_status = outcome.routing_status
            item.fallback_error_status = outcome.fallback_error_status

            if outcome.fallback_used:
                item.fallback_latency_ms = round((perf_counter() - started) * 1000, 2)
                next_request_at = started + 60 / rpm
            if outcome.fallback_error_status is not None:
                item.unconfirmed_reason = "fallback_error"
                quota_reached = outcome.fallback_error_status == 429
    return results


def label_metrics(results: list[FallbackResult], label_field: str) -> dict:
    counts = Counter((row.expected_intent, getattr(row, label_field)) for row in results)
    per_intent = {}
    for intent in INTENTS:
        true_positive = counts[intent, intent]
        support = sum(counts[intent, predicted] for predicted in (*INTENTS, None))
        predicted_count = sum(counts[expected, intent] for expected in INTENTS)
        per_intent[intent] = {
            "support": support,
            "precision": ratio(true_positive, predicted_count),
            "recall": ratio(true_positive, support),
            "f1": ratio(2 * true_positive, predicted_count + support),
        }
    correct = sum(counts[intent, intent] for intent in INTENTS)
    return {"correct": correct, "accuracy": ratio(correct, len(results)), "per_intent": per_intent}


def summarize_fallback(rows: list[FallbackResult]) -> dict:
    attempts = [row for row in rows if row.fallback_used]
    fixed = [row.question_id for row in rows if row.initial_intent != row.expected_intent
             and row.initial_intent is not None and row.final_intent == row.expected_intent]
    regressions = [row.question_id for row in rows if row.initial_intent == row.expected_intent
                   and row.final_intent is not None and row.final_intent != row.expected_intent]
    lost_to_unconfirmed = [row.question_id for row in rows
                           if row.initial_intent == row.expected_intent and row.final_intent is None]
    return {
        "total": len(rows),
        "before": label_metrics(rows, "initial_intent"),
        "after": label_metrics(rows, "final_intent"),
        "fixed_count": len(fixed),
        "fixed_question_ids": fixed,
        "regression_count": len(regressions),
        "regression_question_ids": regressions,
        "initially_correct_unconfirmed_ids": lost_to_unconfirmed,
        "fallback_attempts": len(attempts),
        "fallback_rate": ratio(len(attempts), len(rows)),
        "unconfirmed": sum(row.final_intent is None for row in rows),
        "unconfirmed_by_reason": dict(Counter(row.unconfirmed_reason for row in rows if row.unconfirmed_reason)),
        "api_errors": sum(row.unconfirmed_reason == "decision_error" or row.fallback_error_status is not None
                          for row in rows),
        "average_saved_decision_latency_ms": ratio(sum(row.decision_latency_ms for row in rows), len(rows)),
        "average_fallback_latency_ms": ratio(sum(row.fallback_latency_ms for row in attempts), len(attempts)),
        "average_estimated_routing_latency_ms": ratio(
            sum(row.decision_latency_ms + (row.fallback_latency_ms or 0) for row in rows), len(rows),
        ),
    }


def write_report(output: Path, rows: list[FallbackResult], summary: dict) -> None:
    output.mkdir(parents=True, exist_ok=False)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (output / "results.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(FallbackResult.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Flash-Lite fallback from saved V2 Decision results.")
    parser.add_argument("runs", nargs="+", type=Path, help="V2 report directories.")
    parser.add_argument("--threshold", type=float, help="Override the threshold configured in .env (default: 0.7).")
    parser.add_argument("--rpm", type=int, default=10, help="Maximum Flash-Lite requests per minute.")
    parser.add_argument("--run-api", action="store_true", help="Run Flash-Lite calls; default is offline only.")
    args = parser.parse_args()
    if args.threshold is not None and not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    if args.rpm < 1:
        parser.error("--rpm must be positive")

    runs = {}
    decision_models = set()
    try:
        for directory in args.runs:
            path = directory.resolve()
            if path in runs:
                raise ValueError("Duplicate source run")
            metadata, rows = load_run(path, "v2")
            for row in rows.values():
                if not row.error and not (isfinite(row.confidence) and 0 <= row.confidence <= 1):
                    raise ValueError(f"{row.question_id}: invalid saved confidence")
            runs[path] = list(rows.values())
            decision_models.add(metadata["model"])
        combined = [row for rows in runs.values() for row in rows]
        if len({row.question_id for row in combined}) != len(combined):
            raise ValueError("Runs overlap in question IDs; provide disjoint evaluation sets")
        if len(decision_models) != 1:
            raise ValueError("Use runs from the same Decision model")
    except (KeyError, TypeError, ValueError, OSError) as error:
        parser.error(str(error))

    thresholds = tuple(sorted(set((*THRESHOLDS, args.threshold)))) if args.threshold is not None else THRESHOLDS
    analysis = {
        "combined": analyze_thresholds(combined, thresholds),
        "by_run": {path.name: analyze_thresholds(rows, thresholds) for path, rows in runs.items()},
    }
    print(json.dumps(analysis, indent=2), flush=True)
    if not args.run_api:
        print("Offline analysis complete. No API requests sent.")
        return 0

    overrides = {"intent_confidence_threshold": args.threshold} if args.threshold is not None else {}
    settings = Settings(**overrides)
    if not settings.intent_fallback_enabled:
        parser.error("Set INTENT_FALLBACK_ENABLED=true to run the fallback evaluation")
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value().strip():
        parser.error("GEMINI_API_KEY is required for fallback evaluation")

    started = perf_counter()
    results = evaluate_fallback(runs, settings, args.rpm)
    summary = {
        "threshold": settings.intent_confidence_threshold,
        "decision_model": decision_models.pop(),
        "fallback_model": settings.gemini_model,
        "source_runs": [str(path) for path in runs],
        "threshold_analysis": analysis,
        "elapsed_ms_including_pacing": round((perf_counter() - started) * 1000, 2),
        "combined": summarize_fallback(results),
        "by_run": {
            path.name: summarize_fallback([row for row in results if row.source_run == path.name])
            for path in runs
        },
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = RESULTS_ROOT / f"fallback_{stamp}"
    write_report(output, results, summary)
    print(f"Reports: {output}")
    return 1 if summary["combined"]["unconfirmed"] else 0


if __name__ == "__main__":
    sys.exit(main())
