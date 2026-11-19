import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.evaluate_intent import INTENTS, RESULTS_ROOT, Result, summarize

METRICS = ("accuracy", "average_confidence", "average_latency_ms")
INTENT_METRICS = ("precision", "recall", "f1")


def load_run(directory: Path, version: str) -> tuple[dict, dict[str, Result]]:
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    model = summary["model"]
    prompt = summarize([], model, 0, version)
    if summary["criteria_version"] != prompt["criteria_version"]:
        raise ValueError(f"{directory}: criteria do not match {version}")
    # Historical V1 recorded the criteria hash only.
    if summary.get("prompt_version", "v1") != version or summary.get(
        "instructions_version", prompt["instructions_version"] if version == "v1" else None
    ) != prompt["instructions_version"]:
        raise ValueError(f"{directory}: instructions do not match {version}")

    rows = {}
    with (directory / "results.csv").open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            question_id = row["question_id"]
            if not question_id or question_id in rows:
                raise ValueError(f"{directory}: missing or duplicate question_id")
            expected = row["expected_intent"]
            predicted = row["predicted_intent"]
            error = row["error"]
            if expected not in INTENTS or (not error and predicted not in INTENTS):
                raise ValueError(f"{directory}: invalid intent for {question_id}")
            result = Result(
                question_id, row["question"], expected,
                latency_ms=float(row["latency_ms"]),
            )
            if error:
                result.error = error
            else:
                result.predicted_intent = predicted
                result.confidence = float(row["confidence"])
                result.is_correct = predicted == expected
            rows[question_id] = result
    if not rows or len(rows) != summary["attempted"]:
        raise ValueError(f"{directory}: results.csv count differs from summary")
    return prompt, rows


def metric_delta(before: float | None, after: float | None) -> dict:
    return {
        "v1": before,
        "v2": after,
        "delta": after - before if before is not None and after is not None else None,
    }


def compare_runs(v1_path: Path, v2_path: Path) -> dict:
    v1_prompt, v1 = load_run(v1_path, "v1")
    v2_prompt, v2 = load_run(v2_path, "v2")
    if v1_prompt["model"] != v2_prompt["model"]:
        raise ValueError("Use the same model for both runs")
    if v1.keys() != v2.keys():
        only_v1 = len(v1.keys() - v2.keys())
        only_v2 = len(v2.keys() - v1.keys())
        raise ValueError(
            "Runs must contain the same attempted question IDs. "
            f"V1: {len(v1)}, V2: {len(v2)}, shared: {len(v1) - only_v1}; "
            f"only V1: {only_v1}, only V2: {only_v2}. "
            "Use the same dataset and limit for both runs, and check whether either run stopped early."
        )

    paired_v1 = []
    paired_v2 = []
    fixed = []
    regressions = []
    excluded = []
    for question_id, before in v1.items():
        after = v2[question_id]
        if (before.question, before.expected_intent) != (after.question, after.expected_intent):
            raise ValueError(f"Question text or expected intent differs for {question_id}")
        if before.error or after.error:
            excluded.append({"question_id": question_id, "v1_error": before.error, "v2_error": after.error})
            continue
        paired_v1.append(before)
        paired_v2.append(after)
        if before.is_correct != after.is_correct:
            changes = fixed if after.is_correct else regressions
            changes.append({
                "question_id": question_id,
                "question": before.question,
                "expected_intent": before.expected_intent,
                "v1_prediction": before.predicted_intent,
                "v2_prediction": after.predicted_intent,
                "v1_confidence": before.confidence,
                "v2_confidence": after.confidence,
            })

    before = summarize(paired_v1, v1_prompt["model"], len(excluded), "v1")
    after = summarize(paired_v2, v2_prompt["model"], len(excluded), "v2")
    return {
        "model": before["model"],
        "runs": {
            "v1": {
                "path": str(v1_path.resolve()), "criteria_version": before["criteria_version"],
                "instructions_version": before["instructions_version"],
            },
            "v2": {
                "path": str(v2_path.resolve()), "criteria_version": after["criteria_version"],
                "instructions_version": after["instructions_version"],
            },
        },
        "attempted_in_both": len(v1),
        "compared": len(paired_v1),
        "excluded_api_errors": excluded,
        "metrics": {name: metric_delta(before[name], after[name]) for name in METRICS},
        "per_intent": {
            intent: {
                "support": before["per_intent"][intent]["support"],
                **{
                    name: metric_delta(before["per_intent"][intent][name], after["per_intent"][intent][name])
                    for name in INTENT_METRICS
                },
            }
            for intent in INTENTS
        },
        "fixed": fixed,
        "regressions": regressions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare matching intent evaluation runs offline.")
    parser.add_argument("v1_run", type=Path, help="Folder containing the original or rerun V1 reports.")
    parser.add_argument("v2_run", type=Path, help="Folder containing the V2 reports for the same questions.")
    args = parser.parse_args()
    try:
        report = compare_runs(args.v1_run, args.v2_run)
    except (KeyError, OSError, TypeError, ValueError) as error:
        parser.error(f"Cannot compare runs: {error}")

    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output = RESULTS_ROOT / f"comparison_{stamp}.json"
    with output.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)
        file.write("\n")
    print(f"Compared: {report['compared']} | Fixed: {len(report['fixed'])} | Regressions: {len(report['regressions'])}")
    print(f"Comparison: {output}")


if __name__ == "__main__":
    main()
