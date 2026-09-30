"""Build a validated benchmark CSV from the human-reference workbook.

The workbook is treated as source data. This script only exports rows marked
Selected, after validating completion, quality control, word range, and unique
source IDs.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import pandas as pd


WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    references = pd.read_excel(args.workbook, sheet_name="References", header=4)
    candidates = pd.read_excel(args.workbook, sheet_name="Candidates")
    references = references[references["Source ID"].notna()].copy()
    references["Source ID"] = references["Source ID"].astype(int)
    selected = references[references["Sample"].eq("Selected")].copy()

    if len(selected) != 100 or selected["Source ID"].nunique() != 100:
        raise ValueError("Expected exactly 100 unique Selected references.")
    if not selected["Status"].eq("Complete").all():
        raise ValueError("Every Selected reference must be Complete.")
    if not selected["Quality check"].eq("OK").all():
        raise ValueError("Every Selected reference must pass quality control.")
    if selected["Human reference summary"].isna().any():
        raise ValueError("Selected references cannot be blank.")
    counted_words = selected["Human reference summary"].map(lambda value: word_count(str(value)))
    if ((counted_words < 60) | (counted_words > 100)).any():
        invalid_ids = selected.loc[(counted_words < 60) | (counted_words > 100), "Source ID"].tolist()
        raise ValueError(f"Selected references outside 60–100 words: {invalid_ids}")

    candidates["id"] = candidates["id"].astype(int)
    required = candidates[["id", "title", "url", "article"]].copy()
    exported = selected[["Source ID", "Human reference summary"]].merge(
        required,
        left_on="Source ID",
        right_on="id",
        how="left",
        validate="one_to_one",
    )
    if exported[["title", "url", "article"]].isna().any().any():
        raise ValueError("A Selected Source ID is missing from Candidates.")
    exported = exported.drop(columns=["id"]).rename(
        columns={"Source ID": "id", "Human reference summary": "summary"}
    )
    exported = exported[["id", "title", "url", "article", "summary"]].sort_values("id")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    exported.to_csv(args.output, index=False, quoting=csv.QUOTE_ALL, encoding="utf-8", lineterminator="\n")
    print(f"[OK] exported {len(exported)} validated references to {args.output}")


if __name__ == "__main__":
    main()
