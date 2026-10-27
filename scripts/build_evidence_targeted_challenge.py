"""Build a blind development challenge set for scarce evidence stances.

This set is intentionally enriched with previously adjudicated refutations,
unrelated pairs, and difficult discusses/supports boundaries. It is suitable
for rubric calibration and regression testing, not for estimating natural
class prevalence or for a final independent performance claim.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


BLIND_FIELDS = (
    "order", "evidence_id", "claim", "source_name", "source_title",
    "evidence_excerpt", "source_url", "review_status", "human_stance",
    "confidence", "notes",
)
PRIVATE_FIELDS = (
    "evidence_id", "origin_id", "claim", "source_name", "source_title",
    "evidence_excerpt", "source_url", "target_stratum", "prior_human_label",
    "selection_reason", "source_dataset",
)
LABEL_MAP = {"disagree": "refutes", "unrelated": "unrelated"}


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def compact_excerpt(value: object, limit: int = 500) -> str:
    text = clean(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def challenge_id(origin: str, claim: str, url: str) -> str:
    seed = f"{origin}|{clean(claim).casefold()}|{clean(url).casefold()}"
    return f"ch_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def corpus_candidate(row: dict[str, str]) -> dict[str, str]:
    origin = clean(row.get("pair_id"))
    prior = LABEL_MAP[clean(row.get("final_label")).casefold()]
    return {
        "evidence_id": challenge_id(origin, row.get("claim", ""), row.get("original_url", "")),
        "origin_id": origin,
        "claim": clean(row.get("claim")),
        "source_name": clean(row.get("source_name")),
        "source_title": clean(row.get("title")),
        "evidence_excerpt": compact_excerpt(row.get("article")),
        "source_url": clean(row.get("original_url")),
        "target_stratum": prior,
        "prior_human_label": prior,
        "selection_reason": "previously adjudicated scarce class",
        "source_dataset": "stance_es_pe_v1 development corpus",
    }


def boundary_candidate(row: dict[str, str]) -> dict[str, str]:
    origin = clean(row.get("evidence_id"))
    return {
        "evidence_id": challenge_id(origin, row.get("claim", ""), row.get("source_url", "")),
        "origin_id": origin,
        "claim": clean(row.get("claim")),
        "source_name": clean(row.get("source_name")),
        "source_title": clean(row.get("source_title")),
        "evidence_excerpt": clean(row.get("evidence_excerpt")),
        "source_url": clean(row.get("source_url")),
        "target_stratum": "discusses",
        "prior_human_label": "discusses",
        "selection_reason": "adjudicated supports/discusses boundary",
        "source_dataset": "evidence annotation pilot 2026-10-21",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("output/stance_es_pe_v1/prepared/master_validated.csv"))
    parser.add_argument("--boundary", type=Path, default=Path("output/evidence_annotation_results/adjudication_completed.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/evidence_annotation_targeted_challenge"))
    parser.add_argument("--refutes", type=int, default=20)
    parser.add_argument("--unrelated", type=int, default=20)
    parser.add_argument("--boundary-discusses", type=int, default=7)
    parser.add_argument("--seed", type=int, default=20261022)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    corpus = [row for row in read_csv(args.corpus) if clean(row.get("quality_status")).casefold() == "include"]
    boundary = read_csv(args.boundary)

    by_label = {
        label: [row for row in corpus if clean(row.get("final_label")).casefold() == label]
        for label in LABEL_MAP
    }
    for rows in by_label.values():
        rng.shuffle(rows)

    selected = [corpus_candidate(row) for row in by_label["disagree"][: args.refutes]]
    selected += [corpus_candidate(row) for row in by_label["unrelated"][: args.unrelated]]
    boundary_rows = [
        row for row in boundary
        if clean(row.get("final_status")) == "include" and clean(row.get("final_stance")) == "discusses"
    ]
    rng.shuffle(boundary_rows)
    selected += [boundary_candidate(row) for row in boundary_rows[: args.boundary_discusses]]

    if not selected:
        raise SystemExit("No eligible challenge candidates were found.")
    ids = [row["evidence_id"] for row in selected]
    if len(ids) != len(set(ids)):
        raise SystemExit("Duplicate evidence_id values in challenge set.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    private_path = args.output_dir / "evidence_challenge_key.csv"
    write_csv(private_path, PRIVATE_FIELDS, selected)

    annotator_files: dict[str, Path] = {}
    for offset, annotator in enumerate(("a", "b"), start=1):
        ordered = selected.copy()
        random.Random(args.seed + offset).shuffle(ordered)
        blind_rows = [
            {
                **row,
                "order": str(index),
                "review_status": "",
                "human_stance": "",
                "confidence": "",
                "notes": "",
            }
            for index, row in enumerate(ordered, start=1)
        ]
        path = args.output_dir / f"evidence_challenge_annotator_{annotator}.csv"
        write_csv(path, BLIND_FIELDS, blind_rows)
        annotator_files[annotator] = path

    counts = Counter(row["target_stratum"] for row in selected)
    manifest = {
        "protocol_version": "evidence-challenge-2026-10-22-v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "development calibration and regression challenge",
        "not_valid_for": ["natural class prevalence", "independent confirmatory performance"],
        "seed": args.seed,
        "requested": {"refutes": args.refutes, "unrelated": args.unrelated, "boundary_discusses": args.boundary_discusses},
        "available": {"refutes": len(by_label["disagree"]), "unrelated": len(by_label["unrelated"]), "boundary_discusses": len(boundary_rows)},
        "selected": dict(counts),
        "selected_total": len(selected),
        "known_limitation": "The refutes stratum is concentrated in Peruvian political/electoral coverage and reuses prior human labels.",
        "files": {
            "private_key": {"path": str(private_path), "sha256": file_sha256(private_path)},
            **{
                f"annotator_{name}": {"path": str(path), "sha256": file_sha256(path)}
                for name, path in annotator_files.items()
            },
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
