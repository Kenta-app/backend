"""
Merge ChatGPT id/summary references back into the benchmark CSV.

Expected reference CSV columns:
  id, summary

The output keeps article/title/url from the original candidates and replaces
summary with the generated reference.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge summary references into benchmark CSV")
    parser.add_argument("--candidates", default="data/summary_references/candidates_30_clean.csv")
    parser.add_argument("--references", default="data/summary_references/chatgpt_refs_30.csv")
    parser.add_argument("--output", default="data/summary_references/synthetic_refs_30_fixed.csv")
    return parser


def word_count(text: str) -> int:
    return len((text or "").split())


def main() -> None:
    args = build_arg_parser().parse_args()
    candidates_path = Path(args.candidates)
    references_path = Path(args.references)
    output_path = Path(args.output)

    if not candidates_path.exists():
        raise SystemExit(f"candidates not found: {candidates_path}")
    if not references_path.exists():
        raise SystemExit(f"references not found: {references_path}")

    with references_path.open("r", encoding="utf-8", newline="") as handle:
        references = {
            str(row.get("id", "")).strip(): str(row.get("summary", "")).strip()
            for row in csv.DictReader(handle)
        }

    with candidates_path.open("r", encoding="utf-8", newline="") as handle:
        candidates = list(csv.DictReader(handle))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["id", "title", "url", "article", "summary"]
    missing: list[str] = []
    short_or_long: list[tuple[str, int]] = []

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in candidates:
            row_id = str(row.get("id", "")).strip()
            summary = references.get(row_id, "").strip()
            if not summary:
                missing.append(row_id)
            words = word_count(summary)
            if summary and not 50 <= words <= 130:
                short_or_long.append((row_id, words))

            writer.writerow(
                {
                    "id": row_id,
                    "title": row.get("title", ""),
                    "url": row.get("url", ""),
                    "article": row.get("article", ""),
                    "summary": summary,
                }
            )

    print(f"Merged {len(candidates)} rows into {output_path}")
    if missing:
        print(f"Missing summaries for ids: {', '.join(missing)}")
    if short_or_long:
        rendered = ", ".join(f"{row_id}={words}" for row_id, words in short_or_long)
        print(f"Summaries outside 50-130 words: {rendered}")


if __name__ == "__main__":
    main()
