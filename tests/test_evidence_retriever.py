import unittest

from app.ml.evidence_retriever import EvidenceRetriever


class WhitespaceTokenizer:
    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": list(range(len((text or "").split())))}

    @staticmethod
    def num_special_tokens_to_add(pair=True):
        return 3 if pair else 2

    @staticmethod
    def decode(ids, skip_special_tokens=True):
        return " ".join(f"tok{index}" for index in ids)


class EvidenceRetrieverTests(unittest.TestCase):
    def test_selects_claim_window_and_refutation_window(self):
        retriever = EvidenceRetriever()
        result = retriever.select(
            claim="El JNE publico una encuesta electoral falsa",
            title="El JNE desmiente encuesta difundida en redes",
            body=(
                "La jornada comenzó con otras noticias. "
                "En redes se atribuyó al JNE una encuesta electoral. "
                "El organismo señaló que no publicó esa encuesta y rechazó el contenido. "
                "La imagen fue fabricada por una cuenta anónima."
            ),
            tokenizer=WhitespaceTokenizer(),
            max_length=64,
        )

        self.assertIn("El JNE desmiente encuesta", result.context)
        self.assertIn("no publicó esa encuesta", result.context)
        self.assertIsNotNone(result.primary_index)
        self.assertIsNotNone(result.verdict_index)

    def test_does_not_duplicate_title_already_present_in_body(self):
        retriever = EvidenceRetriever()
        title = "Cusco sí recibe recursos del gas de Camisea"
        result = retriever.select(
            claim="Cusco no recibe recursos del gas de Camisea",
            title=title,
            body=f"{title}. El canon financió obras regionales durante el año.",
            tokenizer=WhitespaceTokenizer(),
            max_length=64,
        )

        self.assertEqual(result.context.count(title), 1)

    def test_respects_pair_token_budget(self):
        retriever = EvidenceRetriever()
        tokenizer = WhitespaceTokenizer()
        claim = "afirmación breve"
        result = retriever.select(
            claim=claim,
            title="Título relevante",
            body=" ".join(["Oración extensa con evidencia pertinente."] * 30),
            tokenizer=tokenizer,
            max_length=24,
        )
        paired_length = (
            len(tokenizer(claim)["input_ids"])
            + len(tokenizer(result.context)["input_ids"])
            + tokenizer.num_special_tokens_to_add(pair=True)
        )

        self.assertLessEqual(paired_length, 24)


if __name__ == "__main__":
    unittest.main()
