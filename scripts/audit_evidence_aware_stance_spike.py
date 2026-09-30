"""Audit the prepared evidence-aware stance feasibility corpus.

The audit is intentionally independent from the preparation script. It checks
artifact integrity, paired examples across representations, grouped splits,
class coverage, and token-budget constraints before any model is trained.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from transformers import AutoTokenizer


SPLITS = ("train", "validation", "test")
LABELS = ("unrelated", "discuss", "agree", "disagree")
PLACEHOLDER = "sin evidencia pertinente"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_examples(prepared_dir: Path, representation: str, split: str) -> list[dict]:
    fnc_dir = prepared_dir / representation / "fnc"
    stances = read_csv(fnc_dir / f"{split}_stances.csv")
    bodies = read_csv(fnc_dir / f"{split}_bodies.csv")
    metadata = read_csv(fnc_dir / f"{split}_metadata.csv")
    bodies_by_id = {row["Body ID"]: row["articleBody"] for row in bodies}
    metadata_by_id = {row["Body ID"]: row for row in metadata}
    if len(bodies_by_id) != len(bodies) or len(metadata_by_id) != len(metadata):
        raise ValueError(f"Duplicate Body ID in {representation}/{split}")
    examples = []
    for stance in stances:
        body_id = stance["Body ID"]
        if body_id not in bodies_by_id or body_id not in metadata_by_id:
            raise ValueError(f"Missing join key {body_id} in {representation}/{split}")
        meta = metadata_by_id[body_id]
        examples.append(
            {
                "pair_id": meta["pair_id"],
                "group_id": meta["group_id"],
                "label": stance["Stance"].casefold(),
                "headline": stance["Headline"],
                "body": bodies_by_id[body_id],
            }
        )
    if len(examples) != len(bodies) or len(examples) != len(metadata):
        raise ValueError(f"Row-count mismatch in {representation}/{split}")
    return examples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepared_dir", type=Path, required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--max_length", type=int, default=192)
    args = parser.parse_args()

    prepared_dir = args.prepared_dir.resolve()
    manifest_path = prepared_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    representations = tuple(manifest["representations"])
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)

    failures: list[str] = []
    checks: dict[str, object] = {}

    hash_failures = []
    for relative_path, expected in manifest["artifacts"].items():
        path = prepared_dir / relative_path
        actual = sha256_file(path) if path.exists() else None
        if actual != expected["sha256"]:
            hash_failures.append({"path": relative_path, "expected": expected["sha256"], "actual": actual})
    checks["artifact_hashes"] = {"checked": len(manifest["artifacts"]), "failures": hash_failures}
    if hash_failures:
        failures.append("One or more prepared artifacts do not match the manifest hashes")

    all_examples: dict[str, dict[str, list[dict]]] = {}
    for representation in representations:
        all_examples[representation] = {}
        for split in SPLITS:
            all_examples[representation][split] = load_examples(prepared_dir, representation, split)

    reference = all_examples[representations[0]]
    alignment_failures = []
    for representation in representations[1:]:
        for split in SPLITS:
            reference_signature = [
                (row["pair_id"], row["group_id"], row["label"], row["headline"])
                for row in reference[split]
            ]
            candidate_signature = [
                (row["pair_id"], row["group_id"], row["label"], row["headline"])
                for row in all_examples[representation][split]
            ]
            if candidate_signature != reference_signature:
                alignment_failures.append(f"{representation}/{split}")
    checks["paired_alignment"] = {"failures": alignment_failures}
    if alignment_failures:
        failures.append("Representations are not aligned over identical examples")

    split_groups = {
        split: {row["group_id"] for row in reference[split]}
        for split in SPLITS
    }
    overlaps = {
        "train_validation": sorted(split_groups["train"] & split_groups["validation"]),
        "train_test": sorted(split_groups["train"] & split_groups["test"]),
        "validation_test": sorted(split_groups["validation"] & split_groups["test"]),
    }
    checks["group_leakage"] = overlaps
    if any(overlaps.values()):
        failures.append("Group leakage exists across splits")

    label_counts = {
        split: dict(Counter(row["label"] for row in reference[split]))
        for split in SPLITS
    }
    checks["label_counts"] = label_counts
    for split, counts in label_counts.items():
        missing = sorted(set(LABELS) - set(counts))
        if missing:
            failures.append(f"{split} is missing labels: {', '.join(missing)}")

    token_stats: dict[str, dict[str, object]] = {}
    placeholder_hits = []
    for representation in representations:
        token_stats[representation] = {}
        for split in SPLITS:
            lengths = []
            over_budget = []
            for row in all_examples[representation][split]:
                encoded = tokenizer(
                    row["headline"], row["body"], add_special_tokens=True, truncation=False,
                )["input_ids"]
                length = len(encoded)
                lengths.append(length)
                if length > args.max_length:
                    over_budget.append(row["pair_id"])
                if PLACEHOLDER in row["body"].casefold():
                    placeholder_hits.append(
                        {"representation": representation, "split": split, "pair_id": row["pair_id"]}
                    )
            token_stats[representation][split] = {
                "records": len(lengths),
                "minimum": min(lengths),
                "median": sorted(lengths)[len(lengths) // 2],
                "maximum": max(lengths),
                "over_max_length": len(over_budget),
                "over_max_length_pair_ids": over_budget,
            }
            if representation != "document_prefix" and over_budget:
                failures.append(f"{representation}/{split} exceeds the paired token budget")
    checks["paired_token_lengths"] = token_stats
    checks["placeholder_leakage"] = placeholder_hits
    if placeholder_hits:
        failures.append("The annotation placeholder appears in model input")

    report = {
        "status": "PASS" if not failures else "FAIL",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "prepared_dir": str(prepared_dir),
        "tokenizer": str(Path(args.tokenizer).resolve()),
        "max_length": args.max_length,
        "records": sum(len(reference[split]) for split in SPLITS),
        "frozen_prospective_set_used": manifest.get("frozen_prospective_set_used"),
        "checks": checks,
        "failures": failures,
    }
    output_path = prepared_dir / "preparation_audit.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
