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
from app.db.database import SessionLocal
from app.processed.predictors import SentimentPrediction
from app.processed.summarizers import LocalModelSummarizer
from app.raw.ingestion_strategies import TwitterApiIngestion, WebScraperIngestion
from app.raw.models import Source
from app.raw.source_catalog import seed_default_sources
from app.serving.repository import NewsRepository

logger = logging.getLogger(__name__)


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
        """Start the scheduler with the configured daily schedule."""
        hour = int(os.getenv("SCRAPING_SCHEDULE_HOUR", "18"))
        minute = int(os.getenv("SCRAPING_SCHEDULE_MINUTE", "58"))

        self.scheduler.add_job(
            self.scheduled_scraping_job,
            CronTrigger(hour=hour, minute=minute),
            id="daily_scraping",
            name="Daily news scraping and pipeline",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("Scheduler started. Pipeline will run daily at %02d:%02d", hour, minute)

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
        return PipelineOrchestrator(
            ingestion_service,
            preprocessing_service,
            clustering_service,
            summarization_service,
            prediction_service,
            publishing_service,
        )
