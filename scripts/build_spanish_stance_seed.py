"""Recover the 122-pair historical diagnostic set as an auditable development seed."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from stance_corpus import CANONICAL_FIELDS, dump_json, read_csv, sha256_text, validate_rows, write_csv


REPO_ROOT = Path(__file__).resolve().parents[1]


def source_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if "rpp.pe" in host:
        return "RPP"
    if "gestion.pe" in host:
        return "Gestión"
    return host or "Fuente no registrada"


def normalize_source_name(value: str) -> str:
    name = value.strip()
    if name.lower() in {"rpp", "rpp noticias"}:
        return "RPP"
    return name or "Fuente no registrada"


def read_external_with_duplicate_headers(path: Path) -> list[dict[str, str]]:
    """Read legacy files whose article/hash columns were accidentally duplicated."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = list(reader)
    if len(header) < 12:
        raise ValueError(f"unexpected external schema in {path}")
    output = []
    for values in rows:
        article = values[12] if len(values) > 12 and values[12].strip() else values[10]
        output.append({
            "pair_id": values[0], "claim": values[1], "article_excerpt": values[2],
            "original_url": values[3], "annotator_1": values[4],
            "label_annotator_1": values[5], "annotator_2": values[6],
            "label_annotator_2": values[7], "adjudicated_label": values[8],
            "adjudication_note": values[9], "article": article,
        })
    return output


def build_rows(root: Path) -> tuple[list[dict[str, str]], dict]:
    inputs = root / "output/paper_v7/annotation_inputs"
    original = read_csv(inputs / "spanish_stance_annotations_merged.csv")
    legacy_stances = read_csv(root / "output/paper_v7/spanish_stance_stratified_stances.csv")
    legacy_bodies = {row["Body ID"]: row["articleBody"] for row in read_csv(root / "output/paper_v7/spanish_stance_stratified_bodies.csv")}
    if len(original) != 100 or len(legacy_stances) != 122:
        raise ValueError("expected the historical 100-pair annotations and 122-pair diagnostic set")

    rows: list[dict[str, str]] = []
    for index, source in enumerate(original):
        legacy = legacy_stances[index]
        article = source["article"].strip()
        article_id = source.get("source_article_id", "").strip() or sha256_text(article)[:16]
        flags = []
        if legacy["Headline"].strip() != source["claim"].strip() or legacy_bodies[legacy["Body ID"]].strip() != article:
            flags.append("legacy_text_mismatch")
        legacy_label = legacy["Stance"].strip().lower()
        expected = (source.get("adjudicated_label") or source.get("label_annotator_1") or "").strip().lower()
        if legacy_label != expected:
            flags.append("legacy_label_mismatch")
        rows.append({
            "pair_id": source["pair_id"], "corpus_version": "stance_es_pe_v1",
            "intended_use": "development", "batch_id": "historical_local_100",
            "group_id": f"article:{article_id}", "event_id": "", "claim_id": f"claim:{source['pair_id']}",
            "article_id": article_id, "pair_construction": source.get("pair_construction", ""),
            "source_name": normalize_source_name(source.get("source_name", "")),
            "title": source.get("title", ""), "original_url": source.get("original_url", ""),
            "published_at": "", "claim": source["claim"], "article": article,
            "annotator_1": source.get("annotator_1", ""), "label_annotator_1": source.get("label_annotator_1", ""),
            "annotator_2": source.get("annotator_2", ""), "label_annotator_2": source.get("label_annotator_2", ""),
            "adjudicated_label": source.get("adjudicated_label", ""),
            "adjudication_note": source.get("adjudication_note", ""), "final_label": "",
            "quality_status": "review" if flags else "include", "quality_flags": "|".join(flags), "split": "",
        })

    external_files = (
        inputs / "external_stance_fulltext_24.csv",
        inputs / "external_stance_replacements_fulltext.csv",
        inputs / "external_stance_replacements2_fulltext.csv",
    )
    external = [row for path in external_files for row in read_external_with_duplicate_headers(path)]
    if len(external) != 22:
        raise ValueError(f"expected 22 historical external pairs, found {len(external)}")
    for offset, source in enumerate(external, start=100):
        legacy = legacy_stances[offset]
        article = source["article"].strip()
        article_id = sha256_text(article)[:16]
        flags = []
        if legacy["Headline"].strip() != source["claim"].strip() or legacy_bodies[legacy["Body ID"]].strip() != article:
            flags.append("legacy_text_mismatch")
        supplied = (source.get("adjudicated_label") or source.get("label_annotator_1") or "").strip().lower()
        if supplied and legacy["Stance"].strip().lower() != supplied:
            flags.append("legacy_label_mismatch")
        if not supplied:
            flags.append("legacy_label_without_annotation_provenance")
        url = source["original_url"]
        rows.append({
            "pair_id": source["pair_id"], "corpus_version": "stance_es_pe_v1",
            "intended_use": "development", "batch_id": "historical_targeted_22",
            "group_id": f"article:{article_id}", "event_id": "", "claim_id": f"claim:{source['pair_id']}",
            "article_id": article_id, "pair_construction": "targeted_external",
            "source_name": source_from_url(url), "title": "", "original_url": url,
            "published_at": "", "claim": source["claim"], "article": article,
            "annotator_1": source.get("annotator_1", ""), "label_annotator_1": source.get("label_annotator_1", ""),
            "annotator_2": source.get("annotator_2", ""), "label_annotator_2": source.get("label_annotator_2", ""),
            "adjudicated_label": source.get("adjudicated_label", ""),
            "adjudication_note": source.get("adjudication_note", ""), "final_label": "",
            "quality_status": "review" if flags else "include", "quality_flags": "|".join(flags), "split": "",
            "legacy_label": legacy["Stance"].strip().lower(),
        })
    return rows, {"legacy_label_counts": dict(Counter(row["Stance"].strip().lower() for row in legacy_stances))}


