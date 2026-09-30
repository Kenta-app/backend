"""Utilities for validating and splitting Kenta Stance Peru datasets."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


VALID_LABELS = ("agree", "disagree", "discuss", "unrelated")
VALID_SPLITS = ("train", "validation", "test")
CANONICAL_FIELDS = (
    "pair_id", "corpus_version", "intended_use", "batch_id", "group_id",
    "event_id", "claim_id", "article_id", "pair_construction", "source_name",
    "ownership_group", "title", "original_url", "published_at", "collected_at",
    "collection_method", "article_sha256", "claim", "article",
    "annotator_1", "label_annotator_1", "evidence_annotator_1", "confidence_annotator_1",
    "annotator_2", "label_annotator_2", "evidence_annotator_2", "confidence_annotator_2",
    "adjudicated_label", "adjudication_note", "final_label", "quality_status",
    "quality_flags", "split",
)


def normalize(value: str | None) -> str:
    return (value or "").strip().lower()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def derive_final_label(row: dict[str, str]) -> tuple[str, list[str]]:
    """Derive the gold label without overwriting independent annotations."""
    left = normalize(row.get("label_annotator_1"))
    right = normalize(row.get("label_annotator_2"))
    adjudicated = normalize(row.get("adjudicated_label"))
    flags: list[str] = []

    if adjudicated == "exclude":
        return "", ["adjudicated_exclusion"]
    if adjudicated:
        if adjudicated not in VALID_LABELS:
            return "", ["invalid_adjudicated_label"]
        if left and left not in VALID_LABELS:
            flags.append("invalid_annotator_1_label")
        if right and right not in VALID_LABELS:
            flags.append("invalid_annotator_2_label")
        if left != right and not (row.get("adjudication_note") or "").strip():
            flags.append("missing_adjudication_note")
        return adjudicated, flags

    if left not in VALID_LABELS or right not in VALID_LABELS:
        return "", ["missing_annotation_provenance"]
    if left != right:
        return "", ["unadjudicated_disagreement"]
    return left, flags


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    field_list = list(fields)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_list, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in field_list})


def validate_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict]:
    pair_counts = Counter((row.get("pair_id") or "").strip() for row in rows)
    article_counts = Counter((row.get("article_id") or "").strip() for row in rows)
    group_counts = Counter((row.get("group_id") or "").strip() for row in rows)
    validated: list[dict[str, str]] = []
    all_flags: Counter[str] = Counter()

    for source in rows:
        row = {field: (source.get(field) or "").strip() for field in CANONICAL_FIELDS}
        flags = {item for item in row["quality_flags"].split("|") if item}
        required = ("pair_id", "group_id", "article_id", "source_name", "claim", "article")
        flags.update(f"missing_{field}" for field in required if not row[field])
        if row["pair_id"] and pair_counts[row["pair_id"]] > 1:
            flags.add("duplicate_pair_id")
        if row["article_id"] and article_counts[row["article_id"]] > 1:
            flags.add("shared_article")
        if row["group_id"] and group_counts[row["group_id"]] > 1:
            flags.add("shared_group")
        if len(row["claim"]) > 240:
            flags.add("claim_over_240_chars")
        if len(row["claim"]) < 20:
            flags.add("claim_under_20_chars")
        if len(row["article"]) < 500:
            flags.add("article_under_500_chars")

        final_label, annotation_flags = derive_final_label(row)
        flags.update(annotation_flags)
        supplied_final = normalize(source.get("final_label"))
        if supplied_final and supplied_final != final_label:
            flags.add("supplied_final_label_mismatch")
        row["final_label"] = final_label

        blocking = {
            flag for flag in flags
            if flag.startswith("missing_")
            or flag.startswith("invalid_")
            or flag in {"duplicate_pair_id", "unadjudicated_disagreement", "supplied_final_label_mismatch"}
        }
        requested_status = normalize(source.get("quality_status"))
        if requested_status == "exclude" or "adjudicated_exclusion" in flags:
            row["quality_status"] = "exclude"
        elif blocking or requested_status == "review":
            row["quality_status"] = "review"
        else:
            row["quality_status"] = "include"
        row["quality_flags"] = "|".join(sorted(flags))
        all_flags.update(flags)
        validated.append(row)

    eligible = [row for row in validated if row["quality_status"] == "include" and row["final_label"]]
    report = {
        "rows": len(validated),
        "eligible_rows": len(eligible),
        "status_counts": dict(Counter(row["quality_status"] for row in validated)),
        "label_counts": dict(Counter(row["final_label"] for row in eligible)),
        "source_counts": dict(Counter(row["source_name"] for row in validated)),
        "unique_groups": len({row["group_id"] for row in validated if row["group_id"]}),
        "unique_articles": len({row["article_id"] for row in validated if row["article_id"]}),
        "flag_counts": dict(all_flags.most_common()),
    }
    return validated, report


def _target_counts(rows: list[dict[str, str]], ratios: dict[str, float]) -> dict[str, Counter[str]]:
    labels = Counter(row["final_label"] for row in rows)
    targets = {split: Counter() for split in VALID_SPLITS}
    for label, total in labels.items():
        train = round(total * ratios["train"])
        validation = round(total * ratios["validation"])
        test = total - train - validation
        targets["train"][label] = train
        targets["validation"][label] = validation
        targets["test"][label] = test
    return targets


def assign_grouped_splits(
    rows: list[dict[str, str]], *, seed: int = 42,
    ratios: dict[str, float] | None = None,
) -> list[dict[str, str]]:
    """Assign groups deterministically while approximately preserving classes."""
    ratios = ratios or {"train": 0.6, "validation": 0.2, "test": 0.2}
    if set(ratios) != set(VALID_SPLITS) or abs(sum(ratios.values()) - 1.0) > 1e-9:
        raise ValueError("split ratios must define train, validation and test and sum to 1")
    if any(row.get("quality_status") != "include" or row.get("final_label") not in VALID_LABELS for row in rows):
        raise ValueError("only included rows with a valid final_label can be split")

    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        group_id = (row.get("group_id") or "").strip()
        if not group_id:
            raise ValueError(f"missing group_id for {row.get('pair_id')}")
        groups[group_id].append(row)

    assignments: dict[str, str] = {}
    observed = {split: Counter() for split in VALID_SPLITS}
    targets = _target_counts(rows, ratios)
    locked: dict[str, str] = {}
    for group_id, members in groups.items():
        locked_splits = {normalize(row.get("split")) for row in members if normalize(row.get("split"))}
        if locked_splits - set(VALID_SPLITS):
            raise ValueError(f"invalid locked split for group {group_id}: {sorted(locked_splits)}")
        if len(locked_splits) > 1:
            raise ValueError(f"group leakage already present for {group_id}: {sorted(locked_splits)}")
        if locked_splits:
            locked[group_id] = next(iter(locked_splits))

    for group_id, split in locked.items():
        assignments[group_id] = split
        observed[split].update(row["final_label"] for row in groups[group_id])

    rng = random.Random(seed)
    unlocked = [group_id for group_id in groups if group_id not in locked]
    rng.shuffle(unlocked)
    unlocked.sort(key=lambda group_id: len(groups[group_id]), reverse=True)

    total_targets = {split: sum(targets[split].values()) for split in VALID_SPLITS}
    global_label_totals = Counter(row["final_label"] for row in rows)
    global_total = max(len(rows), 1)
    for group_id in unlocked:
        group_labels = Counter(row["final_label"] for row in groups[group_id])
        best_split = None
        best_score = None
        for split in VALID_SPLITS:
            label_cost = 0.0
            size_cost = 0.0
            for candidate_split in VALID_SPLITS:
                for label in VALID_LABELS:
                    after = observed[candidate_split][label]
                    if candidate_split == split:
                        after += group_labels[label]
                    denominator = max(global_label_totals[label], 1)
                    label_cost += ((after - targets[candidate_split][label]) / denominator) ** 2
                size_after = sum(observed[candidate_split].values())
                if candidate_split == split:
                    size_after += len(groups[group_id])
                size_cost += ((size_after - total_targets[candidate_split]) / global_total) ** 2
            score = label_cost + size_cost
            tie = (score, sum(observed[split].values()), VALID_SPLITS.index(split))
            if best_score is None or tie < best_score:
                best_score = tie
                best_split = split
        assignments[group_id] = str(best_split)
        observed[str(best_split)].update(group_labels)

    result: list[dict[str, str]] = []
    for row in rows:
        copy = dict(row)
        copy["split"] = assignments[row["group_id"]]
        result.append(copy)
    return result


def export_fnc_splits(rows: list[dict[str, str]], output_dir: Path) -> dict[str, dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, dict] = {}
    for split in VALID_SPLITS:
        split_rows = [row for row in rows if row["split"] == split]
        stances_path = output_dir / f"{split}_stances.csv"
        bodies_path = output_dir / f"{split}_bodies.csv"
        metadata_path = output_dir / f"{split}_metadata.csv"
        stances = []
        bodies = []
        metadata = []
        for body_id, row in enumerate(split_rows, start=1):
            stances.append({"Headline": row["claim"], "Body ID": body_id, "Stance": row["final_label"]})
            bodies.append({"Body ID": body_id, "articleBody": row["article"]})
            metadata.append({
                "Body ID": body_id, "pair_id": row["pair_id"], "group_id": row["group_id"],
                "source_name": row["source_name"], "original_url": row["original_url"],
            })
        write_csv(stances_path, stances, ("Headline", "Body ID", "Stance"))
        write_csv(bodies_path, bodies, ("Body ID", "articleBody"))
        write_csv(metadata_path, metadata, ("Body ID", "pair_id", "group_id", "source_name", "original_url"))
        outputs[split] = {
            "rows": len(split_rows),
            "label_counts": dict(Counter(row["final_label"] for row in split_rows)),
            "groups": len({row["group_id"] for row in split_rows}),
            "files": {
                "stances": {"path": str(stances_path), "sha256": sha256_file(stances_path)},
                "bodies": {"path": str(bodies_path), "sha256": sha256_file(bodies_path)},
                "metadata": {"path": str(metadata_path), "sha256": sha256_file(metadata_path)},
            },
        }
    return outputs


def dump_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
