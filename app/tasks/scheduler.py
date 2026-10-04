from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.application_services.clustering_service import ClusteringService
from app.application_services.ingestion_service import IngestionService
from app.application_services.pipeline_orchestrator import PipelineOrchestrator
from app.application_services.prediction_service import PredictionService
from app.application_services.preprocessing_service import PreprocessingService
from app.application_services.publishing_service import PublishingService
from app.application_services.summarization_service import SummarizationService
from app.dependencies import build_justification_service_optional, is_justification_auto_enabled
from app.db.database import SessionLocal
from app.processed.models import JustificationRun, MlPrediction
from app.processed.predictors import SentimentPrediction
from app.processed.summarizers import LocalModelSummarizer
from app.raw.ingestion_strategies import TwitterApiIngestion, WebScraperIngestion
from app.raw.models import Source
from app.raw.source_catalog import seed_default_sources
from app.serving.models import PublishedNews
from app.serving.repository import NewsRepository

logger = logging.getLogger(__name__)


def configured_scraping_times() -> tuple[list[int], int]:
    """Read a bounded daily schedule, preserving the legacy single-hour setting."""
    raw_hours = os.getenv("SCRAPING_SCHEDULE_HOURS", "").strip()
    if raw_hours:
        parts = [part.strip() for part in raw_hours.split(",")]
        if any(not part.isdigit() for part in parts):
            raise ValueError("SCRAPING_SCHEDULE_HOURS must be comma-separated hours (0-23).")
        hours = sorted({int(part) for part in parts})
    else:
        hours = [int(os.getenv("SCRAPING_SCHEDULE_HOUR") or "18")]

    minute = int(os.getenv("SCRAPING_SCHEDULE_MINUTE") or "58")
    if not hours or len(hours) > 6 or any(hour < 0 or hour > 23 for hour in hours):
        raise ValueError("Configure between one and six scraping hours in the range 0-23.")
    if minute < 0 or minute > 59:
        raise ValueError("SCRAPING_SCHEDULE_MINUTE must be in the range 0-59.")
    return hours, minute


def configured_justification_budget() -> int:
    """Bound automatic Gemini calls made by one complete scheduled cycle."""
    try:
        budget = int(os.getenv("JUSTIFICATION_MAX_PER_SCHEDULED_RUN", "5"))
    except ValueError as exc:
        raise ValueError("JUSTIFICATION_MAX_PER_SCHEDULED_RUN must be an integer.") from exc
    if budget < 0 or budget > 50:
        raise ValueError("JUSTIFICATION_MAX_PER_SCHEDULED_RUN must be between 0 and 50.")
    return budget


def select_balanced_prediction_ids(
    source_predictions: dict[int, list[int]],
    limit: int,
    rotation: int = 0,
) -> list[int]:
    """Interleave sources so a global Gemini budget is not spent on the first outlet."""
    if limit <= 0:
        return []

    source_ids = sorted(
        source_id for source_id, prediction_ids in source_predictions.items() if prediction_ids
    )
    if not source_ids:
        return []

    offset = rotation % len(source_ids)
    source_ids = source_ids[offset:] + source_ids[:offset]
    queues = {
        source_id: deque(dict.fromkeys(source_predictions[source_id]))
        for source_id in source_ids
    }
    selected: list[int] = []
    while len(selected) < limit:
        progressed = False
        for source_id in source_ids:
            if not queues[source_id]:
                continue
            selected.append(queues[source_id].popleft())
            progressed = True
            if len(selected) >= limit:
                break
        if not progressed:
            break
    return selected


class ScrapingScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone=ZoneInfo("America/Lima"))
        self._justification_rotation = 0

    def scheduled_scraping_job(self):
        """Run ingestion + processing pipeline for registered sources."""
        logger.info("Starting scheduled scraping job...")
        db = SessionLocal()
        try:
            seed_default_sources(db)
            sources = db.query(Source).filter(Source.is_active.is_(True)).all()
            justification_service = build_justification_service_optional(db)
            # Search after every outlet finishes so the global budget is not
            # consumed by whichever sources happen to run first.
            orchestrator = self._build_orchestrator(
                db,
                justification_service=justification_service,
                max_auto_justifications=0,
            )
            published_ids: list[int] = []
            for source in sources:
                source_id = source.source_id
                source_name = source.name
                try:
                    result = orchestrator.run_source_pipeline(source_id)
                    published_ids.extend(result["published_news_ids"])
                    logger.info("Pipeline completed for source %s: %s", source_name, result)
                except Exception as exc:
                    db.rollback()
                    logger.exception("Pipeline failed for source %s: %s", source_name, exc)
            self._generate_balanced_related_sources(
                db,
                justification_service,
                published_ids,
            )
        finally:
            db.close()

    def start(self):
        """Start one non-overlapping job at each configured Lima-time hour."""
        hours, minute = configured_scraping_times()

        self.scheduler.add_job(
            self.scheduled_scraping_job,
            CronTrigger(
                hour=",".join(map(str, hours)),
                minute=minute,
                timezone=ZoneInfo("America/Lima"),
            ),
            id="scheduled_scraping",
            name="Scheduled news scraping and pipeline",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
        )
        self.scheduler.start()
        logger.info(
            "Scheduler started. Pipeline will run at %s America/Lima",
            ", ".join(f"{hour:02d}:{minute:02d}" for hour in hours),
        )

    def shutdown(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("Scheduler shutdown")

    def _generate_balanced_related_sources(
        self,
        db,
        justification_service,
        published_ids: list[int],
    ) -> None:
        budget = configured_justification_budget()
        if (
            budget <= 0
            or justification_service is None
            or not published_ids
            or not is_justification_auto_enabled()
            or not os.getenv("GEMINI_API_KEY")
        ):
            return

        rows = (
            db.query(
                PublishedNews.source_id,
                PublishedNews.news_id,
                MlPrediction.prediction_id,
            )
            .join(
                MlPrediction,
                MlPrediction.representative_news_processed_id
                == PublishedNews.representative_news_processed_id,
            )
            .filter(PublishedNews.news_id.in_(set(published_ids)))
            .order_by(PublishedNews.news_id.desc())
            .all()
        )
        by_source: dict[int, list[int]] = defaultdict(list)
        for source_id, _news_id, prediction_id in rows:
            by_source[source_id].append(prediction_id)

        prediction_ids = select_balanced_prediction_ids(
            by_source,
            budget,
            rotation=self._justification_rotation,
        )
        self._justification_rotation += 1
        attempted = 0
        for prediction_id in prediction_ids:
            try:
                result = justification_service.generate_justification(
                    prediction_id=prediction_id,
                    include_context=True,
                    regenerate=False,
                )
                search_status = result.get("search_status")
                source_count = len(result.get("sources", []))
                status = (
                    "no_sources"
                    if search_status in {"no_sources", "no_sources_preserved"}
                    else "success" if source_count else "no_sources"
                )
                error_message = None
                model_used = result.get("model_used") or "unknown"
            except Exception as exc:
                db.rollback()
                status = "failed"
                source_count = 0
                model_used = getattr(justification_service, "model_name", "unknown")
                error_message = str(exc)[:500]
                logger.warning(
                    "Automatic related-source search failed prediction_id=%s: %s",
                    prediction_id,
                    exc,
                )

            db.add(
                JustificationRun(
                    prediction_id=prediction_id,
                    status=status,
                    source_count=source_count,
                    model_used=model_used,
                    error_message=error_message,
                )
            )
            db.commit()
            attempted += 1
        logger.info(
            "Automatic related-source searches attempted=%s selected=%s outlets=%s budget=%s",
            attempted,
            len(prediction_ids),
            len(by_source),
            budget,
        )

    @staticmethod
    def _build_orchestrator(
        db,
        justification_service=None,
        max_auto_justifications: int | None = None,
    ):
        ingestion_service = IngestionService(
            db,
            [WebScraperIngestion(db), TwitterApiIngestion(db)],
        )
        preprocessing_service = PreprocessingService(db)
        clustering_service = ClusteringService(db)
        summarization_service = SummarizationService(LocalModelSummarizer(db))
        prediction_service = PredictionService(SentimentPrediction(db))
        publishing_service = PublishingService(db, NewsRepository(db))
        if justification_service is None:
            justification_service = build_justification_service_optional(db)
        return PipelineOrchestrator(
            ingestion_service,
            preprocessing_service,
            clustering_service,
            summarization_service,
            prediction_service,
            publishing_service,
            justification_service,
            maxAutoJustifications=(
                configured_justification_budget()
                if max_auto_justifications is None
                else max_auto_justifications
            ),
        )
