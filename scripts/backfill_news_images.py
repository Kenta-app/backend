"""Completa image_url en noticias existentes sin cambiar IDs ni relaciones.

Vista previa (no escribe):
    python scripts/backfill_news_images.py --limit 10

Aplicar cambios:
    python scripts/backfill_news_images.py --apply
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import joinedload

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.database import SessionLocal  # noqa: E402
from app.processed.models import ProcessedNews  # noqa: E402
from app.raw.models import RawNews, Source  # noqa: E402
from app.scrapers.base_scraper import extract_representative_image_url  # noqa: E402
from app.serving.models import PublishedNews  # noqa: E402

logger = logging.getLogger("backfill_news_images")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Completa URLs de imágenes en noticias publicadas existentes."
    )
    parser.add_argument("--apply", action="store_true", help="Confirma escrituras en la BD.")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de noticias a revisar.")
    parser.add_argument("--source-id", type=int, default=None, help="Limita a una fuente.")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--delay", type=float, default=0.15, help="Pausa entre páginas.")
    parser.add_argument("--commit-every", type=int, default=20)
    return parser.parse_args()


def fetch_image_url(client: requests.Session, page_url: str, timeout: float) -> str | None:
    response = client.get(page_url, timeout=timeout)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    return extract_representative_image_url(soup, page_url)


def run_backfill(args: argparse.Namespace) -> dict[str, int]:
    stats = {"reviewed": 0, "found": 0, "updated": 0, "missing": 0, "failed": 0}
    db = SessionLocal()
    client = requests.Session()
    client.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "es-PE,es;q=0.9",
        }
    )

    try:
        query = (
            db.query(PublishedNews, ProcessedNews, RawNews, Source)
            .join(
                ProcessedNews,
                PublishedNews.representative_news_processed_id
                == ProcessedNews.news_processed_id,
            )
            .join(RawNews, ProcessedNews.news_raw_id == RawNews.news_raw_id)
            .join(Source, PublishedNews.source_id == Source.source_id)
            .filter(PublishedNews.image_url.is_(None))
            .order_by(PublishedNews.news_id.asc())
        )
        if args.source_id is not None:
            query = query.filter(PublishedNews.source_id == args.source_id)
        if args.limit is not None:
            query = query.limit(max(args.limit, 0))

        rows = query.all()
        logger.info(
            "%s noticias sin imagen encontradas (%s).",
            len(rows),
            "APLICAR" if args.apply else "VISTA PREVIA",
        )

        for published, _processed, raw_news, source in rows:
            stats["reviewed"] += 1
            image_url = raw_news.image_url
            try:
                if not image_url:
                    image_url = fetch_image_url(client, raw_news.original_url, args.timeout)
                    if args.delay > 0:
                        time.sleep(args.delay)
            except Exception as exc:
                stats["failed"] += 1
                logger.warning(
                    "news=%s fuente=%s no pudo consultarse: %s",
                    published.news_id,
                    source.name,
                    exc,
                )
                continue

            if not image_url:
                stats["missing"] += 1
                logger.info("news=%s fuente=%s sin metadato de imagen", published.news_id, source.name)
                continue

            stats["found"] += 1
            logger.info("news=%s fuente=%s imagen=%s", published.news_id, source.name, image_url)
            if args.apply:
                raw_news.image_url = image_url
                published.image_url = image_url
                stats["updated"] += 1
                if stats["updated"] % max(args.commit_every, 1) == 0:
                    db.commit()

        if args.apply:
            db.commit()
        else:
            db.rollback()
        return stats
    except Exception:
        db.rollback()
        raise
    finally:
        client.close()
        db.close()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    stats = run_backfill(args)
    logger.info("Resultado: %s", stats)
    if not args.apply:
        logger.info("Vista previa: no se escribió ningún cambio. Usa --apply para confirmar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
