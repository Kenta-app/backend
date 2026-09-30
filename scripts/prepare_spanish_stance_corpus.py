"""Validate an adjudicated master CSV and export leakage-safe FNC-style splits."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from stance_corpus import (
    CANONICAL_FIELDS,
    VALID_LABELS,
    assign_grouped_splits,
    dump_json,
    export_fnc_splits,
    read_csv,
    sha256_file,
    validate_rows,
    write_csv,
)


def parse_ratios(value: str) -> dict[str, float]:
    parts = [float(item.strip()) for item in value.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("ratios must be train,validation,test")
    ratios = dict(zip(("train", "validation", "test"), parts, strict=True))
    if any(number <= 0 for number in ratios.values()) or abs(sum(ratios.values()) - 1.0) > 1e-9:
        raise argparse.ArgumentTypeError("ratios must be positive and sum to 1")
    return ratios


def readiness(rows: list[dict[str, str]], *, min_per_class: int, max_source_share: float) -> dict:
    eligible = [row for row in rows if row["quality_status"] == "include" and row["final_label"]]
    labels = Counter(row["final_label"] for row in eligible)
    sources = Counter(row["source_name"] for row in eligible)
    total = len(eligible)
    missing_classes = [label for label in VALID_LABELS if labels[label] < min_per_class]
    dominant_source, dominant_count = sources.most_common(1)[0] if sources else ("", 0)
    source_share = dominant_count / total if total else 0.0
    return {
        "ready": not missing_classes and source_share <= max_source_share,
        "eligible_rows": total,
        "label_counts": dict(labels),
        "missing_or_small_classes": missing_classes,
        "source_counts": dict(sources),
        "dominant_source": dominant_source,
        "dominant_source_share": source_share,
        "limits": {"min_per_class": min_per_class, "max_source_share": max_source_share},
    }


def assert_no_leakage(rows: list[dict[str, str]]) -> None:
    by_group: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        by_group[row["group_id"]].add(row["split"])
    leaks = {group: splits for group, splits in by_group.items() if len(splits) > 1}
    if leaks:
        preview = list(leaks.items())[:10]
        raise ValueError(f"group leakage detected: {preview}")


def render_manifest(manifest: dict) -> str:
    lines = [
        "# Manifiesto de Kenta Stance Perú v1",
        "",
        f"- Generado: {manifest['generated_at_utc']}",
        f"- Semilla: {manifest['seed']}",
        f"- Maestro de entrada: {manifest['input_master']}",
        f"- SHA-256 del maestro: {manifest['input_sha256']}",
        f"- Filas totales: {manifest['audit']['rows']}",
        f"- Filas elegibles: {manifest['audit']['eligible_rows']}",
        f"- Preparación lista: {manifest['readiness']['ready']}",
        "",
        "## Divisiones",
        "",
    ]
    for split, data in manifest.get("splits", {}).items():
        lines.append(f"- {split}: {data['rows']} pares, {data['groups']} grupos, {data['label_counts']}")
    lines.extend(["", "## Controles", "", "- No hay grupos compartidos entre splits.", "- Las huellas de todos los archivos están en el JSON del manifiesto.", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Canonical adjudicated master CSV")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ratios", type=parse_ratios, default=parse_ratios("0.6,0.2,0.2"))
    parser.add_argument("--min-per-class", type=int, default=40)
    parser.add_argument("--max-source-share", type=float, default=0.25)
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--allow-not-ready", action="store_true", help="Export development splits even when corpus gates fail")
    args = parser.parse_args()

    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    rows, audit = validate_rows(read_csv(input_path))
    readiness_report = readiness(rows, min_per_class=args.min_per_class, max_source_share=args.max_source_share)
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_master": str(input_path),
        "input_sha256": sha256_file(input_path),
        "seed": args.seed,
        "ratios": args.ratios,
        "audit": audit,
        "readiness": readiness_report,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    validated_path = output_dir / "master_validated.csv"
    write_csv(validated_path, rows, CANONICAL_FIELDS)

    if args.audit_only:
        manifest["mode"] = "audit_only"
    else:
        if not readiness_report["ready"] and not args.allow_not_ready:
            dump_json(output_dir / "manifest.json", manifest)
            raise SystemExit(
                "Corpus is not ready for splitting. Review manifest.json or pass --allow-not-ready for development only."
            )
        eligible = [row for row in rows if row["quality_status"] == "include" and row["final_label"]]
        split_rows = assign_grouped_splits(eligible, seed=args.seed, ratios=args.ratios)
        assert_no_leakage(split_rows)
        split_master = output_dir / "master_split.csv"
        write_csv(split_master, split_rows, CANONICAL_FIELDS)
        manifest["mode"] = "development_split" if not readiness_report["ready"] else "release_split"
        manifest["split_master"] = {"path": str(split_master), "sha256": sha256_file(split_master)}
        manifest["splits"] = export_fnc_splits(split_rows, output_dir / "fnc")

    dump_json(output_dir / "manifest.json", manifest)
    (output_dir / "manifest.md").write_text(render_manifest(manifest), encoding="utf-8")
    print(render_manifest(manifest))


if __name__ == "__main__":
    main()
