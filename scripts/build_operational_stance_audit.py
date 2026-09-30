from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ml.claim_extractor import ClaimExtractor


SPACE_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    """Decode HTML entities and normalize whitespace without rewriting content."""
    return SPACE_RE.sub(" ", html.unescape(value or "")).strip()


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_article_context(title: str, body: str) -> str:
    """Mirror NewsAnalysisPipeline._build_article_context exactly."""
    normalized_title = clean_text(title)
    normalized_body = clean_text(body)
    if not normalized_title:
        return normalized_body
    if normalized_body.lower().startswith(normalized_title.lower()):
        return normalized_body
    return f"{normalized_title}. {normalized_body}".strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def round_robin(items_by_source: dict[str, list[dict[str, Any]]], source_order: list[str]):
    queues = {source: deque(items_by_source[source]) for source in source_order}
    while any(queues[source] for source in source_order):
        for source in source_order:
            if queues[source]:
                yield queues[source].popleft()


def normalized_key(value: str | None) -> str:
    return SPACE_RE.sub(" ", (value or "").strip().lower())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a blind, prospective operational stance evaluation set."
    )
    parser.add_argument("--articles", required=True, type=Path)
    parser.add_argument("--development", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--target-pairs", type=int, default=120)
    args = parser.parse_args()

    raw_articles = read_csv(args.articles)
    development = read_csv(args.development)
    extractor = ClaimExtractor()

    dev_urls = {normalized_key(row.get("original_url")) for row in development if row.get("original_url")}
    dev_groups = {normalized_key(row.get("group_id")) for row in development if row.get("group_id")}
    dev_pair_text = {
        (normalized_key(row.get("claim")), normalized_key(row.get("article")))
        for row in development
    }

    source_order: list[str] = []
    source_rank: Counter[str] = Counter()
    candidates_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    extraction_counts: Counter[int] = Counter()
    articles_without_claims: list[dict[str, str]] = []

    for input_rank, raw in enumerate(raw_articles, start=1):
        source = clean_text(raw.get("source_name"))
        if source not in source_order:
            source_order.append(source)
        source_rank[source] += 1
        title = clean_text(raw.get("title"))
        body = clean_text(raw.get("article"))
        article_context = build_article_context(title, body)
        claims = extractor.extract_with_metadata(title, body)
        extraction_counts[len(claims)] += 1
        if not claims:
            articles_without_claims.append(
                {
                    "article_id": raw.get("article_id", ""),
                    "source_name": source,
                    "title": title,
                }
            )
            continue

        article_item: dict[str, Any] = {
            "raw": raw,
            "source_name": source,
            "source_article_rank": source_rank[source],
            "input_article_rank": input_rank,
            "title": title,
            "article_context": article_context,
            "claims": [],
        }
        for claim_rank, claim in enumerate(claims, start=1):
            model_input = clean_text(claim.model_input or claim.stance_target)
            article_item["claims"].append(
                {
                    "claim_rank": claim_rank,
                    "claim": model_input,
                    "claim_text_original": clean_text(claim.text),
                    "stance_target": clean_text(claim.stance_target),
                    "model_input": model_input,
                    "extraction_mode": claim.extraction_mode,
                    "claim_quality": claim.quality,
                    "claim_quality_reasons": list(claim.quality_reasons),
                }
            )
        candidates_by_source[source].append(article_item)

    # Operational sampling is deliberately label-agnostic. First take claim 1 from
    # every usable article in source round-robin order, then claim 2, then claim 3.
    # This maximizes article diversity while reproducing the backend's ranked claims.
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for claim_rank in range(1, extractor.config.max_claims + 1):
        eligible = {
            source: [item for item in candidates_by_source[source] if len(item["claims"]) >= claim_rank]
            for source in source_order
        }
        for article_item in round_robin(eligible, source_order):
            selected.append((article_item, article_item["claims"][claim_rank - 1]))
            if len(selected) == args.target_pairs:
                break
        if len(selected) == args.target_pairs:
            break

    if len(selected) != args.target_pairs:
        raise RuntimeError(
            f"Only {len(selected)} extractable pairs were available; target was {args.target_pairs}."
        )

    generated_at = datetime.now(timezone.utc).isoformat()
    blind_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    pair_keys: set[str] = set()
    overlap_urls: set[str] = set()
    overlap_groups: set[str] = set()
    overlap_pair_text: set[str] = set()

    for position, (article_item, claim_item) in enumerate(selected, start=1):
        raw = article_item["raw"]
        article_id = clean_text(raw.get("article_id"))
        group_id = clean_text(raw.get("group_id")) or f"article:{article_id}"
        claim = claim_item["claim"]
        article = article_item["article_context"]
        unique_material = f"{article_id}\n{claim_item['claim_rank']}\n{claim}"
        pair_id = f"KSP-F-{stable_hash(unique_material)[:12].upper()}"
        if pair_id in pair_keys:
            raise RuntimeError(f"Duplicate generated pair_id: {pair_id}")
        pair_keys.add(pair_id)

        original_url = clean_text(raw.get("original_url"))
        if normalized_key(original_url) in dev_urls:
            overlap_urls.add(original_url)
        if normalized_key(group_id) in dev_groups:
            overlap_groups.add(group_id)
        if (normalized_key(claim), normalized_key(article)) in dev_pair_text:
            overlap_pair_text.add(pair_id)

        blind = {
            "orden": position,
            "pair_id": pair_id,
            "corpus_version": "stance_es_pe_v1",
            "batch_id": "evaluacion_final_operacional_2026_09_24",
            "intended_use": "final_evaluation_only",
            "group_id": group_id,
            "claim_id": f"claim:{pair_id}",
            "article_id": article_id,
            "source_name": article_item["source_name"],
            "title": article_item["title"],
            "published_at": clean_text(raw.get("published_at")),
            "claim": claim,
            "article": article,
        }
        blind_rows.append(blind)
        private_rows.append(
            {
                **blind,
                "original_url": original_url,
                "article_sha256": clean_text(raw.get("article_sha256")),
                "collected_at": clean_text(raw.get("collected_at")),
                "collection_method": clean_text(raw.get("collection_method")),
                "source_article_rank": article_item["source_article_rank"],
                "input_article_rank": article_item["input_article_rank"],
                "claim_rank": claim_item["claim_rank"],
                "claim_text_original": claim_item["claim_text_original"],
                "stance_target": claim_item["stance_target"],
                "model_input": claim_item["model_input"],
                "extraction_mode": claim_item["extraction_mode"],
                "claim_quality": claim_item["claim_quality"],
                "claim_quality_reasons": claim_item["claim_quality_reasons"],
                "selection_method": "source_round_robin_claim_rank_without_labels_or_predictions",
            }
        )

    source_counts = Counter(row["source_name"] for row in blind_rows)
    article_counts = Counter(row["article_id"] for row in blind_rows)
    claim_rank_counts = Counter(row["claim_rank"] for row in private_rows)
    max_source_share = max(source_counts.values()) / len(blind_rows)
    leakage = {
        "development_url_overlap": sorted(overlap_urls),
        "development_group_overlap": sorted(overlap_groups),
        "development_exact_claim_article_overlap": sorted(overlap_pair_text),
    }
    if any(leakage.values()):
        raise RuntimeError(f"Development leakage detected: {leakage}")
    if len(source_counts) < 6:
        raise RuntimeError(f"Expected at least 6 sources, found {len(source_counts)}")
    if max_source_share > 0.25:
        raise RuntimeError(f"A source exceeds 25% of the final pairs: {max_source_share:.3f}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    blind_json = args.output_dir / "operational_final_blind.json"
    blind_csv = args.output_dir / "operational_final_blind.csv"
    private_json = args.output_dir / "operational_final_private.json"
    audit_json = args.output_dir / "operational_final_audit.json"
    manifest_json = args.output_dir / "operational_final_manifest.json"

    write_json(blind_json, blind_rows)
    write_csv(blind_csv, blind_rows, list(blind_rows[0].keys()))
    write_json(private_json, private_rows)

    audit = {
        "status": "PASS",
        "generated_at_utc": generated_at,
        "target_pairs": args.target_pairs,
        "actual_pairs": len(blind_rows),
        "unique_pair_ids": len(pair_keys),
        "unique_articles": len(article_counts),
        "articles_with_multiple_pairs": sum(1 for count in article_counts.values() if count > 1),
        "source_counts": dict(source_counts),
        "max_source_share": round(max_source_share, 6),
        "claim_rank_counts": {str(key): value for key, value in sorted(claim_rank_counts.items())},
        "input_articles": len(raw_articles),
        "input_source_counts": dict(Counter(clean_text(row.get("source_name")) for row in raw_articles)),
        "extracted_claim_count_distribution": {
            str(key): value for key, value in sorted(extraction_counts.items())
        },
        "articles_without_extractable_claims": articles_without_claims,
        "extractor_strategy": extractor.strategy_name,
        "extractor_config": {
            "max_claims": extractor.config.max_claims,
            "min_words": extractor.config.min_words,
            "max_words": extractor.config.max_words,
            "max_candidates": extractor.config.max_candidates,
        },
        "selection_policy": (
            "Prospective source snapshot; round-robin across sources in listing order; "
            "first backend-ranked claim per usable article before second and third claims; "
            "no label, keyword, class, or model-prediction filtering."
        ),
        "labels_present": False,
        "model_predictions_present": False,
        "leakage_checks": leakage,
    }
    write_json(audit_json, audit)

    manifest = {
        "generated_at_utc": generated_at,
        "frozen_model_checkpoint": (
            "output/stance_es_pe_v1/development_2026_09_24_diagnostic_mbert_base_seed42/best_model"
        ),
        "source_snapshot": str(args.articles.resolve()),
        "source_snapshot_sha256": file_sha256(args.articles),
        "development_reference": str(args.development.resolve()),
        "development_reference_sha256": file_sha256(args.development),
        "artifacts": {},
        "prohibitions": [
            "Do not train, tune, choose a checkpoint, or revise thresholds with these pairs.",
            "Do not generate model predictions before gold labels and exclusions are frozen.",
            "Do not expose the private file or manifest to annotators.",
        ],
    }
    for artifact in (blind_json, blind_csv, private_json, audit_json):
        manifest["artifacts"][artifact.name] = {
            "path": str(artifact.resolve()),
            "sha256": file_sha256(artifact),
        }
    write_json(manifest_json, manifest)

    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
