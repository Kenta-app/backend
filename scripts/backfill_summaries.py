from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import exists

from app.application_services.publishing_service import PublishingService
from app.application_services.summarization_service import SummarizationService
from app.db.database import SessionLocal
from app.processed.models import ProcessedNews, Summary
from app.processed.summarizers import LocalModelSummarizer
from app.serving.models import PublishedNews
from app.serving.repository import NewsRepository

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate missing local-model summaries outside the request path."
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--force", action="store_true", help="Regenerate existing summaries.")
    parser.add_argument(
        "--refresh-published",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh PublishedNews.summary after generating each summary.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to wait between items.")
    return parser.parse_args()


def collect_targets(db, *, limit: int, force: bool) -> list[ProcessedNews]:
    query = (
        db.query(ProcessedNews)
        .filter(ProcessedNews.status == "ok")
        .filter(ProcessedNews.clean_text.isnot(None))
        .filter(ProcessedNews.token_count >= 50)
        .order_by(ProcessedNews.processed_at.desc())
    )
    if not force:
        query = query.filter(
            ~exists().where(
                Summary.representative_news_processed_id == ProcessedNews.news_processed_id
            )
        )
    return query.limit(limit).all()


def refresh_published_summary(db, publishing_service: PublishingService, representative_id: int) -> bool:
    published = (
        db.query(PublishedNews)
        .filter(PublishedNews.representative_news_processed_id == representative_id)
        .first()
    )
    if not published:
        return False
    publishing_service.publishRepresentative(representative_id)
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    db = SessionLocal()
    try:
        targets = collect_targets(db, limit=args.limit, force=args.force)
        logger.info("Found %s summary target(s).", len(targets))
        if args.dry_run:
            for item in targets:
                logger.info("Would summarize processed_news_id=%s", item.news_processed_id)
            return

        summarization_service = SummarizationService(LocalModelSummarizer(db))
        publishing_service = PublishingService(db, NewsRepository(db))

        generated = 0
        refreshed = 0
        failed = 0
        for item in targets:
            representative_id = item.news_processed_id
            try:
                summary = summarization_service.generateSummary(
                    representative_id,
                    force=args.force,
                )
                generated += 1
                logger.info(
                    "Generated summary_id=%s for processed_news_id=%s",
                    summary.summary_id,
                    representative_id,
                )
                if args.refresh_published and refresh_published_summary(
                    db,
                    publishing_service,
                    representative_id,
                ):
                    refreshed += 1
            except Exception as exc:
                failed += 1
                logger.exception(
                    "Failed to summarize processed_news_id=%s: %s",
                    representative_id,
                    exc,
                )
            if args.sleep:
                time.sleep(args.sleep)

        logger.info(
            "Done. generated=%s refreshed=%s failed=%s",
            generated,
            refreshed,
            failed,
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
