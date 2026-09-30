"""Run the one-time external Challenge 05 gate for a frozen stance-v2 package.

This entry point intentionally has no training, threshold search, or model
selection. The primary input follows the backend: claim, title, and selected
evidence from the supplied context.
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


LABELS = ("unrelated", "discuss", "agree", "disagree")
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_SEED = 20260929
DEFAULT_MODEL = PROJECT / "output" / "stance_es_pe_v2" / "final_model_2026_09_29"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def validate_model(model_dir: Path) -> dict:
    audit_path = model_dir / "runtime_package_audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("audit_status") != "PASS":
        raise ValueError("La auditoría del paquete de ejecución no aprobó.")
    for record in audit["model_files"]:
        artifact = model_dir / record["path"]
        if not artifact.is_file() or sha256_file(artifact) != record["sha256"]:
            raise ValueError(f"Cambió el archivo congelado: {record['path']}")
    freeze = json.loads((model_dir / "model_freeze_manifest.json").read_text(encoding="utf-8"))
    serving = json.loads((model_dir / "serving_config.json").read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_AWAITING_CHALLENGE_05_AND_OPERATIONAL_EVALUATION":
        raise ValueError("Estado del modelo inesperado.")
    if serving.get("architecture") != "hierarchical_stance_v2" or serving.get("public_enabled") is not False:
        raise ValueError("Configuración de serving inesperada.")
    return audit


def validate_gold(path: Path) -> tuple[list[dict], dict]:
    manifest_path = path.with_name("challenge05_gold_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "FROZEN":
        raise ValueError("El gold todavía no está congelado.")
    gold_hash = sha256_file(path)
    if manifest.get("gold_sha256") != gold_hash:
        raise ValueError("El hash del gold no coincide con el manifiesto.")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if len(rows) != manifest.get("records") or len(rows) not in (78, 79, 80):
        raise ValueError("Número de pares del gold inesperado.")
    ids = [row["pair_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Hay pair_id duplicados en el gold.")
    required = ("pair_id", "group_id", "source_id", "claim", "title", "context", "gold_label")
    for row in rows:
        if any(not row.get(key) for key in required):
            raise ValueError(f"Campos obligatorios incompletos: {row.get('pair_id')}")
        if str(row["gold_label"]).casefold() not in LABELS:
            raise ValueError(f"Etiqueta inesperada: {row['pair_id']}")
    if len(set(row["group_id"] for row in rows)) != 20:
        raise ValueError("Se esperaban 20 grupos de contexto.")
    if set(str(row["gold_label"]).casefold() for row in rows) != set(LABELS):
        raise ValueError("Falta alguna de las cuatro clases en el gold.")
    return rows, manifest


def percentile_interval(values: list[float]) -> dict[str, float]:
    return {"low": float(np.quantile(values, 0.025)), "high": float(np.quantile(values, 0.975))}


def grouped_bootstrap(predictions: list[dict]) -> dict:
    by_group: dict[str, list[int]] = {}
    for index, row in enumerate(predictions):
        by_group.setdefault(row["group_id"], []).append(index)
    groups = sorted(by_group)
    true = np.asarray([row["gold_label"] for row in predictions])
    predicted = np.asarray([row["prediction"] for row in predictions])
    random = np.random.default_rng(BOOTSTRAP_SEED)
    macro_values: list[float] = []
    accuracy_values: list[float] = []
    disagree_recall_values: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled = random.choice(groups, size=len(groups), replace=True)
        indices = np.asarray([index for group in sampled for index in by_group[group]], dtype=int)
        yt, yp = true[indices], predicted[indices]
        macro_values.append(float(f1_score(yt, yp, labels=LABELS, average="macro", zero_division=0)))
        accuracy_values.append(float(accuracy_score(yt, yp)))
        disagree_count = int(np.sum(yt == "disagree"))
        disagree_recall_values.append(float(np.sum((yt == "disagree") & (yp == "disagree")) / disagree_count) if disagree_count else 0.0)
    return {
        "resampling_unit": "group_id",
        "groups": len(groups),
        "samples": BOOTSTRAP_SAMPLES,
        "seed": BOOTSTRAP_SEED,
        "macro_f1_95ci": percentile_interval(macro_values),
        "accuracy_95ci": percentile_interval(accuracy_values),
        "disagree_recall_95ci": percentile_interval(disagree_recall_values),
    }


def score(predictions: list[dict]) -> dict:
    true = [row["gold_label"] for row in predictions]
    predicted = [row["prediction"] for row in predictions]
    report = classification_report(true, predicted, labels=LABELS, output_dict=True, zero_division=0)
    macro = float(f1_score(true, predicted, labels=LABELS, average="macro", zero_division=0))
    per_class = {
        label: {
            "precision": float(report[label]["precision"]),
            "recall": float(report[label]["recall"]),
            "f1": float(report[label]["f1-score"]),
            "support": int(report[label]["support"]),
        }
        for label in LABELS
    }
    gates = {
        "macro_f1_at_least_0_60": macro >= 0.60,
        "disagree_f1_at_least_0_50": per_class["disagree"]["f1"] >= 0.50,
        "disagree_recall_at_least_0_50": per_class["disagree"]["recall"] >= 0.50,
        "all_class_f1_at_least_0_40": all(per_class[label]["f1"] >= 0.40 for label in LABELS),
        "all_four_classes_predicted": set(predicted) == set(LABELS),
    }
    return {
        "n": len(predictions),
        "groups": len(set(row["group_id"] for row in predictions)),
        "label_order": LABELS,
        "gold_counts": dict(Counter(true)),
        "prediction_counts": dict(Counter(predicted)),
        "accuracy": float(accuracy_score(true, predicted)),
        "macro_f1_fixed_four": macro,
        "per_class": per_class,
        "confusion_matrix": confusion_matrix(true, predicted, labels=LABELS).tolist(),
        "grouped_bootstrap": grouped_bootstrap(predictions),
        "predeclared_gates": gates,
        "all_gates_pass": all(gates.values()),
    }


def main() -> None:
    args = parse_args()
    model_dir = args.model_dir.resolve()
    gold_path = args.gold.resolve()
    output_dir = args.output_dir.resolve()
    metrics_path = output_dir / "challenge05_external_metrics.json"
    predictions_path = output_dir / "challenge05_external_predictions.csv"
    if metrics_path.exists() or predictions_path.exists():
        raise SystemExit("Ya existe una evaluación externa; se cancela la repetición.")

    audit = validate_model(model_dir)
    gold, gold_manifest = validate_gold(gold_path)
    classifier = StanceClassifier(str(model_dir))
    if not classifier.load() or tuple(classifier.serving_config.label_names) != LABELS:
        raise ValueError(classifier.load_error or "No se pudo cargar el modelo con las cuatro etiquetas esperadas.")
    selector = EvidenceRetriever()
    predictions: list[dict] = []
    for index, row in enumerate(gold, start=1):
        evidence = selector.select(
            claim=row["claim"],
            title=row["title"],
            body=row["context"],
            tokenizer=classifier.tokenizer,
            max_length=classifier.serving_config.max_length,
        )
        result = classifier.predict(row["claim"], evidence.context)
        predictions.append({
            "pair_id": row["pair_id"],
            "group_id": row["group_id"],
            "source_id": row["source_id"],
            "gold_label": str(row["gold_label"]).casefold(),
            "prediction": result["label"],
            "confidence": result["confidence"],
            "related_probability": result["related_probability"],
            "decision_path": result["decision_path"],
            **{f"p_{label}": result["probabilities"][label] for label in LABELS},
            "evidence_selected_indexes": ",".join(map(str, evidence.selected_indexes)),
            "evidence_context": evidence.context,
        })
        if index % 20 == 0:
            print(f"Evaluados {index}/{len(gold)} pares", flush=True)

    metrics = score(predictions)
    payload = {
        "status": "FROZEN_MODEL_SINGLE_EXTERNAL_EVALUATION_COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_role": "controlled_balanced_external_challenge_not_natural_prevalence",
        "inference_path": "EvidenceRetriever.select(title,context,claim) -> StanceClassifier.predict(claim,evidence_context)",
        "model_dir": str(model_dir),
        "model_audit_sha256": sha256_file(model_dir / "runtime_package_audit.json"),
        "gold_sha256": gold_manifest["gold_sha256"],
        "no_training_or_threshold_tuning": True,
        "metrics": metrics,
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
    print(json.dumps({"metrics_path": str(metrics_path), "all_gates_pass": metrics["all_gates_pass"], "macro_f1": metrics["macro_f1_fixed_four"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
