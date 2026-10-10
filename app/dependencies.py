from __future__ import annotations

import hmac
import os

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from app.application_services.analytics_service import AnalyticsService
from app.application_services.auth_service import AuthService
from app.application_services.clustering_service import ClusteringService
from app.application_services.draw_service import DrawService
from app.application_services.favorite_service import FavoriteService
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
from app.services.email_service import ResendEmailSender
from app.services.session_token_service import SessionTokenService


def get_session_token_service() -> SessionTokenService:
    return SessionTokenService()


def get_current_user(
    kenta_session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
    session_service: SessionTokenService = Depends(get_session_token_service),
) -> User | None:
    payload = session_service.verify(kenta_session or "")
    if not payload:
        return None
    user = db.query(User).filter(User.user_id == int(payload["uid"])).first()
    if not user:
        return None
    if not hmac.compare_digest(
        str(payload.get("pwd", "")),
        session_service.password_fingerprint(user.password_hash),
    ):
        return None
    return user


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


def get_favorite_service(db: Session = Depends(get_db)) -> FavoriteService:
    return FavoriteService(db)


def get_analytics_service(db: Session = Depends(get_db)) -> AnalyticsService:
    return AnalyticsService(db)


def get_email_sender() -> ResendEmailSender:
    return ResendEmailSender()


def get_draw_service(
    db: Session = Depends(get_db),
    email_sender: ResendEmailSender = Depends(get_email_sender),
) -> DrawService:
    return DrawService(db, email_sender)


def get_auth_service(
    db: Session = Depends(get_db),
    email_sender: ResendEmailSender = Depends(get_email_sender),
) -> AuthService:
    return AuthService(db, email_sender)


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


def is_justification_auto_enabled() -> bool:
    return os.getenv("JUSTIFICATION_AUTO_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def build_justification_service_optional(db: Session) -> GeminiJustificationService | None:
    if not is_justification_auto_enabled() or not os.getenv("GEMINI_API_KEY"):
        return None

    cache_ttl = int(os.getenv("JUSTIFICATION_CACHE_TTL", "3600"))
    max_retries = int(os.getenv("JUSTIFICATION_MAX_RETRIES", "3"))
    retry_delay = float(os.getenv("JUSTIFICATION_RETRY_DELAY", "2.0"))

    return GeminiJustificationService(
        db=db,
        cache_ttl=cache_ttl,
        max_retries=max_retries,
        retry_delay=retry_delay,
    )


def build_justification_reader(db: Session) -> GeminiJustificationService:
    return GeminiJustificationService(
        db=db,
        api_key=None,
        cache_ttl=int(os.getenv("JUSTIFICATION_CACHE_TTL", "3600")),
        max_retries=int(os.getenv("JUSTIFICATION_MAX_RETRIES", "3")),
        retry_delay=float(os.getenv("JUSTIFICATION_RETRY_DELAY", "2.0")),
    )
