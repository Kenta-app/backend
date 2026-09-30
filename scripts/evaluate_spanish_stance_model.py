"""Evaluate a stance checkpoint with per-pair outputs and grouped bootstrap CIs."""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from torch.utils.data import DataLoader
from transformers import AutoModelForSequenceClassification, AutoTokenizer

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ml.training.datasets import FNCDataset, FNC_LABEL_MAP
from app.ml.training.train_stance import STANCE_LABELS


LABEL_IDS = list(range(len(STANCE_LABELS)))
REVERSE_LABELS = {value: key for key, value in FNC_LABEL_MAP.items()}


def percentile_interval(values: list[float], alpha: float = 0.05) -> list[float]:
    return [float(np.quantile(values, alpha / 2)), float(np.quantile(values, 1 - alpha / 2))]


def grouped_bootstrap(
    y_true: list[int], y_pred: list[int], groups: list[str], *,
    iterations: int = 2000, seed: int = 42,
) -> dict:
    if not (len(y_true) == len(y_pred) == len(groups)) or not y_true:
        raise ValueError("truth, predictions and groups must be non-empty and aligned")
    indexes: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        indexes[group].append(index)
    group_ids = sorted(indexes)
    rng = random.Random(seed)
    macro_scores: list[float] = []
    disagree_recalls: list[float] = []
    disagree_id = FNC_LABEL_MAP["disagree"]
    for _ in range(iterations):
        sampled_groups = [rng.choice(group_ids) for _ in group_ids]
        sample_indexes = [index for group in sampled_groups for index in indexes[group]]
        truth = [y_true[index] for index in sample_indexes]
        predictions = [y_pred[index] for index in sample_indexes]
        macro_scores.append(float(f1_score(truth, predictions, labels=LABEL_IDS, average="macro", zero_division=0)))
        report = classification_report(truth, predictions, labels=LABEL_IDS, output_dict=True, zero_division=0)
        disagree_recalls.append(float(report[str(disagree_id)]["recall"]))
    return {
        "method": "percentile bootstrap by group",
        "iterations": iterations,
        "seed": seed,
        "groups": len(group_ids),
        "macro_f1_95_ci": percentile_interval(macro_scores),
        "disagree_recall_95_ci": percentile_interval(disagree_recalls),
    }


def metric_payload(y_true: list[int], y_pred: list[int]) -> dict:
    report = classification_report(
        y_true, y_pred, labels=LABEL_IDS, target_names=STANCE_LABELS,
        output_dict=True, zero_division=0,
    )
    return {
        "macro_f1": float(f1_score(y_true, y_pred, labels=LABEL_IDS, average="macro", zero_division=0)),
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=LABEL_IDS).tolist(),
        "classification_report": report,
        "predicted_label_counts": dict(Counter(REVERSE_LABELS[value] for value in y_pred)),
    }


def deployment_gate(metrics: dict) -> dict:
    report = metrics["classification_report"]
    checks = {
        "macro_f1_at_least_0_60": metrics["macro_f1"] >= 0.60,
        "disagree_f1_at_least_0_50": report["disagree"]["f1-score"] >= 0.50,
        "disagree_recall_at_least_0_50": report["disagree"]["recall"] >= 0.50,
        "all_class_f1_at_least_0_40": all(report[label]["f1-score"] >= 0.40 for label in STANCE_LABELS),
        "no_collapsed_predicted_class": all(metrics["predicted_label_counts"].get(label, 0) > 0 for label in STANCE_LABELS),
    }
    return {"passed": all(checks.values()), "checks": checks}


def load_metadata(path: Path, expected: int) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != expected:
        raise ValueError(f"metadata rows ({len(rows)}) do not match evaluation rows ({expected})")
    return rows


def load_serving_max_length(model_dir: Path) -> int | None:
    config_path = model_dir / "serving_config.json"
    if not config_path.exists():
        return None
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    value = payload.get("max_length")
    return int(value) if value else None


