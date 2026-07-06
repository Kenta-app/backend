from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.interfaces.prediction_service import IPredictionService
from app.ml.pipeline import news_analysis_pipeline
from app.processed.models import MlPrediction, ProcessedNews
from app.raw.models import RawNews


class SentimentPrediction(IPredictionService):
    """
    UML alignment note:
    `sentiment_*` stores the political stance label/score used by the project.
    """

    # Binary classification weights: "False"=fake, "True"=real
    # fake_score = probabilidad de ser fake (inverso de predicción)
    FAKE_RISK_WEIGHTS = {
        "False": 0.9,  # Fake → high risk
        "True": 0.1,   # Real → low risk
    }

    def __init__(self, db: Session, modelPath: str | None = None, threshold: float = 0.6):
        self.db = db
        self.modelPath = modelPath or news_analysis_pipeline.fake_news_model_dir
        self.threshold = float(threshold)

    def predictSentiment(self, representativeNewsProcessedId: int) -> MlPrediction:
        return self.predictAll(representativeNewsProcessedId)

    def predictFakeScore(self, representativeNewsProcessedId: int) -> MlPrediction:
        return self.predictAll(representativeNewsProcessedId)

    def predictAll(self, representativeNewsProcessedId: int) -> MlPrediction:
        processed, raw_news = self._load_processed_raw_pair(representativeNewsProcessedId)
        raw_result = self.runModel(
            {
                "title": raw_news.title_raw,
                "content": processed.clean_text,
            }
        )

        stance = raw_result.get("stance") or {"label": "unrelated", "confidence": 0.0, "probabilities": {}}
        fake_news = raw_result.get("fake_news") or {}
        fake_score = self._calculate_fake_score(fake_news["probabilities"])

        prediction = (
            self.db.query(MlPrediction)
            .filter(MlPrediction.representative_news_processed_id == representativeNewsProcessedId)
            .first()
        )
        if not prediction:
            prediction = MlPrediction(
                representative_news_processed_id=representativeNewsProcessedId,
                model_version=self.getModelVersion(),
            )

        prediction.updateSentiment(stance["label"], stance["confidence"])
        prediction.updateFakeScore(fake_score)
        prediction.model_version = self.getModelVersion()
        prediction.fake_label = fake_news["label"]
        prediction.fake_bucket = fake_news.get("bucket")
        prediction.raw_probabilities = {
            "stance": stance["probabilities"],
            "fake_news": fake_news["probabilities"],
            "fake_news_risk": fake_news.get("risk_score"),
        }

        self.db.add(prediction)
        self.db.commit()
        self.db.refresh(prediction)
        return prediction

    def getModelVersion(self) -> str:
        fake_classifier_name = news_analysis_pipeline.fake_news_classifier.model_name
        fake_classifier_path = news_analysis_pipeline.fake_news_model_dir
        stance_classifier_name = (
            news_analysis_pipeline.stance_classifier.model_name
            if news_analysis_pipeline.stance_classifier.loaded
            else "unavailable"
        )
        return (
            f"stance={stance_classifier_name}:{news_analysis_pipeline.stance_model_dir}"
            f"|fake={fake_classifier_name}:{fake_classifier_path}"
        )

    def tokenize(self, text: str) -> list[int]:
        if not news_analysis_pipeline.load():
            raise RuntimeError(news_analysis_pipeline.load_error or "Modelo no disponible.")
        encoded = news_analysis_pipeline.fake_news_classifier.tokenizer(
            text,
            truncation=True,
            max_length=news_analysis_pipeline.fake_news_classifier.serving_config.max_length,
        )
        return encoded["input_ids"]

    def runModel(self, tokens: dict[str, Any]) -> dict[str, Any]:
        return news_analysis_pipeline.analyze_news(
            title=tokens.get("title"),
            content=tokens.get("content"),
            include_summary=False,
            allow_partial=True,
        )

    def _load_processed_raw_pair(self, representativeNewsProcessedId: int) -> tuple[ProcessedNews, RawNews]:
        processed = (
            self.db.query(ProcessedNews)
            .filter(ProcessedNews.news_processed_id == representativeNewsProcessedId)
            .first()
        )
        if not processed or not processed.clean_text:
            raise ValueError("No existe texto procesado para predecir.")

        raw_news = (
            self.db.query(RawNews)
            .filter(RawNews.news_raw_id == processed.news_raw_id)
            .first()
        )
        if not raw_news:
            raise ValueError("No existe la noticia raw asociada a la noticia procesada.")

        return processed, raw_news

    def _calculate_fake_score(self, probabilities: dict[str, float]) -> float:
        # fake_score should be directly interpretable as the model probability
        # of the "False" label, which maps to fake/high-risk content.
        fake_prob = probabilities.get("False", 0.0)
        return round(float(fake_prob), 4)
