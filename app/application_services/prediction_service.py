from __future__ import annotations

from app.interfaces.prediction_service import IPredictionService
from app.processed.models import MlPrediction


class PredictionService:
    def __init__(self, predictor: IPredictionService):
        self.predictor = predictor

    def predictSentiment(self, representativeNewsProcessedId: int) -> MlPrediction:
        return self.predictor.predictAll(representativeNewsProcessedId)

    def predictFakeScore(self, representativeNewsProcessedId: int) -> MlPrediction:
        return self.predictor.predictAll(representativeNewsProcessedId)

    def predictAll(self, representativeNewsProcessedId: int) -> MlPrediction:
        return self.predictor.predictAll(representativeNewsProcessedId)
