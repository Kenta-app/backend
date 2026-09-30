"""Combine all finalized development splits for one fixed-epoch final training run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


SPLITS = ("train", "validation", "test")
LABELS = ("unrelated", "discuss", "agree", "disagree")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared_dir", type=Path, required=True)
    parser.add_argument("--representation", default="retrieved_evidence")
    parser.add_argument("--output_dir", type=Path, required=True)
    args = parser.parse_args()
    prepared = args.prepared_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    fnc_dir = prepared / args.representation / "fnc"

    bodies_out: list[dict] = []
    stances_out: list[dict] = []
    metadata_out: list[dict] = []
    body_id = 0
    for split in SPLITS:
        stances = read_csv(fnc_dir / f"{split}_stances.csv")
        bodies = {row["Body ID"]: row["articleBody"] for row in read_csv(fnc_dir / f"{split}_bodies.csv")}
        metadata = {row["Body ID"]: row for row in read_csv(fnc_dir / f"{split}_metadata.csv")}
        for stance in stances:
            source_id = stance["Body ID"]
            body_id += 1
            bodies_out.append({"Body ID": body_id, "articleBody": bodies[source_id]})
            stances_out.append({"Headline": stance["Headline"], "Body ID": body_id, "Stance": stance["Stance"]})
            metadata_out.append(
                {
                    "Body ID": body_id,
                    "pair_id": metadata[source_id]["pair_id"],
                    "group_id": metadata[source_id]["group_id"],
                    "article_id": metadata[source_id]["article_id"],
                    "source_name": metadata[source_id]["source_name"],
                    "final_label": metadata[source_id]["final_label"],
                    "representation": args.representation,
                    "development_origin_split": split,
                }
            )

    if len(stances_out) != 198:
        raise ValueError(f"Expected 198 development pairs, got {len(stances_out)}")
    if len({row["pair_id"] for row in metadata_out}) != len(metadata_out):
        raise ValueError("Duplicate pair_id in combined final training data")
    counts = Counter(row["Stance"] for row in stances_out)
    if set(counts) != set(LABELS):
        raise ValueError(f"Missing labels: {counts}")

    body_path = output_dir / "development_all_bodies.csv"
    stance_path = output_dir / "development_all_stances.csv"
    metadata_path = output_dir / "development_all_metadata.csv"
    write_csv(body_path, bodies_out, ["Body ID", "articleBody"])
    write_csv(stance_path, stances_out, ["Headline", "Body ID", "Stance"])
    write_csv(metadata_path, metadata_out, list(metadata_out[0]))
    manifest = {
        "status": "FINAL_TRAINING_DATA_FROZEN",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "representation": args.representation,
        "records": len(stances_out),
        "groups": len({row["group_id"] for row in metadata_out}),
        "label_counts": dict(counts),
        "source_preparation_manifest": str((prepared / "manifest.json").resolve()),
        "source_preparation_manifest_sha256": sha256_file(prepared / "manifest.json"),
        "artifacts": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in (body_path, stance_path, metadata_path)
        },
    }
    manifest_path = output_dir / "final_training_data_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
