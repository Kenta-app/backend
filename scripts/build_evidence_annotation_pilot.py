"""Export a reproducible, blind pilot for related-evidence stance annotation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.database import SessionLocal, engine
from app.processed.models import JustificationSource, MlPrediction
from app.serving.models import PublishedNews


LABELS = ("supports", "refutes", "discusses", "unrelated")
BLIND_FIELDS = (
    "order",
    "evidence_id",
    "claim",
    "source_name",
    "source_title",
    "evidence_excerpt",
    "source_url",
    "review_status",
    "human_stance",
    "confidence",
    "notes",
)
PRIVATE_FIELDS = (
    "evidence_id",
    "prediction_id",
    "news_id",
    "claim",
    "source_name",
    "source_title",
    "evidence_excerpt",
    "source_url",
    "model_stance",
    "relevance_score",
    "publisher_domain",
    "assessment_method",
    "assessment_version",
)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def evidence_id(prediction_id: int, url: str, claim: str) -> str:
    seed = f"{prediction_id}|{url.strip().casefold()}|{clean(claim).casefold()}"
    return f"ev_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def select_balanced(rows: list[dict[str, str]], sample_size: int, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    deduplicated: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (clean(row["claim"]).casefold(), clean(row["publisher_domain"]).casefold())
        if key[0] and key[1] and key not in deduplicated:
            deduplicated[key] = row

    by_label: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in deduplicated.values():
        if row["model_stance"] in LABELS:
            by_label[row["model_stance"]].append(row)
    for candidates in by_label.values():
        rng.shuffle(candidates)

    target_per_label = sample_size // len(LABELS)
    selected: list[dict[str, str]] = []
    selected_ids: set[str] = set()
    for label in LABELS:
        for row in by_label[label][:target_per_label]:
            selected.append(row)
            selected_ids.add(row["evidence_id"])

    remaining = [row for row in deduplicated.values() if row["evidence_id"] not in selected_ids]
    rng.shuffle(remaining)
    selected.extend(remaining[: max(0, sample_size - len(selected))])
    rng.shuffle(selected)
    return selected


def write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("output/evidence_annotation_pilot"))
    parser.add_argument("--sample-size", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument(
        "--include-legacy",
        action="store_true",
        help="Include legacy and cluster sources, which are normally excluded from model evaluation.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.sample_size < 4:
        raise SystemExit("--sample-size must be at least 4")
    inspector = inspect(engine)
    if not inspector.has_table("justification_sources", schema="processed"):
        raise SystemExit(
            "processed.justification_sources does not exist. Run the migration and regenerate evidence first."
        )
    required_columns = {
        "claim",
        "evidence_stance",
        "relevance_score",
        "independence_key",
        "assessment_method",
        "assessment_version",
    }
    current_columns = {
        column["name"]
        for column in inspector.get_columns("justification_sources", schema="processed")
    }
    missing_columns = sorted(required_columns - current_columns)
    if missing_columns:
        raise SystemExit(
            "Evidence migration is pending; missing columns: "
            + ", ".join(missing_columns)
            + ". Run scripts/migrate_evidence_assessment.py before exporting the pilot."
        )

    db = SessionLocal()
    try:
        query = (
            db.query(JustificationSource, MlPrediction, PublishedNews)
            .join(MlPrediction, MlPrediction.prediction_id == JustificationSource.prediction_id)
            .outerjoin(
                PublishedNews,
                PublishedNews.representative_news_processed_id
                == MlPrediction.representative_news_processed_id,
            )
        )
        if not args.include_legacy:
            query = query.filter(
                JustificationSource.assessment_method == "gemini_grounded_explicit_label"
            )
        records = query.order_by(JustificationSource.justification_source_id).all()
    finally:
        db.close()

    candidates: list[dict[str, str]] = []
    for source, prediction, news in records:
        claim = clean(source.claim or (news.title if news else ""))
        url = clean(source.url)
        if not claim or not url:
            continue
        candidates.append({
            "evidence_id": evidence_id(prediction.prediction_id, url, claim),
            "prediction_id": str(prediction.prediction_id),
            "news_id": str(news.news_id if news else ""),
            "claim": claim,
            "source_name": clean(source.source),
            "source_title": clean(source.title),
            "evidence_excerpt": clean(source.excerpt),
            "source_url": url,
            "model_stance": clean(source.evidence_stance).casefold(),
            "relevance_score": (
                f"{float(source.relevance_score):.4f}"
                if source.relevance_score is not None
                else ""
            ),
            "publisher_domain": clean(source.independence_key),
            "assessment_method": clean(source.assessment_method),
            "assessment_version": clean(source.assessment_version),
        })

    selected = select_balanced(candidates, args.sample_size, args.seed)
    if not selected:
        raise SystemExit(
            "No eligible grounded evidence found. Regenerate related sources with the current policy first."
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    private_path = args.output_dir / "evidence_model_key.csv"
    write_csv(private_path, PRIVATE_FIELDS, selected)

    blind_paths: dict[str, Path] = {}
    for index, annotator in enumerate(("a", "b"), start=1):
        ordered = selected.copy()
        random.Random(args.seed + index).shuffle(ordered)
        blind_rows = []
        for order, row in enumerate(ordered, start=1):
            blind_rows.append({
                **row,
                "order": str(order),
                "review_status": "",
                "human_stance": "",
                "confidence": "",
                "notes": "",
            })
        path = args.output_dir / f"evidence_annotations_{annotator}.csv"
        write_csv(path, BLIND_FIELDS, blind_rows)
        blind_paths[annotator] = path

    available_counts = Counter(row["model_stance"] for row in candidates)
    selected_counts = Counter(row["model_stance"] for row in selected)
    manifest = {
        "protocol_version": "evidence-annotation-2026-10-21-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
        "requested_sample_size": args.sample_size,
        "selected_sample_size": len(selected),
        "eligible_candidates": len(candidates),
        "available_model_strata": {label: available_counts[label] for label in LABELS},
        "selected_model_strata": {label: selected_counts[label] for label in LABELS},
        "sampling_unit": "one claim per publisher domain",
        "blind_fields_exclude_model_stance": True,
        "files": {
            "private_key": {"path": str(private_path), "sha256": file_sha256(private_path)},
            **{
                f"annotator_{name}": {"path": str(path), "sha256": file_sha256(path)}
                for name, path in blind_paths.items()
            },
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
