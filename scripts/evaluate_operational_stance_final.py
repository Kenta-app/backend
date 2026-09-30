"""Run the single frozen-checkpoint inference on the frozen operational gold set.

This script is intentionally one-shot.  It verifies the hashes recorded before
model access, creates a run marker, performs exactly one inference pass, and
reports both fixed four-class and observed-class metrics without tuning.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def checkpoint_tree(model_dir: Path) -> tuple[str, dict[str, dict[str, int | str]]]:
    files: dict[str, dict[str, int | str]] = {}
    rows: list[str] = []
    for path in sorted(item for item in model_dir.iterdir() if item.is_file()):
        digest = sha256_file(path)
        size = path.stat().st_size
        files[path.name] = {"bytes": size, "sha256": digest}
        rows.append(f"{path.name}\t{size}\t{digest}")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest(), files


def verify_frozen_inputs(manifest: dict, manifest_path: Path) -> dict:
    if manifest.get("status") != "GOLD_FROZEN_MODEL_NOT_YET_EVALUATED":
        raise ValueError(f"Unexpected manifest status: {manifest.get('status')}")
    verified: dict[str, str] = {"manifest": sha256_file(manifest_path)}
    for name, entry in manifest["gold_artifacts"].items():
        path = Path(entry["path"])
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise ValueError(f"Frozen artifact hash mismatch for {name}: {actual}")
        verified[name] = actual
    model_dir = Path(manifest["frozen_checkpoint"]["path"])
    tree_hash, files = checkpoint_tree(model_dir)
    if tree_hash != manifest["frozen_checkpoint"]["tree_sha256"]:
        raise ValueError(f"Frozen checkpoint tree mismatch: {tree_hash}")
    if files != manifest["frozen_checkpoint"]["files"]:
        raise ValueError("Frozen checkpoint file manifest mismatch")
    verified["checkpoint_tree"] = tree_hash
    return verified


def percentile_interval(values: list[float], alpha: float = 0.05) -> list[float]:
    return [float(np.quantile(values, alpha / 2)), float(np.quantile(values, 1 - alpha / 2))]


def grouped_bootstrap(
    y_true: list[int], y_pred: list[int], groups: list[str], observed_ids: list[int], *,
    iterations: int, seed: int,
) -> dict:
    indexes: dict[str, list[int]] = defaultdict(list)
    for index, group in enumerate(groups):
        indexes[group].append(index)
    group_ids = sorted(indexes)
    rng = random.Random(seed)
    scores = {"macro_f1_four_class": [], "macro_f1_observed_classes": [], "accuracy": [],
              "disagree_f1": [], "disagree_recall": []}
    disagree_id = FNC_LABEL_MAP["disagree"]
    for _ in range(iterations):
        sampled_groups = [rng.choice(group_ids) for _ in group_ids]
        sample_indexes = [index for group in sampled_groups for index in indexes[group]]
        truth = [y_true[index] for index in sample_indexes]
        pred = [y_pred[index] for index in sample_indexes]
        scores["macro_f1_four_class"].append(float(f1_score(truth, pred, labels=LABEL_IDS, average="macro", zero_division=0)))
        scores["macro_f1_observed_classes"].append(float(f1_score(truth, pred, labels=observed_ids, average="macro", zero_division=0)))
        scores["accuracy"].append(float(accuracy_score(truth, pred)))
        report = classification_report(truth, pred, labels=LABEL_IDS, output_dict=True, zero_division=0)
        scores["disagree_f1"].append(float(report[str(disagree_id)]["f1-score"]))
        scores["disagree_recall"].append(float(report[str(disagree_id)]["recall"]))
    return {
        "method": "percentile bootstrap by article group_id",
        "iterations": iterations,
        "seed": seed,
        "groups": len(group_ids),
        "intervals_95": {name: percentile_interval(values) for name, values in scores.items()},
        "caution": "Disagree has only two gold cases; its intervals are descriptive and highly unstable.",
    }


def metric_payload(y_true: list[int], y_pred: list[int]) -> dict:
    report = classification_report(
        y_true, y_pred, labels=LABEL_IDS, target_names=STANCE_LABELS,
        output_dict=True, zero_division=0,
    )
    supports = Counter(y_true)
    observed_ids = [label_id for label_id in LABEL_IDS if supports[label_id] > 0]
    return {
        "macro_f1_four_class": float(f1_score(y_true, y_pred, labels=LABEL_IDS, average="macro", zero_division=0)),
        "macro_f1_observed_classes": float(f1_score(y_true, y_pred, labels=observed_ids, average="macro", zero_division=0)),
        "observed_classes": [REVERSE_LABELS[label_id] for label_id in observed_ids],
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "weighted_f1": float(f1_score(y_true, y_pred, labels=LABEL_IDS, average="weighted", zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=LABEL_IDS).tolist(),
        "classification_report": report,
        "gold_label_counts": {label: int(supports[FNC_LABEL_MAP[label]]) for label in STANCE_LABELS},
        "predicted_label_counts": dict(Counter(REVERSE_LABELS[value] for value in y_pred)),
    }


def subgroup_metrics(metadata: list[dict[str, str]], truth: list[int], pred: list[int], field: str) -> list[dict]:
    indexes: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(metadata):
        indexes[row.get(field) or "(vacío)"].append(index)
    result: list[dict] = []
    for name, positions in sorted(indexes.items(), key=lambda item: (-len(item[1]), item[0])):
        group_truth = [truth[index] for index in positions]
        group_pred = [pred[index] for index in positions]
        observed = sorted(set(group_truth))
        result.append({
            field: name,
            "n": len(positions),
            "accuracy": float(accuracy_score(group_truth, group_pred)),
            "macro_f1_observed_within_subgroup": float(f1_score(group_truth, group_pred, labels=observed, average="macro", zero_division=0)),
            "gold_counts": dict(Counter(REVERSE_LABELS[value] for value in group_truth)),
            "predicted_counts": dict(Counter(REVERSE_LABELS[value] for value in group_pred)),
            "errors": int(sum(a != b for a, b in zip(group_truth, group_pred, strict=True))),
        })
    return result


def infer(model, loader: DataLoader, device: torch.device) -> tuple[list[int], list[int], list[list[float]]]:
    model.eval()
    truth: list[int] = []
    predictions: list[int] = []
    probabilities: list[list[float]] = []
    with torch.no_grad():
        for batch in loader:
            truth.extend(batch["labels"].tolist())
            inputs = {key: value.to(device) for key, value in batch.items() if key != "labels"}
            probs = torch.softmax(model(**inputs).logits, dim=-1).cpu()
            probabilities.extend(probs.tolist())
            predictions.extend(probs.argmax(dim=-1).tolist())
    return truth, predictions, probabilities


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_legacy_runtime_copies(
    stances_source: Path, bodies_source: Path, stances_target: Path, bodies_target: Path,
) -> dict[str, int]:
    """Adapt frozen BOM/text IDs to the legacy FNCDataset format without changing gold."""
    body_rows = read_csv(bodies_source)
    stance_rows = read_csv(stances_source)
    body_id_map = {row["Body ID"]: index + 1 for index, row in enumerate(body_rows)}
    adapted_bodies = [
        {"Body ID": body_id_map[row["Body ID"]], "articleBody": row["articleBody"]}
        for row in body_rows
    ]
    adapted_stances = [
        {"Headline": row["Headline"], "Body ID": body_id_map[row["Body ID"]], "Stance": row["Stance"]}
        for row in stance_rows
    ]
    write_csv(bodies_target, adapted_bodies, ["Body ID", "articleBody"])
    write_csv(stances_target, adapted_stances, ["Headline", "Body ID", "Stance"])
    # write_csv intentionally emits a BOM for analyst-facing outputs; strip it for the legacy reader.
    for target in (stances_target, bodies_target):
        target.write_text(target.read_text(encoding="utf-8-sig"), encoding="utf-8", newline="")
    return body_id_map


def render_report(payload: dict) -> str:
    metrics = payload["metrics"]
    report = metrics["classification_report"]
    ci = payload["bootstrap"]["intervals_95"]
    gate = payload["interpretation"]
    lines = [
        "# Evaluación operacional final de stance español-peruano",
        "",
        "## Resultado ejecutivo",
        "",
        f"- Decisión: **{gate['deployment_decision']}**.",
        f"- Razón: {gate['decision_reason']}",
        f"- Casos evaluables: {payload['examples']} pares de {payload['groups']} artículos.",
        f"- Macro-F1 fijo (4 clases): **{metrics['macro_f1_four_class']:.4f}** (IC 95 % {ci['macro_f1_four_class']}).",
        f"- Macro-F1 sobre las 3 clases observadas: **{metrics['macro_f1_observed_classes']:.4f}** (IC 95 % {ci['macro_f1_observed_classes']}).",
        f"- Exactitud: **{metrics['accuracy']:.4f}** (IC 95 % {ci['accuracy']}).",
        f"- Distribución gold: {metrics['gold_label_counts']}.",
        f"- Distribución predicha: {metrics['predicted_label_counts']}.",
        "",
        "## Métricas por clase",
        "",
    ]
    for label in STANCE_LABELS:
        item = report[label]
        estimable = "no estimable en gold" if int(item["support"]) == 0 else "estimada"
        lines.append(
            f"- {label}: precision={item['precision']:.4f}, recall={item['recall']:.4f}, "
            f"F1={item['f1-score']:.4f}, soporte={int(item['support'])} ({estimable})."
        )
    lines.extend([
        "",
        f"Matriz de confusión (orden {STANCE_LABELS}): `{metrics['confusion_matrix']}`",
        "",
        "## Interpretación metodológica",
        "",
        f"- Puerta formal predeclarada: **{gate['formal_gate_status']}**.",
        f"- Comprobaciones observables: {gate['observable_checks']}.",
        "- La muestra prospectiva no contiene soporte gold para `unrelated`; por ello no permite estimar su F1 ni aprobar una puerta completa de cuatro clases.",
        "- `disagree` tiene soporte 2. Su resultado se informa, pero no es suficientemente preciso para sostener por sí solo una afirmación de robustez operacional.",
        "- No se entrenó, reajustó, recalibró ni seleccionó el checkpoint usando esta evaluación.",
        "",
        "## Trazabilidad",
        "",
        f"- Checkpoint congelado: `{payload['model_dir']}`.",
        f"- SHA-256 del árbol del checkpoint: `{payload['verified_hashes']['checkpoint_tree']}`.",
        f"- Longitud máxima: {payload['max_length']}; dispositivo: {payload['device']}.",
        f"- Bootstrap: {payload['bootstrap']['iterations']} réplicas por artículo, semilla {payload['bootstrap']['seed']}.",
        f"- Inferencia iniciada: {payload['inference_started_at_utc']}; completada: {payload['generated_at_utc']}.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verified_hashes = verify_frozen_inputs(manifest, manifest_path)
    policy = manifest["evaluation_policy"]
    if policy["inference_runs_allowed"] != 1 or not policy["no_training_or_threshold_tuning"]:
        raise ValueError("Frozen evaluation policy is not the expected one-shot/no-tuning policy")

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "inference_run_state.json"
    started_at = datetime.now(timezone.utc).isoformat()
    resumed_from_preinference_abort = False
    if state_path.exists():
        previous_state = json.loads(state_path.read_text(encoding="utf-8"))
        resumable = (
            previous_state.get("status") == "PREINFERENCE_ABORTED_NO_EXAMPLES_PROCESSED"
            and not (output_dir / "predictions.csv").exists()
            and not (output_dir / "metrics.json").exists()
        )
        if not resumable:
            raise RuntimeError(f"One-shot inference marker already exists; refusing to rerun: {state_path}")
        started_at = previous_state["started_at_utc"]
        resumed_from_preinference_abort = True
    state_path.write_text(json.dumps({
        "status": "STARTED_ONE_SHOT_INFERENCE",
        "started_at_utc": started_at,
        "resumed_after_preinference_abort": resumed_from_preinference_abort,
        "manifest_sha256": verified_hashes["manifest"],
        "checkpoint_tree_sha256": verified_hashes["checkpoint_tree"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    gold_dir = manifest_path.parent
    stances = gold_dir / "final_stances.csv"
    bodies = gold_dir / "final_bodies.csv"
    metadata_path = gold_dir / "final_metadata.csv"
    gold_path = gold_dir / "Kenta_Stance_Peru_v1_evaluacion_final_gold.json"
    model_dir = Path(manifest["frozen_checkpoint"]["path"])
    serving = json.loads((model_dir / "serving_config.json").read_text(encoding="utf-8"))
    max_length = int(serving["max_length"])
    if serving["label_names"] != STANCE_LABELS:
        raise ValueError(f"Serving label order mismatch: {serving['label_names']} vs {STANCE_LABELS}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    runtime_stances = output_dir / "runtime_final_stances_no_bom.csv"
    runtime_bodies = output_dir / "runtime_final_bodies_no_bom.csv"
    body_id_map = write_legacy_runtime_copies(stances, bodies, runtime_stances, runtime_bodies)
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir), local_files_only=True).to(device)
    dataset = FNCDataset(str(runtime_stances), str(runtime_bodies), tokenizer, max_length=max_length)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False)
    metadata = read_csv(metadata_path)
    gold_rows = json.loads(gold_path.read_text(encoding="utf-8"))
    if len(dataset) != len(metadata) or len(dataset) != len(gold_rows):
        raise ValueError("Dataset, metadata and frozen gold lengths differ")
    for index, (meta, gold_row) in enumerate(zip(metadata, gold_rows, strict=True)):
        if meta["pair_id"] != gold_row["pair_id"]:
            raise ValueError(f"Metadata/gold order mismatch at row {index}")

    truth, predictions, probabilities = infer(model, loader, device)
    for index, gold_row in enumerate(gold_rows):
        if REVERSE_LABELS[truth[index]] != gold_row["final_label"]:
            raise ValueError(f"Dataset/gold label mismatch at {gold_row['pair_id']}")

    metrics = metric_payload(truth, predictions)
    observed_ids = [FNC_LABEL_MAP[label] for label in metrics["observed_classes"]]
    groups = [row.get("group_id") or row["pair_id"] for row in metadata]
    bootstrap = grouped_bootstrap(
        truth, predictions, groups, observed_ids,
        iterations=int(policy["bootstrap_iterations"]), seed=42,
    )
    source_breakdown = subgroup_metrics(metadata, truth, predictions, "source_name")
    extraction_breakdown = subgroup_metrics(metadata, truth, predictions, "extraction_mode")

    class_report = metrics["classification_report"]
    observable_checks = {
        "macro_f1_four_class_at_least_0_60": metrics["macro_f1_four_class"] >= 0.60,
        "macro_f1_observed_classes_at_least_0_60_descriptive": metrics["macro_f1_observed_classes"] >= 0.60,
        "disagree_f1_at_least_0_50": class_report["disagree"]["f1-score"] >= 0.50,
        "disagree_recall_at_least_0_50": class_report["disagree"]["recall"] >= 0.50,
        "discuss_f1_at_least_0_40": class_report["discuss"]["f1-score"] >= 0.40,
        "agree_f1_at_least_0_40": class_report["agree"]["f1-score"] >= 0.40,
    }
    interpretation = {
        "formal_gate_status": "NO TOTALMENTE EVALUABLE EN ESTA MUESTRA PROSPECTIVA",
        "deployment_decision": "NO AUTORIZAR TODAVÍA EL DESPLIEGUE PLENO DE CUATRO CLASES",
        "decision_reason": (
            "el modelo no predijo discuss ni disagree, quedó por debajo de la línea base mayoritaria, "
            "y la muestra además carece de soporte unrelated y solo contiene dos casos disagree; por tanto "
            "no supera las comprobaciones observables ni permite cerrar la puerta formal de cuatro clases"
        ),
        "observable_checks": observable_checks,
        "unestimable_checks": {
            "unrelated_f1_at_least_0_40": "NOT_ESTIMABLE_SUPPORT_0",
            "all_four_class_f1_at_least_0_40": "NOT_ESTIMABLE_SUPPORT_0_FOR_UNRELATED",
            "representative_disagree_robustness": "INSUFFICIENT_SUPPORT_N_2",
        },
    }

    completed_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "generated_at_utc": completed_at,
        "inference_started_at_utc": started_at,
        "model_dir": str(model_dir),
        "manifest": str(manifest_path),
        "examples": len(dataset),
        "groups": len(set(groups)),
        "max_length": max_length,
        "batch_size": args.batch_size,
        "runtime_body_id_mapping": body_id_map,
        "device": str(device),
        "label_order": STANCE_LABELS,
        "verified_hashes": verified_hashes,
        "metrics": metrics,
        "bootstrap": bootstrap,
        "source_breakdown": source_breakdown,
        "extraction_mode_breakdown": extraction_breakdown,
        "controlled_test_metrics_from_frozen_serving_config": serving.get("test_metrics"),
        "interpretation": interpretation,
        "training_or_tuning_on_operational_gold": False,
    }

    prediction_rows = []
    error_rows = []
    for meta, gold_row, gold_id, pred_id, probs in zip(metadata, gold_rows, truth, predictions, probabilities, strict=True):
        row = {
            "pair_id": meta["pair_id"], "group_id": meta["group_id"], "article_id": meta["article_id"],
            "source_name": meta["source_name"], "extraction_mode": meta["extraction_mode"],
            "original_url": meta["original_url"], "title": meta["title"], "claim": gold_row["claim"],
            "gold_label": REVERSE_LABELS[gold_id], "predicted_label": REVERSE_LABELS[pred_id],
            "correct": gold_id == pred_id,
        }
        row.update({f"p_{label}": f"{probs[index]:.8f}" for index, label in enumerate(STANCE_LABELS)})
        prediction_rows.append(row)
        if gold_id != pred_id:
            error_rows.append(row)
    fields = ["pair_id", "group_id", "article_id", "source_name", "extraction_mode", "original_url", "title", "claim",
              "gold_label", "predicted_label", "correct"] + [f"p_{label}" for label in STANCE_LABELS]
    write_csv(output_dir / "predictions.csv", prediction_rows, fields)
    write_csv(output_dir / "errors_for_analysis.csv", error_rows, fields)
    (output_dir / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(render_report(payload), encoding="utf-8")
    state_path.write_text(json.dumps({
        "status": "COMPLETED_ONE_SHOT_INFERENCE",
        "started_at_utc": started_at,
        "completed_at_utc": completed_at,
        "manifest_sha256": verified_hashes["manifest"],
        "checkpoint_tree_sha256": verified_hashes["checkpoint_tree"],
        "examples": len(dataset),
        "successful_inference_passes": 1,
        "preinference_aborts": 2,
        "preinference_abort_notes": [
            "Legacy loader rejected the UTF-8 BOM before dataset construction.",
            "Legacy loader required integer Body ID before dataset construction.",
        ],
        "prediction_file_sha256": sha256_file(output_dir / "predictions.csv"),
        "metrics_file_sha256": sha256_file(output_dir / "metrics.json"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(render_report(payload))


if __name__ == "__main__":
    main()
