from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from app.ml.evidence_retriever import EvidenceRetriever
from app.ml.stance_classifier import StanceClassifier


LABELS = ["unrelated", "discuss", "agree", "disagree"]
MODEL_DIR = PROJECT / "output" / "stance_es_pe_v1" / "final_model_2026_09_28" / "best_model"
MODEL_MANIFEST = MODEL_DIR.parent / "model_freeze_manifest.json"
WORKSPACE = Path(r"C:\Users\sdiaz\Documents\Codex\2026-09-14\resolver-o-delimitar-el-componente-de")
CHALLENGE_GOLD = WORKSPACE / "outputs" / "challenge_04_2026_09_28" / "integracion_2026_09_28" / "challenge_04_gold.json"
OPERATIONAL_GOLD = WORKSPACE / "outputs" / "evaluacion_final_2026_09_24" / "gold_congelado" / "Kenta_Stance_Peru_v1_evaluacion_final_gold.json"
OUT = WORKSPACE / "outputs" / "challenge_04_2026_09_28" / "evaluacion_modelo_2026_09_28"
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_SEED = 20260928


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_datasets() -> dict[str, list[dict]]:
    challenge = json.loads(CHALLENGE_GOLD.read_text(encoding="utf-8"))
    operational_raw = json.loads(OPERATIONAL_GOLD.read_text(encoding="utf-8"))
    operational = []
    for row in operational_raw:
        operational.append({
            "pair_id": row["pair_id"],
            "group_id": row["group_id"],
            "source_id": row.get("source_name", ""),
            "claim": row["claim"],
            "title": row.get("title", ""),
            "context": row["article"],
            "gold_label": row["final_label"],
        })
    return {"challenge_04": challenge, "operational_legacy": operational}


def predict_dataset(classifier: StanceClassifier, rows: list[dict], batch_size: int = 8) -> list[dict]:
    retriever = EvidenceRetriever()
    selections = []
    for row in rows:
        selected = retriever.select(
            claim=row["claim"],
            title=row.get("title", ""),
            body=row["context"],
            tokenizer=classifier.tokenizer,
            max_length=classifier.serving_config.max_length,
        )
        selections.append(selected)

    outputs = []
    for start in range(0, len(rows), batch_size):
        batch_rows = rows[start:start + batch_size]
        batch_sel = selections[start:start + batch_size]
        encoded = classifier.tokenizer(
            [r["claim"] for r in batch_rows],
            [s.context for s in batch_sel],
            return_tensors="pt",
            truncation="only_second",
            max_length=classifier.serving_config.max_length,
            padding=True,
        )
        encoded = {key: value.to(classifier.device) for key, value in encoded.items()}
        with torch.no_grad():
            logits = classifier.model(**encoded).logits
            probabilities = torch.softmax(logits, dim=-1).detach().cpu().numpy()
        for row, selection, probs in zip(batch_rows, batch_sel, probabilities):
            pred_index = int(np.argmax(probs))
            outputs.append({
                "pair_id": row["pair_id"],
                "group_id": row["group_id"],
                "source_id": row.get("source_id", ""),
                "gold_label": str(row["gold_label"]).lower(),
                "prediction": classifier.serving_config.label_names[pred_index],
                "confidence": float(probs[pred_index]),
                **{f"p_{label}": float(probs[i]) for i, label in enumerate(classifier.serving_config.label_names)},
                "evidence_sentence_count": selection.sentence_count,
                "evidence_selected_indexes": ",".join(map(str, selection.selected_indexes)),
                "evidence_primary_index": selection.primary_index,
                "evidence_verdict_index": selection.verdict_index,
                "evidence_context": selection.context,
            })
    return outputs


def percentile_ci(values: list[float]) -> dict:
    arr = np.asarray(values, dtype=float)
    return {
        "low": float(np.quantile(arr, 0.025)),
        "high": float(np.quantile(arr, 0.975)),
    }


def grouped_bootstrap(predictions: list[dict], labels: list[str]) -> dict:
    by_group: dict[str, list[int]] = {}
    for idx, row in enumerate(predictions):
        by_group.setdefault(row["group_id"], []).append(idx)
    groups = sorted(by_group)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    y_true = np.asarray([row["gold_label"] for row in predictions])
    y_pred = np.asarray([row["prediction"] for row in predictions])
    macro_values = []
    accuracy_values = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sampled = rng.choice(groups, size=len(groups), replace=True)
        indices = np.asarray([idx for group in sampled for idx in by_group[group]], dtype=int)
        macro_values.append(float(f1_score(y_true[indices], y_pred[indices], labels=labels, average="macro", zero_division=0)))
        accuracy_values.append(float(accuracy_score(y_true[indices], y_pred[indices])))
    return {
        "resampling_unit": "group_id",
        "groups": len(groups),
        "samples": BOOTSTRAP_SAMPLES,
        "seed": BOOTSTRAP_SEED,
        "macro_f1_95ci": percentile_ci(macro_values),
        "accuracy_95ci": percentile_ci(accuracy_values),
    }


def metrics(predictions: list[dict]) -> dict:
    y_true = [row["gold_label"] for row in predictions]
    y_pred = [row["prediction"] for row in predictions]
    observed = [label for label in LABELS if label in set(y_true)]
    fixed_macro = float(f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0))
    observed_macro = float(f1_score(y_true, y_pred, labels=observed, average="macro", zero_division=0))
    report = classification_report(y_true, y_pred, labels=LABELS, output_dict=True, zero_division=0)
    return {
        "n": len(predictions),
        "label_order": LABELS,
        "gold_counts": dict(Counter(y_true)),
        "prediction_counts": dict(Counter(y_pred)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1_fixed_four": fixed_macro,
        "macro_f1_observed_classes": observed_macro,
        "observed_classes": observed,
        "classification_report": report,
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=LABELS).tolist(),
        "bootstrap": grouped_bootstrap(predictions, LABELS),
    }


def write_predictions(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if (OUT / "external_evaluation_metrics.json").exists():
        raise SystemExit("La evaluación externa ya existe; se cancela para preservar la ejecución única.")
    OUT.mkdir(parents=True, exist_ok=True)
    freeze = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
    expected_model_hash = freeze["checkpoint"]["files"]["model.safetensors"]["sha256"]
    current_model_hash = sha256_file(MODEL_DIR / "model.safetensors")
    if current_model_hash != expected_model_hash:
        raise SystemExit("El hash del checkpoint no coincide con el manifiesto congelado.")

    classifier = StanceClassifier(str(MODEL_DIR))
    if not classifier.load():
        raise SystemExit(classifier.load_error or "No se pudo cargar el modelo.")
    if list(classifier.serving_config.label_names) != LABELS:
        raise SystemExit(f"Orden de etiquetas inesperado: {classifier.serving_config.label_names}")

    datasets = load_datasets()
    all_metrics = {}
    for name, rows in datasets.items():
        predictions = predict_dataset(classifier, rows)
        write_predictions(OUT / f"{name}_predictions.csv", predictions)
        all_metrics[name] = metrics(predictions)

    payload = {
        "status": "FROZEN_MODEL_EXTERNAL_EVALUATION_COMPLETE",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_dir": str(MODEL_DIR),
        "checkpoint_sha256": current_model_hash,
        "input_contract": freeze["input_contract"],
        "threshold_tuning_after_freeze": False,
        "datasets": all_metrics,
    }
    (OUT / "external_evaluation_metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
