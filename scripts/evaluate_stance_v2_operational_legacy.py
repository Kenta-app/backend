"""One-time secondary diagnostic of frozen stance-v2 on the prior operational gold.

The operational gold is independent of v2 training by exact ID, group, URL,
and context. It was used to diagnose v1 and has no Unrelated support, so this
is a secondary retrospective analysis rather than a new four-class gate.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.ml.evidence_retriever import EvidenceRetriever
from app.ml.stance_classifier import StanceClassifier
from scripts.evaluate_stance_v2_challenge05 import DEFAULT_MODEL, LABELS, sha256_file, validate_model


BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_SEED = 20260930


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def normalized_url(value: str) -> str:
    return str(value or "").strip().split("?")[0].rstrip("/").casefold()


def validate_operational_gold(gold_path: Path) -> tuple[list[dict], dict]:
    manifest_path = gold_path.with_name("gold_freeze_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest["gold_artifacts"][gold_path.name]["sha256"]
    if sha256_file(gold_path) != expected:
        raise ValueError("El gold operativo cambió respecto a su manifiesto congelado.")
    rows = json.loads(gold_path.read_text(encoding="utf-8"))
    if len(rows) != 110 or len({row["pair_id"] for row in rows}) != len(rows):
        raise ValueError("Se esperaban 110 pares operativos únicos.")
    if len({row["group_id"] for row in rows}) != 85:
        raise ValueError("Se esperaban 85 grupos de artículo.")
    counts = Counter(str(row["final_label"]).casefold() for row in rows)
    if counts != {"agree": 101, "discuss": 7, "disagree": 2}:
        raise ValueError(f"Distribución del gold operativo inesperada: {counts}")
    for row in rows:
        if any(not row.get(key) for key in ("pair_id", "group_id", "claim", "title", "article", "final_label")):
            raise ValueError(f"Registro operativo incompleto: {row.get('pair_id')}")
        if row.get("final_quality") != "include":
            raise ValueError(f"Par no incluido en gold: {row['pair_id']}")

    development = json.loads((PROJECT / "data" / "processed" / "stance_es_pe_v2" / "development_v2.json").read_text(encoding="utf-8"))
    ids = {row["pair_id"] for row in development}
    groups = {row["group_id"] for row in development}
    urls = {normalized_url(row["original_url"]) for row in development}
    contexts = {hashlib.sha256(row["context"].encode("utf-8")).hexdigest() for row in development}
    for row in rows:
        if row["pair_id"] in ids or row["group_id"] in groups or normalized_url(row["original_url"]) in urls:
            raise ValueError(f"Solapamiento de par, grupo o URL con desarrollo v2: {row['pair_id']}")
        if hashlib.sha256(row["article"].encode("utf-8")).hexdigest() in contexts:
            raise ValueError(f"Artículo idéntico a contexto de desarrollo v2: {row['pair_id']}")
    return rows, manifest


def grouped_interval(predictions: list[dict], observed_labels: list[str]) -> dict:
    by_group: dict[str, list[int]] = {}
    for index, row in enumerate(predictions):
        by_group.setdefault(row["group_id"], []).append(index)
    groups = sorted(by_group)
    true = np.asarray([row["gold_label"] for row in predictions])
    predicted = np.asarray([row["prediction"] for row in predictions])
    random = np.random.default_rng(BOOTSTRAP_SEED)
    accuracy_values = []
    observed_macro_values = []
    for _ in range(BOOTSTRAP_SAMPLES):
        chosen = random.choice(groups, size=len(groups), replace=True)
        indices = np.asarray([index for group in chosen for index in by_group[group]], dtype=int)
        accuracy_values.append(float(accuracy_score(true[indices], predicted[indices])))
        observed_macro_values.append(float(f1_score(true[indices], predicted[indices], labels=observed_labels, average="macro", zero_division=0)))
    return {
        "resampling_unit": "group_id",
        "groups": len(groups),
        "samples": BOOTSTRAP_SAMPLES,
        "seed": BOOTSTRAP_SEED,
        "accuracy_95ci": {"low": float(np.quantile(accuracy_values, 0.025)), "high": float(np.quantile(accuracy_values, 0.975))},
        "observed_macro_f1_95ci": {"low": float(np.quantile(observed_macro_values, 0.025)), "high": float(np.quantile(observed_macro_values, 0.975))},
    }


def metrics(predictions: list[dict]) -> dict:
    true = [row["gold_label"] for row in predictions]
    predicted = [row["prediction"] for row in predictions]
    observed = [label for label in LABELS if label in set(true)]
    report = classification_report(true, predicted, labels=LABELS, output_dict=True, zero_division=0)
    baseline = ["agree"] * len(true)
    return {
        "n": len(predictions),
        "groups": len(set(row["group_id"] for row in predictions)),
        "label_order": LABELS,
        "observed_gold_labels": observed,
        "gold_counts": dict(Counter(true)),
        "prediction_counts": dict(Counter(predicted)),
        "accuracy": float(accuracy_score(true, predicted)),
        "macro_f1_observed_three_classes": float(f1_score(true, predicted, labels=observed, average="macro", zero_division=0)),
        "macro_f1_fixed_four_for_comparability_only": float(f1_score(true, predicted, labels=LABELS, average="macro", zero_division=0)),
        "per_class": {label: {"precision": float(report[label]["precision"]), "recall": float(report[label]["recall"]), "f1": float(report[label]["f1-score"]), "support": int(report[label]["support"])} for label in LABELS},
        "confusion_matrix": confusion_matrix(true, predicted, labels=LABELS).tolist(),
        "always_agree_baseline": {
            "accuracy": float(accuracy_score(true, baseline)),
            "macro_f1_observed_three_classes": float(f1_score(true, baseline, labels=observed, average="macro", zero_division=0)),
        },
        "grouped_bootstrap": grouped_interval(predictions, observed),
    }


def main() -> None:
    args = parse_args()
    gold_path = args.gold.resolve()
    model_dir = args.model_dir.resolve()
    output_dir = args.output_dir.resolve()
    metrics_path = output_dir / "operational_v2_metrics.json"
    predictions_path = output_dir / "operational_v2_predictions.csv"
    if metrics_path.exists() or predictions_path.exists():
        raise SystemExit("Esta evaluación operativa ya existe; se cancela la repetición.")

    validate_model(model_dir)
    gold, gold_manifest = validate_operational_gold(gold_path)
    classifier = StanceClassifier(str(model_dir))
    if not classifier.load() or tuple(classifier.serving_config.label_names) != LABELS:
        raise ValueError(classifier.load_error or "No se pudo cargar el modelo con las etiquetas esperadas.")
    retriever = EvidenceRetriever()
    predictions = []
    for index, row in enumerate(gold, start=1):
        evidence = retriever.select(
            claim=row["claim"],
            title=row["title"],
            body=row["article"],
            tokenizer=classifier.tokenizer,
            max_length=classifier.serving_config.max_length,
        )
        prediction = classifier.predict(row["claim"], evidence.context)
        predictions.append({
            "pair_id": row["pair_id"],
            "group_id": row["group_id"],
            "source_name": row["source_name"],
            "gold_label": str(row["final_label"]).casefold(),
            "prediction": prediction["label"],
            "confidence": prediction["confidence"],
            "related_probability": prediction["related_probability"],
            "decision_path": prediction["decision_path"],
            **{f"p_{label}": prediction["probabilities"][label] for label in LABELS},
            "evidence_selected_indexes": ",".join(map(str, evidence.selected_indexes)),
            "evidence_context": evidence.context,
        })
        if index % 20 == 0 or index == len(gold):
            print(f"Evaluados {index}/{len(gold)} pares operativos", flush=True)

    result = metrics(predictions)
    payload = {
        "status": "FROZEN_V2_SECONDARY_OPERATIONAL_DIAGNOSTIC_COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "epistemic_role": "retrospective_secondary_operational_diagnostic_not_four_class_gate",
        "limitations": [
            "El gold operativo se usó previamente para diagnosticar v1, aunque no forma parte del entrenamiento v2.",
            "No hay soporte Unrelated y solo hay dos ejemplos Disagree; estas clases no pueden estimarse con precisión en este conjunto.",
            "No se ajustarán pesos, umbrales ni selección de modelo con este resultado.",
        ],
        "inference_path": "EvidenceRetriever.select(title,article,claim) -> StanceClassifier.predict(claim,evidence_context)",
        "model_dir": str(model_dir),
        "model_audit_sha256": sha256_file(model_dir / "runtime_package_audit.json"),
        "gold_sha256": gold_manifest["gold_artifacts"][gold_path.name]["sha256"],
        "metrics": result,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary_predictions = predictions_path.with_suffix(".csv.tmp")
    with temporary_predictions.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(predictions[0]))
        writer.writeheader()
        writer.writerows(predictions)
    temporary_metrics = metrics_path.with_suffix(".json.tmp")
    temporary_metrics.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_predictions.replace(predictions_path)
    temporary_metrics.replace(metrics_path)
    print(json.dumps({"metrics_path": str(metrics_path), "accuracy": result["accuracy"], "observed_macro_f1": result["macro_f1_observed_three_classes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
