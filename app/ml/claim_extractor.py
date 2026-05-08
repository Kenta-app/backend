from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_RE = re.compile(r"\b\w+\b", flags=re.UNICODE)
_CAPITAL_RE = re.compile(r"\b[A-Z][a-z]+\b")
_CODELIKE_PREFIX_RE = re.compile(r"^\s*[A-Z0-9]{1,8}(?:[-/][A-Z0-9]{1,8}){1,4}\b")

NOISY_CANDIDATE_MARKERS = (
    "puedes ver",
    "lee tambien",
    "lee también",
    "te puede interesar",
    "más información",
    "mas informacion",
    "últimas noticias",
    "ultimas noticias",
    "relacionado:",
    "relacionada:",
)

REFUTATION_MARKERS = (
    "niega que ",
    "niegan que ",
    "nego que ",
    "negaron que ",
    "desmiente que ",
    "desmienten que ",
    "desmintio que ",
    "desmintieron que ",
    "rechaza que ",
    "rechazan que ",
    "rechaza ",
    "rechazan ",
    "descarta que ",
    "descartan que ",
    "descarta ",
    "descartan ",
)

REPORTING_MARKERS = (
    "asegura que ",
    "aseguran que ",
    "afirma que ",
    "afirman que ",
    "sostiene que ",
    "sostienen que ",
    "dice que ",
    "dicen que ",
    "dijo que ",
    "declara que ",
    "declaran que ",
    "declaro que ",
    "anuncia que ",
    "anuncian que ",
    "anuncio que ",
    "confirma que ",
    "confirman que ",
    "informa que ",
    "informan que ",
    "detalla que ",
    "detallan que ",
    "revela que ",
    "revelan que ",
)

CLAIM_CUES = (
    "segun",
    "afirma",
    "asegura",
    "dijo",
    "declara",
    "declaro",
    "confirm",
    "report",
    "inform",
    "sostiene",
    "anuncio",
    "anuncia",
    "revela",
    "denunci",
    "acus",
    "reconocio",
    "reconoce",
    "aprobo",
    "veto",
    "publico",
    "establec",
    "promete",
)

FACT_VERBS = (
    "es",
    "son",
    "fue",
    "sera",
    "seran",
    "tiene",
    "tienen",
    "debe",
    "deben",
    "puede",
    "pueden",
)


@dataclass(frozen=True)
class ClaimExtractionConfig:
    max_claims: int
    min_words: int
    max_words: int
    max_candidates: int

    @classmethod
    def from_env(cls) -> "ClaimExtractionConfig":
        return cls(
            max_claims=int(os.getenv("CLAIM_MAX_CLAIMS", "3")),
            min_words=int(os.getenv("CLAIM_MIN_WORDS", "6")),
            max_words=int(os.getenv("CLAIM_MAX_WORDS", "40")),
            max_candidates=int(os.getenv("CLAIM_MAX_CANDIDATES", "30")),
        )


@dataclass(frozen=True)
class ExtractedClaim:
    text: str
    stance_target: str
    extraction_mode: str = "verbatim"


class ClaimExtractor:
    def __init__(self, config: ClaimExtractionConfig | None = None) -> None:
        self.config = config or ClaimExtractionConfig.from_env()

    @property
    def strategy_name(self) -> str:
        return "heuristic_v3"

    def extract_with_metadata(self, title: str | None, body: str | None) -> list[ExtractedClaim]:
        candidates: list[dict[str, object]] = []
        seen: set[str] = set()
        index = 0

        for text, origin in self._iter_candidates(title, body):
            normalized = self._normalize_text(text)
            if not normalized:
                continue
            if not self._is_candidate_usable(normalized):
                continue

            word_count = self._word_count(normalized)
            min_words = self.config.min_words - 2 if origin == "title" else self.config.min_words
            min_words = max(min_words, 3)
            if word_count < min_words or word_count > self.config.max_words:
                continue

            projected_claim = self._project_claim(normalized)
            dedupe_key = self._dedupe_key(projected_claim.stance_target)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            score = self._score_sentence(normalized, origin == "title")
            candidates.append(
                {
                    "claim": projected_claim,
                    "score": score,
                    "index": index,
                }
            )
            index += 1

            if len(candidates) >= self.config.max_candidates:
                break

        candidates.sort(key=lambda item: (-float(item["score"]), int(item["index"])))
        return [item["claim"] for item in candidates[: self.config.max_claims]]

    def extract(self, title: str | None, body: str | None) -> list[str]:
        return [claim.text for claim in self.extract_with_metadata(title, body)]

    def _iter_candidates(self, title: str | None, body: str | None):
        if title:
            yield title, "title"
        if body:
            for sentence in self._split_sentences(body):
                if sentence:
                    yield sentence, "body"

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        cleaned = " ".join(text.split())
        if not cleaned:
            return []
        return [segment.strip() for segment in _SENTENCE_SPLIT_RE.split(cleaned) if segment.strip()]

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.split())

    @staticmethod
    def _word_count(text: str) -> int:
        return len(_WORD_RE.findall(text))

    def _dedupe_key(self, text: str) -> str:
        lowered = self._strip_accents(text.lower())
        return re.sub(r"\W+", " ", lowered).strip()

    def _is_candidate_usable(self, text: str) -> bool:
        lowered = self._strip_accents(text.lower())
        if any(marker in lowered for marker in NOISY_CANDIDATE_MARKERS):
            return False

        if _CODELIKE_PREFIX_RE.match(text):
            return False

        return True

    def _project_claim(self, text: str) -> ExtractedClaim:
        lowered = self._strip_accents(text.lower())

        for marker in REFUTATION_MARKERS:
            target = self._slice_after_marker(text, lowered, marker)
            if target:
                return ExtractedClaim(
                    text=text,
                    stance_target=target,
                    extraction_mode="refutation_projected",
                )

        for marker in REPORTING_MARKERS:
            target = self._slice_after_marker(text, lowered, marker)
            if target:
                return ExtractedClaim(
                    text=text,
                    stance_target=target,
                    extraction_mode="reported_claim",
                )

        return ExtractedClaim(
            text=text,
            stance_target=text,
            extraction_mode="verbatim",
        )

    def _slice_after_marker(self, original_text: str, lowered_text: str, marker: str) -> str | None:
        marker_index = lowered_text.find(marker)
        if marker_index < 0:
            return None

        start = marker_index + len(marker)
        target = self._cleanup_projected_target(original_text[start:])
        if self._word_count(target) < 3:
            return None
        return target

    @staticmethod
    def _cleanup_projected_target(text: str) -> str:
        cleaned = text.strip(" :;,.\"'()[]")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _score_sentence(self, text: str, is_title: bool) -> float:
        score = 0.0
        lowered = self._strip_accents(text.lower())

        if is_title:
            score += 1.5
        if any(char.isdigit() for char in text):
            score += 1.5
        if len(_CAPITAL_RE.findall(text)) >= 2:
            score += 1.0
        if any(cue in lowered for cue in CLAIM_CUES):
            score += 1.0
        if any(verb in lowered.split() for verb in FACT_VERBS):
            score += 0.5
        if text.endswith("?"):
            score -= 0.5

        return score

    @staticmethod
    def _strip_accents(text: str) -> str:
        normalized = unicodedata.normalize("NFD", text)
        return "".join(char for char in normalized if unicodedata.category(char) != "Mn")
