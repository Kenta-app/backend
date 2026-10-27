"""Apply the adjudication workbook to the frozen end-to-end pilot results.

The source workbook is read-only. This script validates that its adjudicated IDs
match the pre-adjudication disagreement sets exactly, then writes auditable CSV
and JSON outputs for the final thesis report.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


SOURCE_LABELS = ("supports", "refutes", "discusses", "unrelated")
SOURCE_STATUSES = {"evaluable", "unavailable", "insufficient_context"}
COVERAGE_LABELS = {"sufficient", "partial", "none", "no_evidence_found", "unable_to_assess"}
MISSING_LABELS = {"yes", "no", "unable_to_assess"}
SOURCE_FROZEN_FIELDS = (
    "evidence_id", "case_id", "claim", "source_name", "source_title",
    "evidence_excerpt", "source_url", "annotator_a_status", "annotator_a_stance",
    "annotator_a_notes", "annotator_b_status", "annotator_b_stance", "annotator_b_notes",
)
COVERAGE_FROZEN_FIELDS = (
    "case_id", "claim", "original_source", "original_url", "returned_source_count",
    "annotator_a_coverage", "annotator_a_missing", "annotator_a_missing_url",
    "annotator_a_notes", "annotator_b_coverage", "annotator_b_missing",
    "annotator_b_missing_url", "annotator_b_notes",
)


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def truthy(value: Any) -> bool:
    return text(value).lower() in {"true", "1", "yes", "si", "sí"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_sheet_records(workbook_path: Path, sheet_name: str) -> list[dict[str, Any]]:
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        sheet = workbook[sheet_name]
        rows = sheet.iter_rows(values_only=True)
        header = [text(value) for value in next(rows)]
        return [dict(zip(header, row)) for row in rows if any(value is not None for value in row)]
    finally:
        workbook.close()


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def classification_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    correct = sum(text(row["model_stance"]) == text(row["final_stance"]) for row in rows)
    per_class: dict[str, dict[str, Any]] = {}
    observed = []
    for label in SOURCE_LABELS:
        tp = sum(text(row["model_stance"]) == label and text(row["final_stance"]) == label for row in rows)
        fp = sum(text(row["model_stance"]) == label and text(row["final_stance"]) != label for row in rows)
        fn = sum(text(row["model_stance"]) != label and text(row["final_stance"]) == label for row in rows)
        support = sum(text(row["final_stance"]) == label for row in rows)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {
            "support": support,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        if support:
            observed.append(f1)

    confusion = {
        gold: {predicted: sum(text(row["final_stance"]) == gold and text(row["model_stance"]) == predicted for row in rows)
               for predicted in SOURCE_LABELS}
        for gold in SOURCE_LABELS
    }
    return {
        "n": n,
        "accuracy": correct / n if n else 0.0,
        "accuracy_count": correct,
        "accuracy_wilson_95": wilson(correct, n),
        "macro_f1_fixed_4": sum(values["f1"] for values in per_class.values()) / len(SOURCE_LABELS),
        "macro_f1_observed_gold_classes": sum(observed) / len(observed) if observed else 0.0,
        "per_class": per_class,
        "confusion_matrix_gold_by_model": confusion,
    }


def validate_and_apply(
    source_rows: list[dict[str, str]],
    coverage_rows: list[dict[str, str]],
    source_adjudications: list[dict[str, Any]],
    coverage_adjudications: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[str] = []
    expected_source = {row["evidence_id"] for row in source_rows if truthy(row["needs_adjudication"])}
    actual_source = {
        text(row.get("evidence_id"))
        for row in source_adjudications
        if text(row.get("evidence_id")) and text(row.get("final_status"))
    }
    expected_coverage = {row["case_id"] for row in coverage_rows if truthy(row["needs_adjudication"])}
    actual_coverage = {
        text(row.get("case_id"))
        for row in coverage_adjudications
        if text(row.get("case_id")) and text(row.get("final_coverage"))
    }
    if expected_source != actual_source:
        errors.append(f"Source adjudication IDs mismatch: expected={sorted(expected_source)}, actual={sorted(actual_source)}")
    if expected_coverage != actual_coverage:
        errors.append(f"Coverage adjudication IDs mismatch: expected={sorted(expected_coverage)}, actual={sorted(actual_coverage)}")

    source_by_id = {
        text(row["evidence_id"]): row
        for row in source_adjudications
        if text(row.get("evidence_id")) and text(row.get("final_status"))
    }
    coverage_by_id = {
        text(row["case_id"]): row
        for row in coverage_adjudications
        if text(row.get("case_id")) and text(row.get("final_coverage"))
    }

    source_expected_by_id = {row["evidence_id"]: row for row in source_rows}
    coverage_expected_by_id = {row["case_id"]: row for row in coverage_rows}
    for identifier, row in source_by_id.items():
        expected = source_expected_by_id.get(identifier)
        if expected is None:
            continue
        for field in SOURCE_FROZEN_FIELDS:
            if text(row.get(field)) != text(expected.get(field)):
                errors.append(f"{identifier}: frozen source field changed: {field}")
    for identifier, row in coverage_by_id.items():
        expected = coverage_expected_by_id.get(identifier)
        if expected is None:
            continue
        for field in COVERAGE_FROZEN_FIELDS:
            if text(row.get(field)) != text(expected.get(field)):
                errors.append(f"{identifier}: frozen coverage field changed: {field}")

    for identifier, row in source_by_id.items():
        status = text(row.get("final_status"))
        stance = text(row.get("final_stance"))
        rationale = text(row.get("adjudication_rationale"))
        if status not in SOURCE_STATUSES:
            errors.append(f"{identifier}: invalid final_status={status!r}")
        if status == "evaluable" and stance not in SOURCE_LABELS:
            errors.append(f"{identifier}: evaluable source requires a valid final_stance")
        if status != "evaluable" and stance:
            errors.append(f"{identifier}: non-evaluable source must not have final_stance")
        if not rationale:
            errors.append(f"{identifier}: missing adjudication rationale")

    for identifier, row in coverage_by_id.items():
        coverage = text(row.get("final_coverage"))
        missing = text(row.get("final_missing"))
        missing_url = text(row.get("final_missing_url"))
        rationale = text(row.get("adjudication_rationale"))
        if coverage not in COVERAGE_LABELS:
            errors.append(f"{identifier}: invalid final_coverage={coverage!r}")
        if missing not in MISSING_LABELS:
            errors.append(f"{identifier}: invalid final_missing={missing!r}")
        if missing == "yes" and not missing_url:
            errors.append(f"{identifier}: final_missing=yes requires final_missing_url")
        if not rationale:
            errors.append(f"{identifier}: missing adjudication rationale")

    if errors:
        raise ValueError("Adjudication validation failed:\n- " + "\n- ".join(errors))

    final_sources: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    for row in source_rows:
        result = dict(row)
        if truthy(row["needs_adjudication"]):
            decision = source_by_id[row["evidence_id"]]
            result["final_status"] = text(decision["final_status"])
            result["final_stance"] = text(decision["final_stance"])
            result["adjudication_rationale"] = text(decision["adjudication_rationale"])
            result["decision_source"] = "adjudication"
            audit.append({
                "record_type": "source",
                "record_id": row["evidence_id"],
                "case_id": row["case_id"],
                "annotator_a": f"{row['annotator_a_status']} / {row['annotator_a_stance']}",
                "annotator_b": f"{row['annotator_b_status']} / {row['annotator_b_stance']}",
                "final_decision": f"{result['final_status']} / {result['final_stance']}",
                "rationale": result["adjudication_rationale"],
            })
        else:
            consensus_stance = text(row["consensus_stance"])
            if consensus_stance:
                result["final_status"] = "evaluable"
                result["final_stance"] = consensus_stance
            else:
                status_a = text(row["annotator_a_status"])
                status_b = text(row["annotator_b_status"])
                if status_a != status_b:
                    raise ValueError(f"{row['evidence_id']}: no adjudication despite status disagreement")
                result["final_status"] = status_a
                result["final_stance"] = ""
            result["adjudication_rationale"] = ""
            result["decision_source"] = "exact_consensus"
        result["model_matches_final"] = text(result["model_stance"]) == text(result["final_stance"])
        final_sources.append(result)

    final_coverage: list[dict[str, Any]] = []
    for row in coverage_rows:
        result = dict(row)
        if truthy(row["needs_adjudication"]):
            decision = coverage_by_id[row["case_id"]]
            result["final_coverage"] = text(decision["final_coverage"])
            result["final_missing"] = text(decision["final_missing"])
            result["final_missing_url"] = text(decision["final_missing_url"])
            result["adjudication_rationale"] = text(decision["adjudication_rationale"])
            result["decision_source"] = "adjudication"
            audit.append({
                "record_type": "coverage",
                "record_id": row["case_id"],
                "case_id": row["case_id"],
                "annotator_a": f"{row['annotator_a_coverage']} / missing={row['annotator_a_missing']}",
                "annotator_b": f"{row['annotator_b_coverage']} / missing={row['annotator_b_missing']}",
                "final_decision": f"{result['final_coverage']} / missing={result['final_missing']}",
                "rationale": result["adjudication_rationale"],
            })
        else:
            result["final_coverage"] = text(row["consensus_coverage"])
            result["final_missing"] = text(row["consensus_missing"])
            urls = [text(row.get("annotator_a_missing_url")), text(row.get("annotator_b_missing_url"))]
            result["final_missing_url"] = next((url for url in urls if url), "")
            result["adjudication_rationale"] = ""
            result["decision_source"] = "exact_consensus"
        final_coverage.append(result)

    return final_sources, final_coverage, audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adjudication", type=Path, required=True)
    parser.add_argument("--pre-results-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--registered-criteria",
        action="store_true",
        help="Evaluate the five criteria registered before the analyzed run.",
    )
    parser.add_argument(
        "--preregistered-v4",
        action="store_true",
        help="Apply the criteria preregistered for the fresh blind v4 sample.",
    )
    args = parser.parse_args()

    source_rows = read_csv(args.pre_results_dir / "source_comparison.csv")
    coverage_rows = read_csv(args.pre_results_dir / "coverage_comparison.csv")
    source_sheet = read_sheet_records(args.adjudication, "Fuentes")
    coverage_sheet = read_sheet_records(args.adjudication, "Cobertura")
    final_sources, final_coverage, audit = validate_and_apply(
        source_rows, coverage_rows, source_sheet, coverage_sheet
    )

    evaluable = [row for row in final_sources if row["final_status"] == "evaluable"]
    relevant = sum(row["final_stance"] != "unrelated" for row in evaluable)
    status_counts = Counter(row["final_coverage"] for row in final_coverage)
    evidence_exists = [row for row in final_coverage if row["final_coverage"] in {"sufficient", "partial", "none"}]
    useful = [row for row in evidence_exists if row["final_coverage"] in {"sufficient", "partial"}]
    sufficient = [row for row in evidence_exists if row["final_coverage"] == "sufficient"]
    zero_source = [row for row in final_coverage if int(row["returned_source_count"]) == 0]
    correct_empty = [row for row in zero_source if row["final_coverage"] == "no_evidence_found"]
    false_empty = [row for row in zero_source if row["final_coverage"] == "none"]
    retrieval_success = sum(int(row["returned_source_count"]) > 0 for row in final_coverage)
    false_empty_rate = len(false_empty) / len(zero_source) if zero_source else 0.0

    with (args.pre_results_dir / "summary.json").open("r", encoding="utf-8") as handle:
        pre_summary = json.load(handle)

    summary = {
        "analysis_stage": "post_adjudication_final",
        "source_workbook": str(args.adjudication.resolve()),
        "source_pairs": len(final_sources),
        "coverage_cases": len(final_coverage),
        "adjudicated_source_n": sum(row["decision_source"] == "adjudication" for row in final_sources),
        "adjudicated_coverage_n": sum(row["decision_source"] == "adjudication" for row in final_coverage),
        "interannotator_agreement_pre_adjudication": {
            "source_agreement": pre_summary["source_agreement"],
            "coverage_agreement": pre_summary["coverage_agreement"],
        },
        "retrieval_source_quality_final": {
            "evaluable_n": len(evaluable),
            "relevant_n": relevant,
            "precision": relevant / len(evaluable) if evaluable else 0.0,
            "precision_wilson_95": wilson(relevant, len(evaluable)),
        },
        "system_stance_final": classification_metrics(evaluable),
        "coverage_final": {
            "status_counts": dict(status_counts),
            "evidence_exists_n": len(evidence_exists),
            "useful_coverage_n": len(useful),
            "useful_coverage_rate": len(useful) / len(evidence_exists) if evidence_exists else 0.0,
            "sufficient_coverage_n": len(sufficient),
            "sufficient_coverage_rate": len(sufficient) / len(evidence_exists) if evidence_exists else 0.0,
            "zero_source_n": len(zero_source),
            "correct_empty_n": len(correct_empty),
            "false_empty_n": len(false_empty),
            "missing_yes_n": sum(row["final_missing"] == "yes" for row in final_coverage),
        },
        "system_run": {
            "retrieval_success_n": retrieval_success,
            "retrieval_success_rate": retrieval_success / len(final_coverage),
            "retrieval_success_wilson_95": wilson(retrieval_success, len(final_coverage)),
        },
        "false_empty_rate": false_empty_rate,
    }
    if args.registered_criteria or args.preregistered_v4:
        summary["registered_criteria"] = {
            "retrieval_at_least_16_of_20": {
                "threshold": 16 / 20,
                "observed": retrieval_success / len(final_coverage),
                "passed": retrieval_success >= 16,
            },
            "useful_coverage_at_least_80_percent": {
                "threshold": 0.80,
                "observed": len(useful) / len(evidence_exists) if evidence_exists else 0.0,
                "passed": bool(evidence_exists) and len(useful) / len(evidence_exists) >= 0.80,
            },
            "false_empty_rate_at_most_20_percent": {
                "threshold": 0.20,
                "observed": false_empty_rate,
                "passed": false_empty_rate <= 0.20,
            },
            "stance_accuracy_at_least_75_percent": {
                "threshold": 0.75,
                "observed": summary["system_stance_final"]["accuracy"],
                "passed": summary["system_stance_final"]["accuracy"] >= 0.75,
            },
            "source_precision_at_least_90_percent": {
                "threshold": 0.90,
                "observed": summary["retrieval_source_quality_final"]["precision"],
                "passed": summary["retrieval_source_quality_final"]["precision"] >= 0.90,
            },
        }
        summary["overall_passed"] = all(
            criterion["passed"] for criterion in summary["registered_criteria"].values()
        )
        summary["limitations"] = [
            "Fresh frozen blind sample of 20 stratified cases; results do not estimate natural feed prevalence.",
            "The five decision criteria were fixed before running and annotating this v4 sample.",
            "The small denominators produce wide uncertainty intervals; results should be replicated on a larger independent sample.",
            "The frozen production snapshot contained no X/social cases.",
            "The final metrics combine exact consensus with explicit adjudication; agreement metrics remain pre-adjudication.",
            "Macro-F1 over four fixed classes is depressed when a gold class is absent; observed-class macro-F1 is also reported.",
        ]
    else:
        summary["limitations"] = [
            "Small stratified pilot; results do not estimate natural feed prevalence.",
            "The frozen production snapshot contained no X/social cases.",
            "No pass/fail threshold was preregistered before this run.",
            "The final metrics combine exact consensus with explicit adjudication; agreement metrics remain pre-adjudication.",
            "Macro-F1 over four fixed classes is depressed when a gold class is absent; observed-class macro-F1 is also reported.",
        ]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "final_source_results.csv", final_sources)
    write_csv(args.output_dir / "final_coverage_results.csv", final_coverage)
    write_csv(args.output_dir / "adjudication_audit.csv", audit)
    with (args.output_dir / "final_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
