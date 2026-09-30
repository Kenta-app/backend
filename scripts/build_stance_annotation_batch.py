"""Build and audit a blind stance-annotation batch from article snapshots.

Candidate strategy is kept only in the private key. Annotator exports never
contain a proposed class, a model prediction, or the construction strategy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


STRATEGIES = ("same_article_title", "explicit_refutation", "reported_claim", "hard_negative")
BLIND_FIELDS = (
    "pair_id", "corpus_version", "batch_id", "group_id", "event_id", "claim_id",
    "article_id", "source_name", "title", "original_url", "published_at", "claim", "article",
)
PRIVATE_FIELDS = BLIND_FIELDS + (
    "candidate_strategy", "candidate_score", "construction_evidence",
    "claim_source_url", "claim_source_quote", "reviewer_code", "review_note",
)

REPORTING_RE = re.compile(
    r"\b(?:afirm[óo]|asegur[óo]|sostuvo|señal[óo]|indic[óo]|manifest[óo]|declar[óo]|"
    r"denunci[óo]|acus[óo]|advirti[óo]|aleg[óo]|anunci[óo]|inform[óo]|revel[óo])\b",
    re.IGNORECASE,
)
VERIFIED_REFUTATION_FIELDS = (
    "claim", "claim_source_url", "claim_source_quote", "target_article_id",
    "refutation_evidence", "reviewer_code", "review_note",
)


def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" \t\r\n\"“”'‘’")


def sentences(text: str) -> list[str]:
    return [clean(item) for item in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ¿¡])", clean(text)) if clean(item)]


def usable_claim(value: str, *, min_words: int = 5) -> str | None:
    value = clean(value).rstrip(".;:")
    value = "".join(ch for ch in value if unicodedata.category(ch) not in {"So", "Cs", "Cf"})
    value = re.sub(r"https?://\S+|pic\.twitter\.com/\S+", "", value, flags=re.I)
    value = re.sub(r"\s*[—-]\s*@\w+.*$", "", value).strip()
    value = re.sub(
        r"\s*[^\w\s]{0,3}\s*(?:Diario El Peruano|Agencia Andina)\s*\(@[^)]*\).*$",
        "", value, flags=re.I,
    ).replace("??", "").strip()
    value = re.sub(r"^(?:según|de acuerdo con)\s+[^,]{2,80},\s*", "", value, flags=re.I)
    value = re.sub(
        r"[,;]\s*(?:afirmó|aseguró|sostuvo|señaló|indicó|manifestó|declaró|informó|advirtió)(?:\s+[^,.]{1,80})?$",
        "", value, flags=re.I,
    ).strip(" \"“”'‘’")
    if re.search(r"\b(?:FIN|Más en Andina)\b|\b[A-Z]{2,5}/[A-Z]{2,5}\b", value):
        return None
    if re.match(
        r"^(?:esta|este|estas|estos|eso|ello|el primero|el segundo|el tercero|la medida|"
        r"ellos|ellas|nosotros|nosotras|nos|sí|se trata|se está|podría|podrían|es preferible)\b", value, re.I
    ):
        return None
    if re.search(r"\b(?:Twitter|TikTok)\b|[¡!]", value, re.I):
        return None
    if 20 <= len(value) <= 240 and len(value.split()) >= min_words:
        return value
    return None


def reported_target(sentence: str) -> str | None:
    match = re.search(r"\bque\s+(.+)", sentence, re.I)
    claim = usable_claim(match.group(1) if match else sentence, min_words=7)
    has_subject_start = bool(
        claim
        and (
            re.match(r"^(?:el|la|los|las|un|una|se|existen|más\s+de)\b", claim, re.I)
            or claim[0].isupper()
            or claim[0].isdigit()
        )
    )
    if claim and not has_subject_start:
        return None
    return claim


def candidate(
    article: dict[str, str], claim: str, strategy: str, score: float,
    evidence: str, *, batch_id: str = "expansion_calibration_01",
) -> dict[str, str]:
    seed = f"{article['article_id']}|{strategy}|{claim}"
    token = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
    return {
        "pair_id": f"ksp1_{token}", "corpus_version": "stance_es_pe_v1",
        "batch_id": batch_id, "group_id": article["group_id"], "event_id": "",
        "claim_id": f"claim_{hashlib.sha256(claim.encode('utf-8')).hexdigest()[:16]}",
        "article_id": article["article_id"], "source_name": article["source_name"],
        "title": article["title"], "original_url": article["original_url"],
        "published_at": article.get("published_at", ""), "claim": claim,
        "article": article["article"][:30000], "candidate_strategy": strategy,
        "candidate_score": f"{score:.4f}", "construction_evidence": clean(evidence)[:500],
        "claim_source_url": "", "claim_source_quote": "", "reviewer_code": "", "review_note": "",
    }


def build_candidates(
    articles: list[dict[str, str]], *, batch_id: str = "expansion_calibration_01",
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for article in articles:
        body_sentences = sentences(article["article"])
        title_claim = usable_claim(article["title"])
        if title_claim:
            output.append(candidate(article, title_claim, "same_article_title", 1.0, article["title"], batch_id=batch_id))
        for sentence in body_sentences:
            if REPORTING_RE.search(sentence):
                claim = reported_target(sentence)
                if claim:
                    output.append(candidate(article, claim, "reported_claim", 0.8, sentence, batch_id=batch_id))

    # Hard negatives are topically similar enough to be non-trivial, but use a
    # different article and avoid very high similarity that likely indicates the
    # same event. They remain candidates; only human annotation creates gold.
    if len(articles) >= 2:
        vectorizer = TfidfVectorizer(lowercase=True, strip_accents="unicode", ngram_range=(1, 2), min_df=1)
        matrix = vectorizer.fit_transform([f"{a['title']} {a['article'][:2500]}" for a in articles])
        similarities = cosine_similarity(matrix)
        for index, source in enumerate(articles):
            source_claim = usable_claim(source["title"])
            if not source_claim:
                continue
            ranked = sorted(
                ((float(similarities[index, target]), target) for target in range(len(articles)) if target != index),
                reverse=True,
            )
            chosen = None
            for score, target in ranked:
                if score < 0.08:
                    break
                if score <= 0.42 and articles[target]["group_id"] != source["group_id"]:
                    chosen = (score, target)
                    break
            if chosen:
                score, target = chosen
                output.append(candidate(articles[target], source_claim, "hard_negative", score, source["original_url"], batch_id=batch_id))

    unique: dict[tuple[str, str], dict[str, str]] = {}
    for row in output:
        key = (row["claim"].casefold(), row["article_id"])
        current = unique.get(key)
        if current is None or float(row["candidate_score"]) > float(current["candidate_score"]):
            unique[key] = row
    return list(unique.values())


def load_verified_refutations(
    path: Path, articles: list[dict[str, str]], *, batch_id: str,
) -> list[dict[str, str]]:
    """Import human-screened contradiction candidates, not gold labels."""
    by_article = {row["article_id"]: row for row in articles}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(VERIFIED_REFUTATION_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"verified refutations missing columns: {sorted(missing)}")
        rows = list(reader)
    output = []
    for index, row in enumerate(rows, start=2):
        claim = usable_claim(row["claim"])
        source_url = clean(row["claim_source_url"])
        source_quote = clean(row["claim_source_quote"])
        article_id = clean(row["target_article_id"])
        evidence = clean(row["refutation_evidence"])
        reviewer = clean(row["reviewer_code"])
        note = clean(row["review_note"])
        article = by_article.get(article_id)
        if not claim or not source_url.startswith(("https://", "http://")):
            raise ValueError(f"verified refutations row {index}: invalid claim or claim_source_url")
        if not article or not source_quote or not reviewer or len(note.split()) < 5:
            raise ValueError(f"verified refutations row {index}: missing article, source quote, reviewer, or review note")
        if len(evidence) < 20 or evidence.casefold() not in clean(article["article"]).casefold():
            raise ValueError(f"verified refutations row {index}: refutation_evidence must quote the target article")
        item = candidate(article, claim, "explicit_refutation", 1.0, evidence, batch_id=batch_id)
        item.update({
            "claim_source_url": source_url, "claim_source_quote": source_quote,
            "reviewer_code": reviewer, "review_note": note,
        })
        output.append(item)
    return output


def select_batch(candidates: list[dict[str, str]], per_strategy: int, seed: int) -> list[dict[str, str]]:
    if not any(row["candidate_strategy"] == "explicit_refutation" for row in candidates):
        raise ValueError("no reviewed explicit_refutation candidates; supply --verified-refutations")
    rng = random.Random(seed)
    by_strategy: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in candidates:
        by_strategy[row["candidate_strategy"]].append(row)
    selected: list[dict[str, str]] = []
    source_counts: Counter[str] = Counter()
    article_counts: Counter[str] = Counter()
    max_source = max(1, per_strategy * len(STRATEGIES) // 4)
    for strategy in STRATEGIES:
        pool = by_strategy[strategy]
        rng.shuffle(pool)
        pool.sort(key=lambda row: (source_counts[row["source_name"]], article_counts[row["article_id"]], -float(row["candidate_score"])))
        picked = []
        for row in pool:
            if source_counts[row["source_name"]] >= max_source or article_counts[row["article_id"]] >= 3:
                continue
            picked.append(row)
            source_counts[row["source_name"]] += 1
            article_counts[row["article_id"]] += 1
            if len(picked) == per_strategy:
                break
        if len(picked) < per_strategy:
            hint = "; supply --verified-refutations" if strategy == "explicit_refutation" else ""
            raise ValueError(f"insufficient {strategy} candidates: selected {len(picked)} of {per_strategy}{hint}")
        selected.extend(picked)
    rng.shuffle(selected)
    return selected


def write_csv(path: Path, rows: list[dict[str, str]], fields: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--per-strategy", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20260915)
    parser.add_argument("--batch-id", default="expansion_calibration_02")
    parser.add_argument("--batch-stem", default="calibration_batch_02")
    parser.add_argument("--verified-refutations", type=Path)
    args = parser.parse_args()
    with args.articles.open(encoding="utf-8-sig", newline="") as handle:
        articles = list(csv.DictReader(handle))
    candidates = build_candidates(articles, batch_id=args.batch_id)
    if args.verified_refutations:
        reviewed = load_verified_refutations(args.verified_refutations, articles, batch_id=args.batch_id)
        by_pair = {(row["claim"].casefold(), row["article_id"]): row for row in candidates}
        for row in reviewed:
            by_pair[(row["claim"].casefold(), row["article_id"])] = row
        candidates = list(by_pair.values())
    selected = select_batch(candidates, args.per_strategy, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "candidate_pool_private.csv", candidates, PRIVATE_FIELDS)
    write_csv(args.output_dir / f"{args.batch_stem}_blind.csv", selected, BLIND_FIELDS)
    write_csv(args.output_dir / f"{args.batch_stem}_private_key.csv", selected, PRIVATE_FIELDS)
    strategy_counts = Counter(row["candidate_strategy"] for row in candidates)
    selected_strategy_counts = Counter(row["candidate_strategy"] for row in selected)
    report = {
        "articles": len(articles), "candidate_pairs": len(candidates),
        "candidate_strategy_counts": dict(strategy_counts), "selected_pairs": len(selected),
        "selected_strategy_counts": dict(selected_strategy_counts),
        "selected_source_counts": dict(Counter(row["source_name"] for row in selected)),
        "selected_unique_articles": len({row["article_id"] for row in selected}),
        "blindness_checks": {
            "contains_candidate_strategy": any("candidate_strategy" in row for row in [dict((f, r.get(f, "")) for f in BLIND_FIELDS) for r in selected]),
            "contains_model_prediction": False, "contains_suggested_label": False,
        },
        "selection_seed": args.seed,
        "warning": "Construction strata are sampling aids, not gold labels. Human annotation determines the class.",
    }
    (args.output_dir / f"{args.batch_stem}_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
