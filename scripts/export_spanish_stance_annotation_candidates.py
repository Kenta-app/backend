"""Create blinded Spanish-Peruvian stance annotation candidates.

The script pairs locally stored Peruvian political articles with claims already
extracted by the Kenta pipeline. It exports two transparent strata:

* ``source_pair``: a claim and the article from which it was extracted; and
* ``cross_pair``: a claim paired with a different article to provide genuine
  unrelated candidates.

The resulting CSV deliberately contains no model predictions. Two annotators
should independently fill ``label_annotator_1`` and ``label_annotator_2``;
only then should an adjudicated label be used for the external evaluation.
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

from sqlalchemy import select


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.database import SessionLocal
from app.ml.claim_extractor import ClaimExtractor
from app.processed.models import ProcessedNews
from app.raw.models import RawNews, Source


FIELDNAMES = [
    "pair_id",
    "pair_construction",
    "source_article_id",
    "source_name",
    "title",
    "original_url",
    "claim",
    "article",
    "annotator_1",
    "label_annotator_1",
    "annotator_2",
    "label_annotator_2",
    "adjudicated_label",
    "adjudication_note",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        help="Optional previous calibration export. Omit to extract candidates from the current local database.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "output/paper_v7/annotation_inputs/spanish_stance_candidates_100.csv",
    )
    parser.add_argument(
        "--source-pairs",
        type=int,
        default=50,
        help="Number of natural claim/article pairs to sample.",
    )
    parser.add_argument(
        "--cross-pairs",
        type=int,
        default=50,
        help="Number of shuffled claim/article pairs to sample as unrelated candidates.",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--database-limit",
        type=int,
        default=250,
        help="Maximum current-database articles considered when --input is omitted.",
    )
    parser.add_argument("--min-article-chars", type=int, default=700)
    return parser.parse_args()


def read_candidates(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    eligible = [
        row
        for row in rows
        if row.get("representative_id", "").strip()
        and row.get("top_claim_model_input", "").strip()
        and row.get("top_claim_quality", "").strip() == "usable"
    ]
    unique: dict[str, dict[str, str]] = {}
    for row in eligible:
        unique.setdefault(row["representative_id"].strip(), row)
    return list(unique.values())


def read_current_database_candidates(limit: int, min_article_chars: int) -> list[dict[str, str]]:
    extractor = ClaimExtractor()
    db = SessionLocal()
    try:
        query = (
            select(
                ProcessedNews.news_processed_id,
                ProcessedNews.clean_text,
                RawNews.title_raw,
                RawNews.original_url,
                Source.name,
            )
            .join(RawNews, RawNews.news_raw_id == ProcessedNews.news_raw_id)
            .join(Source, Source.source_id == ProcessedNews.source_id)
            .where(ProcessedNews.clean_text.isnot(None))
            .where(ProcessedNews.clean_text != "")
            .order_by(ProcessedNews.news_processed_id)
            .limit(max(limit, 1))
        )
        rows = list(db.execute(query))
    finally:
        db.close()

    candidates: list[dict[str, str]] = []
    for row in rows:
        article = (row.clean_text or "").strip()
        if len(article) < min_article_chars:
            continue
        claims = extractor.extract_with_metadata(row.title_raw, article)
        selected = next((claim for claim in claims if claim.quality == "usable"), None)
        if selected is None:
            continue
        candidates.append(
            {
                "representative_id": str(row.news_processed_id),
                "source_name": row.name or "",
                "title": row.title_raw or "",
                "original_url": row.original_url or "",
                "top_claim_model_input": selected.model_input,
            }
        )
    return candidates


def derangement(size: int, rng: random.Random) -> list[int]:
    if size < 2:
        raise ValueError("At least two rows are required to construct cross-pairs.")
    indexes = list(range(size))
    while True:
        candidate = indexes[:]
        rng.shuffle(candidate)
        if all(left != right for left, right in enumerate(candidate)):
            return candidate


def main() -> None:
    args = parse_args()
    if args.source_pairs < 1 or args.cross_pairs < 1:
        raise SystemExit("Both --source-pairs and --cross-pairs must be positive.")
    if args.input:
        if not args.input.exists():
            raise SystemExit(f"Input not found: {args.input}")
        candidates = read_candidates(args.input)
        source_description = str(args.input)
    else:
        candidates = read_current_database_candidates(args.database_limit, args.min_article_chars)
        source_description = "current local database + heuristic_v9 claim extraction"
    requested = max(args.source_pairs, args.cross_pairs)
    if len(candidates) < requested:
        raise SystemExit(f"Only {len(candidates)} eligible rows are available; requested {requested}.")

    rng = random.Random(args.seed)
    rng.shuffle(candidates)
    natural = candidates[: args.source_pairs]
    cross_base = candidates[args.source_pairs : args.source_pairs + args.cross_pairs]
    if len(cross_base) < args.cross_pairs:
        cross_base = candidates[: args.cross_pairs]

    ids = {int(row["representative_id"]) for row in natural + cross_base}
    db = SessionLocal()
    try:
        query = select(ProcessedNews.news_processed_id, ProcessedNews.clean_text).where(
            ProcessedNews.news_processed_id.in_(ids)
        )
        article_by_id = {str(row.news_processed_id): (row.clean_text or "").strip() for row in db.execute(query)}
    finally:
        db.close()

    missing = [row["representative_id"] for row in natural + cross_base if not article_by_id.get(row["representative_id"])]
    if missing:
        raise SystemExit(f"Missing clean article text for processed IDs: {', '.join(missing[:10])}")

    exported: list[dict[str, str]] = []
    for index, row in enumerate(natural, start=1):
        exported.append(
            {
                "pair_id": f"ESPE-S{index:03d}",
                "pair_construction": "source_pair",
                "source_article_id": row["representative_id"],
                "source_name": row.get("source_name", ""),
                "title": row.get("title", ""),
                "original_url": row.get("original_url", ""),
                "claim": row.get("top_claim_model_input", ""),
                "article": article_by_id[row["representative_id"]],
                "annotator_1": "",
                "label_annotator_1": "",
                "annotator_2": "",
                "label_annotator_2": "",
                "adjudicated_label": "",
                "adjudication_note": "",
            }
        )

    permutation = derangement(len(cross_base), rng)
    for index, article_index in enumerate(permutation, start=1):
        claim_row = cross_base[index - 1]
        article_row = cross_base[article_index]
        exported.append(
            {
                "pair_id": f"ESPE-U{index:03d}",
                "pair_construction": "cross_pair",
                "source_article_id": article_row["representative_id"],
                "source_name": article_row.get("source_name", ""),
                "title": article_row.get("title", ""),
                "original_url": article_row.get("original_url", ""),
                "claim": claim_row.get("top_claim_model_input", ""),
                "article": article_by_id[article_row["representative_id"]],
                "annotator_1": "",
                "label_annotator_1": "",
                "annotator_2": "",
                "label_annotator_2": "",
                "adjudicated_label": "",
                "adjudication_note": "",
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(exported)
    print(
        f"Exported {len(exported)} blinded candidates "
        f"({len(natural)} source pairs, {len(cross_base)} cross pairs) from {source_description} to {args.output}"
    )


if __name__ == "__main__":
    main()
