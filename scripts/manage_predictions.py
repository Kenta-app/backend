"""
Inspect claim-based predictions and recompute persisted scores for existing news.

Examples:
    python scripts/manage_predictions.py inspect --limit 5
    python scripts/manage_predictions.py inspect --news-id 12 13
    python scripts/manage_predictions.py recompute --limit 20
    python scripts/manage_predictions.py recompute --all-processed --source-id 3
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.application_services.publishing_service import PublishingService
from app.db.database import SessionLocal
from app.ml.pipeline import news_analysis_pipeline
from app.processed.models import ProcessedNews
from app.processed.predictors import SentimentPrediction
from app.raw.models import RawNews, Source
from app.serving.models import PublishedNews
from app.serving.repository import NewsRepository


@dataclass
class TargetRecord:
    processed: ProcessedNews
    raw_news: RawNews
    source: Source | None
    published: PublishedNews | None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and recompute fake-news predictions stored in the database."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Show detailed claim-based output for existing records without writing to the DB.",
    )
    add_selection_args(inspect_parser)
    inspect_parser.add_argument("--json", action="store_true", help="Print raw JSON output.")

    recompute_parser = subparsers.add_parser(
        "recompute",
        help="Recompute predictions and update DB rows for the selected records.",
    )
    add_selection_args(recompute_parser)
    recompute_parser.set_defaults(refresh_published=True)
    recompute_parser.add_argument(
        "--no-refresh-published",
        dest="refresh_published",
        action="store_false",
        help="Do not copy the updated prediction scores into serving.news.",
    )

    return parser


def add_selection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--representative-id",
        type=int,
        nargs="+",
        help="One or more processed representative IDs.",
    )
    parser.add_argument(
        "--news-id",
        type=int,
        nargs="+",
        help="One or more serving.news IDs.",
    )
    parser.add_argument(
        "--source-id",
        type=int,
        help="Restrict selection to a single source_id.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of rows to inspect/recompute when IDs are not provided. Use 0 for all.",
    )
    parser.add_argument(
        "--all-processed",
        action="store_true",
        help="Use processed.news_processed rows instead of only published serving.news rows.",
    )


def select_targets(db, args: argparse.Namespace) -> list[TargetRecord]:
    query = (
        db.query(ProcessedNews, RawNews, Source, PublishedNews)
        .join(RawNews, RawNews.news_raw_id == ProcessedNews.news_raw_id)
        .outerjoin(Source, Source.source_id == ProcessedNews.source_id)
        .outerjoin(
            PublishedNews,
            PublishedNews.representative_news_processed_id == ProcessedNews.news_processed_id,
        )
    )

    if args.representative_id:
        query = query.filter(ProcessedNews.news_processed_id.in_(args.representative_id))
    elif args.news_id:
        query = query.filter(PublishedNews.news_id.in_(args.news_id))
    else:
        if not args.all_processed:
            query = query.filter(PublishedNews.published_at.isnot(None))

    if args.source_id is not None:
        query = query.filter(ProcessedNews.source_id == args.source_id)

    if args.representative_id or args.news_id:
        rows = query.order_by(ProcessedNews.news_processed_id.asc()).all()
    else:
        if args.all_processed:
            ordered_query = query.order_by(ProcessedNews.processed_at.desc())
        else:
            ordered_query = query.order_by(PublishedNews.published_at.desc())
        rows = ordered_query.all() if args.limit == 0 else ordered_query.limit(args.limit).all()

    return [
        TargetRecord(
            processed=processed,
            raw_news=raw_news,
            source=source,
            published=published,
        )
        for processed, raw_news, source, published in rows
        if processed and raw_news and (processed.clean_text or "").strip()
    ]


def print_runtime_header() -> None:
    status = news_analysis_pipeline.warm_up(include_summarizer=False)
    print("Active ML configuration")
    print(f"  stance checkpoint : {status['classifier_checkpoint_path']}")
    print(f"  fake checkpoint   : {status['fake_news_classifier_checkpoint_path']}")
    print(f"  fake source       : {status['fake_news_classifier_source']}")
    print(f"  claims enabled    : {news_analysis_pipeline.use_claims}")
    print("")


def inspect_targets(args: argparse.Namespace) -> int:
    print_runtime_header()

    db = SessionLocal()
    try:
        targets = select_targets(db, args)
        if not targets:
            print("No matching records were found.")
            return 1

        for index, target in enumerate(targets, start=1):
            result = news_analysis_pipeline.analyze_news(
                title=target.raw_news.title_raw,
                content=target.processed.clean_text,
                include_summary=False,
            )
            payload = build_inspection_payload(target, result)

            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print_human_inspection(index, len(targets), payload)
        return 0
    finally:
        db.close()


def recompute_targets(args: argparse.Namespace) -> int:
    print_runtime_header()

    db = SessionLocal()
    predictor = SentimentPrediction(db)
    publisher = PublishingService(db, NewsRepository(db))

    updated = 0
    refreshed = 0
    failed = 0

    try:
        targets = select_targets(db, args)
        if not targets:
            print("No matching records were found.")
            return 1

        total = len(targets)
        for index, target in enumerate(targets, start=1):
            try:
                prediction = predictor.predictAll(target.processed.news_processed_id)
                updated += 1

                if args.refresh_published and target.published is not None:
                    publisher.refreshPublishedNews(target.published.news_id)
                    refreshed += 1

                print(
                    f"[{index}/{total}] rep={target.processed.news_processed_id} "
                    f"news={target.published.news_id if target.published else '-'} "
                    f"fake_score={float(prediction.fake_score):.4f}"
                )
            except Exception as exc:
                db.rollback()
                failed += 1
                print(
                    f"[{index}/{total}] rep={target.processed.news_processed_id} "
                    f"news={target.published.news_id if target.published else '-'} "
                    f"ERROR: {exc}"
                )

        print("")
        print("Recompute summary")
        print(f"  updated predictions : {updated}")
        print(f"  refreshed published : {refreshed}")
        print(f"  failed              : {failed}")
        return 0 if failed == 0 else 2
    finally:
        db.close()


def build_inspection_payload(target: TargetRecord, result: dict) -> dict:
    fake_news = result.get("fake_news") or {}
    stance = result.get("stance") or {}
    claims = (fake_news.get("claims") or {}).get("items") or []

    return {
        "representative_id": target.processed.news_processed_id,
        "news_id": target.published.news_id if target.published else None,
        "source_id": target.processed.source_id,
        "source_name": target.source.name if target.source else None,
        "published_at": (
            target.published.published_at.isoformat()
            if target.published and target.published.published_at
            else None
        ),
        "title": target.raw_news.title_raw,
        "stance": {
            "label": stance.get("label"),
            "confidence": stance.get("confidence"),
        },
        "fake_news": {
            "label": fake_news.get("label"),
            "display_label": fake_news.get("display_label"),
            "confidence": fake_news.get("confidence"),
            "bucket": fake_news.get("bucket"),
            "is_fake": fake_news.get("is_fake"),
            "decision_threshold": fake_news.get("decision_threshold"),
            "risk_score": fake_news.get("risk_score"),
            "real_support": fake_news.get("real_support"),
            "probabilities": fake_news.get("probabilities"),
            "source": fake_news.get("source"),
            "claim_based": fake_news.get("claim_based"),
        },
        "claims": [
            {
                "text": item.get("text"),
                "stance_target": item.get("stance_target"),
                "extraction_mode": item.get("extraction_mode"),
                "label": (item.get("prediction") or {}).get("label"),
                "confidence": (item.get("prediction") or {}).get("confidence"),
                "probabilities": (item.get("prediction") or {}).get("probabilities"),
                "article_stance": item.get("article_stance"),
                "signals": item.get("signals"),
            }
            for item in claims
        ],
    }


def print_human_inspection(index: int, total: int, payload: dict) -> None:
    fake_news = payload["fake_news"]
    probabilities = fake_news.get("probabilities") or {}
    print("=" * 72)
    print(
        f"[{index}/{total}] rep={payload['representative_id']} "
        f"news={payload['news_id'] or '-'} source={payload['source_name'] or '-'}"
    )
    print(f"title: {payload['title']}")
    print(
        f"stance: {payload['stance']['label']} "
        f"(confidence={payload['stance']['confidence']})"
    )
    print(
        f"fake : label={fake_news.get('label')} "
        f"display={fake_news.get('display_label')} "
        f"risk={fake_news.get('risk_score')} "
        f"p_false={probabilities.get('False')} "
        f"p_true={probabilities.get('True')} "
        f"threshold_false={fake_news.get('decision_threshold')} "
        f"claim_based={fake_news.get('claim_based')}"
    )

    if not payload["claims"]:
        print("claims: none")
        print("")
        return

    print("claims:")
    for claim_index, claim in enumerate(payload["claims"], start=1):
        claim_probs = claim.get("probabilities") or {}
        article_stance = claim.get("article_stance") or {}
        signals = claim.get("signals") or {}
        print(f"  {claim_index}. {claim['text']}")
        print(
            f"     mode={claim.get('extraction_mode')} "
            f"target={claim.get('stance_target')}"
        )
        print(
            f"     label={claim.get('label')} "
            f"confidence={claim.get('confidence')} "
            f"p_false={claim_probs.get('False')} "
            f"p_true={claim_probs.get('True')}"
        )
        print(
            f"     article_stance={article_stance.get('label')} "
            f"stance_conf={article_stance.get('confidence')} "
            f"fake_risk={signals.get('fake_risk')} "
            f"support={signals.get('support_score')} "
            f"refute={signals.get('refute_score')}"
        )
    print("")


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "inspect":
        return inspect_targets(args)
    if args.command == "recompute":
        return recompute_targets(args)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
