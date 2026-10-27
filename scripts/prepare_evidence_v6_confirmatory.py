"""Audit and freeze a fresh, blind end-to-end evidence evaluation sample.

The ``audit`` phase is read-only and reports whether the current database can
support the preregistered sample. The ``freeze`` phase refuses to create a
sample unless every composition constraint is satisfied. Retrieval is a
separate, resumable phase handled by ``run_evidence_end_to_end_pilot.py run``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application_services.justification_service import GeminiJustificationService
from app.application_services.preprocessing_service import PreprocessingService
from app.db.database import SessionLocal
from app.evidence_assessment import ASSESSMENT_VERSION
from app.processed.models import ClusterMember, JustificationSource, MlPrediction, ProcessedNews
from app.raw.models import RawNews, Source
from app.serving.models import PublishedNews


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output" / "evidence_confirmatory_v6_2026_10_26"
DEFAULT_PROTOCOL = "evidence-end-to-end-v6-confirmatory-v1"
DEFAULT_SEED = 20261026
SAMPLE_SIZE = 24
SOCIAL_TARGET = 6
SOCIAL_REFERENCED_MINIMUM = 4
WEB_SOURCE_MINIMUM = 3
DISTINCT_SOURCE_MINIMUM = 4
OFFICIAL_SOURCE_MINIMUM = 2
MAX_PER_SOURCE = 8
RISK_MINIMUMS = {"low": 6, "medium": 6, "high": 4}
OFFICIAL_SOURCES = {"El Peruano", "Agencia Andina"}
SOCIAL_PLATFORMS = {"twitter", "x", "social"}
PREREGISTERED_THRESHOLDS = {
    "returned_content_rate": 0.80,
    "independent_source_precision": 0.90,
    "useful_coverage_rate": 0.80,
    "stance_accuracy": 0.75,
    "false_empty_rate_maximum": 0.20,
    "social_context_correct_rate": 0.80,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def risk_band(score: float) -> str:
    if score < 0.35:
        return "low"
    if score < 0.70:
        return "medium"
    return "high"


def prior_evaluation_keys(exclude_dir: Path) -> tuple[set[int], set[str], set[tuple[str, str]]]:
    prediction_ids: set[int] = set()
    claims: set[str] = set()
    claim_urls: set[tuple[str, str]] = set()
    output_root = PROJECT_ROOT / "output"
    for path in output_root.rglob("*.csv"):
        if exclude_dir.resolve() in path.resolve().parents:
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fields = set(reader.fieldnames or [])
                if not fields.intersection({"case_id", "evidence_id", "prediction_id"}):
                    continue
                for row in reader:
                    value = str(row.get("prediction_id") or "").strip()
                    if value.isdigit():
                        prediction_ids.add(int(value))
                    claim = normalize(row.get("claim"))
                    url = normalize(row.get("original_url") or row.get("source_url"))
                    if claim:
                        claims.add(claim)
                        if url:
                            claim_urls.add((claim, url))
        except (OSError, UnicodeError, csv.Error):
            continue
    return prediction_ids, claims, claim_urls


def social_context_summary(raw: RawNews) -> dict[str, Any]:
    context = raw.social_context if isinstance(raw.social_context, dict) else {}
    available = [
        item for item in context.get("references") or []
        if item.get("status") == "available" and normalize(item.get("text"))
    ]
    return {
        "completeness": context.get("completeness") or "none",
        "available_reference_count": len(available),
        "reference_types": sorted({str(item.get("type") or "unknown") for item in available}),
    }


def candidate_rows(db, output_dir: Path) -> list[dict[str, Any]]:
    prior_ids, prior_claims, prior_pairs = prior_evaluation_keys(output_dir)
    rows = (
        db.query(PublishedNews, MlPrediction, ProcessedNews, RawNews, Source, ClusterMember.cluster_id)
        .join(
            MlPrediction,
            MlPrediction.representative_news_processed_id
            == PublishedNews.representative_news_processed_id,
        )
        .join(
            ProcessedNews,
            ProcessedNews.news_processed_id == PublishedNews.representative_news_processed_id,
        )
        .join(RawNews, RawNews.news_raw_id == ProcessedNews.news_raw_id)
        .join(Source, Source.source_id == PublishedNews.source_id)
        .outerjoin(ClusterMember, ClusterMember.news_processed_id == ProcessedNews.news_processed_id)
        .outerjoin(JustificationSource, JustificationSource.prediction_id == MlPrediction.prediction_id)
        .filter(
            JustificationSource.justification_source_id.is_(None),
            Source.type.in_(("web", "social", "twitter")),
            RawNews.content_raw.isnot(None),
            func.length(func.trim(RawNews.content_raw)) >= 20,
        )
        .all()
    )
    preprocessor = PreprocessingService(db)
    candidates: list[dict[str, Any]] = []
    for published, prediction, processed, raw, source, cluster_id in rows:
        platform = normalize(raw.platform)
        is_social = platform in SOCIAL_PLATFORMS or normalize(source.type) in SOCIAL_PLATFORMS
        minimum_length = 20 if is_social else 80
        if len(normalize(raw.content_raw)) < minimum_length:
            continue
        claim = " ".join(GeminiJustificationService._central_claim(raw, processed).split())
        url = " ".join((raw.original_url or "").split())
        key = (normalize(claim), normalize(url))
        if prediction.prediction_id in prior_ids or normalize(claim) in prior_claims or key in prior_pairs:
            continue
        context = social_context_summary(raw)
        score = float(prediction.fake_score)
        candidates.append({
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
            "title": " ".join((raw.title_raw or published.title or "").split()),
            "claim": claim,
            "publication_context": preprocessor._build_raw_text(raw)[:4000],
            "original_url": url,
            "source_published_at": raw.published_at.isoformat() if raw.published_at else "",
            "fake_score": score,
            "risk_band": risk_band(score),
            "is_social": is_social,
            "social_context_completeness": context["completeness"],
            "social_reference_count": context["available_reference_count"],
            "social_reference_types": ",".join(context["reference_types"]),
            "is_official_source": source.name in OFFICIAL_SOURCES,
        })
    return candidates


def readiness(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    unique_groups = len({row["group_key"] for row in candidates})
    social = [row for row in candidates if row["is_social"]]
    web = [row for row in candidates if not row["is_social"]]
    referenced_social = [row for row in social if row["social_reference_count"] > 0]
    official = [row for row in web if row["is_official_source"]]
    web_sources = {row["original_source"] for row in web}
    all_sources = {row["original_source"] for row in candidates}
    risk_counts = Counter(row["risk_band"] for row in candidates)
    checks = {
        "sample_size": unique_groups >= SAMPLE_SIZE,
        "social_cases": len({row["group_key"] for row in social}) >= SOCIAL_TARGET,
        "social_with_reference_context": len({row["group_key"] for row in referenced_social}) >= SOCIAL_REFERENCED_MINIMUM,
        "web_cases": len({row["group_key"] for row in web}) >= SAMPLE_SIZE - SOCIAL_TARGET,
        "distinct_web_sources": len(web_sources) >= WEB_SOURCE_MINIMUM,
        "distinct_all_sources": len(all_sources) >= DISTINCT_SOURCE_MINIMUM,
        "official_source_cases": len({row["group_key"] for row in official}) >= OFFICIAL_SOURCE_MINIMUM,
        **{f"risk_{band}": risk_counts[band] >= minimum for band, minimum in RISK_MINIMUMS.items()},
    }
    return {
        "audited_at_utc": utc_now(),
        "protocol": DEFAULT_PROTOCOL,
        "eligible_candidate_n": len(candidates),
        "eligible_unique_group_n": unique_groups,
        "platform_counts": dict(Counter("social" if row["is_social"] else "web" for row in candidates)),
        "source_counts": dict(Counter(row["original_source"] for row in candidates)),
        "risk_counts": dict(risk_counts),
        "social_reference_context_n": len(referenced_social),
        "official_source_n": len(official),
        "requirements": {
            "sample_size": SAMPLE_SIZE,
            "social_target": SOCIAL_TARGET,
            "social_referenced_minimum": SOCIAL_REFERENCED_MINIMUM,
            "web_source_minimum": WEB_SOURCE_MINIMUM,
            "distinct_source_minimum": DISTINCT_SOURCE_MINIMUM,
            "official_source_minimum": OFFICIAL_SOURCE_MINIMUM,
            "maximum_per_source": MAX_PER_SOURCE,
            "risk_minimums": RISK_MINIMUMS,
        },
        "checks": checks,
        "ready_to_freeze": all(checks.values()),
    }


def selection_is_valid(rows: list[dict[str, Any]]) -> bool:
    if len(rows) != SAMPLE_SIZE or len({row["group_key"] for row in rows}) != SAMPLE_SIZE:
        return False
    social = [row for row in rows if row["is_social"]]
    web = [row for row in rows if not row["is_social"]]
    if len(social) != SOCIAL_TARGET or len(web) != SAMPLE_SIZE - SOCIAL_TARGET:
        return False
    if sum(row["social_reference_count"] > 0 for row in social) < SOCIAL_REFERENCED_MINIMUM:
        return False
    if len({row["original_source"] for row in web}) < WEB_SOURCE_MINIMUM:
        return False
    if len({row["original_source"] for row in rows}) < DISTINCT_SOURCE_MINIMUM:
        return False
    if sum(row["is_official_source"] for row in rows) < OFFICIAL_SOURCE_MINIMUM:
        return False
    if max(Counter(row["original_source"] for row in rows).values()) > MAX_PER_SOURCE:
        return False
    risks = Counter(row["risk_band"] for row in rows)
    return all(risks[band] >= minimum for band, minimum in RISK_MINIMUMS.items())


def select_sample(candidates: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    by_group: dict[str, dict[str, Any]] = {}
    for row in candidates:
        by_group.setdefault(row["group_key"], row)
    unique = list(by_group.values())
    social = [row for row in unique if row["is_social"]]
    web = [row for row in unique if not row["is_social"]]
    for _ in range(100_000):
        chosen = rng.sample(social, SOCIAL_TARGET) + rng.sample(web, SAMPLE_SIZE - SOCIAL_TARGET)
        if selection_is_valid(chosen):
            rng.shuffle(chosen)
            for index, row in enumerate(chosen, start=1):
                row["case_id"] = f"C6-{index:03d}"
            return chosen
    raise RuntimeError("Candidate pool passed marginal checks but no joint sample satisfied all constraints.")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("audit", "freeze"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        candidates = candidate_rows(db, output_dir)
    finally:
        db.close()
    audit = readiness(candidates)
    audit_path = output_dir / "readiness.json"
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    if args.phase == "audit":
        return
    if not audit["ready_to_freeze"]:
        failed = [name for name, passed in audit["checks"].items() if not passed]
        raise SystemExit(f"Sample not frozen. Failed readiness checks: {', '.join(failed)}")

    frozen_path = output_dir / "frozen_claim_sample.csv"
    manifest_path = output_dir / "selection_manifest.json"
    if frozen_path.exists() or manifest_path.exists():
        raise RuntimeError(f"Frozen sample already exists in {output_dir}; refusing to resample.")
    selected = select_sample(candidates, args.seed)
    fields = [
        "case_id", "prediction_id", "news_id", "news_processed_id", "news_raw_id",
        "cluster_id", "group_key", "original_source", "source_type", "platform",
        "content_type", "title", "claim", "publication_context", "original_url",
        "source_published_at", "fake_score", "risk_band", "is_social",
        "social_context_completeness", "social_reference_count", "social_reference_types",
        "is_official_source",
    ]
    write_csv(frozen_path, selected, fields)
    manifest = {
        "protocol": DEFAULT_PROTOCOL,
        "phase": "frozen_before_retrieval",
        "confirmatory": True,
        "frozen_at_utc": utc_now(),
        "seed": args.seed,
        "sample_size": SAMPLE_SIZE,
        "sampling_unit": "one representative publication; at most one per existing cluster",
        "sample_platform_counts": dict(Counter("social" if row["is_social"] else "web" for row in selected)),
        "sample_source_counts": dict(Counter(row["original_source"] for row in selected)),
        "sample_risk_counts": dict(Counter(row["risk_band"] for row in selected)),
        "social_reference_context_n": sum(row["social_reference_count"] > 0 for row in selected),
        "official_source_n": sum(row["is_official_source"] for row in selected),
        "assessment_version": ASSESSMENT_VERSION,
        "preregistered_thresholds": PREREGISTERED_THRESHOLDS,
        "frozen_sample_sha256": sha256_file(frozen_path),
        "development_overlap_rule": "exclude prior prediction_id and normalized prior claim",
        "policy_change_after_unblinding_prohibited": True,
        "readiness_audit": audit,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
