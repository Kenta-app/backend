"""Compare a non-persistent retrieval regression with adjudicated pilot coverage."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regression-dir", type=Path, required=True)
    parser.add_argument("--adjudicated-coverage", type=Path, required=True)
    parser.add_argument("--baseline-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    run_rows = read_jsonl(args.regression_dir / "retrieval_run.jsonl")
    coverage = {row["case_id"]: row for row in read_csv(args.adjudicated_coverage)}
    baseline = json.loads(args.baseline_summary.read_text(encoding="utf-8"))
    run_summary = json.loads((args.regression_dir / "run_summary.json").read_text(encoding="utf-8"))

    empty_ids = [row["case_id"] for row in run_rows if int(row["source_count"]) == 0]
    correct_empty_ids = [
        case_id for case_id in empty_ids
        if coverage[case_id]["final_coverage"] == "no_evidence_found"
    ]
    false_empty_ids = [case_id for case_id in empty_ids if case_id not in correct_empty_ids]
    retrieval_target = 16
    false_empty_rate_target = 0.20
    false_empty_rate = len(false_empty_ids) / len(empty_ids) if empty_ids else 0.0

    report = {
        "analysis_stage": "retrieval_regression_before_new_human_annotation",
        "sample_sha256": run_summary["frozen_sample_sha256"],
        "case_count": run_summary["case_count"],
        "baseline": {
            "cases_with_sources": baseline["system_run"]["retrieval_success_n"],
            "retrieval_rate": baseline["system_run"]["retrieval_success_rate"],
            "false_empty_n": baseline["coverage_final"]["false_empty_n"],
            "zero_source_n": baseline["coverage_final"]["zero_source_n"],
        },
        "regression": {
            "cases_with_sources": run_summary["cases_with_sources"],
            "retrieval_rate": run_summary["cases_with_sources"] / run_summary["case_count"],
            "evidence_row_count": run_summary["evidence_row_count"],
            "empty_case_ids": empty_ids,
            "correct_empty_case_ids": correct_empty_ids,
            "false_empty_case_ids": false_empty_ids,
            "false_empty_n": len(false_empty_ids),
            "false_empty_rate_among_empty_results": false_empty_rate,
            "database_modified": run_summary["production_database_modified"],
        },
        "preregistered_checks": {
            "retrieval_at_least_16_of_20": {
                "threshold": retrieval_target,
                "observed": run_summary["cases_with_sources"],
                "passed": run_summary["cases_with_sources"] >= retrieval_target,
            },
            "false_empty_rate_at_most_20_percent": {
                "threshold": false_empty_rate_target,
                "observed": false_empty_rate,
                "passed": false_empty_rate <= false_empty_rate_target,
            },
            "source_precision_at_least_90_percent": {"status": "pending_blind_annotation"},
            "useful_coverage_at_least_80_percent": {"status": "pending_blind_annotation"},
            "stance_accuracy_at_least_75_percent": {"status": "pending_blind_annotation"},
        },
        "interpretation": (
            "Retrieval improved materially and met its count target, but the strict false-empty "
            "criterion did not pass. Quality, coverage and stance require new blind annotation "
            "because the regression returned a different set of source pairs."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
