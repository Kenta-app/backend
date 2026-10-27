"""Validate two blind evidence annotations, adjudicate conflicts, and compute metrics."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sklearn.metrics import accuracy_score, classification_report, cohen_kappa_score, confusion_matrix, f1_score


LABELS = ("supports", "refutes", "discusses", "unrelated")
STATUSES = ("include", "exclude_unavailable", "exclude_insufficient_context")


def normalize(value: object) -> str:
    return str(value or "").strip().casefold()


def read_unique(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    keyed: dict[str, dict[str, str]] = {}
    for number, row in enumerate(rows, start=2):
        item_id = normalize(row.get("evidence_id"))
        if not item_id:
            raise ValueError(f"{path}:{number}: evidence_id is required")
        if item_id in keyed:
            raise ValueError(f"{path}:{number}: duplicate evidence_id {item_id}")
        keyed[item_id] = row
    return keyed


def validate_annotation(path: Path, rows: dict[str, dict[str, str]]) -> None:
    errors: list[str] = []
    for item_id, row in rows.items():
        status = normalize(row.get("review_status"))
        label = normalize(row.get("human_stance"))
        if status not in STATUSES:
            errors.append(f"{item_id}: review_status must be one of {STATUSES}")
        elif status == "include" and label not in LABELS:
            errors.append(f"{item_id}: included rows require human_stance in {LABELS}")
        elif status != "include" and label:
            errors.append(f"{item_id}: excluded rows must leave human_stance empty")
    if errors:
        raise ValueError(f"Invalid annotations in {path}:\n- " + "\n- ".join(errors[:20]))


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def bootstrap_macro_f1(
    truth: list[str], predicted: list[str], *, labels: tuple[str, ...] = LABELS,
    seed: int, repetitions: int
) -> dict[str, float] | None:
    if len(truth) < 2 or repetitions <= 0:
        return None
    rng = random.Random(seed)
    scores: list[float] = []
    for _ in range(repetitions):
        indexes = [rng.randrange(len(truth)) for _ in truth]
        scores.append(float(f1_score(
            [truth[i] for i in indexes],
            [predicted[i] for i in indexes],
            labels=labels,
            average="macro",
            zero_division=0,
        )))
    return {"low": percentile(scores, 0.025), "high": percentile(scores, 0.975)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-key", type=Path, required=True)
    parser.add_argument("--annotator-a", type=Path, required=True)
    parser.add_argument("--annotator-b", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("output/evidence_annotation_results"))
    parser.add_argument("--bootstrap-repetitions", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261021)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = read_unique(args.model_key)
    first = read_unique(args.annotator_a)
    second = read_unique(args.annotator_b)
    if set(model) != set(first) or set(model) != set(second):
        raise SystemExit("Model key and both annotation files must contain the same evidence_id values.")
    validate_annotation(args.annotator_a, first)
    validate_annotation(args.annotator_b, second)

    jointly_included = [
        item_id for item_id in model
        if normalize(first[item_id]["review_status"]) == "include"
        and normalize(second[item_id]["review_status"]) == "include"
    ]
    a_labels = [normalize(first[item_id]["human_stance"]) for item_id in jointly_included]
    b_labels = [normalize(second[item_id]["human_stance"]) for item_id in jointly_included]
    disagreements = [
        item_id for item_id in model
        if normalize(first[item_id]["review_status"]) != normalize(second[item_id]["review_status"])
        or (
            normalize(first[item_id]["review_status"]) == "include"
            and normalize(second[item_id]["review_status"]) == "include"
            and normalize(first[item_id]["human_stance"])
            != normalize(second[item_id]["human_stance"])
        )
    ]

    adjudicated = read_unique(args.adjudication) if args.adjudication else {}
    final: dict[str, tuple[str, str]] = {}
    unresolved: list[str] = []
    for item_id in model:
        a_status = normalize(first[item_id]["review_status"])
        b_status = normalize(second[item_id]["review_status"])
        a_label = normalize(first[item_id]["human_stance"])
        b_label = normalize(second[item_id]["human_stance"])
        if a_status == b_status and (a_status != "include" or a_label == b_label):
            final[item_id] = (a_status, a_label if a_status == "include" else "")
            continue
        decision = adjudicated.get(item_id)
        status = normalize(decision.get("final_status")) if decision else ""
        label = normalize(decision.get("final_stance")) if decision else ""
        if status not in STATUSES or (status == "include" and label not in LABELS):
            unresolved.append(item_id)
        else:
            final[item_id] = (status, label if status == "include" else "")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    conflicts_path = args.output_dir / "adjudication_needed.csv"
    with conflicts_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = (
            "evidence_id", "claim", "source_name", "source_title", "evidence_excerpt",
            "source_url", "annotator_a_status", "annotator_a_stance",
            "annotator_a_confidence", "annotator_a_notes", "annotator_b_status",
            "annotator_b_stance", "annotator_b_confidence", "annotator_b_notes",
            "final_status", "final_stance", "rationale",
        )
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item_id in disagreements:
            writer.writerow({
                "evidence_id": item_id,
                "claim": model[item_id].get("claim", ""),
                "source_name": model[item_id].get("source_name", ""),
                "source_title": model[item_id].get("source_title", ""),
                "evidence_excerpt": model[item_id].get("evidence_excerpt", ""),
                "source_url": model[item_id].get("source_url", ""),
                "annotator_a_status": first[item_id].get("review_status", ""),
                "annotator_a_stance": first[item_id].get("human_stance", ""),
                "annotator_a_confidence": first[item_id].get("confidence", ""),
                "annotator_a_notes": first[item_id].get("notes", ""),
                "annotator_b_status": second[item_id].get("review_status", ""),
                "annotator_b_stance": second[item_id].get("human_stance", ""),
                "annotator_b_confidence": second[item_id].get("confidence", ""),
                "annotator_b_notes": second[item_id].get("notes", ""),
                "final_status": adjudicated.get(item_id, {}).get("final_status", ""),
                "final_stance": adjudicated.get(item_id, {}).get("final_stance", ""),
                "rationale": adjudicated.get(item_id, {}).get("rationale", ""),
            })

    included_ids = [item_id for item_id, (status, _label) in final.items() if status == "include"]
    truth = [final[item_id][1] for item_id in included_ids]
    predicted = [normalize(model[item_id].get("model_stance")) for item_id in included_ids]
    metrics = None
    if not unresolved and truth:
        observed_labels = tuple(label for label in LABELS if label in set(truth))
        metrics = {
            "accuracy": float(accuracy_score(truth, predicted)),
            "macro_f1_four_class": float(f1_score(
                truth, predicted, labels=LABELS, average="macro", zero_division=0
            )),
            "macro_f1_four_class_95_percentile_interval": bootstrap_macro_f1(
                truth,
                predicted,
                labels=LABELS,
                seed=args.seed,
                repetitions=args.bootstrap_repetitions,
            ),
            "observed_gold_labels": list(observed_labels),
            "missing_gold_labels": [label for label in LABELS if label not in observed_labels],
            "macro_f1_observed_classes": float(f1_score(
                truth, predicted, labels=observed_labels, average="macro", zero_division=0
            )),
            "macro_f1_observed_classes_95_percentile_interval": bootstrap_macro_f1(
                truth,
                predicted,
                labels=observed_labels,
                seed=args.seed,
                repetitions=args.bootstrap_repetitions,
            ),
            "confusion_matrix_label_order": list(LABELS),
            "confusion_matrix": confusion_matrix(truth, predicted, labels=LABELS).tolist(),
            "classification_report": classification_report(
                truth, predicted, labels=LABELS, output_dict=True, zero_division=0
            ),
        }

    raw_agreement = (
        sum(left == right for left, right in zip(a_labels, b_labels, strict=True)) / len(a_labels)
        if a_labels
        else None
    )
    kappa = None
    if len(a_labels) >= 2 and len(set(a_labels + b_labels)) >= 2:
        kappa = float(cohen_kappa_score(a_labels, b_labels, labels=LABELS))
    report = {
        "protocol_version": "evidence-annotation-2026-10-21-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_size": len(model),
        "jointly_included_before_adjudication": len(jointly_included),
        "raw_stance_agreement_on_jointly_included": raw_agreement,
        "cohen_kappa_on_jointly_included": kappa,
        "disagreements_requiring_adjudication": len(disagreements),
        "unresolved_evidence_ids": unresolved,
        "final_included": len(included_ids),
        "final_excluded": sum(status != "include" for status, _ in final.values()),
        "gold_label_counts": dict(Counter(truth)),
        "metrics_status": "complete" if metrics else "pending_adjudication_or_no_included_rows",
        "model_metrics": metrics,
        "conflicts_file": str(conflicts_path),
    }
    report_path = args.output_dir / "evidence_annotation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if unresolved:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
