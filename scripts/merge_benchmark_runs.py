"""Merge benchmark CSV runs after confirming shared source IDs."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows: list[dict[str, str]] = []
    fieldnames: list[str] | None = None
    model_ids: dict[str, set[str]] = {}
    for path in args.inputs:
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if fieldnames is None:
                fieldnames = reader.fieldnames
            elif reader.fieldnames != fieldnames:
                raise ValueError(f"Columns differ in {path}")
            for row in reader:
                model = row["model"]
                source_id = row["source_id"]
                if source_id in model_ids.setdefault(model, set()):
                    raise ValueError(f"Duplicate source ID {source_id} for {model}")
                model_ids[model].add(source_id)
                rows.append(row)

    if len(model_ids) < 2:
        raise ValueError("Expected at least two model runs.")
    reference_ids = next(iter(model_ids.values()))
    if any(ids != reference_ids for ids in model_ids.values()):
        raise ValueError("Models do not share an identical source-ID set.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] merged {len(rows)} rows for {len(model_ids)} models; n={len(reference_ids)} per model")


if __name__ == "__main__":
    main()
