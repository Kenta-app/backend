"""Aggregate the preregistered multi-seed stance representation comparison."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


REPRESENTATIONS = (
    "document_prefix",
    "retrieved_evidence",
    "oracle_evidence_no_title",
    "retrieved_evidence_no_title",
)
SEEDS = (42, 123, 2026)


def metric(summary: dict, split: str, key: str) -> float:
    section = summary[split]
    if key == "macro_f1":
        return float(section["macro_f1"])
    label, field = key.split("_", 1)
    return float(section["per_class"][label][field])


def mean_std(values: list[float]) -> dict:
    return {
        "mean": float(np.mean(values)),
        "sample_std": float(np.std(values, ddof=1)) if len(values) > 1 else 0.0,
        "minimum": float(np.min(values)),
        "maximum": float(np.max(values)),
        "values": values,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs_dir", type=Path, required=True)
    parser.add_argument("--output_dir", type=Path, required=True)
    args = parser.parse_args()
    runs_dir = args.runs_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: dict[str, dict[int, dict]] = {}
    missing = []
    for representation in REPRESENTATIONS:
        summaries[representation] = {}
        for seed in SEEDS:
            path = runs_dir / f"{representation}_seed{seed}" / "run_summary.json"
            if not path.exists():
                missing.append(str(path))
                continue
            summaries[representation][seed] = json.loads(path.read_text(encoding="utf-8"))
    if missing:
        raise FileNotFoundError("Missing completed summaries:\n" + "\n".join(missing))

    aggregate: dict[str, dict] = {}
    rows = []
    for representation, seed_summaries in summaries.items():
        result = {
            "all_seeds_development_go": all(
                summary["development_gate"]["decision"] == "GO"
                for summary in seed_summaries.values()
            ),
            "validation": {},
            "test_descriptive_not_for_selection": {},
        }
        for split, output_name in (
            ("validation", "validation"),
            ("test_descriptive_not_for_tuning", "test_descriptive_not_for_selection"),
        ):
            for key in ("macro_f1", "disagree_f1", "disagree_recall", "agree_f1"):
                values = [metric(seed_summaries[seed], split, key) for seed in SEEDS]
                result[output_name][key] = mean_std(values)
        aggregate[representation] = result
        rows.append(
            {
                "representation": representation,
                "all_seeds_development_go": result["all_seeds_development_go"],
                "validation_macro_f1_mean": result["validation"]["macro_f1"]["mean"],
                "validation_macro_f1_std": result["validation"]["macro_f1"]["sample_std"],
                "validation_disagree_f1_mean": result["validation"]["disagree_f1"]["mean"],
                "validation_disagree_recall_mean": result["validation"]["disagree_recall"]["mean"],
                "test_macro_f1_mean_descriptive": result["test_descriptive_not_for_selection"]["macro_f1"]["mean"],
                "test_macro_f1_std_descriptive": result["test_descriptive_not_for_selection"]["macro_f1"]["sample_std"],
                "test_disagree_f1_mean_descriptive": result["test_descriptive_not_for_selection"]["disagree_f1"]["mean"],
            }
        )

    primary = aggregate["retrieved_evidence"]
    payload = {
        "status": "COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seeds": SEEDS,
        "selection_rule": "Choose using validation only; internal test remains descriptive.",
        "primary_deployment_candidate": "retrieved_evidence",
        "primary_all_seeds_go": primary["all_seeds_development_go"],
        "representations": aggregate,
    }
    json_path = output_dir / "multiseed_aggregate.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = output_dir / "multiseed_aggregate.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    labels = {
        "document_prefix": "Inicio del documento",
        "retrieved_evidence": "Evidencia recuperada + título",
        "oracle_evidence_no_title": "Evidencia humana sin título",
        "retrieved_evidence_no_title": "Evidencia recuperada sin título",
    }
    lines = [
        "# Comparación multisemilla de stance",
        "",
        "Semillas: 42, 123 y 2026. La selección se realiza exclusivamente con validación; el test interno se conserva como descripción.",
        "",
        "| Representación | GO 3/3 | Validación macro-F1 | Validación F1 Disagree | Test macro-F1 descriptivo | Test F1 Disagree descriptivo |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for representation in REPRESENTATIONS:
        result = aggregate[representation]
        validation = result["validation"]
        test = result["test_descriptive_not_for_selection"]
        lines.append(
            f"| {labels[representation]} | {'Sí' if result['all_seeds_development_go'] else 'No'} | "
            f"{validation['macro_f1']['mean']:.4f} ± {validation['macro_f1']['sample_std']:.4f} | "
            f"{validation['disagree_f1']['mean']:.4f} | "
            f"{test['macro_f1']['mean']:.4f} ± {test['macro_f1']['sample_std']:.4f} | "
            f"{test['disagree_f1']['mean']:.4f} |"
        )
    lines.extend(
        [
            "",
            "El candidato de despliegue preespecificado es `retrieved_evidence`. La evidencia sin título funciona como prueba de robustez y no como sustituto del contrato de producción.",
        ]
    )
    markdown_path = output_dir / "MULTISEED_COMPARISON.md"
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "csv": str(csv_path), "markdown": str(markdown_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
