import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ml.pipeline import ModelNotReadyError
from app.routers.ml_router import router


class MLRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = FastAPI()
        app.include_router(router, prefix="/ml")
        cls.client = TestClient(app)

    def test_analyze_returns_pipeline_response(self):
        expected = {
            "input": {
                "title": "Titular",
                "content_length": 1200,
                "summary_requested": True,
                "summary_generated": True,
            },
            "fake_news": {
                "label": "false",
                "display_label": "falso",
                "confidence": 0.91,
                "probabilities": {"false": 0.91, "true": 0.09},
                "ranking": [],
                "bucket": "fake",
                "is_fake": True,
            },
            "stance": {
                "label": "discuss",
                "display_label": "discusion",
                "confidence": 0.77,
                "probabilities": {"discuss": 0.77, "agree": 0.23},
                "ranking": [],
            },
            "summary": "Resumen generado",
            "models": {
                "classifier": "MultiTaskBert",
                "classifier_checkpoint": "output/multitask_bert/best_model/model.pt",
                "classifier_base_model": "bert-base-uncased",
                "summarizer": "facebook/bart-large-cnn",
            },
            "warnings": [],
        }

        with patch(
            "app.routers.ml_router.news_analysis_pipeline.analyze_news",
            return_value=expected,
        ) as mock_analyze:
            response = self.client.post(
                "/ml/analyze",
                json={
                    "title": "Titular",
                    "content": "Contenido largo",
                    "include_summary": True,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        mock_analyze.assert_called_once_with(
            title="Titular",
            content="Contenido largo",
            text=None,
            include_summary=True,
            force_summary=False,
        )

    def test_predict_returns_503_when_model_is_missing(self):
        with patch(
            "app.routers.ml_router.news_analysis_pipeline.analyze_news",
            side_effect=ModelNotReadyError("checkpoint missing"),
        ):
            response = self.client.post("/ml/predict", json={"text": "texto"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "checkpoint missing"})

    def test_analyze_requires_some_text(self):
        response = self.client.post("/ml/analyze", json={"include_summary": False})

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
