"""Evaluate two annotations for the targeted evidence challenge.

The historical label is reported only as a development reference. It is not
treated as an independent gold standard because it was used to construct the
challenge sample.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sklearn.metrics import cohen_kappa_score, confusion_matrix, f1_score


LABELS = ("supports", "refutes", "discusses", "unrelated")
STATUSES = ("include", "exclude_unavailable", "exclude_insufficient_context")


def norm(value: object) -> str:
    return str(value or "").strip().casefold()


def read_unique(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, str]] = {}
    for line, row in enumerate(rows, start=2):
        evidence_id = norm(row.get("evidence_id"))
        if not evidence_id:
            raise ValueError(f"{path}:{line}: evidence_id is required")
        if evidence_id in result:
            raise ValueError(f"{path}:{line}: duplicate evidence_id {evidence_id}")
        result[evidence_id] = row
    return result


def validate(path: Path, rows: dict[str, dict[str, str]]) -> None:
    errors: list[str] = []
    for evidence_id, row in rows.items():
        status = norm(row.get("review_status"))
        stance = norm(row.get("human_stance"))
        confidence = norm(row.get("confidence"))
        if status not in STATUSES:
            errors.append(f"{evidence_id}: invalid review_status {status!r}")
        if status == "include" and stance not in LABELS:
            errors.append(f"{evidence_id}: included rows require a valid stance")
        if status != "include" and stance:
            errors.append(f"{evidence_id}: excluded rows must have blank stance")
        if confidence and confidence not in {"alta", "media", "baja", "high", "medium", "low"}:
            errors.append(f"{evidence_id}: invalid confidence {confidence!r}")
    if errors:
        raise ValueError(f"Invalid annotations in {path}:\n- " + "\n- ".join(errors))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--annotator-a", type=Path, required=True)
    parser.add_argument("--annotator-b", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    key = read_unique(args.key)
    a = read_unique(args.annotator_a)
    b = read_unique(args.annotator_b)
    if set(key) != set(a) or set(key) != set(b):
        raise SystemExit("The key and both annotation files must contain identical evidence_id values.")
    validate(args.annotator_a, a)
    validate(args.annotator_b, b)

    ordered_ids = list(key)
    status_agreements = [norm(a[i]["review_status"]) == norm(b[i]["review_status"]) for i in ordered_ids]
    jointly_included = [
        i for i in ordered_ids
        if norm(a[i]["review_status"]) == "include" and norm(b[i]["review_status"]) == "include"
    ]
    a_labels = [norm(a[i]["human_stance"]) for i in jointly_included]
    b_labels = [norm(b[i]["human_stance"]) for i in jointly_included]
    stance_agreements = [left == right for left, right in zip(a_labels, b_labels, strict=True)]
    conflicts = [
        i for i in ordered_ids
        if norm(a[i]["review_status"]) != norm(b[i]["review_status"])
        or (
            norm(a[i]["review_status"]) == "include"
            and norm(b[i]["review_status"]) == "include"
            and norm(a[i]["human_stance"]) != norm(b[i]["human_stance"])
        )
    ]

    kappa = None
    if len(jointly_included) >= 2 and len(set(a_labels + b_labels)) >= 2:
        kappa = float(cohen_kappa_score(a_labels, b_labels, labels=LABELS))

    prior = [norm(key[i].get("prior_human_label")) for i in ordered_ids]
    a_all = [norm(a[i]["human_stance"]) for i in ordered_ids]
    b_all = [norm(b[i]["human_stance"]) for i in ordered_ids]

    def historical_summary(values: list[str]) -> dict[str, object]:
        matches = [left == right for left, right in zip(values, prior, strict=True)]
        return {
            "match_rate": sum(matches) / len(matches),
            "macro_f1_four_class": float(
                f1_score(prior, values, labels=LABELS, average="macro", zero_division=0)
            ),
            "confusion_matrix_label_order": list(LABELS),
            "confusion_matrix": confusion_matrix(prior, values, labels=LABELS).tolist(),
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    conflict_path = args.output_dir / "adjudication_needed.csv"
    fields = (
        "evidence_id", "claim", "source_name", "source_title", "evidence_excerpt", "source_url",
        "annotator_a_status", "annotator_a_stance", "annotator_a_confidence", "annotator_a_notes",
        "annotator_b_status", "annotator_b_stance", "annotator_b_confidence", "annotator_b_notes",
        "final_status", "final_stance", "rationale",
    )
    with conflict_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for evidence_id in conflicts:
            writer.writerow({
                "evidence_id": evidence_id,
                "claim": key[evidence_id].get("claim", ""),
                "source_name": key[evidence_id].get("source_name", ""),
                "source_title": key[evidence_id].get("source_title", ""),
                "evidence_excerpt": key[evidence_id].get("evidence_excerpt", ""),
                "source_url": key[evidence_id].get("source_url", ""),
                "annotator_a_status": a[evidence_id].get("review_status", ""),
                "annotator_a_stance": a[evidence_id].get("human_stance", ""),
                "annotator_a_confidence": a[evidence_id].get("confidence", ""),
                "annotator_a_notes": a[evidence_id].get("notes", ""),
                "annotator_b_status": b[evidence_id].get("review_status", ""),
                "annotator_b_stance": b[evidence_id].get("human_stance", ""),
                "annotator_b_confidence": b[evidence_id].get("confidence", ""),
                "annotator_b_notes": b[evidence_id].get("notes", ""),
                "final_status": "",
                "final_stance": "",
                "rationale": "",
            })

    report = {
        "protocol_version": "evidence-policy-2026-10-22-v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "design_note": (
            "Targeted development challenge enriched for prior refutes/unrelated/boundary cases; "
            "historical-label comparisons are not independent confirmatory performance estimates."
        ),
        "sample_size": len(ordered_ids),
        "status_agreement": sum(status_agreements) / len(status_agreements),
        "jointly_included": len(jointly_included),
        "stance_raw_agreement": sum(stance_agreements) / len(stance_agreements),
        "cohen_kappa": kappa,
        "conflicts_requiring_adjudication": len(conflicts),
        "agreement_label_counts": dict(Counter(
            a[evidence_id]["human_stance"] for evidence_id in ordered_ids
            if norm(a[evidence_id]["human_stance"]) == norm(b[evidence_id]["human_stance"])
        )),
        "annotator_a_label_counts": dict(Counter(a_all)),
        "annotator_b_label_counts": dict(Counter(b_all)),
        "historical_reference_only": {
            "prior_label_counts": dict(Counter(prior)),
            "annotator_a": historical_summary(a_all),
            "annotator_b": historical_summary(b_all),
        },
        "conflicts_file": str(conflict_path),
    }
    report_path = args.output_dir / "targeted_challenge_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
