"""Validate and adapt frozen Challenge 05 for confirmatory evidence-policy evaluation."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


LABEL_MAP = {
    "agree": "supports",
    "disagree": "refutes",
    "discuss": "discusses",
    "unrelated": "unrelated",
}


def norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--development", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN":
        raise SystemExit("Challenge 05 is not frozen.")
    actual_hash = sha256_file(args.gold)
    if actual_hash != manifest.get("gold_sha256"):
        raise SystemExit("Challenge 05 hash does not match its frozen manifest.")
    rows = json.loads(args.gold.read_text(encoding="utf-8"))
    if len(rows) != manifest.get("records"):
        raise SystemExit("Challenge 05 record count does not match its manifest.")

    development_keys: set[tuple[str, str]] = set()
    development_claims: set[str] = set()
    for path in args.development:
        for row in read_csv(path):
            claim = norm(row.get("claim"))
            url = norm(row.get("source_url") or row.get("original_url"))
            if claim:
                development_claims.add(claim)
                development_keys.add((claim, url))

    exact_overlap: list[str] = []
    claim_overlap: list[str] = []
    adapted: list[dict[str, str]] = []
    for row in rows:
        claim = norm(row.get("claim"))
        url = norm(row.get("original_url"))
        if (claim, url) in development_keys:
            exact_overlap.append(row["pair_id"])
        elif claim in development_claims:
            claim_overlap.append(row["pair_id"])
        label = LABEL_MAP[norm(row.get("gold_label"))]
        adapted.append({
            "evidence_id": row["pair_id"],
            "group_id": row["group_id"],
            "claim": row["claim"],
            "source_name": row["source_name"],
            "source_title": row["title"],
            "evidence_excerpt": row["context"],
            "source_url": row["original_url"],
            "final_status": "include",
            "final_stance": label,
            "decision_source": row.get("gold_origin", ""),
            "rationale": row.get("adjudication_rationale", ""),
        })

    if exact_overlap or claim_overlap:
        raise SystemExit(
            f"Overlap detected. exact={exact_overlap}; claim_only={claim_overlap}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "challenge05_evidence_gold.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=adapted[0].keys())
        writer.writeheader()
        writer.writerows(adapted)

    report = {
        "prepared_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_batch": manifest.get("batch_id"),
        "source_gold_sha256": actual_hash,
        "source_status": manifest.get("status"),
        "epistemic_role": "independent_confirmatory_evaluation_for_evidence_policy_v3",
        "records": len(adapted),
        "groups": manifest.get("groups"),
        "label_counts": dict(Counter(row["final_stance"] for row in adapted)),
        "human_agreement_before_adjudication": manifest.get("agreement_before_adjudication"),
        "exact_overlap_with_evidence_development": len(exact_overlap),
        "claim_overlap_with_evidence_development": len(claim_overlap),
        "model_policy_frozen_before_first_read": "evidence-policy-2026-10-22-v3",
        "training_or_threshold_tuning_prohibited": True,
        "adapted_gold": str(csv_path),
    }
    report_path = args.output_dir / "confirmatory_preparation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
