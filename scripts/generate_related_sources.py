from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func

from app.application_services.justification_service import GeminiJustificationService
from app.db.database import SessionLocal
from app.processed.models import JustificationSource, MlPrediction
from app.serving.models import PublishedNews


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera fuentes periodísticas relacionadas con Gemini para noticias publicadas."
    )
    parser.add_argument("--limit", type=int, default=20, help="Máximo de noticias a procesar.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenera fuentes aunque ya existan en la base de datos.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra qué procesaría sin llamar a Gemini.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help="Segundos de pausa entre llamadas para controlar cuota y carga.",
    )
    parser.add_argument(
        "--min-fake-score",
        type=float,
        default=None,
        help="Procesa solo noticias con fake_score igual o mayor a este valor.",
    )
    return parser.parse_args()


def load_targets(db, limit: int, force: bool, min_fake_score: float | None):
    source_counts = (
        db.query(
            JustificationSource.prediction_id.label("prediction_id"),
            func.count(JustificationSource.justification_source_id).label("source_count"),
        )
        .group_by(JustificationSource.prediction_id)
        .subquery()
    )

    query = (
        db.query(PublishedNews, MlPrediction, func.coalesce(source_counts.c.source_count, 0))
        .join(
            MlPrediction,
            MlPrediction.representative_news_processed_id
            == PublishedNews.representative_news_processed_id,
        )
        .outerjoin(source_counts, source_counts.c.prediction_id == MlPrediction.prediction_id)
        .filter(PublishedNews.published_at.isnot(None))
        .order_by(PublishedNews.published_at.desc(), PublishedNews.news_id.desc())
    )

    if min_fake_score is not None:
        query = query.filter(PublishedNews.fake_score >= min_fake_score)

    if not force:
        query = query.filter(func.coalesce(source_counts.c.source_count, 0) == 0)

    return query.limit(max(1, limit)).all()


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    try:
        targets = load_targets(db, args.limit, args.force, args.min_fake_score)
        logger.info("Targets selected=%s force=%s dry_run=%s", len(targets), args.force, args.dry_run)

        if args.dry_run:
            for news, prediction, source_count in targets:
                logger.info(
                    "Would process news_id=%s prediction_id=%s existing_sources=%s title=%r",
                    news.news_id,
                    prediction.prediction_id,
                    source_count,
                    news.title[:120],
                )
            return 0

        service = GeminiJustificationService(db)
        generated = 0
        failed = 0
        for index, (news, prediction, source_count) in enumerate(targets, start=1):
            try:
                logger.info(
                    "[%s/%s] Generating sources news_id=%s prediction_id=%s existing_sources=%s",
                    index,
                    len(targets),
                    news.news_id,
                    prediction.prediction_id,
                    source_count,
                )
                result = service.generate_justification(
                    prediction.prediction_id,
                    include_context=True,
                    regenerate=args.force,
                )
                logger.info(
                    "Generated %s sources for prediction_id=%s",
                    len(result.get("sources", [])),
                    prediction.prediction_id,
                )
                generated += 1
            except Exception as exc:
                logger.exception(
                    "Failed news_id=%s prediction_id=%s: %s",
                    news.news_id,
                    prediction.prediction_id,
                    exc,
                )
                failed += 1

            if index < len(targets) and args.sleep > 0:
                time.sleep(args.sleep)

        logger.info("Done. generated=%s failed=%s", generated, failed)
        return 0 if failed == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
