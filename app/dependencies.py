from __future__ import annotations

import os

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.application_services.auth_service import AuthService
from app.application_services.clustering_service import ClusteringService
from app.application_services.ingestion_service import IngestionService
from app.application_services.interaction_service import InteractionService
from app.application_services.justification_service import GeminiJustificationService
from app.application_services.prediction_service import PredictionService
from app.application_services.preprocessing_service import PreprocessingService
from app.application_services.publishing_service import PublishingService
from app.application_services.summarization_service import SummarizationService
from app.db.database import get_db
from app.processed.predictors import SentimentPrediction
from app.processed.summarizers import LocalModelSummarizer
from app.raw.ingestion_strategies import TwitterApiIngestion, WebScraperIngestion
from app.serving.models import User
from app.serving.repository import NewsRepository


def get_current_user(
    x_user_id: int | None = Header(default=None, alias="X-User-Id"),
    db: Session = Depends(get_db),
) -> User | None:
    if x_user_id is None:
        return None
    return db.query(User).filter(User.user_id == x_user_id).first()


def get_ingestion_service(db: Session = Depends(get_db)) -> IngestionService:
    strategies = [WebScraperIngestion(db), TwitterApiIngestion(db)]
    return IngestionService(db, strategies)


def get_preprocessing_service(db: Session = Depends(get_db)) -> PreprocessingService:
    return PreprocessingService(db)


def get_clustering_service(db: Session = Depends(get_db)) -> ClusteringService:
    return ClusteringService(db)


def get_summarization_service(db: Session = Depends(get_db)) -> SummarizationService:
    return SummarizationService(LocalModelSummarizer(db))


def get_prediction_service(db: Session = Depends(get_db)) -> PredictionService:
    return PredictionService(SentimentPrediction(db))


def get_publishing_service(db: Session = Depends(get_db)) -> PublishingService:
    return PublishingService(db, NewsRepository(db))


def get_interaction_service(db: Session = Depends(get_db)) -> InteractionService:
    return InteractionService(db)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


def get_justification_service(db: Session = Depends(get_db)) -> GeminiJustificationService:
    """
    Inyecta el servicio de justificación con configuración desde variables de entorno.
    """
    cache_ttl = int(os.getenv("JUSTIFICATION_CACHE_TTL", "3600"))
    max_retries = int(os.getenv("JUSTIFICATION_MAX_RETRIES", "3"))
    retry_delay = float(os.getenv("JUSTIFICATION_RETRY_DELAY", "2.0"))

    return GeminiJustificationService(
        db=db,
        cache_ttl=cache_ttl,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )

