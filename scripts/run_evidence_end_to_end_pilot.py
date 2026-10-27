"""Freeze and run a non-persistent end-to-end evidence retrieval pilot.

The script has two explicit phases so that the evaluation sample is written and
hashed before Gemini is called:

    python scripts/run_evidence_end_to_end_pilot.py freeze
    python scripts/run_evidence_end_to_end_pilot.py run

The run phase calls the same private generation path used by the application,
but deliberately does not call ``persist_sources`` or commit a database write.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application_services.justification_service import GeminiJustificationService
from app.db.database import SessionLocal
from app.evidence_assessment import ASSESSMENT_VERSION
from app.processed.models import ClusterMember, JustificationSource, MlPrediction, ProcessedNews
from app.raw.models import RawNews, Source
from app.serving.models import PublishedNews


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "evidence_end_to_end_2026_10_24"
DEFAULT_SEED = 20261024
DEFAULT_PROTOCOL = "evidence-end-to-end-pilot-v1"
SOURCE_RISK_QUOTAS: dict[str, dict[str, int]] = {
    "El Comercio": {"low": 2, "medium": 4, "high": 4},
    "RPP Noticias": {"low": 5, "medium": 1, "high": 1},
    "Peru21": {"low": 2, "medium": 0, "high": 1},
}
V4_BLIND_RISK_QUOTAS = {"low": 8, "medium": 8, "high": 4}
V4_BLIND_SOURCE_MINIMUMS = {"RPP Noticias": 3}
PRIOR_EVALUATION_FILES = (
    PROJECT_ROOT / "output" / "evidence_annotation_pilot" / "evidence_model_key.csv",
    PROJECT_ROOT / "output" / "evidence_annotation_targeted_results" / "final_annotations.csv",
    PROJECT_ROOT / "output" / "evidence_confirmatory_challenge05" / "challenge05_evidence_gold.csv",
)


def prior_evaluation_files(exclude_output_dir: Path | None = None) -> list[Path]:
    """List prior evaluation files that can reveal an already seen case."""
    excluded = exclude_output_dir.resolve() if exclude_output_dir else None
    discovered = list(PRIOR_EVALUATION_FILES)
    for path in (PROJECT_ROOT / "output").glob(
        "evidence_end_to_end*/frozen_claim_sample.csv"
    ):
        if excluded is not None and path.parent.resolve() == excluded:
            continue
        discovered.append(path)
    return sorted(set(discovered), key=lambda path: str(path).lower())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def risk_band(score: float) -> str:
    if score < 0.35:
        return "low"
    if score < 0.70:
        return "medium"
    return "high"


def normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_prior_prediction_ids(exclude_output_dir: Path | None = None) -> set[int]:
    prediction_ids: set[int] = set()
    for path in prior_evaluation_files(exclude_output_dir):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if "prediction_id" not in (reader.fieldnames or []):
                continue
            for row in reader:
                value = (row.get("prediction_id") or "").strip()
                if value.isdigit():
                    prediction_ids.add(int(value))
    return prediction_ids


def candidate_rows(db, exclude_output_dir: Path | None = None) -> list[dict[str, Any]]:
    prior_prediction_ids = load_prior_prediction_ids(exclude_output_dir)
    rows = (
        db.query(
            PublishedNews,
            MlPrediction,
            ProcessedNews,
            RawNews,
            Source,
            ClusterMember.cluster_id,
        )
        .join(
            MlPrediction,
            MlPrediction.representative_news_processed_id
            == PublishedNews.representative_news_processed_id,
        )
        .join(
            ProcessedNews,
            ProcessedNews.news_processed_id
            == PublishedNews.representative_news_processed_id,
        )
        .join(RawNews, RawNews.news_raw_id == ProcessedNews.news_raw_id)
        .join(Source, Source.source_id == PublishedNews.source_id)
        .outerjoin(
            ClusterMember,
            ClusterMember.news_processed_id == ProcessedNews.news_processed_id,
        )
        .outerjoin(
            JustificationSource,
            JustificationSource.prediction_id == MlPrediction.prediction_id,
        )
        .filter(
            JustificationSource.justification_source_id.is_(None),
            Source.type == "web",
            RawNews.content_raw.isnot(None),
            func.length(func.trim(RawNews.content_raw)) >= 80,
        )
        .all()
    )

    candidates: list[dict[str, Any]] = []
    for published, prediction, processed, raw, source, cluster_id in rows:
        if prediction.prediction_id in prior_prediction_ids:
            continue
        score = float(prediction.fake_score)
        title = normalize_text(raw.title_raw or published.title)
        claim = GeminiJustificationService._central_claim(raw, processed)
        candidates.append(
            {
                "prediction_id": prediction.prediction_id,
                "news_id": published.news_id,
                "news_processed_id": processed.news_processed_id,
                "news_raw_id": raw.news_raw_id,
                "cluster_id": cluster_id,
                "group_key": f"cluster:{cluster_id}" if cluster_id else f"prediction:{prediction.prediction_id}",
                "original_source": source.name,
                "source_type": source.type,
                "platform": raw.platform,
                "content_type": published.content_type,
                "title": title,
                "claim": normalize_text(claim),
                "publication_context": normalize_text(raw.content_raw)[:1800],
                "original_url": raw.original_url,
                "source_published_at": raw.published_at.isoformat() if raw.published_at else "",
                "fake_score": score,
                "risk_band": risk_band(score),
            }
        )
    return candidates


def stratified_sample(candidates: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    used_groups: set[str] = set()

    for source_name, risk_quotas in SOURCE_RISK_QUOTAS.items():
        for band, quota in risk_quotas.items():
            pool = [
                row
                for row in candidates
                if row["original_source"] == source_name and row["risk_band"] == band
            ]
            rng.shuffle(pool)
            picked = []
            for row in pool:
                if row["group_key"] in used_groups:
                    continue
                picked.append(row)
                used_groups.add(row["group_key"])
                if len(picked) == quota:
                    break
            if len(picked) != quota:
                raise RuntimeError(
                    f"Insufficient candidates for {source_name}/{band}: "
                    f"required={quota}, available_unique={len(picked)}"
                )
            selected.extend(picked)

    rng.shuffle(selected)
    for index, row in enumerate(selected, start=1):
        row["case_id"] = f"E2E-{index:03d}"
    return selected


def stratified_v4_blind_sample(
    candidates: list[dict[str, Any]], seed: int
) -> list[dict[str, Any]]:
    """Select a fresh challenge sample when earlier rounds exhausted strata.

    The risk quotas remain fixed before retrieval. A small source minimum keeps
    all still-eligible RPP cases, while the remaining positions are sampled
    within risk bands without relaxing the one-case-per-cluster rule.
    """
    rng = random.Random(seed)
    selected: list[dict[str, Any]] = []
    used_groups: set[str] = set()
    remaining_risk = dict(V4_BLIND_RISK_QUOTAS)

    def add(row: dict[str, Any]) -> None:
        selected.append(row)
        used_groups.add(row["group_key"])
        remaining_risk[row["risk_band"]] -= 1

    for source_name, minimum in V4_BLIND_SOURCE_MINIMUMS.items():
        pool = [row for row in candidates if row["original_source"] == source_name]
        rng.shuffle(pool)
        picked = 0
        for row in pool:
            if row["group_key"] in used_groups or remaining_risk[row["risk_band"]] <= 0:
                continue
            add(row)
            picked += 1
            if picked == minimum:
                break
        if picked != minimum:
            raise RuntimeError(
                f"Insufficient fresh candidates for {source_name}: "
                f"required={minimum}, available={picked}"
            )

    for band in ("high", "medium", "low"):
        pool = [row for row in candidates if row["risk_band"] == band]
        rng.shuffle(pool)
        required = remaining_risk[band]
        if required == 0:
            continue
        picked = 0
        for row in pool:
            if row["group_key"] in used_groups:
                continue
            add(row)
            picked += 1
            if picked == required:
                break
        if picked != required:
            raise RuntimeError(
                f"Insufficient fresh candidates for risk={band}: "
                f"required={required}, available={picked}"
            )

    rng.shuffle(selected)
    for index, row in enumerate(selected, start=1):
        row["case_id"] = f"V4-{index:03d}"
    return selected


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def freeze_sample(
    output_dir: Path,
    seed: int,
    protocol: str,
    sampling_design: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    frozen_path = output_dir / "frozen_claim_sample.csv"
    manifest_path = output_dir / "selection_manifest.json"
    if frozen_path.exists() or manifest_path.exists():
        raise RuntimeError(
            f"Frozen sample already exists in {output_dir}. Refusing to resample."
        )

    db = SessionLocal()
    try:
        candidates = candidate_rows(db, output_dir)
        if sampling_design == "v4-blind":
            selected = stratified_v4_blind_sample(candidates, seed)
        else:
            selected = stratified_sample(candidates, seed)
        persisted_before = db.query(JustificationSource).count()
    finally:
        db.close()

    fields = [
        "case_id",
        "prediction_id",
        "news_id",
        "news_processed_id",
        "news_raw_id",
        "cluster_id",
        "group_key",
        "original_source",
        "source_type",
        "platform",
        "content_type",
        "title",
        "claim",
        "publication_context",
        "original_url",
        "source_published_at",
        "fake_score",
        "risk_band",
    ]
    write_csv(frozen_path, selected, fields)
    manifest = {
        "protocol": protocol,
        "phase": "frozen_before_retrieval",
        "frozen_at_utc": utc_now(),
        "seed": seed,
        "candidate_count": len(candidates),
        "sample_size": len(selected),
        "sampling_unit": "one representative publication; at most one per existing cluster",
        "sampling_design": sampling_design,
        "source_risk_quotas": (
            SOURCE_RISK_QUOTAS if sampling_design == "legacy-source-risk" else None
        ),
        "risk_quotas": V4_BLIND_RISK_QUOTAS if sampling_design == "v4-blind" else None,
        "source_minimums": (
            V4_BLIND_SOURCE_MINIMUMS if sampling_design == "v4-blind" else None
        ),
        "sample_source_counts": dict(Counter(row["original_source"] for row in selected)),
        "sample_risk_counts": dict(Counter(row["risk_band"] for row in selected)),
        "exclusions": [
            "predictions with persisted justification sources",
            "prediction ids present in prior evidence-development files",
            "non-web sources",
            "content shorter than 80 characters",
        ],
        "scope_limitation": (
            "The production snapshot contained no social/X records; this pilot therefore "
            "evaluates the web-publication path only."
        ),
        "persisted_source_rows_before": persisted_before,
        "frozen_sample_sha256": sha256_file(frozen_path),
        "prior_evaluation_files_checked": [
            str(path) for path in prior_evaluation_files(output_dir) if path.exists()
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def read_frozen_sample(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_blind_annotation_csvs(
    output_dir: Path,
    source_rows: list[dict[str, Any]],
    coverage_rows: list[dict[str, Any]],
) -> None:
    source_fields = [
        "order", "evidence_id", "case_id", "claim", "original_source",
        "source_name", "source_title", "evidence_excerpt",
        "source_url", "review_status", "human_stance", "confidence", "notes",
    ]
    coverage_fields = [
        "order", "case_id", "claim", "publication_context", "original_source",
        "original_url", "returned_source_count", "coverage_status",
        "missing_relevant_evidence", "missing_source_url", "notes",
    ]
    for annotator, seed in (("a", 20261025), ("b", 20261026)):
        rng = random.Random(seed)
        blind_sources = [
            {
                **{field: row.get(field, "") for field in source_fields},
                "review_status": "",
                "human_stance": "",
                "confidence": "",
                "notes": "",
            }
            for row in source_rows
        ]
        rng.shuffle(blind_sources)
        for order, row in enumerate(blind_sources, start=1):
            row["order"] = order

        blind_coverage = [
            {
                **{field: row.get(field, "") for field in coverage_fields},
                "coverage_status": "",
                "missing_relevant_evidence": "",
                "missing_source_url": "",
                "notes": "",
            }
            for row in coverage_rows
        ]
        rng.shuffle(blind_coverage)
        for order, row in enumerate(blind_coverage, start=1):
            row["order"] = order

        write_csv(
            output_dir / f"annotator_{annotator}_sources.csv",
            blind_sources,
            source_fields,
        )
        write_csv(
            output_dir / f"annotator_{annotator}_coverage.csv",
            blind_coverage,
            coverage_fields,
        )


def completed_case_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            completed.add(str(json.loads(line)["case_id"]))
    return completed


def run_retrieval(output_dir: Path) -> None:
    frozen_path = output_dir / "frozen_claim_sample.csv"
    manifest_path = output_dir / "selection_manifest.json"
    run_path = output_dir / "retrieval_run.jsonl"
    if not frozen_path.exists() or not manifest_path.exists():
        raise RuntimeError("Freeze the sample before running retrieval.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_hash = sha256_file(frozen_path)
    if actual_hash != manifest["frozen_sample_sha256"]:
        raise RuntimeError("Frozen sample hash mismatch; refusing to run.")

    frozen_rows = read_frozen_sample(frozen_path)
    done = completed_case_ids(run_path)
    db = SessionLocal()
    service = GeminiJustificationService(db=db)
    try:
        persisted_before = db.query(JustificationSource).count()
        for index, row in enumerate(frozen_rows, start=1):
            case_id = row["case_id"]
            if case_id in done:
                print(f"[{index}/{len(frozen_rows)}] {case_id}: already completed")
                continue

            prediction = db.query(MlPrediction).filter_by(
                prediction_id=int(row["prediction_id"])
            ).one()
            processed = db.query(ProcessedNews).filter_by(
                news_processed_id=int(row["news_processed_id"])
            ).one()
            raw = db.query(RawNews).filter_by(news_raw_id=int(row["news_raw_id"])).one()

            start = time.perf_counter()
            error = None
            sources: list[dict[str, Any]] = []
            try:
                report = service._generate_with_retries(prediction, processed, raw)
                sources = report.get("sources", [])
                status = "success" if sources else "no_sources"
            except Exception as exc:  # Keep the frozen case and record operational failure.
                status = "error"
                error = f"{type(exc).__name__}: {exc}"
            elapsed = round(time.perf_counter() - start, 3)
            payload = {
                "case_id": case_id,
                "prediction_id": prediction.prediction_id,
                "status": status,
                "error": error,
                "elapsed_seconds": elapsed,
                "model": service.model_name,
                "assessment_version": ASSESSMENT_VERSION,
                "search_policy_version": service.SEARCH_POLICY_VERSION,
                "source_count": len(sources),
                "sources": sources,
                "completed_at_utc": utc_now(),
            }
            append_jsonl(run_path, payload)
            print(
                f"[{index}/{len(frozen_rows)}] {case_id}: "
                f"status={status} sources={len(sources)} elapsed={elapsed}s",
                flush=True,
            )

        persisted_after = db.query(JustificationSource).count()
        if persisted_after != persisted_before:
            raise RuntimeError(
                "Non-persistence invariant failed: justification source row count changed."
            )
    finally:
        db.rollback()
        db.close()

    results = [json.loads(line) for line in run_path.read_text(encoding="utf-8").splitlines() if line]
    result_by_case = {row["case_id"]: row for row in results}
    source_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for frozen in frozen_rows:
        result = result_by_case[frozen["case_id"]]
        coverage_rows.append(
            {
                "case_id": frozen["case_id"],
                "claim": frozen["claim"],
                "publication_context": frozen["publication_context"],
                "original_source": frozen["original_source"],
                "original_url": frozen["original_url"],
                "retrieval_status": result["status"],
                "returned_source_count": result["source_count"],
            }
        )
        for source_index, source in enumerate(result["sources"], start=1):
            source_rows.append(
                {
                    "evidence_id": f"{frozen['case_id']}-S{source_index:02d}",
                    "case_id": frozen["case_id"],
                    "claim": frozen["claim"],
                    "publication_context": frozen["publication_context"],
                    "original_source": frozen["original_source"],
                    "original_url": frozen["original_url"],
                    "source_name": source.get("source", ""),
                    "source_title": source.get("title", ""),
                    "evidence_excerpt": source.get("excerpt", ""),
                    "source_url": source.get("url", ""),
                    "model_stance": source.get("evidenceStance", ""),
                    "assessment_method": source.get("assessmentMethod", ""),
                    "assessment_version": source.get("assessmentVersion", ""),
                    "independence_key": source.get("independenceKey", ""),
                }
            )

    write_csv(
        output_dir / "evidence_annotation_key.csv",
        source_rows,
        [
            "evidence_id", "case_id", "claim", "publication_context",
            "original_source", "original_url", "source_name", "source_title",
            "evidence_excerpt", "source_url", "model_stance", "assessment_method",
            "assessment_version", "independence_key",
        ],
    )
    write_csv(
        output_dir / "coverage_annotation_key.csv",
        coverage_rows,
        [
            "case_id", "claim", "publication_context", "original_source",
            "original_url", "retrieval_status", "returned_source_count",
        ],
    )
    write_blind_annotation_csvs(output_dir, source_rows, coverage_rows)

    completed_times = [datetime.fromisoformat(row["completed_at_utc"]) for row in results]
    inferred_starts = [
        completed - timedelta(seconds=float(row["elapsed_seconds"]))
        for completed, row in zip(completed_times, results)
    ]
    started_at = min(inferred_starts).isoformat()
    finished_at = max(completed_times).isoformat()
    summary = {
        "protocol": manifest["protocol"],
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "frozen_sample_sha256": actual_hash,
        "model": service.model_name,
        "assessment_version": ASSESSMENT_VERSION,
        "search_policy_version": service.SEARCH_POLICY_VERSION,
        "case_count": len(frozen_rows),
        "cases_with_sources": sum(row["source_count"] > 0 for row in results),
        "cases_without_sources": sum(row["status"] == "no_sources" for row in results),
        "cases_with_errors": sum(row["status"] == "error" for row in results),
        "evidence_row_count": len(source_rows),
        "system_stance_counts": dict(Counter(row["model_stance"] for row in source_rows)),
        "persisted_source_rows_before": persisted_before,
        "persisted_source_rows_after": persisted_after,
        "production_database_modified": False,
        "human_evaluation_pending": True,
    }
    (output_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    parser.add_argument(
        "--sampling-design",
        choices=("legacy-source-risk", "v4-blind"),
        default="legacy-source-risk",
    )
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if args.phase == "freeze":
        freeze_sample(
            output_dir,
            args.seed,
            args.protocol,
            args.sampling_design,
        )
    else:
        run_retrieval(output_dir)


if __name__ == "__main__":
    main()
