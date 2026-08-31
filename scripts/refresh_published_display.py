from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.application_services.publishing_service import PublishingService
from app.db.database import SessionLocal
from app.processed.models import ProcessedNews
from app.raw.models import RawNews
from app.serving.models import PublishedNews
from app.serving.repository import NewsRepository

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh published-news display fields from raw/processed content."
    )
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--only-social", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()

    db = SessionLocal()
    try:
        query = db.query(PublishedNews).order_by(PublishedNews.published_at.desc())
        if args.only_social:
            query = (
                query.join(
                    ProcessedNews,
                    PublishedNews.representative_news_processed_id
                    == ProcessedNews.news_processed_id,
                )
                .join(RawNews, ProcessedNews.news_raw_id == RawNews.news_raw_id)
                .filter(
                    (RawNews.platform.in_(["twitter", "x", "social"]))
                    | (RawNews.original_url.ilike("%x.com/%"))
                    | (RawNews.original_url.ilike("%twitter.com/%"))
                )
            )
        items = query.limit(args.limit).all()
        logger.info("Found %s published item(s).", len(items))
        if args.dry_run:
            for item in items:
                logger.info(
                    "Would refresh news_id=%s representative=%s",
                    item.news_id,
                    item.representative_news_processed_id,
                )
            return

        service = PublishingService(db, NewsRepository(db))
        refreshed = 0
        failed = 0
        for item in items:
            try:
                service.refreshPublishedNews(item.news_id)
                refreshed += 1
                logger.info("Refreshed news_id=%s", item.news_id)
            except Exception as exc:
                failed += 1
                logger.exception("Failed to refresh news_id=%s: %s", item.news_id, exc)
        logger.info("Done. refreshed=%s failed=%s", refreshed, failed)
    finally:
        db.close()


if __name__ == "__main__":
    main()
