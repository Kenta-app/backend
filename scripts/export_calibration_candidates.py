"""
Export fake-news calibration candidates from the project database.

Typical usage:
    python scripts/export_calibration_candidates.py --output data/calibration_candidates.csv --limit 100 --min-fake-score 0.6
    python scripts/export_calibration_candidates.py --output data/source3_candidates.csv --source-id 3 --limit 50
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.database import SessionLocal
from app.ml.pipeline import news_analysis_pipeline
from app.processed.models import MlPrediction, ProcessedNews
from app.raw.models import RawNews, Source
from app.serving.models import PublishedNews


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export calibration candidates from the DB.")
    parser.add_argument("--output", required=True, help="Destination CSV path.")
    parser.add_argument(
        "--source-id",
        type=int,
        nargs="+",
        help="Optional source_id filter.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum number of rows to export. Use 0 for all.",
    )
    parser.add_argument(
        "--min-fake-score",
        type=float,
        default=0.0,
        help="Minimum stored fake_score to include.",
    )
    parser.add_argument(
        "--max-fake-score",
        type=float,
        default=1.0,
        help="Maximum stored fake_score to include.",
    )
    parser.add_argument(
        "--all-processed",
        action="store_true",
        help="Export processed rows even if they are not published.",
    )
    parser.add_argument(
        "--reanalyze",
        action="store_true",
        help="Run the current fake-news pipeline and export live claim analysis fields.",
    )
    return parser


def fetch_rows(db, args: argparse.Namespace):
    query = (
        db.query(ProcessedNews, RawNews, Source, MlPrediction, PublishedNews)
        .join(RawNews, RawNews.news_raw_id == ProcessedNews.news_raw_id)
        .join(Source, Source.source_id == ProcessedNews.source_id)
        .join(
            MlPrediction,
            MlPrediction.representative_news_processed_id == ProcessedNews.news_processed_id,
        )
        .outerjoin(
            PublishedNews,
            PublishedNews.representative_news_processed_id == ProcessedNews.news_processed_id,
        )
        .filter(MlPrediction.fake_score >= args.min_fake_score)
        .filter(MlPrediction.fake_score <= args.max_fake_score)
        .filter(ProcessedNews.clean_text.isnot(None))
    )

    if not args.all_processed:
        query = query.filter(PublishedNews.published_at.isnot(None))

    if args.source_id:
        query = query.filter(ProcessedNews.source_id.in_(args.source_id))

    query = query.order_by(
        MlPrediction.fake_score.desc(),
        PublishedNews.published_at.desc(),
        ProcessedNews.news_processed_id.desc(),
    )

    return query.all() if args.limit == 0 else query.limit(args.limit).all()


def analyze_record(title: str | None, content: str | None) -> dict:
    try:
        return news_analysis_pipeline.analyze_news(
            title=title,
            content=content,
            include_summary=False,
            allow_partial=True,
        )
    except Exception as exc:
        return {"error": str(exc)}


def first_claim(result: dict) -> dict | None:
    claims = ((result.get("fake_news") or {}).get("claims") or {}).get("items") or []
    return claims[0] if claims else None


def row_to_csv(row, args: argparse.Namespace) -> dict[str, str]:
    processed, raw_news, source, prediction, published = row
    result = analyze_record(raw_news.title_raw, processed.clean_text) if args.reanalyze else {}
    fake_news = result.get("fake_news") or {}
    claim = first_claim(result or {})
    claim_prediction = (claim or {}).get("prediction") or {}
    claim_probabilities = claim_prediction.get("probabilities") or {}

    warnings = " | ".join(result.get("warnings") or []) if result else ""
    error = result.get("error", "") if result else ""

    return {
        "representative_id": str(processed.news_processed_id),
        "news_id": str(published.news_id) if published else "",
        "source_id": str(processed.source_id),
        "source_name": source.name if source else "",
        "published_at": published.published_at.isoformat() if published and published.published_at else "",
        "title": raw_news.title_raw or "",
        "original_url": raw_news.original_url or "",
        "stored_fake_score": f"{float(prediction.fake_score):.4f}",
        "stored_sentiment_label": prediction.sentiment_label or "",
        "analysis_risk_score": (
            f"{float(fake_news.get('risk_score')):.4f}"
            if fake_news.get("risk_score") is not None
            else ""
        ),
        "analysis_triage_label": fake_news.get("triage_label") or "",
        "analysis_triage_display": fake_news.get("triage_display") or "",
        "analysis_fake_label": fake_news.get("label") or "",
        "analysis_claim_based": str(bool(fake_news.get("claim_based"))) if fake_news else "",
        "top_claim_text": (claim or {}).get("text") or "",
        "top_claim_target": (claim or {}).get("stance_target") or "",
        "top_claim_model_input": (claim or {}).get("model_input") or "",
        "top_claim_mode": (claim or {}).get("extraction_mode") or "",
        "top_claim_quality": (claim or {}).get("quality") or "",
        "top_claim_quality_reasons": " | ".join((claim or {}).get("quality_reasons") or []),
        "top_claim_label": claim_prediction.get("label") or "",
        "top_claim_p_false": (
            f"{float(claim_probabilities.get('False')):.4f}"
            if claim_probabilities.get("False") is not None
            else ""
        ),
        "warnings": warnings,
        "error": error,
        "manual_gold": "",
        "notes": "",
    }


def write_csv(path: str, rows: list[dict[str, str]]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "representative_id",
        "news_id",
        "source_id",
        "source_name",
        "published_at",
        "title",
        "original_url",
        "stored_fake_score",
        "stored_sentiment_label",
        "analysis_risk_score",
        "analysis_triage_label",
        "analysis_triage_display",
        "analysis_fake_label",
        "analysis_claim_based",
        "top_claim_text",
        "top_claim_target",
        "top_claim_model_input",
        "top_claim_mode",
        "top_claim_quality",
        "top_claim_quality_reasons",
        "top_claim_label",
        "top_claim_p_false",
        "warnings",
        "error",
        "manual_gold",
        "notes",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        fetch_args = argparse.Namespace(**vars(args))
        if args.reanalyze and args.limit > 0:
            fetch_args.limit = args.limit * 5

        rows = fetch_rows(db, fetch_args)
        if not rows:
            print("No matching rows were found.")
            return 1

        exported_rows: list[dict[str, str]] = []
        skipped_without_claim = 0
        for row in rows:
            csv_row = row_to_csv(row, args)
            if args.reanalyze and not csv_row["top_claim_model_input"]:
                skipped_without_claim += 1
                continue
            exported_rows.append(csv_row)
            if args.limit > 0 and len(exported_rows) >= args.limit:
                break

        if not exported_rows:
            print("No rows with extracted claims were found.")
            return 1

        write_csv(args.output, exported_rows)
        suffix = f" (skipped {skipped_without_claim} rows without claims)" if skipped_without_claim else ""
        print(f"Exported {len(exported_rows)} rows to {args.output}{suffix}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
