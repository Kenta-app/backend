"""Finalize an independently annotated stance corpus and export development files.

The input annotation log is deliberately plain CSV so the adjudication workbook
remains an immutable human-readable source while this step is reproducible.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from stance_corpus import (
    CANONICAL_FIELDS,
    VALID_LABELS,
    derive_final_label,
    read_csv,
    sha256_file,
    validate_rows,
    write_csv,
)


ANNOTATION_FLAG_PREFIXES = ("missing_annot", "invalid_annot")
STALE_ANNOTATION_FLAGS = {
    "adjudicated_exclusion",
    "legacy_label_without_annotation_provenance",
    "missing_adjudication_note",
    "missing_annotation_provenance",
    "supplied_final_label_mismatch",
    "unadjudicated_disagreement",
}


def normalize(value: object) -> str:
    return str(value or "").strip()


def clean_flags(value: str) -> str:
    flags = {
        item.strip()
        for item in (value or "").split("|")
        if item.strip()
    }
    kept = {
        flag for flag in flags
        if flag not in STALE_ANNOTATION_FLAGS
        and not flag.startswith(ANNOTATION_FLAG_PREFIXES)
    }
    return "|".join(sorted(kept))


def cohen_kappa(left: list[str], right: list[str]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("paired non-empty labels are required for Cohen's kappa")
    total = len(left)
    observed = sum(a == b for a, b in zip(left, right, strict=True)) / total
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(left_counts[label] * right_counts[label] for label in VALID_LABELS) / (total * total)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def readiness(rows: list[dict[str, str]], min_per_class: int, max_source_share: float) -> dict:
    eligible = [row for row in rows if row["quality_status"] == "include" and row["final_label"]]
    labels = Counter(row["final_label"] for row in eligible)
    sources = Counter(row["source_name"] for row in eligible)
    total = len(eligible)
    dominant_source, dominant_count = sources.most_common(1)[0] if sources else ("", 0)
    small_classes = [label for label in VALID_LABELS if labels[label] < min_per_class]
    source_share = dominant_count / total if total else 0.0
    return {
        "ready": not small_classes and source_share <= max_source_share,
        "eligible_rows": total,
        "label_counts": dict(labels),
        "missing_or_small_classes": small_classes,
        "source_counts": dict(sources),
        "dominant_source": dominant_source,
        "dominant_source_share": source_share,
        "limits": {"min_per_class": min_per_class, "max_source_share": max_source_share},
    }


def merge_annotations(
    seed_rows: list[dict[str, str]], annotation_rows: list[dict[str, str]]
) -> tuple[list[dict[str, str]], dict]:
    seed_ids = [normalize(row.get("pair_id")) for row in seed_rows]
    annotation_ids = [normalize(row.get("pair_id")) for row in annotation_rows]
    if len(seed_ids) != len(set(seed_ids)):
        raise ValueError("duplicate pair_id in seed master")
    if len(annotation_ids) != len(set(annotation_ids)):
        raise ValueError("duplicate pair_id in annotation log")
    if set(seed_ids) != set(annotation_ids):
        missing = sorted(set(seed_ids) - set(annotation_ids))
        extra = sorted(set(annotation_ids) - set(seed_ids))
        raise ValueError(f"pair_id mismatch; missing={missing[:10]}, extra={extra[:10]}")

    by_id = {normalize(row["pair_id"]): row for row in annotation_rows}
    merged: list[dict[str, str]] = []
    invalid: list[str] = []
    disagreements = 0
    adjudicated = 0

    for seed in seed_rows:
        pair_id = normalize(seed["pair_id"])
        annotation = by_id[pair_id]
        row = {field: normalize(seed.get(field)) for field in CANONICAL_FIELDS}
        row["annotator_1"] = normalize(annotation.get("annotator_1_name"))
        row["label_annotator_1"] = normalize(annotation.get("label_annotator_1")).lower()
        row["annotator_2"] = normalize(annotation.get("annotator_2_name"))
        row["label_annotator_2"] = normalize(annotation.get("label_annotator_2")).lower()
        row["adjudicated_label"] = normalize(annotation.get("adjudicated_label")).lower()
        row["adjudication_note"] = normalize(annotation.get("adjudication_note"))
        row["quality_flags"] = clean_flags(normalize(seed.get("quality_flags")))
        row["split"] = ""

        expected_final, flags = derive_final_label(row)
        supplied_final = normalize(annotation.get("final_label")).lower()
        if supplied_final != expected_final or flags:
            invalid.append(f"{pair_id}: supplied={supplied_final!r}, expected={expected_final!r}, flags={flags}")
        row["final_label"] = expected_final
        row["quality_status"] = "exclude" if row["adjudicated_label"] == "exclude" else "include"
        if row["label_annotator_1"] != row["label_annotator_2"]:
            disagreements += 1
            if row["adjudicated_label"]:
                adjudicated += 1
        merged.append(row)

    if invalid:
        raise ValueError("invalid final annotation rows: " + "; ".join(invalid[:10]))

    validated, audit = validate_rows(merged)
    unresolved = [row["pair_id"] for row in validated if "unadjudicated_disagreement" in row["quality_flags"]]
    if unresolved:
        raise ValueError(f"unresolved disagreements: {unresolved}")
    return validated, {"audit": audit, "disagreements": disagreements, "adjudicated": adjudicated}


def export_development_fnc(rows: list[dict[str, str]], output_dir: Path) -> dict:
    eligible = [row for row in rows if row["quality_status"] == "include" and row["final_label"]]
    output_dir.mkdir(parents=True, exist_ok=True)
    group_to_body: dict[str, int] = {}
    bodies: list[dict[str, object]] = []
    stances: list[dict[str, object]] = []
    metadata: list[dict[str, object]] = []
    group_article: dict[str, str] = {}

    for row in eligible:
        group_id = row["group_id"]
        article = row["article"]
        if group_id in group_article and group_article[group_id] != article:
            raise ValueError(f"group {group_id} contains different article text")
        if group_id not in group_to_body:
            body_id = len(group_to_body) + 1
            group_to_body[group_id] = body_id
            group_article[group_id] = article
            bodies.append({"Body ID": body_id, "articleBody": article})
        body_id = group_to_body[group_id]
        stances.append({"Headline": row["claim"], "Body ID": body_id, "Stance": row["final_label"]})
        metadata.append({
            "Body ID": body_id,
            "pair_id": row["pair_id"],
            "group_id": group_id,
            "article_id": row["article_id"],
            "source_name": row["source_name"],
            "original_url": row["original_url"],
        })

    paths = {
        "stances": output_dir / "development_stances.csv",
        "bodies": output_dir / "development_bodies.csv",
        "metadata": output_dir / "development_metadata.csv",
    }
    write_csv(paths["stances"], stances, ("Headline", "Body ID", "Stance"))
    write_csv(paths["bodies"], bodies, ("Body ID", "articleBody"))
    write_csv(paths["metadata"], metadata, ("Body ID", "pair_id", "group_id", "article_id", "source_name", "original_url"))
    return {
        "pairs": len(stances),
        "bodies": len(bodies),
        "files": {name: {"path": str(path), "sha256": sha256_file(path)} for name, path in paths.items()},
    }


def render_report(manifest: dict, decisions: list[dict[str, str]]) -> str:
    agreement = manifest["agreement"]
    gate = manifest["readiness"]
    labels = gate["label_counts"]
    lines = [
        "# Cierre de anotación de Kenta Stance Perú v1",
        "",
        "## Resultado",
        "",
        f"Se consolidaron {manifest['audit']['rows']} pares con trazabilidad de dos anotadores. "
        f"Los {agreement['disagreements']} desacuerdos fueron adjudicados y no quedan casos pendientes.",
        "",
        f"- Acuerdo bruto previo a adjudicación: {agreement['raw_agreement']:.2%}",
        f"- Cohen κ: {agreement['cohen_kappa']:.4f}",
        f"- Cobertura de adjudicación de desacuerdos: {agreement['adjudication_coverage']:.2%}",
        f"- Distribución final: agree={labels.get('agree', 0)}, disagree={labels.get('disagree', 0)}, "
        f"discuss={labels.get('discuss', 0)}, unrelated={labels.get('unrelated', 0)}",
        "",
        "## Decisiones de adjudicación",
        "",
        "| pair_id | Jimena | Salvador | Final | Justificación |",
        "|---|---|---|---|---|",
    ]
    for row in decisions:
        if row["agreement_status"] != "disagreement":
            continue
        note = row["adjudication_note"].replace("|", "/")
        lines.append(
            f"| {row['pair_id']} | {row['label_annotator_1']} | {row['label_annotator_2']} | "
            f"{row['adjudicated_label']} | {note} |"
        )
    lines.extend([
        "",
        "## Delimitación de uso",
        "",
        "Este cierre valida el lote histórico como corpus local de desarrollo y evidencia que las cuatro clases están presentes. "
        "No autoriza todavía presentarlo como corpus peruano representativo ni como conjunto final de prueba.",
        "",
        f"La compuerta de representatividad queda en **{gate['ready']}**. "
        f"Las clases bajo el mínimo de {gate['limits']['min_per_class']} son: "
        f"{', '.join(gate['missing_or_small_classes']) or 'ninguna'}. "
        f"La fuente dominante es {gate['dominant_source']} con {gate['dominant_source_share']:.2%} de los pares, "
        f"frente al máximo definido de {gate['limits']['max_source_share']:.0%}.",
        "",
        "Por tanto, los archivos FNC se exportan con prefijo `development_` y sin una división oficial train/validation/test. "
        "La división y el entrenamiento final deben esperar la ampliación del corpus y la reserva de un conjunto local representativo.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-master", type=Path, required=True)
    parser.add_argument("--annotation-log", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-per-class", type=int, default=40)
    parser.add_argument("--max-source-share", type=float, default=0.25)
    args = parser.parse_args()

    seed_rows = read_csv(args.seed_master)
    annotation_rows = read_csv(args.annotation_log)
    rows, merge_report = merge_annotations(seed_rows, annotation_rows)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    master_path = output_dir / "Kenta_Stance_Peru_v1_maestro_adjudicado.csv"
    write_csv(master_path, rows, CANONICAL_FIELDS)
    fnc = export_development_fnc(rows, output_dir / "fnc")

    left = [row["label_annotator_1"] for row in rows]
    right = [row["label_annotator_2"] for row in rows]
    agreements = sum(a == b for a, b in zip(left, right, strict=True))
    disagreement_count = merge_report["disagreements"]
    gate = readiness(rows, args.min_per_class, args.max_source_share)
    manifest = {
        "corpus_version": "stance_es_pe_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "intended_use": "development",
        "inputs": {
            "seed_master": {"path": str(args.seed_master.resolve()), "sha256": sha256_file(args.seed_master)},
            "annotation_log": {"path": str(args.annotation_log.resolve()), "sha256": sha256_file(args.annotation_log)},
        },
        "master": {"path": str(master_path), "sha256": sha256_file(master_path)},
        "audit": merge_report["audit"],
        "agreement": {
            "pairs": len(rows),
            "agreements": agreements,
            "disagreements": disagreement_count,
            "raw_agreement": agreements / len(rows),
            "cohen_kappa": cohen_kappa(left, right),
            "adjudicated_disagreements": merge_report["adjudicated"],
            "adjudication_coverage": merge_report["adjudicated"] / disagreement_count if disagreement_count else 1.0,
        },
        "readiness": gate,
        "fnc_development": fnc,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = output_dir / "Informe_cierre_anotacion_stance.md"
    report_path.write_text(render_report(manifest, annotation_rows), encoding="utf-8")
    print(report_path)


if __name__ == "__main__":
    main()
