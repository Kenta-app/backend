import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import json

import torch

from app.ml.claim_extractor import ClaimExtractionConfig, ClaimExtractor, ExtractedClaim
from app.ml.pipeline import ModelNotReadyError, NewsAnalysisPipeline
from app.processed.predictors import SentimentPrediction
from app.ml.training.datasets import _build_model_inputs
from app.ml.training.fakenews_data import LIARFakeNewsDataset
from app.ml.training.train_fakenews import resolve_model_source, resolve_serving_model_name


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

        prediction = pipeline._predict_fake_news("texto")

        dedicated.predict.assert_called_once_with("texto")
        self.assertEqual(prediction["bucket"], "fake")
        self.assertTrue(prediction["is_fake"])
        self.assertEqual(prediction["display_label"], "falso")
        self.assertEqual(prediction["ranking"][0]["display"], "falso")

    def test_pipeline_requires_dedicated_fake_news_classifier(self):
        pipeline = NewsAnalysisPipeline()
        dedicated = Mock()
        dedicated.loaded = False
        dedicated.load.return_value = False
        dedicated.load_error = "checkpoint missing"
        pipeline.fake_news_classifier = dedicated

        with self.assertRaises(ModelNotReadyError):
            pipeline._predict_fake_news("texto")

    def test_analyze_news_uses_fake_news_when_stance_checkpoint_is_missing(self):
        pipeline = NewsAnalysisPipeline()
        pipeline.use_claims = False
        dedicated = Mock()
        dedicated.loaded = True
        dedicated.load.return_value = True
        dedicated.predict.return_value = {
            "label": "False",
            "confidence": 0.92,
            "probabilities": {"False": 0.92, "True": 0.08},
            "ranking": [
                {"label": "False", "score": 0.92},
                {"label": "True", "score": 0.08},
            ],
            "decision_threshold": 0.57,
            "source": "dedicated_fakenews_classifier",
        }
        pipeline.fake_news_classifier = dedicated
        pipeline.stance_classifier = Mock(
            loaded=False,
            load=Mock(return_value=False),
            load_error="stance checkpoint missing",
        )

        result = pipeline.analyze_news(
            title="Titular",
            content="Contenido",
            include_summary=False,
            allow_partial=True,
        )

        self.assertIsNone(result["stance"])
        self.assertEqual(result["fake_news"]["label"], "False")
        self.assertEqual(result["fake_news"]["aggregation_method"], "direct_dedicated_classifier")
        self.assertEqual(result["fake_news"]["triage_label"], "likely_fake")
        self.assertEqual(result["warnings"], [])

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

    def test_train_fakenews_resolves_existing_local_checkpoint_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            checkpoint_dir = Path(tmp_dir) / "best_model"
            checkpoint_dir.mkdir(parents=True)

            resolved = resolve_model_source(str(checkpoint_dir))

            self.assertEqual(resolved, str(checkpoint_dir.resolve()))

    def test_train_fakenews_raises_helpful_error_for_missing_local_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            missing_dir = Path(tmp_dir) / "missing_model"

            with self.assertRaises(FileNotFoundError) as context:
                resolve_model_source(str(missing_dir))

            self.assertIn("No se encontro el checkpoint local", str(context.exception))

    def test_train_fakenews_keeps_huggingface_repo_ids_with_namespace(self):
        resolved = resolve_model_source("FacebookAI/xlm-roberta-base")

        self.assertEqual(resolved, "FacebookAI/xlm-roberta-base")

    def test_train_fakenews_preserves_original_model_name_from_serving_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            checkpoint_dir = Path(tmp_dir) / "best_model"
            checkpoint_dir.mkdir(parents=True)
            (checkpoint_dir / "serving_config.json").write_text(
                json.dumps({"model_name": "xlm-roberta-base"}),
                encoding="utf-8",
            )

            serving_name = resolve_serving_model_name(str(checkpoint_dir))

            self.assertEqual(serving_name, "xlm-roberta-base")

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

    def test_claim_extractor_discards_subjective_direct_quotes(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            'Keiko Fujimori: "Todos los votos tienen que contabilizarse"',
            None,
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_discards_first_person_political_quotes(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            'Keiko Fujimori: "Soy respetuosa de lo que el JNE vaya a determinar. Nos corresponde esperar con prudencia"',
            None,
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_discards_self_exculpatory_first_person_claims(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            "No hemos tenido otra intencion que garantizar un uso adecuado de los recursos del Estado, apunto.",
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_projects_factcheck_question_headlines(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            "PerúCheck: ¿Las actas con serie 900 fueron creadas para cometer un fraude electoral? Es falsa la declaración de López Aliaga",
            None,
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].extraction_mode, "factcheck_question")
        self.assertEqual(
            claims[0].stance_target,
            "Las actas con serie 900 fueron creadas para cometer un fraude electoral",
        )

    def test_claim_extractor_projects_factcheck_verdict_phrases(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            "Es falso que las actas con serie 900 fueron creadas para cometer un fraude electoral",
            None,
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].extraction_mode, "factcheck_verdict")
        self.assertEqual(
            claims[0].stance_target,
            "las actas con serie 900 fueron creadas para cometer un fraude electoral",
        )

    def test_claim_extractor_projects_embedded_factcheck_claims(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            "PerÃºCheck: Es falso el video de Inka VisiÃ³n de Cusco que demostrarÃ­a que se le han quitado votos a Jorge Nieto",
            None,
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].extraction_mode, "factcheck_embedded")
        self.assertEqual(
            claims[0].stance_target,
            "se le han quitado votos a jorge nieto",
        )

    def test_claim_extractor_prefers_quantified_official_claim_over_crisis_lead(self):
        extractor = ClaimExtractor(
            ClaimExtractionConfig(max_claims=1, min_words=6, max_words=40, max_candidates=10)
        )

        claims = extractor.extract_with_metadata(
            "Pleno del JNE evalúa salidas en medio de la crisis electoral",
            (
                "Aunque no pública, una intensa jornada se desarrolló este miércoles 22 de abril "
                "al interior del Jurado Nacional de Elecciones JNE. "
                "También mencionó que se habían remitido a los distintos Jurados Electorales "
                "Especiales 50,983 actas observadas."
            ),
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].extraction_mode, "reported_claim")
        self.assertEqual(
            claims[0].stance_target,
            "se habían remitido a los distintos Jurados Electorales Especiales 50,983 actas observadas",
        )

    def test_claim_extractor_discards_low_value_political_opinion_targets(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            'Alfonso López Chau: "El pacto mafioso quiere una presidencia entre sus candidatos"',
            (
                "El exrector de la Universidad Nacional de Ingeniería UNI afirmó que esta decisión "
                "afecta al sistema democrático. Aceptar una renuncia que la ley prohíbe y promover "
                "elecciones complementarias sin sustento legal es abrir la puerta a una maniobra "
                "antidemocrática."
            ),
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_projects_flexible_reporting_after_source_phrase(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            (
                "Burneo dijo a este diario que Corvetto nos mintio a todos. "
                "Asimismo, senalo que la Contraloria remitio un informe completo."
            ),
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].extraction_mode, "reported_claim")
        self.assertEqual(
            claims[0].stance_target,
            "la Contraloria remitio un informe completo",
        )
        self.assertIn("Contraloria remitio un informe completo", claims[0].model_input)

    def test_claim_extractor_builds_self_contained_model_input_for_reported_result(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            (
                "Sin embargo, la Oficina Nacional de Procesos Electorales ONPE, "
                "al 100 de actas contabilizadas en Lambayeque, reporto que "
                "Keiko Fujimori, de Fuerza Popular, obtuvo el primer lugar."
            ),
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(
            claims[0].stance_target,
            "Keiko Fujimori, de Fuerza Popular, obtuvo el primer lugar",
        )
        self.assertIn("ONPE", claims[0].model_input)
        self.assertIn("Lambayeque", claims[0].model_input)
        self.assertIn("100", claims[0].model_input)
        self.assertIn("Keiko Fujimori", claims[0].model_input)

    def test_claim_extractor_discards_weak_context_dependent_reported_claims(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            "Balcazar sostuvo que su gestion mantiene compromisos que demandan recursos.",
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_strips_sourceless_reporting_prefix_from_model_input(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            (
                "Tambien menciono que se habian remitido a los distintos "
                "Jurados Electorales Especiales 50,983 actas observadas."
            ),
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(
            claims[0].stance_target,
            "se habian remitido a los distintos Jurados Electorales Especiales 50,983 actas observadas",
        )
        self.assertEqual(claims[0].model_input, claims[0].stance_target)

    def test_claim_extractor_discards_sourceless_future_procedure_claims(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            "Preciso que evaluara que medidas se tomaran respecto a la carta notarial.",
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_discards_speculative_or_low_value_future_claims(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            (
                "El proximo Congreso podria ser presidido por el parlamentario mas votado. "
                "El lider reafirmo su voluntad de mantener dialogos con otros partidos."
            ),
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_discards_summary_credit_and_numeric_fragments(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            (
                "Cancilleria confirma retorno de 7 peruanos desde Rusia Leer resumen "
                "La Cancilleria confirmo que siete peruanos retornaron al pais. "
                "Creditos: Adrian Sarria Munoz La detencion preliminar era por 15 dias. "
                "903706, donde, segun sus registros, el candidato obtuvo 55 votos. "
                "-Los genios se impuso como el libro del 2023."
            ),
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_discards_rhetorical_trust_statements(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            (
                "La confianza de los peruanos no se gana firmando hojas de compromiso, "
                "sino con acciones claras y gestos politicos comprobables."
            ),
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_discards_question_and_first_person_candidates(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            "Keiko Fujimori: Soy respetuosa de lo que el JNE vaya a determinar",
            (
                "Estoy de acuerdo con que puedan ir a votar las personas que no pudieron hacerlo. "
                "Cuántos votos posibles hay para una nueva constitución?"
            ),
        )

        self.assertEqual(claims, [])

    def test_claim_extractor_projects_segun_attribution_targets(self):
        extractor = ClaimExtractor()

        claims = extractor.extract_with_metadata(
            None,
            (
                "Según afirmó el organismo electoral, el comité continuará brindando "
                "acompañamiento técnico durante la segunda vuelta electoral."
            ),
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].extraction_mode, "reported_claim")
        self.assertEqual(
            claims[0].stance_target,
            "el comité continuará brindando acompañamiento técnico durante la segunda vuelta electoral",
        )

    def test_claim_based_fake_news_prediction_uses_model_input(self):
        pipeline = NewsAnalysisPipeline()
        model_input = (
            "La ONPE reporto que Keiko Fujimori obtuvo el primer lugar "
            "en Lambayeque al 100 de actas contabilizadas."
        )
        pipeline.claim_extractor = Mock()
        pipeline.claim_extractor.strategy_name = "heuristic_test"
        pipeline.claim_extractor.config = Mock(max_claims=3)
        pipeline.claim_extractor.extract_with_metadata.return_value = [
            ExtractedClaim(
                text=model_input,
                stance_target="Keiko Fujimori obtuvo el primer lugar",
                extraction_mode="reported_claim",
                model_input=model_input,
            )
        ]

        with patch.object(
            pipeline,
            "_predict_fake_news",
            return_value={
                "label": "True",
                "display_label": "verdadero",
                "confidence": 0.8,
                "probabilities": {"False": 0.2, "True": 0.8},
                "ranking": [],
                "source": "dedicated_fakenews_classifier",
                "decision_threshold": 0.57,
            },
        ) as mock_predict:
            prediction = pipeline._predict_fake_news_from_claims_without_stance(
                "titulo",
                "cuerpo",
                "articulo completo",
            )

        mock_predict.assert_called_once_with(model_input)
        claim_item = prediction["claims"]["items"][0]
        self.assertEqual(claim_item["stance_target"], "Keiko Fujimori obtuvo el primer lugar")
        self.assertEqual(claim_item["model_input"], model_input)

    def test_claim_aggregation_reduces_risk_when_article_refutes_false_claim(self):
        pipeline = NewsAnalysisPipeline()
        pipeline.stance_classifier.loaded = True
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
        self.assertEqual(prediction["triage_label"], "likely_real")

    def test_claim_aggregation_keeps_high_risk_when_article_supports_false_claim(self):
        pipeline = NewsAnalysisPipeline()
        pipeline.stance_classifier.loaded = True
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
                        "unrelated": 0.0,
                        "discuss": 0.0,
                        "agree": 1.0,
                        "disagree": 0.0,
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
        self.assertEqual(prediction["triage_label"], "likely_fake")


if __name__ == "__main__":
    unittest.main()
