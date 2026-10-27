"""Evaluate the production stance-review pass on an adjudicated fixed-pair set.

This is a development regression, not a confirmatory evaluation. It reuses
opened gold labels to detect regressions while changing the stance policy.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from app.application_services.justification_service import GeminiJustificationService
from app.evidence_assessment import ASSESSMENT_VERSION


LABELS = ("supports", "refutes", "discusses", "unrelated")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    load_dotenv(encoding="utf-8-sig")
    rows = read_csv(args.gold)
    evaluable = [row for row in rows if row.get("final_status") == "evaluable"]
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in evaluable:
        grouped[row["case_id"]].append(row)

    service = GeminiJustificationService(db=None)
    predictions: list[dict[str, str]] = []
    for index, (case_id, case_rows) in enumerate(sorted(grouped.items()), start=1):
        claim = case_rows[0]["claim"]
        sources = [
            {
                "url": row["source_url"],
                "source": row["source_name"],
                "title": row["source_title"],
                "excerpt": row["evidence_excerpt"],
                "evidenceStance": row["model_stance"],
            }
            for row in case_rows
        ]
        reviewed = service._review_source_stances(claim, sources)
        for row, source in zip(case_rows, reviewed, strict=True):
            predictions.append({
                "evidence_id": row["evidence_id"],
                "case_id": case_id,
                "gold_stance": row["final_stance"],
                "previous_model_stance": row["model_stance"],
                "reviewed_stance": source["evidenceStance"],
                "assessment_method": source.get("assessmentMethod", ""),
            })
        print(f"[{index}/{len(grouped)}] {case_id}: {len(case_rows)} sources", flush=True)

    truth = [row["gold_stance"] for row in predictions]
    predicted = [row["reviewed_stance"] for row in predictions]
    previous = [row["previous_model_stance"] for row in predictions]
    matrix = {
        gold: {
            label: sum(g == gold and p == label for g, p in zip(truth, predicted, strict=True))
            for label in LABELS
        }
        for gold in LABELS
    }
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_role": "opened_gold_development_regression",
        "assessment_version": ASSESSMENT_VERSION,
        "sample_size": len(predictions),
        "gold_counts": dict(Counter(truth)),
        "reviewed_counts": dict(Counter(predicted)),
        "previous_accuracy": sum(a == b for a, b in zip(truth, previous, strict=True)) / len(truth),
        "reviewed_accuracy": sum(a == b for a, b in zip(truth, predicted, strict=True)) / len(truth),
        "reviewed_correct_n": sum(a == b for a, b in zip(truth, predicted, strict=True)),
        "confusion_matrix_gold_by_reviewed": matrix,
        "fallback_label_n": sum(not row["assessment_method"] for row in predictions),
        "limitations": [
            "The adjudicated labels were already opened and influenced policy development.",
            "This regression can detect known-case regressions but cannot estimate generalization.",
            "A new blind sample is required before reporting confirmatory performance.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "predictions.csv", predictions)
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
