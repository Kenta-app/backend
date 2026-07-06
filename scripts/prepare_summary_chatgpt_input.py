"""
Prepare a compact CSV for ChatGPT-based synthetic summary references.

Input:
  data/summary_references/candidates_30_clean.csv

Output:
  data/summary_references/chatgpt_input_30.csv

The output intentionally excludes existing summaries and URLs so ChatGPT only
uses the title and article content, and returns a small id/summary file.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare compact ChatGPT summary-reference input")
    parser.add_argument("--input", default="data/summary_references/candidates_30_clean.csv")
    parser.add_argument("--output", default="data/summary_references/chatgpt_input_30.csv")
    parser.add_argument("--max_article_chars", type=int, default=4500)
    parser.add_argument("--limit", type=int, default=30)
    return parser


def compact_text(text: str) -> str:
    return " ".join((text or "").split())


def main() -> None:
    args = build_arg_parser().parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        raise SystemExit(f"input not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    with output_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=["id", "title", "article"])
        writer.writeheader()
        count = 0
        for row in rows:
            if args.limit and count >= args.limit:
                break
            article = compact_text(row.get("article", ""))[: args.max_article_chars]
            writer.writerow(
                {
                    "id": row.get("id", ""),
                    "title": compact_text(row.get("title", "")),
                    "article": article,
                }
            )
            count += 1

    print(f"Prepared {count} rows in {output_path}")


if __name__ == "__main__":
    main()
