"""Build a *candidate-only* blind pilot from screened Peruvian fact-checks.

The input manifest documents why a pair is worth annotating. It is never a
gold label and its provenance fields are omitted from the annotator export.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from build_stance_annotation_batch import BLIND_FIELDS, build_candidates, candidate, select_batch
from collect_stance_articles import clean_text, extract_article


def prepare(manifest_path: Path, article_pool: Path, *, per_strategy: int, seed: int) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("screening_status") != "candidates_only_not_gold":
        raise ValueError("manifest must explicitly state candidates_only_not_gold")
    with article_pool.open(encoding="utf-8-sig", newline="") as handle:
        articles = list(csv.DictReader(handle))
    existing_urls = {row["original_url"] for row in articles}
    existing_hashes = {row.get("article_sha256") for row in articles}
    screened = []
    for item in manifest["records"]:
        if item["article_url"] in existing_urls:
            raise ValueError(f"fact-check already in pool: {item['article_url']}")
        response = requests.get(item["article_url"], timeout=30, headers={"User-Agent": "KentaStanceResearch/1.0"})
        response.raise_for_status()
        parsed = extract_article(response.text, response.url)
        body = clean_text(parsed["article"])
        evidence = clean_text(item["refutation_evidence"])
        if evidence.casefold() not in body.casefold():
            raise ValueError(f"non-literal evidence: {item['seed_id']}")
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if digest in existing_hashes:
            raise ValueError(f"duplicate fact-check text: {item['seed_id']}")
        record = {
            "article_id": f"art_{digest[:16]}", "group_id": f"article:art_{digest[:16]}",
            "source_name": item["article_source"], "ownership_group": item["article_source"],
            "title": parsed["title"], "original_url": response.url,
            "published_at": parsed["published_at"], "article": body,
            "article_sha256": digest, "collected_at": datetime.now(timezone.utc).isoformat(),
            "collection_method": "screened_factcheck_manifest",
        }
        articles.append(record)
        existing_urls.add(response.url)
        existing_hashes.add(digest)
        screened.append((item, record))

    candidates = build_candidates(articles, batch_id=manifest["batch_id"])
    candidate_by_pair = {(row["claim"].casefold(), row["article_id"]): row for row in candidates}
    for item, article in screened:
        row = candidate(
            article, item["claim"], "explicit_refutation", 1.0,
            item["refutation_evidence"], batch_id=manifest["batch_id"],
        )
        row.update({
            "screening_seed_id": item["seed_id"],
            "claim_source_url": item["claim_origin_url"],
            "claim_source_quote": item["reported_quote"],
            "claim_origin_status": item["claim_origin_status"],
            "reviewer_code": "AI_RESEARCH_SCREEN",
            "review_note": item["screening_note"],
            "article_sha256": article["article_sha256"],
        })
        candidate_by_pair[(row["claim"].casefold(), row["article_id"])] = row
    candidates = list(candidate_by_pair.values())
    selected = select_batch(candidates, per_strategy, seed)
    blind = [{field: row.get(field, "") for field in BLIND_FIELDS} for row in selected]
    if any("candidate_strategy" in row or "claim_origin_status" in row for row in blind):
        raise AssertionError("private screening metadata leaked into blind set")
    audit = {
        "batch_id": manifest["batch_id"], "status": "candidate_only_not_gold",
        "source_articles": len(articles), "screened_refutations": len(screened),
        "selected_pairs": len(selected),
        "selected_by_strategy_private": dict(Counter(row["candidate_strategy"] for row in selected)),
        "selected_sources": dict(Counter(row["source_name"] for row in selected)),
        "distinct_articles": len({row["article_id"] for row in selected}),
        "seed": seed,
        "warning": "Fact-check publication and screening are sampling aids, not stance labels. Five linked original videos/posts remain unplayed and require provenance review.",
    }
    return {"blind": blind, "private": selected, "audit": audit}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--article-pool", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--per-strategy", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()
    result = prepare(args.manifest, args.article_pool, per_strategy=args.per_strategy, seed=args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for key in ("blind", "private", "audit"):
        path = args.output_dir / f"calibration_02a_{key}.json"
        if path.exists():
            raise FileExistsError(f"Refusing to replace frozen pilot file: {path}")
        path.write_text(json.dumps(result[key], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["audit"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
