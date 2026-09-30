from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


SPANISH_STOPWORDS = {
    "a", "al", "algo", "ante", "bajo", "con", "contra", "de", "del", "desde", "donde",
    "e", "el", "ella", "en", "entre", "era", "es", "esa", "ese", "esta", "este", "fue",
    "ha", "hasta", "hay", "la", "las", "le", "lo", "los", "más", "muy", "no", "o", "para",
    "pero", "por", "que", "se", "según", "ser", "si", "sin", "sobre", "su", "sus", "también",
    "un", "una", "y", "ya",
}

VERDICT_CUES = (
    "es falso", "es falsa", "falso", "falsa", "no es cierto", "no ocurrió", "no ocurrio",
    "desmint", "refut", "negó", "nego", "rechaz", "carece de sustento", "sin sustento",
    "imprecis", "engaños", "enganos", "incorrect", "rectific", "en realidad", "sino",
)


@dataclass(frozen=True)
class EvidenceSelection:
    context: str
    sentence_count: int
    selected_indexes: tuple[int, ...]
    primary_index: int | None
    verdict_index: int | None

    def metadata(self) -> dict[str, Any]:
        return {
            "strategy": "tfidf_overlap_verdict_windows_v1",
            "sentence_count": self.sentence_count,
            "selected_indexes": list(self.selected_indexes),
            "primary_index": self.primary_index,
            "verdict_index": self.verdict_index,
            "context_chars": len(self.context),
            "context_preview": self.context[:280],
        }


class EvidenceRetriever:
    """Select the title and claim-relevant sentence windows used by stance v1."""

    @staticmethod
    def _normalized(text: str) -> str:
        text = unicodedata.normalize("NFKC", text or "").casefold()
        text = "".join(
            char
            for char in unicodedata.normalize("NFD", text)
            if unicodedata.category(char) != "Mn"
        )
        text = re.sub(r"[^\w%]+", " ", text, flags=re.UNICODE)
        return " ".join(text.split())

    @classmethod
    def _content_tokens(cls, text: str) -> set[str]:
        return {
            token
            for token in cls._normalized(text).split()
            if len(token) > 2 and token not in SPANISH_STOPWORDS
        }

    @staticmethod
    def _sentence_split(text: str) -> list[str]:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return []
        pieces = re.split(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡"“])', cleaned)
        return [piece.strip() for piece in pieces if piece.strip()]

    @classmethod
    def _strip_repeated_title(cls, title: str, body: str) -> str:
        title_clean = " ".join((title or "").split())
        body_clean = " ".join((body or "").split())
        if title_clean and body_clean.casefold().startswith(title_clean.casefold()):
            return body_clean[len(title_clean):].lstrip(" .:-—|")
        return body_clean

    @classmethod
    def _relevance_scores(cls, claim: str, sentences: list[str]) -> list[float]:
        try:
            vectorizer = TfidfVectorizer(
                lowercase=True,
                strip_accents="unicode",
                ngram_range=(1, 2),
                sublinear_tf=True,
            )
            matrix = vectorizer.fit_transform([claim, *sentences])
            cosine = cosine_similarity(matrix[0:1], matrix[1:]).ravel()
        except ValueError:
            cosine = np.zeros(len(sentences), dtype=float)
        claim_tokens = cls._content_tokens(claim)
        claim_norm = cls._normalized(claim)
        scores = []
        for index, sentence in enumerate(sentences):
            sentence_tokens = cls._content_tokens(sentence)
            overlap = len(claim_tokens & sentence_tokens) / max(1, len(claim_tokens))
            exact_bonus = 1.5 if claim_norm and claim_norm in cls._normalized(sentence) else 0.0
            scores.append(float(cosine[index]) + overlap + exact_bonus)
        return scores

    @classmethod
    def _verdict_score(cls, sentence: str, claim: str, base_score: float) -> float:
        lowered = cls._normalized(sentence)
        cue_count = sum(cue in lowered for cue in VERDICT_CUES)
        if not cue_count:
            return -1.0
        claim_tokens = cls._content_tokens(claim)
        overlap = len(cls._content_tokens(sentence) & claim_tokens) / max(1, len(claim_tokens))
        return base_score + (0.35 * cue_count) + overlap

    @staticmethod
    def _fit_token_budget(tokenizer, claim: str, pieces: list[str], max_length: int) -> str:
        claim_ids = tokenizer(claim, add_special_tokens=False)["input_ids"]
        budget = max_length - len(claim_ids) - tokenizer.num_special_tokens_to_add(pair=True)
        budget = max(24, budget)
        kept: list[str] = []
        used = 0
        for piece in pieces:
            piece = " ".join((piece or "").split())
            if not piece or piece in kept:
                continue
            ids = tokenizer(piece, add_special_tokens=False)["input_ids"]
            remaining = budget - used
            if remaining <= 0:
                break
            if len(ids) <= remaining:
                kept.append(piece)
                used += len(ids)
            elif not kept:
                kept.append(tokenizer.decode(ids[:remaining], skip_special_tokens=True))
                used = budget
        return " ".join(kept).strip()

    def select(
        self,
        *,
        claim: str,
        title: str,
        body: str,
        tokenizer,
        max_length: int,
    ) -> EvidenceSelection:
        title_clean = " ".join((title or "").split())
        article = self._strip_repeated_title(title_clean, body)
        sentences = self._sentence_split(article)
        if not sentences:
            context = self._fit_token_budget(
                tokenizer, claim, [title_clean, article], max_length,
            )
            return EvidenceSelection(context, 0, tuple(), None, None)

        scores = self._relevance_scores(claim, sentences)
        primary = max(range(len(sentences)), key=lambda index: scores[index])
        selected = {primary}
        if primary > 0:
            selected.add(primary - 1)
        if primary + 1 < len(sentences):
            selected.add(primary + 1)

        verdict_candidates = [
            (self._verdict_score(sentence, claim, scores[index]), index)
            for index, sentence in enumerate(sentences)
        ]
        verdict_value, verdict_index = max(verdict_candidates)
        if verdict_value >= 0:
            selected.add(verdict_index)
            if verdict_index > 0:
                selected.add(verdict_index - 1)
            if verdict_index + 1 < len(sentences):
                selected.add(verdict_index + 1)
        else:
            verdict_index = None

        ordered = [sentences[index] for index in sorted(selected)]
        context = self._fit_token_budget(
            tokenizer, claim, [title_clean, *ordered], max_length,
        )
        return EvidenceSelection(
            context=context,
            sentence_count=len(sentences),
            selected_indexes=tuple(sorted(selected)),
            primary_index=primary,
            verdict_index=verdict_index,
        )
