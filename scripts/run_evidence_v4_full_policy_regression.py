"""Replay the frozen 20-case v4 sample under the v3/v5 evidence policies.

This is a resumable, non-persistent development regression. It does not replace
the adjudicated v4 result and is not a confirmatory evaluation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application_services.justification_service import GeminiJustificationService
from app.db.database import SessionLocal
from app.evidence_assessment import ASSESSMENT_VERSION, build_evidence_assessment
from app.processed.models import JustificationSource, MlPrediction, ProcessedNews
from app.raw.models import RawNews
from scripts.run_evidence_end_to_end_pilot import (
    append_jsonl,
    completed_case_ids,
    read_frozen_sample,
    utc_now,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample",
        type=Path,
        default=PROJECT_ROOT / "output/evidence_end_to_end_v4_blind_2026_10_25/frozen_claim_sample.csv",
    )
    parser.add_argument(
        "--baseline-run",
        type=Path,
        default=PROJECT_ROOT / "output/evidence_end_to_end_v4_blind_2026_10_25/retrieval_run.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "output/evidence_v4_full_policy_regression_2026_10_25",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=[],
        help="Optionally replay only selected case IDs; may be repeated.",
    )
    args = parser.parse_args()

    sample = read_frozen_sample(args.sample)
    if len(sample) != 20:
        raise RuntimeError(f"Expected the frozen 20-case v4 sample, got {len(sample)} cases.")
    if args.case_id:
        requested = set(args.case_id)
        sample = [row for row in sample if row["case_id"] in requested]
        found = {row["case_id"] for row in sample}
        if found != requested:
            raise RuntimeError(f"Unknown case IDs: {sorted(requested - found)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output_dir / "retrieval_run.jsonl"
    done = completed_case_ids(checkpoint)

    db = SessionLocal()
    service = GeminiJustificationService(db=db)
    try:
        persisted_before = db.query(JustificationSource).count()
        for index, row in enumerate(sample, start=1):
            case_id = row["case_id"]
            if case_id in done:
                print(f"[{index}/{len(sample)}] {case_id}: already completed", flush=True)
                continue
            prediction = db.query(MlPrediction).filter_by(
                prediction_id=int(row["prediction_id"])
            ).one()
            processed = db.query(ProcessedNews).filter_by(
                news_processed_id=int(row["news_processed_id"])
            ).one()
            raw = db.query(RawNews).filter_by(news_raw_id=int(row["news_raw_id"])).one()

            started = time.perf_counter()
            error = None
            sources = []
            try:
                report = service._generate_with_retries(prediction, processed, raw)
                sources = report.get("sources", [])
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            independent = [
                source for source in sources
                if source.get("assessmentMethod") != "original_publication_context"
            ]
            primary = [
                source for source in sources
                if source.get("assessmentMethod") == "original_publication_context"
            ]
            assessment = build_evidence_assessment(sources)
            violations = []
            if any(source.get("independenceEligible") is not False for source in primary):
                violations.append("primary_context_marked_independent")
            if assessment["status"] in {"supported", "disputed"} and assessment["distinctPublisherSources"] < 2:
                violations.append("aggregate_status_without_two_publishers")
            payload = {
                "case_id": case_id,
                "prediction_id": int(row["prediction_id"]),
                "claim": row["claim"],
                "status": "error" if error else "success",
                "error": error,
                "source_count": len(sources),
                "independent_source_count": len(independent),
                "primary_context_count": len(primary),
                "assessment": assessment,
                "policy_violations": violations,
                "sources": sources,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "model": service.model_name,
                "assessment_version": ASSESSMENT_VERSION,
                "search_policy_version": service.SEARCH_POLICY_VERSION,
                "completed_at_utc": utc_now(),
            }
            append_jsonl(checkpoint, payload)
            print(
                f"[{index}/{len(sample)}] {case_id}: status={payload['status']} "
                f"total={len(sources)} independent={len(independent)} primary={len(primary)}",
                flush=True,
            )

        persisted_after = db.query(JustificationSource).count()
        if persisted_after != persisted_before:
            raise RuntimeError("Non-persistence invariant failed.")
    finally:
        db.rollback()
        db.close()

    results = [
        json.loads(line) for line in checkpoint.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_case = {row["case_id"]: row for row in results}
    expected_cases = {row["case_id"] for row in sample}
    if set(by_case) != expected_cases:
        raise RuntimeError(
            f"Completed case IDs do not match request: expected={sorted(expected_cases)}, "
            f"actual={sorted(by_case)}"
        )

    baseline = [
        json.loads(line) for line in args.baseline_run.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    baseline_by_case = {row["case_id"]: row for row in baseline}
    comparison = []
    for row in sample:
        case_id = row["case_id"]
        old_count = int(baseline_by_case[case_id]["source_count"])
        new = by_case[case_id]
        comparison.append({
            "case_id": case_id,
            "baseline_source_count": old_count,
            "new_source_count": new["source_count"],
            "new_independent_source_count": new["independent_source_count"],
            "new_primary_context_count": new["primary_context_count"],
        })

    summary = {
        "purpose": "full development regression of retrieval v3 and assessment v5",
        "case_count": len(sample),
        "operational_error_n": sum(row["status"] == "error" for row in results),
        "nonempty_case_n": sum(row["source_count"] > 0 for row in results),
        "independent_source_case_n": sum(row["independent_source_count"] > 0 for row in results),
        "primary_context_only_case_n": sum(
            row["primary_context_count"] > 0 and row["independent_source_count"] == 0
            for row in results
        ),
        "total_source_records": sum(row["source_count"] for row in results),
        "total_independent_sources": sum(row["independent_source_count"] for row in results),
        "policy_violation_n": sum(bool(row["policy_violations"]) for row in results),
        "baseline_nonempty_case_n": sum(int(row["source_count"]) > 0 for row in baseline),
        "assessment_version": ASSESSMENT_VERSION,
        "search_policy_version": service.SEARCH_POLICY_VERSION,
        "confirmatory": False,
        "requires_human_review": True,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "comparison.json").write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
