import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import torch

from app.ml.pipeline import NewsAnalysisPipeline
from app.ml.training.datasets import _build_model_inputs
from app.ml.training.fakenews_data import LIARFakeNewsDataset


class DummyTokenizer:
    def __call__(self, text, **kwargs):
        return {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }


class FakeNewsComponentsTests(unittest.TestCase):
    def test_build_model_inputs_supports_encoders_without_token_type_ids(self):
        encoded = {
            "input_ids": torch.tensor([[1, 2, 3]]),
            "attention_mask": torch.tensor([[1, 1, 1]]),
        }

        batch = _build_model_inputs(encoded)

        self.assertEqual(set(batch.keys()), {"input_ids", "attention_mask"})

    def test_liar_dataset_strict_strategy_drops_half_true(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "liar.tsv"
            dataset_path.write_text(
                "\n".join(
                    [
                        "1\thalf-true\tThis one is ambiguous",
                        "2\tfalse\tThis is false",
                        "3\ttrue\tThis is true",
                    ]
                ),
                encoding="utf-8",
            )

            dataset = LIARFakeNewsDataset(
                str(dataset_path),
                DummyTokenizer(),
                label_strategy="strict",
            )

            self.assertEqual(len(dataset), 2)
            self.assertEqual(dataset.label_counts[0], 1)
            self.assertEqual(dataset.label_counts[1], 1)
            self.assertEqual(dataset.skipped_labels["half-true"], 1)

    def test_liar_dataset_relaxed_strategy_keeps_half_true(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            dataset_path = Path(tmp_dir) / "liar.tsv"
            dataset_path.write_text(
                "\n".join(
                    [
                        "1\thalf-true\tThis one is ambiguous",
                        "2\tfalse\tThis is false",
                        "3\ttrue\tThis is true",
                    ]
                ),
                encoding="utf-8",
            )

            dataset = LIARFakeNewsDataset(
                str(dataset_path),
                DummyTokenizer(),
                label_strategy="relaxed",
            )

            self.assertEqual(len(dataset), 3)
            self.assertEqual(dataset.label_counts[0], 1)
            self.assertEqual(dataset.label_counts[1], 2)

    def test_pipeline_prefers_dedicated_fake_news_classifier(self):
        pipeline = NewsAnalysisPipeline()
        dedicated = Mock()
        dedicated.loaded = True
        dedicated.predict.return_value = {
            "label": "False",
            "confidence": 0.91,
            "probabilities": {"False": 0.91, "True": 0.09},
            "ranking": [
                {"label": "False", "score": 0.91},
                {"label": "True", "score": 0.09},
            ],
            "source": "dedicated_fakenews_classifier",
        }
        pipeline.fake_news_classifier = dedicated

        with patch.object(
            pipeline,
            "_predict_fake_news_multitask",
            side_effect=AssertionError("Should not use multitask fallback."),
        ):
            prediction = pipeline._predict_fake_news("texto")

        dedicated.predict.assert_called_once_with("texto")
        self.assertEqual(prediction["bucket"], "fake")
        self.assertTrue(prediction["is_fake"])
        self.assertEqual(prediction["display_label"], "falso")
        self.assertEqual(prediction["ranking"][0]["display"], "falso")

    def test_pipeline_uses_multitask_fallback_when_dedicated_model_is_unavailable(self):
        pipeline = NewsAnalysisPipeline()
        dedicated = Mock()
        dedicated.loaded = False
        pipeline.fake_news_classifier = dedicated

        expected = {
            "label": "True",
            "confidence": 0.75,
            "probabilities": {"False": 0.25, "True": 0.75},
            "ranking": [],
            "bucket": "real",
            "is_fake": False,
            "source": "multitask_fallback",
        }

        with patch.object(
            pipeline,
            "_predict_fake_news_multitask",
            return_value=expected,
        ) as mock_fallback:
            prediction = pipeline._predict_fake_news("texto")

        mock_fallback.assert_called_once_with("texto")
        self.assertEqual(prediction, expected)


if __name__ == "__main__":
    unittest.main()
