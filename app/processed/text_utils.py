from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"[.!?…][\"'»”)]*$")
_CAMEL_SPLIT = re.compile(r"([a-záéíóúüñ])([A-ZÁÉÍÓÚÜÑ])")
_WORD = re.compile(r"\b[^\W\d_]+\b", re.UNICODE)
_ENGLISH_INTRUSIONS = frozenset({"and", "by", "for", "of", "that", "with"})
_SAFE_TRANSLATIONS = {
    "and": "y",
    "by": "por",
    "of": "de",
    "that": "que",
    "with": "con",
}
_SPANISH_ARTICLES = frozenset({"el", "la", "los", "las", "un", "una", "unos", "unas"})


def normalize_summary_text(text: str | None) -> str:
    cleaned = str(text or "").replace("\xa0", " ")
    cleaned = _CAMEL_SPLIT.sub(r"\1 \2", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r",([^\s])", r", \1", cleaned)
    cleaned = re.sub(r":([^\s])", r": \1", cleaned)
    return cleaned.strip()


def repair_english_intrusions(text: str | None, source_text: str | None = None) -> str:
    """Repair isolated English connectors in an otherwise Spanish summary.

    The original article is preferred as evidence: if the words surrounding an
    intrusion also occur in the source, the connector between them is recovered
    from there. Conservative deterministic translations are only a fallback.
    """
    value = normalize_summary_text(text)
    if not value:
        return ""

    summary_words = list(_WORD.finditer(value))
    source_words = [match.group(0) for match in _WORD.finditer(normalize_summary_text(source_text))]
    source_lower = [word.casefold() for word in source_words]
    replacements: list[tuple[int, int, str]] = []

    for index, match in enumerate(summary_words):
        english = match.group(0).casefold()
        if english not in _ENGLISH_INTRUSIONS:
            continue

        previous_word = summary_words[index - 1].group(0).casefold() if index else None
        next_word = (
            summary_words[index + 1].group(0).casefold()
            if index + 1 < len(summary_words)
            else None
        )
        replacement = _connector_from_source(
            previous_word,
            next_word,
            source_words,
            source_lower,
        )
        if replacement is None:
            replacement = _fallback_translation(english, next_word)
        replacements.append((match.start(), match.end(), replacement))

    for start, end, replacement in reversed(replacements):
        value = f"{value[:start]}{replacement}{value[end:]}"
    return normalize_summary_text(value)


def contains_english_intrusions(text: str | None) -> bool:
    return any(
        match.group(0).casefold() in _ENGLISH_INTRUSIONS
        for match in _WORD.finditer(normalize_summary_text(text))
    )


def _connector_from_source(
    previous_word: str | None,
    next_word: str | None,
    source_words: list[str],
    source_lower: list[str],
) -> str | None:
    if not previous_word or not next_word:
        return None

    candidates = {
        source_words[index + 1]
        for index in range(len(source_words) - 2)
        if source_lower[index] == previous_word
        and source_lower[index + 2] == next_word
        and source_lower[index + 1] not in _ENGLISH_INTRUSIONS
    }
    return next(iter(candidates)) if len(candidates) == 1 else None


def _fallback_translation(english: str, next_word: str | None) -> str:
    if english == "for":
        # "para" normally introduces an infinitive; before an article, "por"
        # is the safer causal/agentive reading.
        if next_word and next_word.endswith(("ar", "er", "ir")):
            return "para"
        if next_word in _SPANISH_ARTICLES:
            return "por"
        return "por"
    return _SAFE_TRANSLATIONS[english]


def looks_complete_sentence(text: str) -> bool:
    return bool(_SENTENCE_END.search(text.strip()))


def clip_readable(text: str | None, max_chars: int) -> str:
    cleaned = normalize_summary_text(text)
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return finish_truncated(cleaned)

    window = cleaned[:max_chars].rstrip()
    sentence_break = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence_break >= int(max_chars * 0.45):
        return window[: sentence_break + 1].strip()

    word_break = window.rfind(" ")
    if word_break > int(max_chars * 0.4):
        return finish_truncated(window[:word_break])
    return finish_truncated(window)


def finish_truncated(text: str | None) -> str:
    value = normalize_summary_text(text)
    if not value:
        return ""
    if looks_complete_sentence(value):
        return value

    last_sentence = max(value.rfind(". "), value.rfind("! "), value.rfind("? "))
    if last_sentence >= 24:
        return value[: last_sentence + 1].strip()

    last_space = value.rfind(" ")
    if last_space >= 24:
        trimmed = value[:last_space].rstrip(" ,;:")
        return trimmed if looks_complete_sentence(trimmed) else f"{trimmed}…"
    return f"{value}…"
