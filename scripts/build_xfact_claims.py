"""
Build a Spanish claims dataset from X-Fact (utahnlp/x-fact).

Usage:
    python scripts/build_xfact_claims.py --output_dir data/xfact --language es

Notes:
- Requires datasets: pip install datasets
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import unicodedata
from collections import Counter
from typing import Any

from datasets import load_dataset


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_SPLITS = "train,dev,test"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build X-Fact claims dataset")
    parser.add_argument("--output_dir", default="data/xfact")
    parser.add_argument("--language", default="es")
    parser.add_argument("--splits", default=DEFAULT_SPLITS)
    parser.add_argument("--max_items", type=int, default=0, help="Limit total items (0=all)")
    parser.add_argument("--claim_field", default="")
    parser.add_argument("--label_field", default="")
    parser.add_argument("--language_field", default="")
    return parser


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return " ".join(stripped.lower().split())


def map_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value == 1:
            return "true"
        if value == 0:
            return "false"
        return None

    normalized = normalize_text(str(value))
    if not normalized:
        return None

    true_keys = ["true", "support", "supported", "correct", "yes", "verdadero", "cierto"]
    false_keys = ["false", "refute", "refuted", "incorrect", "no", "falso", "bulo"]
    skip_keys = ["not enough", "nei", "unknown", "mixture", "mixed", "partly", "half"]

    if any(key in normalized for key in skip_keys):
        return None
    if any(key in normalized for key in true_keys):
        return "true"
    if any(key in normalized for key in false_keys):
        return "false"
    return None


def guess_field(columns: list[str], preferred: list[str]) -> str | None:
    for candidate in preferred:
        if candidate in columns:
            return candidate
    for candidate in columns:
        lowered = candidate.lower()
        for key in preferred:
            if key in lowered:
                return candidate
    return None


def load_xfact(language: str, splits: list[str]):
    try:
        return load_dataset("utahnlp/x-fact", language, split=splits)
    except Exception:
        dataset = load_dataset("utahnlp/x-fact", "all_languages", split=splits)
        return dataset


def main() -> None:
    args = build_arg_parser().parse_args()
    splits = [item.strip() for item in args.splits.split(",") if item.strip()]

    dataset = load_xfact(args.language, splits)
    if isinstance(dataset, list):
        columns = list(dataset[0].column_names)
    else:
        columns = list(dataset.column_names)

    claim_field = args.claim_field or guess_field(columns, ["claim", "statement", "text"])
    label_field = args.label_field or guess_field(columns, ["label", "verdict", "rating"])
    language_field = args.language_field or guess_field(columns, ["language", "lang"])

    if not claim_field or not label_field:
        raise SystemExit(
            f"Could not detect claim/label fields. Columns: {columns}. "
            "Use --claim_field and --label_field."
        )

    logger.info(
        "Using fields: claim=%s label=%s language=%s",
        claim_field,
        label_field,
        language_field or "<none>",
    )

    items: list[dict] = []
    skipped = 0
    counts = Counter()

    def iter_rows():
        if isinstance(dataset, list):
            for subset in dataset:
                for item in subset:
                    yield item
        else:
            for item in dataset:
                yield item

    for idx, row in enumerate(iter_rows(), start=1):
        if args.max_items and idx > args.max_items:
            break

        if language_field:
            lang = row.get(language_field)
            if lang and str(lang).lower() != args.language.lower():
                continue

        claim = row.get(claim_field)
        raw_label = row.get(label_field)
        if not claim:
            skipped += 1
            continue

        label = map_label(raw_label)
        if label is None:
            skipped += 1
            continue

        counts[label] += 1
        items.append(
            {
                "id": str(len(items) + 1),
                "claim_text": str(claim).strip(),
                "label": label,
                "verdict_raw": str(raw_label),
                "url": row.get("url") or row.get("source") or "",
                "source": "xfact",
                "date": row.get("date") or "",
            }
        )

    if not items:
        raise SystemExit("No usable items collected. Check field mapping.")

    os.makedirs(args.output_dir, exist_ok=True)
    output_path = os.path.join(args.output_dir, f"claims_{args.language}.jsonl")

    with open(output_path, "w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    logger.info(
        "Saved %s items to %s (true=%s false=%s skipped=%s)",
        len(items),
        output_path,
        counts.get("true", 0),
        counts.get("false", 0),
        skipped,
    )


if __name__ == "__main__":
    main()
