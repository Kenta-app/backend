"""Apply protocol-based adjudication and produce the final targeted challenge set."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DECISIONS = {
    "ch_06c1c12e3260f6c3": (
        "include",
        "refutes",
        "La fuente califica las denuncias de fraude como carentes de pruebas; esto contradice la premisa material de que las fallas demostraron fraude.",
    ),
    "ch_db8207c15df7b102": (
        "include",
        "refutes",
        "La fuente rechaza expresamente la acusación de corrupción y no presenta la prueba atribuida a López Aliaga; contradice la proposición de que quedó probada.",
    ),
    "ch_23fc0dcfcefcf318": (
        "include",
        "refutes",
        "La fuente descarta de forma categórica el fraude y las actas fantasma por falta de sustento técnico o legal; la negación general cubre la serie específica alegada.",
    ),
    "ch_ffbd35d4ba986c90": (
        "include",
        "discusses",
        "La fuente confirma un avance del conteo oficial, pero el fragmento no demuestra que exista una actualización continua y literalmente en tiempo real.",
    ),
}


def norm(value: object) -> str:
    return str(value or "").strip().casefold()


def read_unique(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {norm(row.get("evidence_id")): row for row in rows}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--annotator-a", type=Path, required=True)
    parser.add_argument("--annotator-b", type=Path, required=True)
    parser.add_argument("--conflicts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    key = read_unique(args.key)
    a = read_unique(args.annotator_a)
    b = read_unique(args.annotator_b)
    conflicts = read_unique(args.conflicts)
    if set(conflicts) != set(DECISIONS):
        raise SystemExit(
            f"Adjudication set mismatch. expected={sorted(DECISIONS)} actual={sorted(conflicts)}"
        )

    for evidence_id, row in conflicts.items():
        status, stance, rationale = DECISIONS[evidence_id]
        row["final_status"] = status
        row["final_stance"] = stance
        row["rationale"] = rationale

    args.output_dir.mkdir(parents=True, exist_ok=True)
    completed_path = args.output_dir / "adjudication_completed.csv"
    conflict_fields = list(next(iter(conflicts.values())).keys())
    with completed_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=conflict_fields)
        writer.writeheader()
        writer.writerows(conflicts.values())

    final_rows: list[dict[str, str]] = []
    for evidence_id, key_row in key.items():
        a_status, b_status = norm(a[evidence_id]["review_status"]), norm(b[evidence_id]["review_status"])
        a_stance, b_stance = norm(a[evidence_id]["human_stance"]), norm(b[evidence_id]["human_stance"])
        if a_status == b_status and (a_status != "include" or a_stance == b_stance):
            final_status, final_stance = a_status, a_stance
            decision_source = "agreement"
            rationale = "Coincidencia entre ambos anotadores."
        else:
            final_status, final_stance, rationale = DECISIONS[evidence_id]
            decision_source = "adjudication"
        final_rows.append({
            "evidence_id": evidence_id,
            "claim": key_row.get("claim", ""),
            "source_name": key_row.get("source_name", ""),
            "source_title": key_row.get("source_title", ""),
            "evidence_excerpt": key_row.get("evidence_excerpt", ""),
            "source_url": key_row.get("source_url", ""),
            "final_status": final_status,
            "final_stance": final_stance,
            "decision_source": decision_source,
            "rationale": rationale,
        })

    final_path = args.output_dir / "final_annotations.csv"
    final_fields = list(final_rows[0].keys())
    with final_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=final_fields)
        writer.writeheader()
        writer.writerows(final_rows)

    final_labels = [row["final_stance"] for row in final_rows if row["final_status"] == "include"]
    historical_matches = sum(
        row["final_stance"] == norm(key[row["evidence_id"]].get("prior_human_label"))
        for row in final_rows
    )
    report = {
        "protocol_version": "evidence-policy-2026-10-22-v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_size": len(final_rows),
        "agreement_decisions": sum(row["decision_source"] == "agreement" for row in final_rows),
        "adjudicated_decisions": sum(row["decision_source"] == "adjudication" for row in final_rows),
        "final_status_counts": dict(Counter(row["final_status"] for row in final_rows)),
        "final_label_counts": dict(Counter(final_labels)),
        "historical_reference_match_rate": historical_matches / len(final_rows),
        "interpretation_limit": (
            "The historical labels helped define the targeted sample. Their match rate is a regression "
            "consistency check, not an independent performance estimate."
        ),
        "completed_adjudication": str(completed_path),
        "final_annotations": str(final_path),
    }
    report_path = args.output_dir / "targeted_challenge_final_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
