"""
Combine multiple claims JSONL files into stratified train/val/test TSVs.

Usage:
    python scripts/combine_claims.py --inputs data/newtral/claims.jsonl data/maldita/claims.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
from typing import Iterable


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Combine claims JSONL files")
    parser.add_argument("--inputs", nargs="+", required=True, help="JSONL files")
    parser.add_argument("--output_dir", default="data/claims_combined")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train_ratio", type=float, default=0.8)
    parser.add_argument("--val_ratio", type=float, default=0.1)
    parser.add_argument(
        "--max_ratio",
        type=float,
        default=0.0,
        help="Cap majority/minority ratio before splitting (0=disabled)",
    )
    return parser


def load_items(paths: Iterable[str]) -> list[dict]:
    items: list[dict] = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = json.loads(line)
                if item.get("label") in ("true", "false"):
                    items.append(item)
    return items


def split_items(
    items: list[dict],
    train_ratio: float,
    val_ratio: float,
    seed: int,
    max_ratio: float,
):
    rng = random.Random(seed)
    by_label = {"true": [], "false": []}
    for item in items:
        by_label[item["label"]].append(item)

    for group in by_label.values():
        rng.shuffle(group)

    if max_ratio and max_ratio > 0:
        counts = {label: len(group) for label, group in by_label.items()}
        min_count = min(counts.values())
        if min_count > 0:
            for label, group in by_label.items():
                cap = int(min_count * max_ratio)
                if len(group) > cap:
                    by_label[label] = group[:cap]

    train: list[dict] = []
    val: list[dict] = []
    test: list[dict] = []

    for group in by_label.values():
        total = len(group)
        train_end = int(total * train_ratio)
        val_end = train_end + int(total * val_ratio)
        train.extend(group[:train_end])
        val.extend(group[train_end:val_end])
        test.extend(group[val_end:])

    rng.shuffle(train)
    rng.shuffle(val)
    rng.shuffle(test)
    return train, val, test


def write_tsv(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        for idx, item in enumerate(rows, start=1):
            writer.writerow(
                [
                    idx,
                    item.get("label"),
                    item.get("claim_text"),
                    item.get("source", ""),
                    item.get("url", ""),
                    item.get("verdict_raw", ""),
                    item.get("date", "") or "",
                ]
            )


def main() -> None:
    args = build_arg_parser().parse_args()
    items = load_items(args.inputs)
    if not items:
        raise SystemExit("No usable items found in inputs.")

    train, val, test = split_items(
        items,
        args.train_ratio,
        args.val_ratio,
        args.seed,
        args.max_ratio,
    )

    os.makedirs(args.output_dir, exist_ok=True)
    write_tsv(os.path.join(args.output_dir, "train.tsv"), train)
    write_tsv(os.path.join(args.output_dir, "validation.tsv"), val)
    write_tsv(os.path.join(args.output_dir, "test.tsv"), test)

    print(
        f"train={len(train)} val={len(val)} test={len(test)} total={len(items)}"
    )


if __name__ == "__main__":
    main()
