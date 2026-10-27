"""Prepare blind focused review inputs for changed v5 evidence results."""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def concise_excerpt(text: str, limit: int = 500) -> str:
    """Keep coverage context readable in the review workbook."""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    shortened = normalized[:limit].rsplit(" ", 1)[0]
    return f"{shortened}…"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--consolidated-run",
        type=Path,
        default=Path("output/evidence_v4_policy_v5_consolidated_2026_10_25/retrieval_run.jsonl"),
    )
    parser.add_argument(
        "--baseline-run",
        type=Path,
        default=Path("output/evidence_end_to_end_v4_blind_2026_10_25/retrieval_run.jsonl"),
    )
    parser.add_argument(
        "--sample",
        type=Path,
        default=Path("output/evidence_end_to_end_v4_blind_2026_10_25/frozen_claim_sample.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/evidence_v5_focused_review_2026_10_25"),
    )
    args = parser.parse_args()

    current = {row["case_id"]: row for row in read_jsonl(args.consolidated_run)}
    baseline = {row["case_id"]: row for row in read_jsonl(args.baseline_run)}
    sample = {row["case_id"]: row for row in read_csv(args.sample)}
    if set(current) != set(baseline) or set(current) != set(sample):
        raise RuntimeError("Current, baseline, and frozen sample case IDs must match exactly.")

    changed_cases = []
    source_key = []
    for case_id in sorted(current):
        old_urls = {source["url"] for source in baseline[case_id].get("sources", [])}
        new_urls = {source["url"] for source in current[case_id].get("sources", [])}
        if old_urls != new_urls:
            changed_cases.append(case_id)
        independent_new = [
            source for source in current[case_id].get("sources", [])
            if source["url"] not in old_urls and source.get("independenceEligible", True)
        ]
        for index, source in enumerate(independent_new, start=1):
            source_key.append({
                "evidence_id": f"V5F-{case_id}-S{index:02d}",
                "case_id": case_id,
                "claim": sample[case_id]["claim"],
                "original_source": sample[case_id]["original_source"],
                "source_name": source.get("source", ""),
                "source_title": source.get("title", ""),
                "evidence_excerpt": source.get("excerpt", ""),
                "source_url": source.get("url", ""),
                "model_stance": source.get("evidenceStance", ""),
                "assessment_method": source.get("assessmentMethod", ""),
            })

    coverage_key = []
    for case_id in changed_cases:
        sources = current[case_id].get("sources", [])
        source_lines = [
            f"[{source.get('sourceRole', 'independent_evidence')}] "
            f"{source.get('source', '')}: {source.get('title', '')}"
            for source in sources
        ]
        context = concise_excerpt(sample[case_id]["publication_context"])
        coverage_key.append({
            "case_id": case_id,
            "claim": sample[case_id]["claim"],
            "publication_context": f"EXTRACTO DE LA PUBLICACIÓN ORIGINAL:\n{context}\n\nFUENTES RECUPERADAS:\n" + "\n".join(source_lines),
            "original_source": sample[case_id]["original_source"],
            "original_url": sample[case_id]["original_url"],
            "returned_source_count": len(sources),
            "independent_source_count": current[case_id]["independent_source_count"],
            "primary_context_count": current[case_id]["primary_context_count"],
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        args.output_dir / "focused_source_key.csv",
        source_key,
        [
            "evidence_id", "case_id", "claim", "original_source", "source_name",
            "source_title", "evidence_excerpt", "source_url", "model_stance",
            "assessment_method",
        ],
    )
    write_csv(
        args.output_dir / "focused_coverage_key.csv",
        coverage_key,
        [
            "case_id", "claim", "publication_context", "original_source", "original_url",
            "returned_source_count", "independent_source_count", "primary_context_count",
        ],
    )

    source_fields = [
        "order", "evidence_id", "case_id", "claim", "original_source",
        "source_name", "source_title", "evidence_excerpt", "source_url",
        "review_status", "human_stance", "confidence", "notes",
    ]
    coverage_fields = [
        "order", "case_id", "claim", "publication_context", "original_source",
        "original_url", "returned_source_count", "coverage_status",
        "missing_relevant_evidence", "missing_source_url", "notes",
    ]
    for annotator, seed in (("a", 20261026), ("b", 20261027)):
        rng = random.Random(seed)
        sources = [
            {
                "order": 0,
                **{key: row.get(key, "") for key in source_fields},
                "review_status": "",
                "human_stance": "",
                "confidence": "",
                "notes": "",
            }
            for row in source_key
        ]
        rng.shuffle(sources)
        for order, row in enumerate(sources, start=1):
            row["order"] = order

        coverage = [
            {
                "order": 0,
                **{key: row.get(key, "") for key in coverage_fields},
                "coverage_status": "",
                "missing_relevant_evidence": "",
                "missing_source_url": "",
                "notes": "",
            }
            for row in coverage_key
        ]
        rng.shuffle(coverage)
        for order, row in enumerate(coverage, start=1):
            row["order"] = order
        write_csv(args.output_dir / f"annotator_{annotator}_sources.csv", sources, source_fields)
        write_csv(args.output_dir / f"annotator_{annotator}_coverage.csv", coverage, coverage_fields)

    manifest = {
        "purpose": "blind focused human review of evidence changed by retrieval v5",
        "changed_case_n": len(changed_cases),
        "new_independent_source_n": len(source_key),
        "coverage_review_n": len(coverage_key),
        "model_stance_hidden": True,
        "primary_context_excluded_from_source_stance_review": True,
        "confirmatory": False,
        "changed_case_ids": changed_cases,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
