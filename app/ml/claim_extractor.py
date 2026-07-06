from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_RE = re.compile(r"\b\w+\b", flags=re.UNICODE)
_CAPITAL_RE = re.compile(r"\b[A-Z][a-z]+\b")
_CODELIKE_PREFIX_RE = re.compile(r"^\s*[A-Z0-9]{1,8}(?:[-/][A-Z0-9]{1,8}){1,4}\b")
_NUMERIC_FRAGMENT_PREFIX_RE = re.compile(r"^\s*\d{4,}\b")
_BULLET_FRAGMENT_PREFIX_RE = re.compile(r"^\s*[-–—]\S")
_DIRECT_QUOTE_RE = re.compile(r":\s*[\"“”']")

NOISY_CANDIDATE_MARKERS = (
    "leer resumen",
    "creditos:",
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
    "aseguro que ",
    "afirma que ",
    "afirman que ",
    "afirmo que ",
    "sostiene que ",
    "sostienen que ",
    "sostuvo que ",
    "dice que ",
    "dicen que ",
    "dijo que ",
    "declara que ",
    "declaran que ",
    "declaro que ",
    "anuncia que ",
    "anuncian que ",
    "anuncio que ",
    "adelanta que ",
    "adelantan que ",
    "adelanto que ",
    "confirma que ",
    "confirman que ",
    "confirmaron que ",
    "confirmo que ",
    "reporta que ",
    "reportan que ",
    "reporto que ",
    "reportaron que ",
    "informa que ",
    "informan que ",
    "informo que ",
    "detalla que ",
    "detallan que ",
    "detallo que ",
    "revela que ",
    "revelan que ",
    "revelo que ",
    "senala que ",
    "senalan que ",
    "senalo que ",
    "subraya que ",
    "subrayan que ",
    "subrayo que ",
    "indica que ",
    "indican que ",
    "indico que ",
    "precisa que ",
    "precisan que ",
    "preciso que ",
    "manifiesta que ",
    "manifiestan que ",
    "manifesto que ",
    "expresa que ",
    "expresan que ",
    "expreso que ",
    "menciona que ",
    "mencionan que ",
    "menciono que ",
)

FLEXIBLE_REPORTING_VERBS = (
    "afirma",
    "afirman",
    "afirmo",
    "asegura",
    "aseguran",
    "aseguro",
    "dice",
    "dicen",
    "dijo",
    "indica",
    "indican",
    "indico",
    "informa",
    "informan",
    "informo",
    "reporta",
    "reportan",
    "reporto",
    "reportaron",
    "senala",
    "senalan",
    "senalo",
    "sostiene",
    "sostienen",
    "sostuvo",
    "confirmaron",
    "subraya",
    "subrayan",
    "subrayo",
)

