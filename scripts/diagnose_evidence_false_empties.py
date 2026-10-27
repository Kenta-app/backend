"""Classify adjudicated zero-source cases without calling external services."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


def normalize_url(value: str) -> str:
    parsed = urlparse((value or "").strip())
    domain = parsed.netloc.casefold().removeprefix("www.")
    return f"{domain}{parsed.path.rstrip('/')}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    with args.coverage.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    diagnosed = []
    for row in rows:
        if int(row["returned_source_count"]) != 0 or row["final_coverage"] != "none":
            continue
        original = normalize_url(row.get("original_url", ""))
        missing = normalize_url(row.get("final_missing_url", ""))
        if missing and missing == original:
            category = "primary_context_only"
            cause = "La publicación original existía, pero la política la excluía de toda salida."
            correction = "Mostrarla como contexto primario y excluirla de corroboración independiente."
        elif missing:
            category = "independent_retrieval_miss"
            cause = "Existía una cobertura distinta que las consultas o filtros no recuperaron."
            correction = "Ampliar consultas breves y búsquedas site: a medios pertinentes."
        else:
            category = "unresolved_false_empty"
            cause = "La adjudicación indicó evidencia existente sin URL verificable."
            correction = "Revisión manual antes de modificar la política."
        diagnosed.append({
            "case_id": row["case_id"],
            "claim": row["claim"],
            "original_source": row["original_source"],
            "original_url": row["original_url"],
            "missing_url": row.get("final_missing_url", ""),
            "category": category,
            "root_cause": cause,
            "implemented_correction": correction,
        })

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_csv = args.output_dir / "false_empty_diagnosis.csv"
    with output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(diagnosed[0]) if diagnosed else [])
        if diagnosed:
            writer.writeheader()
            writer.writerows(diagnosed)

    summary = {
        "zero_source_false_empty_n": len(diagnosed),
        "category_counts": dict(Counter(row["category"] for row in diagnosed)),
        "policy_decision": (
            "Primary context may be displayed but is never eligible for independent "
            "corroboration or supported/disputed status."
        ),
        "output_csv": str(output_csv.resolve()),
    }
    (args.output_dir / "false_empty_diagnosis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
