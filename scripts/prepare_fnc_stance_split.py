"""
Create a reproducible train/validation split for FNC-1 stance training.

The original FNC-1 files in this project provide:
  - train_stances.csv / train_bodies.csv
  - competition_test_stances.csv / competition_test_bodies.csv

For a cleaner paper setup, this script splits the original training stances into
train and validation, while leaving competition_test untouched for final test
evaluation. The split is grouped by Body ID to reduce article-body leakage
between train and validation.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare grouped FNC-1 stance train/validation split")
    parser.add_argument("--input_stances", default="data/fnc-1/train_stances.csv")
    parser.add_argument("--output_dir", default="data/fnc-1-paper-split")
    parser.add_argument("--validation_ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def label_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    return dict(Counter(row["Stance"] for row in rows))


def split_by_body_id(
    rows: list[dict[str, str]],
    *,
    validation_ratio: float,
    seed: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[int], list[int]]:
    by_body: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_body[int(row["Body ID"])].append(row)

    body_ids = list(by_body.keys())
    random.Random(seed).shuffle(body_ids)

    target_validation_rows = int(round(len(rows) * validation_ratio))
    validation_body_ids: set[int] = set()
    validation_count = 0

    for body_id in body_ids:
        if validation_count >= target_validation_rows:
            break
        validation_body_ids.add(body_id)
        validation_count += len(by_body[body_id])

    train_rows: list[dict[str, str]] = []
    validation_rows: list[dict[str, str]] = []

    for row in rows:
        body_id = int(row["Body ID"])
        if body_id in validation_body_ids:
            validation_rows.append(row)
        else:
            train_rows.append(row)

    train_body_ids = [body_id for body_id in body_ids if body_id not in validation_body_ids]
    return train_rows, validation_rows, train_body_ids, sorted(validation_body_ids)


def main() -> None:
    args = build_arg_parser().parse_args()
    input_path = Path(args.input_stances)
    output_dir = Path(args.output_dir)

    if not input_path.exists():
        raise SystemExit(f"input_stances not found: {input_path}")
    if not 0 < args.validation_ratio < 1:
        raise SystemExit("validation_ratio must be between 0 and 1")

    rows = read_rows(input_path)
    if not rows:
        raise SystemExit(f"No rows found in {input_path}")

    fieldnames = list(rows[0].keys())
    train_rows, validation_rows, train_body_ids, validation_body_ids = split_by_body_id(
        rows,
        validation_ratio=args.validation_ratio,
        seed=args.seed,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    train_path = output_dir / "train_stances.csv"
    validation_path = output_dir / "validation_stances.csv"
    metadata_path = output_dir / "split_metadata.json"

    write_rows(train_path, train_rows, fieldnames)
    write_rows(validation_path, validation_rows, fieldnames)

    metadata = {
        "source_stances": str(input_path),
        "validation_ratio": args.validation_ratio,
        "seed": args.seed,
        "split_strategy": "grouped_by_body_id",
        "train_stances": str(train_path),
        "validation_stances": str(validation_path),
        "train_rows": len(train_rows),
        "validation_rows": len(validation_rows),
        "train_body_ids": len(train_body_ids),
        "validation_body_ids": len(validation_body_ids),
        "train_label_counts": label_counts(train_rows),
        "validation_label_counts": label_counts(validation_rows),
        "final_test_stances": "data/fnc-1/competition_test_stances.csv",
        "final_test_bodies": "data/fnc-1/competition_test_bodies.csv",
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=True, indent=2), encoding="utf-8")

    print(f"Train rows      : {len(train_rows)}")
    print(f"Validation rows : {len(validation_rows)}")
    print(f"Train labels    : {metadata['train_label_counts']}")
    print(f"Validation labels: {metadata['validation_label_counts']}")
    print(f"Wrote {train_path}")
    print(f"Wrote {validation_path}")
    print(f"Wrote {metadata_path}")


if __name__ == "__main__":
    main()
