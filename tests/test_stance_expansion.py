import unittest
import csv
import tempfile
from pathlib import Path

from scripts.build_stance_annotation_batch import (
    BLIND_FIELDS, VERIFIED_REFUTATION_FIELDS, build_candidates,
    load_verified_refutations, select_batch,
)
from scripts.collect_stance_articles import extract_article


class StanceExpansionTests(unittest.TestCase):
    def test_blind_export_has_no_strategy_prediction_or_label(self):
        self.assertNotIn("candidate_strategy", BLIND_FIELDS)
        self.assertFalse(any("prediction" in field for field in BLIND_FIELDS))
        self.assertFalse(any("label" in field for field in BLIND_FIELDS))

    def test_jsonld_article_snapshot_is_extracted(self):
        body = " ".join(["Texto político peruano con información verificable."] * 20)
        html = f'''<html><head><script type="application/ld+json">{{
          "@type":"NewsArticle", "headline":"El Congreso aprobó una reforma política relevante",
          "datePublished":"2026-09-15", "articleBody":"{body}"
        }}</script></head><body><h1>Título alterno</h1></body></html>'''

        article = extract_article(html, "https://example.pe/noticia/1")

        self.assertEqual(article["title"], "El Congreso aprobó una reforma política relevante")
        self.assertGreaterEqual(len(article["article"]), 500)
        self.assertEqual(article["published_at"], "2026-09-15")

    def test_candidate_pool_uses_human_authored_claim_texts(self):
        articles = [
            {
                "article_id": "art_1", "group_id": "article:art_1", "source_name": "Fuente A",
                "title": "La autoridad negó que se hayan alterado los resultados electorales",
                "original_url": "https://a.pe/1", "published_at": "2026-09-15",
                "article": ("La autoridad negó que se hayan alterado los resultados electorales. "
                            "El organismo aseguró que las actas fueron procesadas con normalidad. ") * 8,
            },
            {
                "article_id": "art_2", "group_id": "article:art_2", "source_name": "Fuente B",
                "title": "Denuncian una presunta alteración de resultados electorales en Lima",
                "original_url": "https://b.pe/2", "published_at": "2026-09-15",
                "article": ("Un candidato denunció que El organismo alteró los resultados electorales en Lima. "
                            "La fiscalía informó que revisará la acusación presentada. ") * 8,
            },
            {
                "article_id": "art_3", "group_id": "article:art_3", "source_name": "Fuente C",
                "title": "El Congreso debate medidas para mejorar la seguridad ciudadana",
                "original_url": "https://c.pe/3", "published_at": "2026-09-15",
                "article": ("El Congreso debate medidas para mejorar la seguridad ciudadana. "
                            "La comisión recibió propuestas de distintas bancadas parlamentarias. ") * 8,
            },
        ]

        candidates = build_candidates(articles)

        strategies = {row["candidate_strategy"] for row in candidates}
        self.assertIn("same_article_title", strategies)
        self.assertIn("reported_claim", strategies)
        self.assertNotIn("explicit_refutation", strategies)
        self.assertTrue(all(20 <= len(row["claim"]) <= 240 for row in candidates))

    def test_refutation_requires_reviewed_source_and_literal_article_evidence(self):
        article = {
            "article_id": "art_checked", "group_id": "article:art_checked",
            "source_name": "Fuente peruana", "title": "La entidad aclaró el dato electoral",
            "original_url": "https://medio.pe/nota", "published_at": "2026-09-20",
            "article": "La entidad verificó las actas originales y confirmó que ninguna mesa fue eliminada del cómputo.",
        }
        record = {
            "claim": "La entidad eliminó mesas del cómputo electoral",
            "claim_source_url": "https://origen.pe/declaracion",
            "claim_source_quote": "La entidad eliminó mesas del cómputo electoral",
            "target_article_id": "art_checked",
            "refutation_evidence": "confirmó que ninguna mesa fue eliminada del cómputo",
            "reviewer_code": "R1",
            "review_note": "La negación afecta el mismo hecho central del claim.",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviewed.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=VERIFIED_REFUTATION_FIELDS)
                writer.writeheader()
                writer.writerow(record)
            reviewed = load_verified_refutations(path, [article], batch_id="expansion_calibration_02")
            self.assertEqual(len(reviewed), 1)
            self.assertEqual(reviewed[0]["candidate_strategy"], "explicit_refutation")
            self.assertEqual(reviewed[0]["batch_id"], "expansion_calibration_02")
            self.assertNotIn("claim_source_url", BLIND_FIELDS)
            record["refutation_evidence"] = "Un texto que no figura en el artículo de destino."
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=VERIFIED_REFUTATION_FIELDS)
                writer.writeheader()
                writer.writerow(record)
            with self.assertRaisesRegex(ValueError, "must quote the target article"):
                load_verified_refutations(path, [article], batch_id="expansion_calibration_02")

    def test_selection_fails_closed_without_reviewed_refutations(self):
        with self.assertRaisesRegex(ValueError, "supply --verified-refutations"):
            select_batch([], per_strategy=1, seed=42)


if __name__ == "__main__":
    unittest.main()
