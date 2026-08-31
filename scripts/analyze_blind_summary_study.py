"""Audit and decode completed blinded BART-vs-mT5 human annotations.

The evaluators' workbooks are first extracted without model labels.  This script
is intended to be run only after both evaluators have completed all cases.  It
then applies the pre-registered A/B assignments, reports inter-annotator
agreement, and writes a transparent list of disagreements for adjudication.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


MODEL_NAMES = {
    "facebook/bart-large-cnn": "BART",
    "ELiRF/mt5-base-dacsa-es": "mT5",
}
PREFERENCE_FIELDS = ("fidelity", "fluency", "overall")
ENGLISH_FIELDS = ("english_a", "english_b")
VALID_PREFERENCES = {"A", "B", "Empate"}
VALID_ENGLISH = {"Sí", "No"}


def cohen_kappa(first: list[str], second: list[str]) -> float | None:
    if len(first) != len(second) or not first:
        return None
    observed = sum(left == right for left, right in zip(first, second)) / len(first)
    categories = set(first) | set(second)
    expected = sum((first.count(category) / len(first)) * (second.count(category) / len(second)) for category in categories)
    if expected == 1:
        return None
    return (observed - expected) / (1 - expected)


def preference_counts(values: list[str]) -> dict[str, int]:
    return {category: values.count(category) for category in ("BART", "mT5", "Empate")}


def as_percent(part: int, total: int) -> str:
    return f"{100 * part / total:.1f}%" if total else "n/a"


def decode_preference(raw_value: str, mapping: dict[str, str]) -> str:
    if raw_value == "Empate":
        return "Empate"
    return MODEL_NAMES[mapping[raw_value]]


def decode_english(raw: dict[str, Any], mapping: dict[str, str], model: str) -> str:
    system = "A" if MODEL_NAMES[mapping["A"]] == model else "B"
    return raw[f"english_{system.lower()}"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, default=Path("output/paper_v7/blind_summary_study/blind_study_payload.json"))
    parser.add_argument("--salvador", type=Path, default=Path("output/paper_v7/blind_summary_study/responses_salvador.json"))
    parser.add_argument("--jimena", type=Path, default=Path("output/paper_v7/blind_summary_study/responses_jimena.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/paper_v7/blind_summary_study/analysis_pre_adjudication"))
    args = parser.parse_args()

    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    responses = {
        "Salvador": json.loads(args.salvador.read_text(encoding="utf-8")),
        "Jimena": json.loads(args.jimena.read_text(encoding="utf-8")),
    }
    cases = {record["case_id"]: record for record in payload["cases"]}
    expected_ids = list(cases)
    decoded: dict[str, dict[str, dict[str, Any]]] = {"Salvador": {}, "Jimena": {}}

    for evaluator, response_payload in responses.items():
        raw_cases = {record["case_id"]: record for record in response_payload["cases"]}
        if list(raw_cases) != expected_ids:
            raise ValueError(f"{evaluator}: case IDs do not match the pre-registered sample.")
        for case_id in expected_ids:
            raw = raw_cases[case_id]
            if raw["status"] != "Completado":
                raise ValueError(f"{evaluator}: {case_id} is not marked Completado.")
            if any(raw[field] not in VALID_PREFERENCES for field in PREFERENCE_FIELDS):
                raise ValueError(f"{evaluator}: invalid A/B/Empate answer in {case_id}.")
            if any(raw[field] not in VALID_ENGLISH for field in ENGLISH_FIELDS):
                raise ValueError(f"{evaluator}: invalid Sí/No answer in {case_id}.")
            mapping = cases[case_id][f"{evaluator.lower()}_mapping"]
            decoded[evaluator][case_id] = {
                "title": cases[case_id]["title"],
                "source_id": cases[case_id]["source_id"],
                "comment": raw["comment"],
                **{field: decode_preference(raw[field], mapping) for field in PREFERENCE_FIELDS},
                "english_bart": decode_english(raw, mapping, "BART"),
                "english_mt5": decode_english(raw, mapping, "mT5"),
            }

    total = len(expected_ids)
    summary: dict[str, Any] = {
        "study": payload["study"],
        "sample_size": total,
        "selection_seed": payload["selection_seed"],
        "assignment_seed": payload["assignment_seed"],
        "status": "Both evaluators completed every case before model-label decoding.",
        "preference_dimensions": {},
        "english_code_switch": {},
    }
    disagreements: list[dict[str, str]] = []

    for field in PREFERENCE_FIELDS:
        salvador_values = [decoded["Salvador"][case_id][field] for case_id in expected_ids]
        jimena_values = [decoded["Jimena"][case_id][field] for case_id in expected_ids]
        exact = sum(left == right for left, right in zip(salvador_values, jimena_values))
        summary["preference_dimensions"][field] = {
            "salvador": preference_counts(salvador_values),
            "jimena": preference_counts(jimena_values),
            "exact_agreement": exact,
            "exact_agreement_percent": round(100 * exact / total, 1),
            "cohen_kappa": None if cohen_kappa(salvador_values, jimena_values) is None else round(cohen_kappa(salvador_values, jimena_values), 4),
        }
        for case_id, left, right in zip(expected_ids, salvador_values, jimena_values):
            if left != right:
                disagreements.append(
                    {
                        "case_id": case_id,
                        "source_id": str(cases[case_id]["source_id"]),
                        "title": cases[case_id]["title"],
                        "criterion": field,
                        "salvador": left,
                        "jimena": right,
                        "salvador_comment": decoded["Salvador"][case_id]["comment"],
                        "jimena_comment": decoded["Jimena"][case_id]["comment"],
                    }
                )

    for model, field in (("BART", "english_bart"), ("mT5", "english_mt5")):
        salvador_values = [decoded["Salvador"][case_id][field] for case_id in expected_ids]
        jimena_values = [decoded["Jimena"][case_id][field] for case_id in expected_ids]
        exact = sum(left == right for left, right in zip(salvador_values, jimena_values))
        summary["english_code_switch"][model] = {
            "salvador_yes": salvador_values.count("Sí"),
            "jimena_yes": jimena_values.count("Sí"),
            "exact_agreement": exact,
            "exact_agreement_percent": round(100 * exact / total, 1),
            "cohen_kappa": None if cohen_kappa(salvador_values, jimena_values) is None else round(cohen_kappa(salvador_values, jimena_values), 4),
        }
        for case_id, left, right in zip(expected_ids, salvador_values, jimena_values):
            if left != right:
                disagreements.append(
                    {
                        "case_id": case_id,
                        "source_id": str(cases[case_id]["source_id"]),
                        "title": cases[case_id]["title"],
                        "criterion": f"english_{model.lower()}",
                        "salvador": left,
                        "jimena": right,
                        "salvador_comment": decoded["Salvador"][case_id]["comment"],
                        "jimena_comment": decoded["Jimena"][case_id]["comment"],
                    }
                )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output_dir / "disagreements.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "source_id", "title", "criterion", "salvador", "jimena", "salvador_comment", "jimena_comment"])
        writer.writeheader()
        writer.writerows(disagreements)

    # Preserve blindness for consensus review.  Use Salvador's A/B order as the
    # fixed presentation order, and express Jimena's first-round preferences in
    # that same anonymous A/B notation.  The model names stay out of this file.
    disagreements_by_case: dict[str, list[dict[str, str]]] = {}
    for item in disagreements:
        disagreements_by_case.setdefault(item["case_id"], []).append(item)
    adjudication_cases = []
    for case_id, items in disagreements_by_case.items():
        case = cases[case_id]
        presentation = case["salvador_mapping"]

        def encode_for_presentation(value: str) -> str:
            if value == "Empate":
                return value
            if value in ("BART", "mT5"):
                return "A" if MODEL_NAMES[presentation["A"]] == value else "B"
            # English fields use Sí/No and do not require mapping in the current
            # dataset, but preserve the value for a future run.
            return value

        criteria = []
        for item in items:
            criteria.append(
                {
                    "criterion": item["criterion"],
                    "salvador_initial": encode_for_presentation(item["salvador"]),
                    "jimena_initial": encode_for_presentation(item["jimena"]),
                    "salvador_comment": item["salvador_comment"],
                    "jimena_comment": item["jimena_comment"],
                }
            )
        adjudication_cases.append(
            {
                "case_id": case_id,
                "source_id": case["source_id"],
                "title": case["title"],
                "url": case["url"],
                "article": case["article"],
                "system_a": case["outputs"][presentation["A"]],
                "system_b": case["outputs"][presentation["B"]],
                "criteria": criteria,
            }
        )
    (args.output_dir / "adjudication_payload.json").write_text(
        json.dumps({"cases": adjudication_cases}, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Evaluación humana ciega de resúmenes — resultados previos a adjudicación",
        "",
        f"- Casos evaluados de forma independiente: {total}",
        "- Ambos evaluadores completaron los 30 casos antes de decodificar A/B.",
        f"- Respuestas que requieren adjudicación: {len(disagreements)} criterio-caso.",
        "",
        "## Preferencias por dimensión",
        "",
        "| Dimensión | Acuerdo exacto | κ de Cohen | Salvador (BART/mT5/empate) | Jimena (BART/mT5/empate) |",
        "|---|---:|---:|---|---|",
    ]
    for field, label in (("fidelity", "Fidelidad"), ("fluency", "Fluidez en español"), ("overall", "Calidad global")):
        result = summary["preference_dimensions"][field]
        s_counts = result["salvador"]
        j_counts = result["jimena"]
        lines.append(
            f"| {label} | {result['exact_agreement']}/{total} ({result['exact_agreement_percent']:.1f}%) | {result['cohen_kappa']} | "
            f"{s_counts['BART']}/{s_counts['mT5']}/{s_counts['Empate']} | {j_counts['BART']}/{j_counts['mT5']}/{j_counts['Empate']} |"
        )
    lines.extend([
        "",
        "## Mezcla injustificada de inglés",
        "",
        "| Sistema | Salvador: Sí | Jimena: Sí | Acuerdo exacto | κ de Cohen |",
        "|---|---:|---:|---:|---:|",
    ])
    for model in ("BART", "mT5"):
        result = summary["english_code_switch"][model]
        lines.append(
            f"| {model} | {result['salvador_yes']}/{total} | {result['jimena_yes']}/{total} | "
            f"{result['exact_agreement']}/{total} ({result['exact_agreement_percent']:.1f}%) | {result['cohen_kappa']} |"
        )
    lines.extend([
        "",
        "Los conteos de preferencia no se interpretan como decisión final hasta adjudicar los desacuerdos registrados en `disagreements.csv`.",
    ])
    (args.output_dir / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
