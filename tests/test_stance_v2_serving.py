import json
import tempfile
import unittest
from pathlib import Path

from app.ml.pipeline import NewsAnalysisPipeline
from app.ml.stance_classifier import StanceClassifier, StanceServingConfig


class StanceV2ServingTests(unittest.TestCase):
    def test_serving_config_recognizes_hierarchical_architecture(self):
        config = StanceServingConfig.from_dict({
            "architecture": "hierarchical_stance_v2",
            "label_names": ["unrelated", "discuss", "agree", "disagree"],
            "max_length": 384,
        })

        self.assertEqual(config.architecture, "hierarchical_stance_v2")
        self.assertEqual(config.max_length, 384)

    def test_checkpoint_exists_requires_complete_hierarchical_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stage_a_base_nli").mkdir()
            (root / "stage_b_relation").mkdir()
            (root / "serving_config.json").write_text("{}", encoding="utf-8")
            (root / "stage_a_relevance.joblib").write_bytes(b"placeholder")
            (root / "stage_a_base_nli" / "config.json").write_text("{}", encoding="utf-8")
            (root / "stage_b_relation" / "config.json").write_text("{}", encoding="utf-8")

            self.assertTrue(StanceClassifier(str(root)).checkpoint_exists)

    def test_pipeline_prefers_newest_v2_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "stance_es_pe_v2" / "final_model_2026_09_29"
            candidate.mkdir(parents=True)
            (candidate / "serving_config.json").write_text(
                json.dumps({"architecture": "hierarchical_stance_v2"}), encoding="utf-8"
            )

            resolved = NewsAnalysisPipeline._resolve_stance_model_dir(None, output_root=str(root))

            self.assertEqual(Path(resolved), candidate)


if __name__ == "__main__":
    unittest.main()
