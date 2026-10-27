"""Overlay targeted v4/v5 reruns onto the full v3 development regression."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base",
        type=Path,
        default=Path("output/evidence_v4_full_policy_regression_2026_10_25/retrieval_run.jsonl"),
    )
    parser.add_argument(
        "--overlay",
        type=Path,
        action="append",
        default=[
            Path("output/evidence_v4_empty_retry_v4_regression_2026_10_25/retrieval_run.jsonl"),
            Path("output/evidence_v4_case009_unrelated_filter_regression_2026_10_25/retrieval_run.jsonl"),
        ],
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/evidence_v4_policy_v5_consolidated_2026_10_25"),
    )
    args = parser.parse_args()

    merged = {row["case_id"]: row for row in read_jsonl(args.base)}
    provenance = {case_id: str(args.base) for case_id in merged}
    for overlay in args.overlay:
        for row in read_jsonl(overlay):
            merged[row["case_id"]] = row
            provenance[row["case_id"]] = str(overlay)
    if len(merged) != 20:
        raise RuntimeError(f"Expected 20 consolidated cases, got {len(merged)}")

    rows = [merged[case_id] for case_id in sorted(merged)]
    errors = [row["case_id"] for row in rows if row["status"] == "error"]
    violations = [row["case_id"] for row in rows if row["policy_violations"]]
    unrelated = [
        (row["case_id"], source.get("url"))
        for row in rows
        for source in row["sources"]
        if source.get("evidenceStance") == "unrelated"
    ]
    if errors or violations or unrelated:
        raise RuntimeError(
            f"Consolidation invariants failed: errors={errors}, "
            f"violations={violations}, unrelated={unrelated}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_path = args.output_dir / "retrieval_run.jsonl"
    run_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = {
        "purpose": "consolidated development regression after targeted v4/v5 corrections",
        "case_count": 20,
        "operational_error_n": 0,
        "nonempty_case_n": sum(row["source_count"] > 0 for row in rows),
        "independent_source_case_n": sum(row["independent_source_count"] > 0 for row in rows),
        "primary_context_only_case_n": sum(
            row["primary_context_count"] > 0 and row["independent_source_count"] == 0
            for row in rows
        ),
        "total_source_records": sum(row["source_count"] for row in rows),
        "total_independent_sources": sum(row["independent_source_count"] for row in rows),
        "unrelated_visible_n": 0,
        "policy_violation_n": 0,
        "assessment_version": "evidence-policy-2026-10-25-v5",
        "search_policy_version": "retrieval-policy-2026-10-25-v5",
        "confirmatory": False,
        "requires_human_review": True,
        "case_provenance": provenance,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
