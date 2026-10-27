"""Re-run only the six adjudicated v4 false-empty cases without persistence.

This is a diagnostic regression on a development set, not a confirmatory test.
The JSONL checkpoint makes the command resumable.
"""

from __future__ import annotations

import argparse
import csv
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
        "--diagnosis",
        type=Path,
        default=PROJECT_ROOT / "output/evidence_v4_false_empty_diagnosis_2026_10_25/false_empty_diagnosis.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "output/evidence_v4_false_empty_regression_2026_10_25",
    )
    args = parser.parse_args()

    with args.diagnosis.open("r", encoding="utf-8-sig", newline="") as handle:
        diagnosis = {row["case_id"]: row for row in csv.DictReader(handle)}
    sample = [row for row in read_frozen_sample(args.sample) if row["case_id"] in diagnosis]
    if len(sample) != len(diagnosis):
        raise RuntimeError("The frozen sample does not contain every diagnosed false-empty case.")

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
            report = service._generate_with_retries(prediction, processed, raw)
            sources = report.get("sources", [])
            independent = [
                source for source in sources
                if source.get("assessmentMethod") != "original_publication_context"
            ]
            primary = [
                source for source in sources
                if source.get("assessmentMethod") == "original_publication_context"
            ]
            payload = {
                "case_id": case_id,
                "diagnostic_category": diagnosis[case_id]["category"],
                "source_count": len(sources),
                "independent_source_count": len(independent),
                "primary_context_count": len(primary),
                "assessment": build_evidence_assessment(sources),
                "sources": sources,
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "model": service.model_name,
                "assessment_version": ASSESSMENT_VERSION,
                "search_policy_version": service.SEARCH_POLICY_VERSION,
                "completed_at_utc": utc_now(),
            }
            append_jsonl(checkpoint, payload)
            print(
                f"[{index}/{len(sample)}] {case_id}: total={len(sources)} "
                f"independent={len(independent)} primary={len(primary)}",
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
    independent_target = [row for row in results if row["diagnostic_category"] == "independent_retrieval_miss"]
    summary = {
        "purpose": "diagnostic regression on the six v4 false-empty development cases",
        "case_count": len(results),
        "nonempty_n": sum(row["source_count"] > 0 for row in results),
        "primary_context_recovered_n": sum(row["primary_context_count"] > 0 for row in results),
        "independent_source_recovered_n": sum(row["independent_source_count"] > 0 for row in results),
        "independent_miss_case_passed": bool(independent_target) and all(
            row["independent_source_count"] > 0 for row in independent_target
        ),
        "assessment_version": ASSESSMENT_VERSION,
        "search_policy_version": service.SEARCH_POLICY_VERSION,
        "confirmatory": False,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