def render_audit(report: dict) -> str:
    lines = [
        "# Auditoría del lote histórico de stance",
        "",
        "Este lote se clasifica como desarrollo. No es el test final de Kenta Stance Perú v1.",
        "",
        f"- Pares recuperados: {report['rows']}",
        f"- Pares elegibles con trazabilidad: {report['eligible_rows']}",
        f"- Estados de calidad: {report['status_counts']}",
        f"- Etiquetas finales trazables: {report['label_counts']}",
        f"- Etiquetas del CSV diagnóstico legado: {report['legacy_label_counts']}",
        f"- Fuentes: {report['source_counts']}",
        f"- Artículos únicos: {report['unique_articles']}",
        f"- Grupos únicos: {report['unique_groups']}",
        "",
        "## Hallazgos",
        "",
        f"- Banderas de auditoría: {report['flag_counts']}",
        "- Dos etiquetas del diagnóstico legado no conservan su procedencia de anotación y deben reanotarse.",
        "- La distribución fue construida para diagnóstico, con alta concentración temática y de fuente en los casos dirigidos.",
        "- Los 122 pares no deben mezclarse con el test final; pueden apoyar calibración de la guía, desarrollo y análisis de errores.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output-dir", type=Path, default=Path("output/stance_es_pe_v1/audit"))
    args = parser.parse_args()
    root = args.repo_root.resolve()
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    source_rows, extra = build_rows(root)
    rows, report = validate_rows(source_rows)
    report.update(extra)
    report["intended_use"] = "development"
    report["valid_as_final_test"] = False
    csv_path = output_dir / "pilot_existing_122.csv"
    fields = list(CANONICAL_FIELDS) + ["legacy_label"]
    write_csv(csv_path, rows, fields)
    metadata_path = output_dir / "pilot_existing_122_metadata.csv"
    metadata = [
        {
            "Body ID": index,
            "pair_id": row["pair_id"],
            "group_id": row["group_id"],
            "source_name": row["source_name"],
            "original_url": row["original_url"],
        }
        for index, row in enumerate(rows, start=1)
    ]
    write_csv(metadata_path, metadata, ("Body ID", "pair_id", "group_id", "source_name", "original_url"))
    report["canonical_csv"] = str(csv_path)
    report["legacy_metadata_csv"] = str(metadata_path)
    dump_json(output_dir / "pilot_existing_122_audit.json", report)
    (output_dir / "pilot_existing_122_audit.md").write_text(render_audit(report), encoding="utf-8")
    print(render_audit(report))


if __name__ == "__main__":
    main()
