"""Validate human stance annotations and create an FNC-compatible test split."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sklearn.metrics import cohen_kappa_score


VALID_LABELS = {"agree", "disagree", "discuss", "unrelated"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("output/paper_v7/annotation_inputs/spanish_stance_candidates_100.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/paper_v7/spanish_stance_test"),
    )
    return parser.parse_args()


def normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def main() -> None:
    args = parse_args()
    if not args.input.exists():
        raise SystemExit(f"Annotation input not found: {args.input}")
    with args.input.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    annotator_1: list[str] = []
    annotator_2: list[str] = []
    included: list[dict[str, str]] = []
    excluded: list[str] = []
    errors: list[str] = []

    for row_number, row in enumerate(rows, start=2):
        pair_id = row.get("pair_id", f"row-{row_number}")
        left = normalize(row.get("label_annotator_1"))
        right = normalize(row.get("label_annotator_2"))
        adjudicated = normalize(row.get("adjudicated_label"))
        if left not in VALID_LABELS or right not in VALID_LABELS:
            errors.append(f"{pair_id}: both independent labels must be one of {sorted(VALID_LABELS)}")
            continue
        annotator_1.append(left)
        annotator_2.append(right)
        if adjudicated == "exclude":
            excluded.append(pair_id)
            continue
        final_label = adjudicated or (left if left == right else "")
        if final_label not in VALID_LABELS:
            errors.append(f"{pair_id}: disagreement requires a valid adjudicated_label")
            continue
        if not row.get("claim", "").strip() or not row.get("article", "").strip():
            errors.append(f"{pair_id}: claim and article must be non-empty")
            continue
        row["final_label"] = final_label
        included.append(row)

    if errors:
        joined = "\n- ".join(errors[:20])
        raise SystemExit(f"Annotation validation failed:\n- {joined}")
    if not included:
        raise SystemExit("No adjudicated rows remain after exclusions.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stances_path = args.output_dir / "test_stances.csv"
    bodies_path = args.output_dir / "test_bodies.csv"
    report_path = args.output_dir / "annotation_report.json"

    with stances_path.open("w", encoding="utf-8", newline="") as stance_handle, bodies_path.open(
        "w", encoding="utf-8", newline=""
    ) as body_handle:
        stance_writer = csv.DictWriter(stance_handle, fieldnames=["Headline", "Body ID", "Stance"])
        body_writer = csv.DictWriter(body_handle, fieldnames=["Body ID", "articleBody"])
        stance_writer.writeheader()
        body_writer.writeheader()
        for body_id, row in enumerate(included, start=1):
            stance_writer.writerow({"Headline": row["claim"], "Body ID": body_id, "Stance": row["final_label"]})
            body_writer.writerow({"Body ID": body_id, "articleBody": row["article"]})

    disagreements = sum(left != right for left, right in zip(annotator_1, annotator_2, strict=True))
    final_label_counts = Counter(row["final_label"] for row in included)
    underrepresented_labels = {
        label: int(final_label_counts.get(label, 0))
        for label in sorted(VALID_LABELS)
        if final_label_counts.get(label, 0) < 10
    }
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input),
        "independent_annotations": len(annotator_1),
        "raw_agreement": (len(annotator_1) - disagreements) / len(annotator_1),
        "cohen_kappa": cohen_kappa_score(annotator_1, annotator_2),
        "disagreements": disagreements,
        "excluded_pair_ids": excluded,
        "final_test_size": len(included),
        "final_label_counts": dict(final_label_counts),
        "underrepresented_labels_below_10": underrepresented_labels,
        "outputs": {"stances": str(stances_path), "bodies": str(bodies_path)},
    }
    with report_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
