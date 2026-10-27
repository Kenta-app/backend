"""Combine unchanged v4 gold decisions with the adjudicated v5 focused review.

This is a development regression on the same frozen 20-case sample.  It is not
confirmatory: changed evidence sets use the new focused review, while unchanged
source pairs and coverage cases retain their prior blind adjudicated decisions.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from finalize_evidence_end_to_end_adjudication import classification_metrics, wilson, write_csv


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-run", type=Path, required=True)
    parser.add_argument("--v4-final-dir", type=Path, required=True)
    parser.add_argument("--focused-final-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    current = read_jsonl(args.current_run)
    old_sources = {
        (row["case_id"], row["source_url"]): row
        for row in read_csv(args.v4_final_dir / "final_source_results.csv")
    }
    focused_sources = {
        (row["case_id"], row["source_url"]): row
        for row in read_csv(args.focused_final_dir / "final_source_results.csv")
    }
    old_coverage = {
        row["case_id"]: row
        for row in read_csv(args.v4_final_dir / "final_coverage_results.csv")
    }
    focused_coverage = {
        row["case_id"]: row
        for row in read_csv(args.focused_final_dir / "final_coverage_results.csv")
    }

    source_results: list[dict[str, Any]] = []
    coverage_results: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    errors: list[str] = []

    for case in sorted(current, key=lambda row: row["case_id"]):
        independent_index = 0
        for source in case.get("sources", []):
            if not source.get("independenceEligible", True):
                continue
            independent_index += 1
            key = (case["case_id"], source["url"])
            matches = [("v5_focused_review", focused_sources[key])] if key in focused_sources else []
            if key in old_sources:
                matches.append(("v4_prior_blind_review", old_sources[key]))
            if len(matches) != 1:
                errors.append(f"{key}: expected exactly one human gold match, found {len(matches)}")
                continue
            review_source, gold = matches[0]
            row = {
                "evidence_id": f"V5FULL-{case['case_id']}-S{independent_index:02d}",
                "case_id": case["case_id"],
                "claim": case.get("claim", ""),
                "source_name": source.get("source", ""),
                "source_title": source.get("title", ""),
                "evidence_excerpt": source.get("excerpt", ""),
                "source_url": source.get("url", ""),
                "source_role": source.get("sourceRole", "independent_evidence"),
                "model_stance": source.get("evidenceStance", ""),
                "final_status": gold.get("final_status", ""),
                "final_stance": gold.get("final_stance", ""),
                "model_matches_final": source.get("evidenceStance", "") == gold.get("final_stance", ""),
                "review_provenance": review_source,
                "human_decision_source": gold.get("decision_source", ""),
                "adjudication_rationale": gold.get("adjudication_rationale", ""),
            }
            if row["final_status"] != "evaluable" or not row["final_stance"]:
                errors.append(f"{key}: inherited gold is not evaluable with a stance")
            source_results.append(row)
            provenance.append({
                "record_type": "source",
                "record_id": row["evidence_id"],
                "case_id": row["case_id"],
                "review_provenance": review_source,
                "source_role": row["source_role"],
                "url": row["source_url"],
            })

        case_id = case["case_id"]
        if case_id in focused_coverage:
            review_source, gold = "v5_focused_review", focused_coverage[case_id]
        elif case_id in old_coverage:
            review_source, gold = "v4_prior_blind_review", old_coverage[case_id]
        else:
            errors.append(f"{case_id}: no coverage gold found")
            continue
        sources = case.get("sources", [])
        coverage_row = {
            "case_id": case_id,
            "claim": case.get("claim", ""),
            "original_source": case.get("original_source", ""),
            "original_url": case.get("original_url", ""),
            "returned_source_count": len(sources),
            "independent_source_count": sum(source.get("independenceEligible", True) for source in sources),
            "primary_context_count": sum(not source.get("independenceEligible", True) for source in sources),
            "final_coverage": gold.get("final_coverage", ""),
            "final_missing": gold.get("final_missing", ""),
            "final_missing_url": gold.get("final_missing_url", ""),
            "review_provenance": review_source,
            "human_decision_source": gold.get("decision_source", ""),
            "adjudication_rationale": gold.get("adjudication_rationale", ""),
        }
        if not coverage_row["final_coverage"] or not coverage_row["final_missing"]:
            errors.append(f"{case_id}: incomplete inherited coverage decision")
        coverage_results.append(coverage_row)
        provenance.append({
            "record_type": "coverage",
            "record_id": case_id,
            "case_id": case_id,
            "review_provenance": review_source,
            "source_role": "case_set",
            "url": coverage_row["original_url"],
        })

    if errors:
        raise ValueError("Full v5 evaluation validation failed:\n- " + "\n- ".join(errors))
    if len(source_results) != 26 or len(coverage_results) != 20:
        raise ValueError(f"Unexpected final sizes: sources={len(source_results)}, coverage={len(coverage_results)}")

    relevant = sum(row["final_stance"] != "unrelated" for row in source_results)
    stance = classification_metrics(source_results)
    coverage_counts = Counter(row["final_coverage"] for row in coverage_results)
    evidence_exists = [row for row in coverage_results if row["final_coverage"] in {"sufficient", "partial", "none"}]
    useful = [row for row in evidence_exists if row["final_coverage"] in {"sufficient", "partial"}]
    zero_source = [row for row in coverage_results if int(row["returned_source_count"]) == 0]
    false_empty = [row for row in zero_source if row["final_coverage"] == "none"]
    retrieval_success = sum(int(row["returned_source_count"]) > 0 for row in coverage_results)
    false_empty_rate = len(false_empty) / len(zero_source) if zero_source else 0.0

    reference_criteria = {
        "retrieval_at_least_16_of_20": {"threshold": 0.80, "observed": retrieval_success / 20, "passed": retrieval_success >= 16},
        "source_precision_at_least_90_percent": {"threshold": 0.90, "observed": relevant / len(source_results), "passed": relevant / len(source_results) >= 0.90},
        "useful_coverage_at_least_80_percent": {"threshold": 0.80, "observed": len(useful) / len(evidence_exists), "passed": len(useful) / len(evidence_exists) >= 0.80},
        "stance_accuracy_at_least_75_percent": {"threshold": 0.75, "observed": stance["accuracy"], "passed": stance["accuracy"] >= 0.75},
        "false_empty_rate_at_most_20_percent": {"threshold": 0.20, "observed": false_empty_rate, "passed": false_empty_rate <= 0.20},
    }
    focused_summary = json.loads((args.focused_final_dir / "final_summary.json").read_text(encoding="utf-8"))
    summary = {
        "analysis_stage": "v5_development_regression_final",
        "confirmatory": False,
        "coverage_cases": len(coverage_results),
        "independent_source_pairs": len(source_results),
        "primary_context_only_cases": sum(row["independent_source_count"] == 0 for row in coverage_results),
        "independent_evidence_cases": sum(row["independent_source_count"] > 0 for row in coverage_results),
        "review_provenance": {
            "v5_focused_source_n": sum(row["review_provenance"] == "v5_focused_review" for row in source_results),
            "v4_reused_source_n": sum(row["review_provenance"] == "v4_prior_blind_review" for row in source_results),
            "v5_focused_coverage_n": sum(row["review_provenance"] == "v5_focused_review" for row in coverage_results),
            "v4_reused_coverage_n": sum(row["review_provenance"] == "v4_prior_blind_review" for row in coverage_results),
        },
        "focused_interannotator_agreement_pre_adjudication": focused_summary["interannotator_agreement_pre_adjudication"],
        "retrieval_source_quality_final": {
            "evaluable_n": len(source_results),
            "relevant_n": relevant,
            "precision": relevant / len(source_results),
            "precision_wilson_95": wilson(relevant, len(source_results)),
        },
        "system_stance_final": stance,
        "coverage_final": {
            "status_counts": dict(coverage_counts),
            "evidence_exists_n": len(evidence_exists),
            "useful_coverage_n": len(useful),
            "useful_coverage_rate": len(useful) / len(evidence_exists),
            "zero_source_n": len(zero_source),
            "false_empty_n": len(false_empty),
            "false_empty_rate": false_empty_rate,
            "false_empty_rate_denominator_zero": not zero_source,
            "missing_yes_n": sum(row["final_missing"] == "yes" for row in coverage_results),
        },
        "system_run": {
            "retrieval_success_n": retrieval_success,
            "retrieval_success_rate": retrieval_success / 20,
            "retrieval_success_wilson_95": wilson(retrieval_success, 20),
        },
        "reference_criteria": reference_criteria,
        "reference_criteria_passed_n": sum(value["passed"] for value in reference_criteria.values()),
        "overall_reference_passed": all(value["passed"] for value in reference_criteria.values()),
        "limitations": [
            "Development regression on the same frozen 20-case sample used to diagnose and improve retrieval; it is not a fresh confirmatory evaluation.",
            "Changed evidence sets use the new focused blind review; unchanged records reuse prior blind adjudicated decisions only when case ID and URL match exactly.",
            "Three cases contain primary context only. Primary context supports interpretation but is excluded from independent-source precision and stance metrics.",
            "No X/social cases were present, so thread and quote context still requires a separate social-media evaluation.",
            "No final human examples of refutes or unrelated were observed; fixed four-class macro-F1 is therefore not a central metric.",
            "There were no empty result sets, so the false-empty rate has a zero denominator; zero false-empty events were observed.",
        ],
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "final_source_results.csv", source_results)
    write_csv(args.output_dir / "final_coverage_results.csv", coverage_results)
    write_csv(args.output_dir / "provenance_audit.csv", provenance)
    (args.output_dir / "final_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
