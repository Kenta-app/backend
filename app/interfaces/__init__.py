from app.interfaces.ingestion_strategy import IIngestionStrategy
from app.interfaces.news_repository import INewsRepository
from app.interfaces.prediction_service import IPredictionService
from app.interfaces.summarizer_service import ISummarizerService

__all__ = [
    "IIngestionStrategy",
    "INewsRepository",
    "IPredictionService",
    "ISummarizerService",
]