def infer(model, loader: DataLoader, device: torch.device) -> tuple[list[int], list[int], list[list[float]]]:
    model.eval()
    truth: list[int] = []
    predictions: list[int] = []
    probabilities: list[list[float]] = []
    with torch.no_grad():
        for batch in loader:
            truth.extend(batch["labels"].tolist())
            inputs = {key: value.to(device) for key, value in batch.items() if key != "labels"}
            logits = model(**inputs).logits
            probs = torch.softmax(logits, dim=-1).cpu()
            probabilities.extend(probs.tolist())
            predictions.extend(probs.argmax(dim=-1).tolist())
    return truth, predictions, probabilities


def write_predictions(
    path: Path, metadata: list[dict[str, str]], truth: list[int],
    predictions: list[int], probabilities: list[list[float]],
) -> None:
    fields = ["pair_id", "group_id", "source_name", "original_url", "gold_label", "predicted_label", "correct"] + [f"p_{label}" for label in STANCE_LABELS]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for meta, gold, predicted, probs in zip(metadata, truth, predictions, probabilities, strict=True):
            row = {
                "pair_id": meta.get("pair_id", ""), "group_id": meta.get("group_id", ""),
                "source_name": meta.get("source_name", ""), "original_url": meta.get("original_url", ""),
                "gold_label": REVERSE_LABELS[gold], "predicted_label": REVERSE_LABELS[predicted],
                "correct": gold == predicted,
            }
            row.update({f"p_{label}": f"{probs[index]:.8f}" for index, label in enumerate(STANCE_LABELS)})
            writer.writerow(row)


def render_report(payload: dict) -> str:
    metrics = payload["metrics"]
    report = metrics["classification_report"]
    lines = [
        "# Evaluación local de stance",
        "",
        f"- Modelo: {payload['model_dir']}",
        f"- Longitud máxima: {payload['max_length']}",
        f"- Ejemplos: {payload['examples']}",
        f"- Grupos: {payload['bootstrap']['groups']}",
        f"- Macro-F1: {metrics['macro_f1']:.4f} (IC 95 %: {payload['bootstrap']['macro_f1_95_ci']})",
        f"- Exactitud: {metrics['accuracy']:.4f}",
        f"- Conteos predichos: {metrics['predicted_label_counts']}",
        f"- Puerta de despliegue: {'APROBADA' if payload['deployment_gate']['passed'] else 'NO APROBADA'}",
        "",
        "## Métricas por clase",
        "",
    ]
    for label in STANCE_LABELS:
        entry = report[label]
        lines.append(
            f"- {label}: precision={entry['precision']:.4f}, recall={entry['recall']:.4f}, "
            f"F1={entry['f1-score']:.4f}, soporte={int(entry['support'])}"
        )
    lines.extend(["", f"Matriz de confusión (orden {STANCE_LABELS}): `{metrics['confusion_matrix']}`", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--stances", type=Path, required=True)
    parser.add_argument("--bodies", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-length", type=int, default=None, help="Defaults to serving_config.json, then 512")
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=42)
    args = parser.parse_args()

    model_dir = args.model_dir.resolve()
    max_length = args.max_length or load_serving_max_length(model_dir) or 512
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir)).to(device)
    dataset = FNCDataset(str(args.stances), str(args.bodies), tokenizer, max_length=max_length)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False)
    metadata = load_metadata(args.metadata, len(dataset))
    truth, predictions, probabilities = infer(model, loader, device)
    metrics = metric_payload(truth, predictions)
    groups = [row.get("group_id") or row.get("pair_id") or str(index) for index, row in enumerate(metadata)]
    bootstrap = grouped_bootstrap(
        truth, predictions, groups, iterations=args.bootstrap_iterations, seed=args.bootstrap_seed,
    )
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_dir": str(model_dir),
        "stances": str(args.stances.resolve()), "bodies": str(args.bodies.resolve()),
        "metadata": str(args.metadata.resolve()), "examples": len(dataset), "max_length": max_length,
        "label_order": STANCE_LABELS, "metrics": metrics, "bootstrap": bootstrap,
        "deployment_gate": deployment_gate(metrics),
    }
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    write_predictions(output_dir / "predictions.csv", metadata, truth, predictions, probabilities)
    (output_dir / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render_report(payload)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