CLAIM_CUES = (
    "segun",
    "afirma",
    "afirmo",
    "asegura",
    "aseguro",
    "dijo",
    "declara",
    "declaro",
    "senala",
    "senalo",
    "indica",
    "indico",
    "menciona",
    "menciono",
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

SUBJECTIVE_FIRST_PERSON_MARKERS = (
    "yo ",
    "yo no ",
    "he ",
    "hemos ",
    "no he ",
    "no hemos ",
    "nosotros ",
    "nos corresponde ",
    "nuestro ",
    "nuestra ",
    "nuestros ",
    "nuestras ",
    "me ",
    "mi ",
    "mis ",
    "soy ",
    "somos ",
    "estoy ",
    "estamos ",
    "descartamos ",
    "tengamos ",
    "quiero ",
    "creo ",
    "pienso ",
    "considero ",
    "opino ",
    "he buscado ",
    "voy a ",
    "esperamos ",
    "vamos a ",
)

NORMATIVE_OR_OPINION_MARKERS = (
    "tiene que ",
    "tienen que ",
    "debe ",
    "deben ",
    "hay que ",
    "corresponde ",
    "prudencia",
    "respeto",
    "respetuosa",
    "receta al fracaso",
    "fracaso",
    "verdadero fraude",
    "mafioso",
    "imbecil",
    "imbécil",
    "dudas",
    "certezas",
    "no son correctas",
    "afecta al sistema democratico",
    "antidemocratica",
    "etapa de negacion",
    "ha dilapidado",
    "solo tenemos certezas",
    "tengamos dudas",
    "tono confrontacional",
    "se modero",
    "determinante conocer",
    "disparate",
    "aberrante",
    "capricho",
    "prudente",
    "no debia ",
    "deberia ",
    "aceptaria ",
    "es necesario ",
    "izquierda radical",
    "totalitaria",
    "busca ser ambigua",
    "no debia cargar",
    "mintio",
    "mentido al pais",
    "sin sustento",
    "sin ningun calculo politico",
    "lo que se discute",
    "profundo anhelo",
    "postura a favor",
    "estoy de acuerdo",
    "soy respetuosa",
    "respetara lo que",
    "lo que tenemos que preguntarnos",
    "cuantos votos posibles",
    "que va a hacer",
    "deseo de verlo",
    "cuestionarlo con dureza",
    "demostro ser",
    "mas madura",
    "vergonzoso",
    "inaceptable",
)

OPINION_ATTRIBUTION_MARKERS = (
    "senalo",
    "señaló",
    "aseguro",
    "aseguró",
    "subrayo",
    "subrayó",
    "respondio",
    "respondió",
    "apunto",
    "apuntó",
    "indico",
    "preciso",
    "manifesto",
    "expreso",
    "en su cuenta de x",
    "antes twitter",
)

LOW_VALUE_TARGET_MARKERS = (
    "leer resumen",
    "es lo que mencionabas",
    "intensa jornada se desarrollo",
    "evalua salidas en medio",
    "evaluara que medidas",
    "que medidas se tomaran",
    "enviara representantes",
    "propondra un programa",
    "se presentara a licitacion",
    "se continuara con el proceso",
    "podria ser",
    "podrian estar",
    "debera ahora anunciar",
    "puede generar un credito suplementario",
    "les gustaria firmar",
    "reafirmo su voluntad",
    "mantener dialogos",
    "confianza de los peruanos no se gana",
    "no se gana firmando hojas",
    "gestos politicos comprobables",
    "narra lo que paso",
    "actitudes dictatoriales",
    "bien lo resumia",
    "comunicacion y la posibilidad de formar alianzas",
    "se mantienen hasta el momento",
    "publico una infografia",
    "publico en su cuenta de x",
    "expuso el panorama politico",
    "lo que se discute es",
    "todo el mundo encuentra",
    "ningun caso invalida",
    "abrir la puerta",
    "no es culpa",
    "no estan contentos",
    "recordarles",
    "han dicho",
    "resulta evidente",
    "esta percepcion",
    "pacto del congreso",
    "no tiene ningun basamento",
    "presion mediatica",
    "afectando gravemente",
    "es importante que",
    "se considera",
    "rompe reglas",
    "le gustaria",
    "hay que llamar",
    "no sera motivo de confrontacion",
    "es cosa de mi partido",
    "el remedio puede ser peor",
)

DISCOURSE_PREFIXES = (
    "no obstante",
    "sin embargo",
    "en ese contexto",
    "por otro lado",
    "en esa linea",
    "de esta manera",
    "sobre ",
    "frente a",
)

OFFICIAL_SOURCE_MARKERS = (
    "contraloria",
    "congreso",
    "fiscalia",
    "fap",
    "indecopi",
    "jne",
    "jnj",
    "ministerio publico",
    "onpe",
    "poder judicial",
)

ACTION_VERB_CUES = (
    "aprobo",
    "archivo",
    "asumio",
    "autorizo",
    "contabilizadas",
    "designan",
    "designo",
    "entrego",
    "firmo",
    "obtuvo",
    "presento",
    "publico",
    "recibido",
    "recibieron",
    "remitio",
    "reporta",
    "reporto",
    "renuncio",
)

QUESTION_PREFIXES = (
    "que ",
    "quien ",
    "quienes ",
    "cuando ",
    "cuanto ",
    "cuantos ",
    "cuales ",
    "como ",
    "por que ",
)

CONTEXT_DEPENDENT_PREFIXES = (
    "su ",
    "sus ",
    "este ",
    "esta ",
    "estos ",
    "estas ",
    "ese ",
    "esa ",
    "esos ",
    "esas ",
    "dicho ",
    "dicha ",
    "dichos ",
    "dichas ",
    "ello ",
    "esto ",
)

AMBIGUOUS_SUBJECT_PREFIXES = (
    "se ",
)

WEAK_GENERIC_TARGET_MARKERS = (
    "mantiene compromisos que demandan recursos",
    "mantiene compromisos",
    "demandan recursos",
)

SOURCELESS_REPORTING_PREFIXES = (
    "tambien afirmo que ",
    "tambien aseguro que ",
    "tambien detallo que ",
    "tambien indico que ",
    "tambien menciono que ",
    "tambien preciso que ",
    "tambien senalo que ",
    "asimismo afirmo que ",
    "asimismo aseguro que ",
    "asimismo detallo que ",
    "asimismo indico que ",
    "asimismo menciono que ",
    "asimismo preciso que ",
    "asimismo senalo que ",
    "ademas afirmo que ",
    "ademas aseguro que ",
    "ademas detallo que ",
    "ademas indico que ",
    "ademas menciono que ",
    "ademas preciso que ",
    "ademas senalo que ",
    "afirmo que ",
    "aseguro que ",
    "detallo que ",
    "dice que ",
    "dijo que ",
    "indico que ",
    "menciono que ",
    "preciso que ",
    "senalo que ",
)

FACTCHECK_SOURCE_PREFIXES = (
    "perucheck",
    "newtral",
    "maldita",
    "maldita.es",
    "chequeado",
    "afp factual",
)

FACTCHECK_VERDICT_MARKERS = (
    "es falso",
    "es falsa",
    "fue falso",
    "fue falsa",
    "es verdadero",
    "es verdadera",
    "fue verdadero",
    "fue verdadera",
    "es enganoso",
    "es engañoso",
    "es impreciso",
    "es incorrecto",
)

FACTCHECK_CLAIM_MARKERS = (
    "es falso que ",
    "es falsa que ",
    "es verdadero que ",
    "es verdadera que ",
    "falso que ",
    "falsa que ",
    "verdadero que ",
    "verdadera que ",
    "enganoso que ",
    "engañoso que ",
    "incorrecto que ",
    "impreciso que ",
)

FACTCHECK_EMBEDDED_CLAIM_MARKERS = (
    "demostraria que ",
    "demostraría que ",
    "mostraria que ",
    "mostraría que ",
    "muestra que ",
    "probaria que ",
    "probaría que ",
    "prueba que ",
    "evidencia que ",
    "revela que ",
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
    model_input: str | None = None
    quality: str = "usable"
    quality_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.model_input is None:
            object.__setattr__(self, "model_input", self.stance_target)


class ClaimExtractor:
    def __init__(self, config: ClaimExtractionConfig | None = None) -> None:
        self.config = config or ClaimExtractionConfig.from_env()

    @property
    def strategy_name(self) -> str:
        return "heuristic_v9"

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
            if not self._is_claim_verifiable(projected_claim):
                continue
            dedupe_key = self._dedupe_key(projected_claim.stance_target)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            score = self._score_sentence(normalized, origin == "title", projected_claim)
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

    def _has_objective_signal(self, lowered_text: str, original_text: str) -> bool:
        return (
            any(char.isdigit() for char in original_text)
            or any(marker in lowered_text for marker in OFFICIAL_SOURCE_MARKERS)
            or any(cue in lowered_text for cue in ACTION_VERB_CUES)
        )

    @staticmethod
    def _contains_phrase_marker(lowered_text: str, markers: tuple[str, ...]) -> bool:
        padded_text = f" {lowered_text} "
        return any(f" {marker.strip()} " in padded_text for marker in markers)

    def _build_claim(self, text: str, target: str, extraction_mode: str) -> ExtractedClaim:
        cleaned_target = self._cleanup_projected_target(target)
        model_input = self._build_model_input(text, cleaned_target, extraction_mode)
        quality_reasons = self._claim_quality_reasons(
            target=cleaned_target,
            model_input=model_input,
            extraction_mode=extraction_mode,
        )
        quality = "usable" if not quality_reasons else "skip"
        return ExtractedClaim(
            text=text,
            stance_target=cleaned_target,
            extraction_mode=extraction_mode,
            model_input=model_input,
            quality=quality,
            quality_reasons=quality_reasons,
        )

    def _build_model_input(self, text: str, target: str, extraction_mode: str) -> str:
        if extraction_mode.startswith("factcheck_"):
            return target
        if extraction_mode == "verbatim":
            return target

        cleaned_text = self._cleanup_projected_target(text)
        lowered_cleaned_text = self._strip_accents(cleaned_text.lower())
        if lowered_cleaned_text.startswith(SOURCELESS_REPORTING_PREFIXES):
            return target

        if self._word_count(cleaned_text) < self._word_count(target):
            return target
        return cleaned_text

    def _claim_quality_reasons(
        self,
        *,
        target: str,
        model_input: str,
        extraction_mode: str,
    ) -> tuple[str, ...]:
        lowered_target = self._strip_accents(target.lower())
        lowered_model_input = self._strip_accents(model_input.lower())
        reasons: list[str] = []

        if any(marker in lowered_target for marker in WEAK_GENERIC_TARGET_MARKERS):
            reasons.append("low_value_generic_claim")

        if self._starts_with_context_dependent_prefix(lowered_target):
            if model_input == target:
                reasons.append("context_dependent_target")
            elif not self._has_objective_signal(lowered_model_input, model_input):
                reasons.append("context_dependent_without_objective_context")

        if (
            extraction_mode in {"reported_claim", "refutation_projected"}
            and model_input == target
            and self._looks_under_contextualized(lowered_target)
        ):
            reasons.append("under_contextualized_reported_claim")

        if extraction_mode in {"reported_claim", "refutation_projected"}:
            if self._starts_with_ambiguous_subject(lowered_target) and not self._has_explicit_actor(target):
                reasons.append("missing_explicit_actor")

        return tuple(reasons)

    @staticmethod
    def _starts_with_context_dependent_prefix(lowered_text: str) -> bool:
        return lowered_text.startswith(CONTEXT_DEPENDENT_PREFIXES)

    @staticmethod
    def _starts_with_ambiguous_subject(lowered_text: str) -> bool:
        return lowered_text.startswith(AMBIGUOUS_SUBJECT_PREFIXES)

    def _has_explicit_actor(self, text: str) -> bool:
        lowered = self._strip_accents(text.lower())
        if any(marker in lowered for marker in OFFICIAL_SOURCE_MARKERS):
            return True
        if _CAPITAL_RE.search(text):
            return True
        if any(char.isdigit() for char in text):
            return True
        return False

    def _looks_under_contextualized(self, lowered_text: str) -> bool:
        return self._starts_with_context_dependent_prefix(lowered_text)

    def _is_candidate_usable(self, text: str) -> bool:
        lowered = self._strip_accents(text.lower())
        if any(marker in lowered for marker in NOISY_CANDIDATE_MARKERS):
            return False

        if _CODELIKE_PREFIX_RE.match(text):
            return False

        if _NUMERIC_FRAGMENT_PREFIX_RE.match(text):
            return False

        if _BULLET_FRAGMENT_PREFIX_RE.match(text):
            return False

        return True

    def _is_claim_verifiable(self, claim: ExtractedClaim) -> bool:
        text = claim.text
        target = claim.stance_target
        lowered_text = self._strip_accents(text.lower())
        lowered_target = self._strip_accents(target.lower())
        model_input = claim.model_input or target
        lowered_model_input = self._strip_accents(model_input.lower())

        direct_quote_like = bool(_DIRECT_QUOTE_RE.search(text)) or any(char in text for char in ("“", "”", "\""))
        first_person = self._contains_phrase_marker(lowered_target, SUBJECTIVE_FIRST_PERSON_MARKERS)
        normative_or_opinion = any(marker in lowered_target for marker in NORMATIVE_OR_OPINION_MARKERS)
        opinion_attribution = any(marker in lowered_text for marker in OPINION_ATTRIBUTION_MARKERS)
        low_value_target = any(marker in lowered_target for marker in LOW_VALUE_TARGET_MARKERS)
        objective_signal = self._has_objective_signal(lowered_model_input, model_input)
        unicode_quote_like = any(char in text for char in ("\u201c", "\u201d"))

        if claim.quality != "usable":
            return False

        if first_person:
            return False

        if (unicode_quote_like or ":" in text) and (first_person or normative_or_opinion):
            return False

        if direct_quote_like and (first_person or normative_or_opinion):
            return False

        if lowered_target.startswith(SUBJECTIVE_FIRST_PERSON_MARKERS):
            return False

        if low_value_target:
            return False

        if claim.extraction_mode != "factcheck_question" and (
            text.endswith("?") or lowered_target.startswith(QUESTION_PREFIXES)
        ):
            return False

        if normative_or_opinion and opinion_attribution:
            return False

        if normative_or_opinion and not claim.extraction_mode.startswith("factcheck_"):
            return False

        if claim.extraction_mode == "verbatim" and not objective_signal:
            return False

        return True

    def _project_claim(self, text: str) -> ExtractedClaim:
        factcheck_claim = self._extract_factcheck_claim(text)
        if factcheck_claim is not None:
            return factcheck_claim

        lowered = self._strip_accents(text.lower())

        for marker in REFUTATION_MARKERS:
            target = self._slice_after_marker(text, lowered, marker)
            if target:
                return self._build_claim(text, target, "refutation_projected")

        for marker in REPORTING_MARKERS:
            target = self._slice_after_marker(text, lowered, marker)
            if target:
                return self._build_claim(text, target, "reported_claim")

        flexible_target = self._slice_after_flexible_reporting_marker(text, lowered)
        if flexible_target:
            return self._build_claim(text, flexible_target, "reported_claim")

        segun_target = self._extract_segun_attribution_target(text, lowered)
        if segun_target:
            return self._build_claim(text, segun_target, "reported_claim")

        return self._build_claim(text, text, "verbatim")

    def _extract_factcheck_claim(self, text: str) -> ExtractedClaim | None:
        trimmed_text = self._strip_factcheck_source_prefix(text)
        lowered = self._strip_accents(trimmed_text.lower())

        question_claim = self._extract_question_factcheck_claim(trimmed_text, lowered)
        if question_claim:
            return self._build_claim(
                question_claim,
                question_claim,
                "factcheck_question",
            )

        for marker in FACTCHECK_CLAIM_MARKERS:
            target = self._slice_after_marker(trimmed_text, lowered, marker)
            if target:
                return self._build_claim(
                    target,
                    target,
                    "factcheck_verdict",
                )

        embedded_target = self._extract_embedded_factcheck_claim(trimmed_text)
        if embedded_target:
            return self._build_claim(
                embedded_target,
                embedded_target,
                "factcheck_embedded",
            )

        return None

    def _strip_factcheck_source_prefix(self, text: str) -> str:
        prefix, separator, remainder = text.partition(":")
        if not separator:
            return text

        normalized_prefix = self._strip_accents(prefix.strip().lower())
        if normalized_prefix in FACTCHECK_SOURCE_PREFIXES:
            return remainder.strip()
        return text

    def _extract_question_factcheck_claim(self, text: str, lowered: str) -> str | None:
        if "?" not in text:
            return None
        question_end = text.find("?")
        if question_end <= 0:
            return None

        remainder = self._strip_accents(text[question_end + 1 :].lower())
        if not any(marker in remainder for marker in FACTCHECK_VERDICT_MARKERS):
            return None

        candidate = text[:question_end].strip()
        candidate = candidate.lstrip("¿").strip()
        candidate = self._cleanup_projected_target(candidate)
        if self._word_count(candidate) < 4:
            return None
        return candidate

    def _extract_embedded_factcheck_claim(self, text: str) -> str | None:
        lowered = self._strip_accents(text.lower())
        verdict_positions = [
            (lowered.find(marker), marker)
            for marker in FACTCHECK_VERDICT_MARKERS
            if lowered.find(marker) >= 0
        ]
        if not verdict_positions:
            return None

        for marker in FACTCHECK_EMBEDDED_CLAIM_MARKERS:
            normalized_marker = self._strip_accents(marker.lower())
            marker_index = lowered.find(normalized_marker)
            if marker_index < 0:
                continue
            target = self._cleanup_projected_target(lowered[marker_index + len(normalized_marker) :])
            if target and self._word_count(target) >= 4:
                return target

        verdict_index, verdict_marker = min(verdict_positions, key=lambda item: item[0])
        verdict_segment = lowered[verdict_index + len(verdict_marker) :]
        if " que " in verdict_segment:
            target = self._cleanup_projected_target(verdict_segment.rsplit(" que ", 1)[-1])
            if target and self._word_count(target) >= 4:
                return target

        return None

    def _slice_after_marker(self, original_text: str, lowered_text: str, marker: str) -> str | None:
        marker_index = lowered_text.find(marker)
        if marker_index < 0:
            return None

        start = marker_index + len(marker)
        target = self._cleanup_projected_target(original_text[start:])
        if self._word_count(target) < 3:
            return None
        return target

    def _slice_after_flexible_reporting_marker(
        self,
        original_text: str,
        lowered_text: str,
    ) -> str | None:
        verbs = "|".join(re.escape(verb) for verb in FLEXIBLE_REPORTING_VERBS)
        match = re.search(
            rf"\b(?:{verbs})\b(?:\s+\S+){{0,8}}\s+que\s+",
            lowered_text,
        )
        if not match:
            return None

        target = self._cleanup_projected_target(original_text[match.end() :])
        if self._word_count(target) < 3:
            return None
        return target

    def _extract_segun_attribution_target(self, original_text: str, lowered_text: str) -> str | None:
        if not lowered_text.startswith("segun "):
            return None

        comma_index = original_text.find(",")
        if comma_index < 0 or comma_index > 140:
            return None

        target = self._cleanup_projected_target(original_text[comma_index + 1 :])
        if self._word_count(target) < 3:
            return None
        return target

    @staticmethod
    def _cleanup_projected_target(text: str) -> str:
        cleaned = text.strip(" :;,.\"'()[]")
        cleaned = re.sub(
            r"(?i)^(?:no obstante|sin embargo|en ese contexto|por otro lado|en esa linea|en esa línea|de esta manera)\s*,?\s+",
            "",
            cleaned,
        )
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _score_sentence(self, text: str, is_title: bool, claim: ExtractedClaim) -> float:
        score = 0.0
        lowered = self._strip_accents(text.lower())
        lowered_target = self._strip_accents(claim.stance_target.lower())

        if is_title:
            score += 0.6
        if claim.extraction_mode.startswith("factcheck_"):
            score += 4.0
        elif claim.extraction_mode in {"reported_claim", "refutation_projected"}:
            score += 0.8
        if any(char.isdigit() for char in text):
            score += 1.5
        if len(_CAPITAL_RE.findall(text)) >= 2:
            score += 0.8
        if any(cue in lowered for cue in CLAIM_CUES):
            score += 1.0
        if any(verb in lowered.split() for verb in FACT_VERBS):
            score += 0.5
        if any(marker in lowered for marker in OFFICIAL_SOURCE_MARKERS):
            score += 0.5
        if any(cue in lowered for cue in ACTION_VERB_CUES):
            score += 0.8
        if any(lowered_target.startswith(prefix) for prefix in DISCOURSE_PREFIXES):
            score -= 0.8
        if any(marker in lowered_target for marker in NORMATIVE_OR_OPINION_MARKERS):
            score -= 1.2
        if any(marker in lowered_target for marker in LOW_VALUE_TARGET_MARKERS):
            score -= 2.0
        if ":" in text and any(char in text for char in ("\"", "“", "”")):
            score -= 0.8
        if text.endswith("?"):
            score -= 0.5

        return score

    @staticmethod
    def _strip_accents(text: str) -> str:
        normalized = unicodedata.normalize("NFD", text)
        return "".join(char for char in normalized if unicodedata.category(char) != "Mn")
