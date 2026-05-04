"""
Legacy facade kept for backwards compatibility.

The active ingestion flow now lives in `app.raw.ingestion_strategies` and
`app.application_services`. This manager simply delegates to the new pipeline.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.application_services.clustering_service import ClusteringService
from app.application_services.ingestion_service import IngestionService
from app.application_services.pipeline_orchestrator import PipelineOrchestrator
from app.application_services.prediction_service import PredictionService
from app.application_services.preprocessing_service import PreprocessingService
from app.application_services.publishing_service import PublishingService
from app.application_services.summarization_service import SummarizationService
from app.processed.predictors import SentimentPrediction
from app.processed.summarizers import LocalModelSummarizer
from app.raw.ingestion_strategies import TwitterApiIngestion, WebScraperIngestion
from app.raw.models import Source
from app.raw.source_catalog import seed_default_sources
from app.serving.repository import NewsRepository


class ScraperManager:
    def run_all_scrapers(self, db: Session) -> list[dict]:
        seed_default_sources(db)
        sources = db.query(Source).all()
        orchestrator = self._build_orchestrator(db)
        return [orchestrator.run_source_pipeline(source.source_id) for source in sources]

    @staticmethod
    def _build_orchestrator(db: Session) -> PipelineOrchestrator:
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
