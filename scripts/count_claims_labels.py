"""
Count labels in claims JSONL files.

Usage:
    python scripts/count_claims_labels.py --inputs data/newtral/claims.jsonl data/maldita/claims.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Count labels in JSONL claims")
    parser.add_argument("--inputs", nargs="+", required=True, help="JSONL files")
    return parser


def count_labels(path: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            label = item.get("label")
            if label:
                counter[str(label)] += 1
    return counter


def main() -> None:
    args = build_arg_parser().parse_args()
    for path in args.inputs:
        counts = count_labels(path)
        total = sum(counts.values())
        print(f"{path}: total={total} true={counts.get('true', 0)} false={counts.get('false', 0)}")


if __name__ == "__main__":
    main()
