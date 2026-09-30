from __future__ import annotations

import logging
import os
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
from app.dependencies import build_justification_service_optional
from app.db.database import SessionLocal
from app.processed.predictors import SentimentPrediction
from app.processed.summarizers import LocalModelSummarizer
from app.raw.ingestion_strategies import TwitterApiIngestion, WebScraperIngestion
from app.raw.models import Source
from app.raw.source_catalog import seed_default_sources
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


class ScrapingScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone=ZoneInfo("America/Lima"))

    def scheduled_scraping_job(self):
        """Run ingestion + processing pipeline for registered sources."""
        logger.info("Starting scheduled scraping job...")
        db = SessionLocal()
        try:
            seed_default_sources(db)
            sources = db.query(Source).all()
            for source in sources:
                source_id = source.source_id
                source_name = source.name
                orchestrator = self._build_orchestrator(db)
                try:
                    result = orchestrator.run_source_pipeline(source_id)
                    logger.info("Pipeline completed for source %s: %s", source_name, result)
                except Exception as exc:
                    db.rollback()
                    logger.exception("Pipeline failed for source %s: %s", source_name, exc)
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

    @staticmethod
    def _build_orchestrator(db):
        ingestion_service = IngestionService(
            db,
            [WebScraperIngestion(db), TwitterApiIngestion(db)],
        )
        preprocessing_service = PreprocessingService(db)
        clustering_service = ClusteringService(db)
        summarization_service = SummarizationService(LocalModelSummarizer(db))
        prediction_service = PredictionService(SentimentPrediction(db))
        publishing_service = PublishingService(db, NewsRepository(db))
        justification_service = build_justification_service_optional(db)
        return PipelineOrchestrator(
            ingestion_service,
            preprocessing_service,
            clustering_service,
            summarization_service,
            prediction_service,
            publishing_service,
            justification_service,
        )
