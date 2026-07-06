"""
Export article candidates for synthetic or human summary references.

The output CSV is compatible with scripts/benchmark_summarizers.py:
  id, title, url, article, summary

Fill the summary column manually, with a separate LLM, or with
scripts/generate_synthetic_summary_references.py.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from sqlalchemy import text

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.db.database import SessionLocal


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export articles for summary reference creation")
    parser.add_argument("--output", default="data/summary_references/candidates.csv")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min_article_chars", type=int, default=700)
    parser.add_argument(
        "--fix_mojibake",
        action="store_true",
        help="Try to repair common UTF-8 text decoded as Latin-1.",
    )
    parser.add_argument(
        "--include_existing_summary",
        action="store_true",
        help="Copy the current stored summary into the reference column.",
    )
    parser.add_argument(
        "--omit_existing_summary",
        action="store_true",
        help="Do not include the existing_summary helper column in the output CSV.",
    )
    return parser


def fix_mojibake(text: str) -> str:
    if not text:
        return text
    markers = ("Ã", "Â", "â€œ", "â€", "â€™", "ðŸ")
    if not any(marker in text for marker in markers):
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return text


def main() -> None:
    args = build_arg_parser().parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    query = text(
        """
        select
            p.news_processed_id as id,
            coalesce(r.title_raw, '') as title,
            coalesce(r.original_url, '') as url,
            p.clean_text as article,
            coalesce(s.summary_text, '') as existing_summary
        from processed.news_processed p
        join raw.news_raw r
          on r.news_raw_id = p.news_raw_id
        left join processed.summaries s
          on s.representative_news_processed = p.news_processed_id
        where length(coalesce(p.clean_text, '')) >= :min_article_chars
        order by p.news_processed_id
        limit :limit
        """
    )

    db = SessionLocal()
    try:
        rows = db.execute(
            query,
            {
                "min_article_chars": args.min_article_chars,
                "limit": max(args.limit, 1),
            },
        ).mappings()

        with output_path.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = ["id", "title", "url", "article", "summary"]
            if not args.omit_existing_summary:
                fieldnames.append("existing_summary")
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
            )
            writer.writeheader()
            count = 0
            for row in rows:
                title = str(row["title"] or "").strip()
                article = str(row["article"] or "").strip()
                existing_summary = str(row["existing_summary"] or "").strip()
                if args.fix_mojibake:
                    title = fix_mojibake(title)
                    article = fix_mojibake(article)
                    existing_summary = fix_mojibake(existing_summary)
                output_row = {
                    "id": row["id"],
                    "title": title,
                    "url": row["url"],
                    "article": article,
                    "summary": existing_summary if args.include_existing_summary else "",
                }
                if not args.omit_existing_summary:
                    output_row["existing_summary"] = existing_summary
                writer.writerow(output_row)
                count += 1
    finally:
        db.close()

    print(f"Exported {count} rows to {output_path}")


if __name__ == "__main__":
    main()
