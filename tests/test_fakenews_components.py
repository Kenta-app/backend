import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import json

import torch

from app.ml.claim_extractor import ClaimExtractor, ExtractedClaim
from app.ml.pipeline import NewsAnalysisPipeline
from app.processed.predictors import SentimentPrediction
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

    def test_pipeline_auto_selects_best_fake_news_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_root = Path(tmp_dir) / "output"
            liar_dir = output_root / "fakenews_bert" / "best_model"
            spanish_dir = output_root / "fakenews_newtral" / "best_model"
            liar_dir.mkdir(parents=True)
            spanish_dir.mkdir(parents=True)

            (liar_dir / "serving_config.json").write_text(
                json.dumps({"validation_metrics": {"macro_f1": 0.64}}),
                encoding="utf-8",
            )
            (spanish_dir / "serving_config.json").write_text(
                json.dumps({"validation_metrics": {"macro_f1": 0.87}}),
                encoding="utf-8",
            )

            selected_dir = NewsAnalysisPipeline._resolve_fake_news_model_dir(
                None,
                output_root=str(output_root),
            )

            self.assertEqual(selected_dir, str(spanish_dir))

    def test_pipeline_prefers_explicit_fake_news_model_dir_over_auto_selection(self):
        selected_dir = NewsAnalysisPipeline._resolve_fake_news_model_dir(
            "output/custom_fake_news/best_model",
            output_root="output",
        )

        self.assertEqual(selected_dir, "output/custom_fake_news/best_model")

    def test_fake_score_matches_false_probability(self):
        predictor = SentimentPrediction(db=Mock())

        score = predictor._calculate_fake_score({"False": 0.63, "True": 0.37})

        self.assertEqual(score, 0.63)

    def test_claim_extractor_discards_promotional_candidates(self):
        extractor = ClaimExtractor()

        claims = extractor.extract(
            "Indecopi designan a Juan Carlos del Prado como nuevo presidente",
            (
                "PUEDES VER: Elecciones 2026: los 10 posibles diputados que recibieron menos "
                "de 3 mil votos Jan Carlos del Prado es el nuevo presidente de Indecopi. "
                "El funcionario asumio el cargo tras la renuncia del anterior titular."
            ),
        )

        self.assertTrue(claims)
        self.assertTrue(all("PUEDES VER" not in claim for claim in claims))

    def test_claim_extractor_discards_codelike_reference_snippets(self):
        extractor = ClaimExtractor()

        claims = extractor.extract(
            "Indecopi designan a Juan Carlos del Prado como nuevo presidente",
            (
                "145-2026-PCM, publicada en el diario oficial El Peruano este 6 de mayo. "
                "El funcionario asumio el cargo tras la renuncia del anterior titular."
            ),
        )

        self.assertTrue(claims)
        self.assertTrue(all(not claim.startswith("145-2026-PCM") for claim in claims))

    def test_claim_extractor_projects_reported_claim_targets(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            "El ministro asegura que la auditoria no condicionara los resultados.",
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].extraction_mode, "reported_claim")
        self.assertEqual(
            claims[0].stance_target,
            "la auditoria no condicionara los resultados",
        )

    def test_claim_extractor_projects_refuted_claim_targets(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            "El JNE niega que Roberto Burneo y Luis Galarreta se hayan reunido en Panama.",
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].extraction_mode, "refutation_projected")
        self.assertEqual(
            claims[0].stance_target,
            "Roberto Burneo y Luis Galarreta se hayan reunido en Panama",
        )

    def test_claim_aggregation_reduces_risk_when_article_refutes_false_claim(self):
        pipeline = NewsAnalysisPipeline()
        pipeline.claim_extractor = Mock()
        pipeline.claim_extractor.strategy_name = "heuristic_test"
        pipeline.claim_extractor.config = Mock(max_claims=3)
        pipeline.claim_extractor.extract_with_metadata.return_value = [
            ExtractedClaim(
                text="El JNE niega que hubo fraude electoral.",
                stance_target="hubo fraude electoral.",
                extraction_mode="refutation_projected",
            )
        ]

        with patch.object(
            pipeline,
            "load",
            return_value=True,
        ), patch.object(
            pipeline,
            "_predict_fake_news",
            return_value={
                "label": "False",
                "display_label": "falso",
                "confidence": 0.9,
                "probabilities": {"False": 0.9, "True": 0.1},
                "ranking": [],
                "source": "dedicated_fakenews_classifier",
                "decision_threshold": 0.57,
            },
        ), patch.object(
            pipeline,
            "_predict_stance",
            side_effect=[
                {
                    "label": "agree",
                    "display_label": "a favor",
                    "confidence": 0.8,
                    "probabilities": {
                        "unrelated": 0.05,
                        "discuss": 0.1,
                        "agree": 0.8,
                        "disagree": 0.05,
                    },
                    "ranking": [],
                },
                {
                    "label": "disagree",
                    "display_label": "en contra",
                    "confidence": 0.88,
                    "probabilities": {
                        "unrelated": 0.02,
                        "discuss": 0.08,
                        "agree": 0.05,
                        "disagree": 0.85,
                    },
                    "ranking": [],
                },
            ],
        ):
            prediction = pipeline.analyze_news(
                title="El JNE niega que hubo fraude electoral.",
                content="El organismo descarto la acusacion y explico el proceso.",
                include_summary=False,
            )["fake_news"]

        self.assertEqual(prediction["label"], "True")
        self.assertLess(prediction["risk_score"], 0.2)

    def test_claim_aggregation_keeps_high_risk_when_article_supports_false_claim(self):
        pipeline = NewsAnalysisPipeline()
        pipeline.claim_extractor = Mock()
        pipeline.claim_extractor.strategy_name = "heuristic_test"
        pipeline.claim_extractor.config = Mock(max_claims=3)
        pipeline.claim_extractor.extract_with_metadata.return_value = [
            ExtractedClaim(
                text="Hubo fraude electoral.",
                stance_target="Hubo fraude electoral.",
                extraction_mode="verbatim",
            )
        ]

        with patch.object(
            pipeline,
            "load",
            return_value=True,
        ), patch.object(
            pipeline,
            "_predict_fake_news",
            return_value={
                "label": "False",
                "display_label": "falso",
                "confidence": 0.9,
                "probabilities": {"False": 0.9, "True": 0.1},
                "ranking": [],
                "source": "dedicated_fakenews_classifier",
                "decision_threshold": 0.57,
            },
        ), patch.object(
            pipeline,
            "_predict_stance",
            side_effect=[
                {
                    "label": "agree",
                    "display_label": "a favor",
                    "confidence": 0.8,
                    "probabilities": {
                        "unrelated": 0.05,
                        "discuss": 0.1,
                        "agree": 0.8,
                        "disagree": 0.05,
                    },
                    "ranking": [],
                },
                {
                    "label": "agree",
                    "display_label": "a favor",
                    "confidence": 0.92,
                    "probabilities": {
                        "unrelated": 0.02,
                        "discuss": 0.08,
                        "agree": 0.85,
                        "disagree": 0.05,
                    },
                    "ranking": [],
                },
            ],
        ):
            prediction = pipeline.analyze_news(
                title="Hubo fraude electoral.",
                content="El articulo sostiene que existio fraude en la primera vuelta.",
                include_summary=False,
            )["fake_news"]

        self.assertEqual(prediction["label"], "False")
        self.assertGreater(prediction["risk_score"], 0.5)


if __name__ == "__main__":
    unittest.main()
