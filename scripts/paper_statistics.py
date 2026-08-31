"""Reproducible statistical analysis for the Kenta paper experiments.

The script re-evaluates the saved classification checkpoints on their fixed
test sets, stores only labels/predictions/scores (never article text), and
reports:

* percentile bootstrap 95% confidence intervals for macro-F1 and accuracy;
* paired bootstrap comparisons of macro-F1; and
* exact McNemar tests for paired accuracy comparisons.

For summarization, it consumes the existing per-example benchmark CSV and
reports bootstrap intervals and paired bootstrap comparisons for ROUGE F1.

Examples
--------
python scripts/paper_statistics.py --tasks fakenews --bootstrap-samples 10000
python scripts/paper_statistics.py --tasks stance summarization
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import sys
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Callable

import numpy as np
import torch
from scipy.stats import binomtest
from torch.utils.data import DataLoader
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from transformers.utils import logging as transformers_logging


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ml.training.datasets import FNC_LABEL_MAP, FNCDataset
from app.ml.training.fakenews_data import LIARFakeNewsDataset


FAKENEWS_MODELS = {
    "XLM-RoBERTa": REPO_ROOT / "output/fakenews_xlmroberta_full_v1/best_model",
    "mBERT": REPO_ROOT / "output/fakenews_mbert_full_v1/best_model",
    "DistilmBERT": REPO_ROOT / "output/fakenews_distilmbert_full_v1/best_model",
}
STANCE_MODELS = {
    "mBERT + weighted sampling": REPO_ROOT / "output/stance_mbert_weighted_paper/best_model",
    "mBERT": REPO_ROOT / "output/stance_mbert_paper/best_model",
    "DistilmBERT + weighted sampling": REPO_ROOT / "output/stance_distilmbert_weighted_paper/best_model",
}
SUMMARY_METRICS = ("rouge1_f1", "rouge2_f1", "rougeL_f1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tasks",
        nargs="+",
        choices=("fakenews", "stance", "summarization"),
        default=("fakenews", "stance", "summarization"),
        help="Experiment families to analyse.",
    )
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=REPO_ROOT / "output/paper_v7/statistics",
        help="Directory for generated reports and text-free prediction files.",
    )
    parser.add_argument(
        "--fakenews-test-path",
        type=Path,
        default=REPO_ROOT / "data/claims_es_pe_full/test.tsv",
    )
    parser.add_argument(
        "--stance-test-stances",
        type=Path,
        default=REPO_ROOT / "data/fnc-1/competition_test_stances.csv",
    )
    parser.add_argument(
        "--stance-test-bodies",
        type=Path,
        default=REPO_ROOT / "data/fnc-1/competition_test_bodies.csv",
    )
    parser.add_argument(
        "--summarization-csv",
        type=Path,
        default=REPO_ROOT / "output/summarizer_benchmark_synthetic_refs_fixed.csv",
    )
    parser.add_argument(
        "--reuse-predictions-csv",
        type=Path,
        help=(
            "Reuse a text-free classifier prediction CSV produced by this script. "
            "Use with exactly one classifier task (fakenews or stance) to recompute "
            "statistics without rerunning checkpoint inference."
        ),
    )
    return parser.parse_args()


def read_serving_config(model_dir: Path) -> dict:
    config_path = model_dir / "serving_config.json"
    if not config_path.exists():
        return {}
    with config_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def macro_f1(confusions: np.ndarray) -> np.ndarray:
    """Return macro-F1 for one CxC confusion matrix or a stack of them."""
    true_positive = np.diagonal(confusions, axis1=-2, axis2=-1)
    predicted_total = confusions.sum(axis=-2)
    actual_total = confusions.sum(axis=-1)
    precision = np.divide(
        true_positive,
        predicted_total,
        out=np.zeros_like(true_positive, dtype=float),
        where=predicted_total != 0,
    )
    recall = np.divide(
        true_positive,
        actual_total,
        out=np.zeros_like(true_positive, dtype=float),
        where=actual_total != 0,
    )
    f1 = np.divide(
        2 * precision * recall,
        precision + recall,
        out=np.zeros_like(precision, dtype=float),
        where=(precision + recall) != 0,
    )
    return f1.mean(axis=-1)


def accuracy(confusions: np.ndarray) -> np.ndarray:
    total = confusions.sum(axis=(-2, -1))
    return np.divide(
        np.trace(confusions, axis1=-2, axis2=-1),
        total,
        out=np.zeros_like(total, dtype=float),
        where=total != 0,
    )


def confidence_interval(values: np.ndarray, point: float) -> dict[str, float]:
    return {
        "point": float(point),
        "ci95_low": float(np.quantile(values, 0.025)),
        "ci95_high": float(np.quantile(values, 0.975)),
    }


def bootstrap_two_sided_pvalue(differences: np.ndarray) -> float:
    """Return a finite two-sided paired-bootstrap p-value with a +1 correction."""
    sample_count = len(differences)
    probability_nonpositive = (int(np.sum(differences <= 0)) + 1) / (sample_count + 1)
    probability_nonnegative = (int(np.sum(differences >= 0)) + 1) / (sample_count + 1)
    return float(min(1.0, 2 * min(probability_nonpositive, probability_nonnegative)))


def bootstrap_confusions(
    joint_counts: np.ndarray,
    sample_size: int,
    bootstrap_samples: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw non-parametric bootstrap contingency tables in memory-safe batches.

    Resampling the observed categorical outcomes is equivalent to drawing from
    the corresponding multinomial distribution. It avoids holding a large
    bootstrap-index matrix for the 25k-row FNC-1 test set.
    """
    probabilities = joint_counts.astype(float) / float(joint_counts.sum())
    batches: list[np.ndarray] = []
    batch_size = min(500, bootstrap_samples)
    remaining = bootstrap_samples
    while remaining:
        current = min(batch_size, remaining)
        batches.append(rng.multinomial(sample_size, probabilities, size=current))
        remaining -= current
    return np.concatenate(batches, axis=0)


def classifier_statistics(
    predictions: dict[str, dict[str, np.ndarray]],
    labels: list[str],
    bootstrap_samples: int,
    seed: int,
) -> dict:
    ordered_models = list(predictions)
    class_count = len(labels)
    sample_size = len(next(iter(predictions.values()))["true"])
    result: dict = {
        "sample_size": sample_size,
        "labels": labels,
        "models": {},
        "paired_comparisons": [],
    }

    for offset, model_name in enumerate(ordered_models):
        y_true = predictions[model_name]["true"]
        y_pred = predictions[model_name]["pred"]
        counts = np.bincount(y_true * class_count + y_pred, minlength=class_count**2)
        point_confusion = counts.reshape(class_count, class_count)
        boot = bootstrap_confusions(
            counts,
            sample_size,
            bootstrap_samples,
            np.random.default_rng(seed + offset),
        ).reshape(bootstrap_samples, class_count, class_count)
        result["models"][model_name] = {
            "macro_f1": confidence_interval(macro_f1(boot), float(macro_f1(point_confusion))),
            "accuracy": confidence_interval(accuracy(boot), float(accuracy(point_confusion))),
            "confusion_matrix": point_confusion.tolist(),
        }

    for offset, (left_name, right_name) in enumerate(combinations(ordered_models, 2)):
        y_true = predictions[left_name]["true"]
        left_pred = predictions[left_name]["pred"]
        right_pred = predictions[right_name]["pred"]
        if not np.array_equal(y_true, predictions[right_name]["true"]):
            raise ValueError(f"Prediction order differs between {left_name} and {right_name}.")
        joint_code = y_true * class_count**2 + left_pred * class_count + right_pred
        joint_counts = np.bincount(joint_code, minlength=class_count**3)
        boot_joint = bootstrap_confusions(
            joint_counts,
            sample_size,
            bootstrap_samples,
            np.random.default_rng(seed + 100 + offset),
        ).reshape(bootstrap_samples, class_count, class_count, class_count)
        left_confusion = boot_joint.sum(axis=3)
        right_confusion = boot_joint.sum(axis=2)
        differences = macro_f1(left_confusion) - macro_f1(right_confusion)
        point_left = macro_f1(joint_counts.reshape(class_count, class_count, class_count).sum(axis=2))
        point_right = macro_f1(joint_counts.reshape(class_count, class_count, class_count).sum(axis=1))

        left_correct_right_wrong = int(np.sum((left_pred == y_true) & (right_pred != y_true)))
        right_correct_left_wrong = int(np.sum((left_pred != y_true) & (right_pred == y_true)))
        discordant = left_correct_right_wrong + right_correct_left_wrong
        mcnemar_pvalue = (
            float(binomtest(left_correct_right_wrong, n=discordant, p=0.5).pvalue)
            if discordant
            else 1.0
        )
        result["paired_comparisons"].append(
            {
                "left_model": left_name,
                "right_model": right_name,
                "metric": "macro_f1",
                "difference_left_minus_right": confidence_interval(
                    differences,
                    float(point_left - point_right),
                ),
                "bootstrap_two_sided_pvalue": bootstrap_two_sided_pvalue(differences),
                "mcnemar_accuracy": {
                    "left_correct_right_wrong": left_correct_right_wrong,
                    "right_correct_left_wrong": right_correct_left_wrong,
                    "exact_two_sided_pvalue": mcnemar_pvalue,
                },
            }
        )
    return result


def collect_classifier_predictions(
    *,
    models: dict[str, Path],
    dataset_factory: Callable,
    max_length_from_config: bool,
    threshold_from_config: bool,
    batch_size: int,
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, dict]]:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    all_predictions: dict[str, dict[str, np.ndarray]] = {}
    details: dict[str, dict] = {}
    shared_true: np.ndarray | None = None

    for name, model_dir in models.items():
        if not model_dir.exists():
            raise FileNotFoundError(f"Checkpoint missing: {model_dir}")
        serving = read_serving_config(model_dir)
        max_length = int(serving.get("max_length", 512 if max_length_from_config else 128))
        threshold = float(serving.get("decision_threshold", 0.5)) if threshold_from_config else None
        tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
        model = AutoModelForSequenceClassification.from_pretrained(str(model_dir)).to(device)
        model.eval()
        dataset = dataset_factory(tokenizer, max_length)
        loader = DataLoader(
            dataset,
            batch_size=batch_size,
            shuffle=False,
            pin_memory=device.type == "cuda",
        )
        true_values: list[int] = []
        predictions: list[int] = []
        scores: list[float] = []
        with torch.inference_mode():
            for batch in loader:
                true_values.extend(batch["labels"].tolist())
                inputs = {key: value.to(device) for key, value in batch.items() if key != "labels"}
                logits = model(**inputs).logits
                probabilities = torch.softmax(logits, dim=-1)
                if threshold is None:
                    predictions.extend(logits.argmax(dim=-1).cpu().tolist())
                    scores.extend(probabilities.max(dim=-1).values.cpu().tolist())
                else:
                    positive_scores = probabilities[:, 1].cpu().tolist()
                    scores.extend(positive_scores)
                    predictions.extend(int(score >= threshold) for score in positive_scores)
        y_true = np.asarray(true_values, dtype=np.int64)
        y_pred = np.asarray(predictions, dtype=np.int64)
        if shared_true is not None and not np.array_equal(shared_true, y_true):
            raise ValueError(f"Dataset order changed while evaluating {name}.")
        shared_true = y_true
        all_predictions[name] = {"true": y_true, "pred": y_pred, "score": np.asarray(scores, dtype=float)}
        details[name] = {
            "checkpoint": str(model_dir.relative_to(REPO_ROOT)),
            "max_length": max_length,
            "decision_threshold": threshold,
        }
        del model, tokenizer, dataset, loader
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()
    return all_predictions, details


def save_predictions(path: Path, task: str, predictions: dict[str, dict[str, np.ndarray]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("task", "model", "sample_index", "label", "prediction", "score"),
        )
        writer.writeheader()
        for model_name, data in predictions.items():
            for index, (label, prediction, score) in enumerate(
                zip(data["true"], data["pred"], data["score"], strict=True)
            ):
                writer.writerow(
                    {
                        "task": task,
                        "model": model_name,
                        "sample_index": index,
                        "label": int(label),
                        "prediction": int(prediction),
                        "score": f"{float(score):.12f}",
                    }
                )


def load_predictions(path: Path, task: str, expected_models: dict[str, Path]) -> dict[str, dict[str, np.ndarray]]:
    """Load the script's text-free prediction export and validate its structure."""
    if not path.exists():
        raise FileNotFoundError(f"Prediction CSV missing: {path}")
    grouped: dict[str, list[tuple[int, int, int, float]]] = {name: [] for name in expected_models}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("task") != task:
                continue
            name = row.get("model", "")
            if name not in grouped:
                raise ValueError(f"Unexpected model in {path}: {name}")
            grouped[name].append(
                (int(row["sample_index"]), int(row["label"]), int(row["prediction"]), float(row["score"]))
            )
    predictions: dict[str, dict[str, np.ndarray]] = {}
    for name, rows in grouped.items():
        if not rows:
            raise ValueError(f"Prediction CSV has no {task} rows for {name}.")
        rows.sort(key=lambda row: row[0])
        expected_indexes = list(range(len(rows)))
        if [row[0] for row in rows] != expected_indexes:
            raise ValueError(f"Prediction CSV sample indexes are not contiguous for {name}.")
        predictions[name] = {
            "true": np.asarray([row[1] for row in rows], dtype=np.int64),
            "pred": np.asarray([row[2] for row in rows], dtype=np.int64),
            "score": np.asarray([row[3] for row in rows], dtype=float),
        }
    return predictions


def model_details(models: dict[str, Path], max_length_from_config: bool, threshold_from_config: bool) -> dict[str, dict]:
    """Read checkpoint metadata without loading model weights."""
    details: dict[str, dict] = {}
    for name, model_dir in models.items():
        if not model_dir.exists():
            raise FileNotFoundError(f"Checkpoint missing: {model_dir}")
        serving = read_serving_config(model_dir)
        details[name] = {
            "checkpoint": str(model_dir.relative_to(REPO_ROOT)),
            "max_length": int(serving.get("max_length", 512 if max_length_from_config else 128)),
            "decision_threshold": (
                float(serving.get("decision_threshold", 0.5)) if threshold_from_config else None
            ),
        }
    return details


def summary_statistics(csv_path: Path, bootstrap_samples: int, seed: int) -> dict:
    csv_path = csv_path.resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"Summarization benchmark missing: {csv_path}")
    grouped: dict[str, dict[str, dict[str, float]]] = {}
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            grouped.setdefault(row["model"], {})[row["source_id"]] = {
                metric: float(row[metric]) for metric in SUMMARY_METRICS
            }
    model_names = list(grouped)
    common_ids = sorted(set.intersection(*(set(grouped[name]) for name in model_names)))
    if not common_ids:
        raise ValueError("No shared source_id values in the summarization benchmark.")
    values = {
        model: {metric: np.asarray([grouped[model][source_id][metric] for source_id in common_ids]) for metric in SUMMARY_METRICS}
        for model in model_names
    }
    rng = np.random.default_rng(seed + 500)
    sample_indices = rng.integers(0, len(common_ids), size=(bootstrap_samples, len(common_ids)))
    result: dict = {
        "sample_size": len(common_ids),
        "models": {},
        "paired_comparisons": [],
        "input_file": str(csv_path.relative_to(REPO_ROOT)),
    }
    for model in model_names:
        result["models"][model] = {}
        for metric in SUMMARY_METRICS:
            scores = values[model][metric]
            boot_means = scores[sample_indices].mean(axis=1)
            result["models"][model][metric] = confidence_interval(boot_means, float(scores.mean()))
    for left_model, right_model in combinations(model_names, 2):
        for metric in SUMMARY_METRICS:
            pairwise = values[left_model][metric] - values[right_model][metric]
            differences = pairwise[sample_indices].mean(axis=1)
            result["paired_comparisons"].append(
                {
                    "left_model": left_model,
                    "right_model": right_model,
                    "metric": metric,
                    "difference_left_minus_right": confidence_interval(differences, float(pairwise.mean())),
                    "bootstrap_two_sided_pvalue": bootstrap_two_sided_pvalue(differences),
                }
            )
    return result


def fmt_interval(interval: dict[str, float]) -> str:
    return f"{interval['point']:.4f} [{interval['ci95_low']:.4f}, {interval['ci95_high']:.4f}]"


def fmt_pvalue(value: float | None) -> str:
    if value is None:
        return "n/a"
    return "< 0.0001" if value < 0.0001 else f"{value:.4f}"


def render_markdown(payload: dict) -> str:
    lines = ["# Statistical analysis for Kenta paper v7", ""]
    lines.append(f"- Generated: {payload['generated_at_utc']}")
    lines.append(f"- Bootstrap resamples: {payload['bootstrap_samples']}")
    lines.append(f"- Random seed: {payload['seed']}")
    lines.append("")
    for task_name, task in payload["tasks"].items():
        lines.extend([f"## {task_name.replace('_', ' ').title()}", ""])
        lines.append(f"Test examples: {task['statistics']['sample_size']}")
        lines.append("")
        if task_name == "summarization":
            lines.append("| Model | ROUGE-1 F1 (95% CI) | ROUGE-2 F1 (95% CI) | ROUGE-L F1 (95% CI) |")
            lines.append("| --- | --- | --- | --- |")
            for model, metrics in task["statistics"]["models"].items():
                lines.append(
                    f"| {model} | {fmt_interval(metrics['rouge1_f1'])} | "
                    f"{fmt_interval(metrics['rouge2_f1'])} | {fmt_interval(metrics['rougeL_f1'])} |"
                )
        else:
            lines.append("| Model | Macro-F1 (95% CI) | Accuracy (95% CI) |")
            lines.append("| --- | --- | --- |")
            for model, metrics in task["statistics"]["models"].items():
                lines.append(f"| {model} | {fmt_interval(metrics['macro_f1'])} | {fmt_interval(metrics['accuracy'])} |")
        lines.extend(["", "### Paired comparisons", ""])
        comparisons = task["statistics"]["paired_comparisons"]
        if not comparisons:
            lines.append("Only one model was analysed.")
        else:
            lines.append("| Comparison (left - right) | Metric | Difference (95% CI) | Bootstrap p | McNemar p |")
            lines.append("| --- | --- | --- | --- | --- |")
            for comparison in comparisons:
                mcnemar = comparison.get("mcnemar_accuracy") or {}
                mcnemar_p = mcnemar.get("exact_two_sided_pvalue")
                lines.append(
                    f"| {comparison['left_model']} - {comparison['right_model']} | {comparison['metric']} | "
                    f"{fmt_interval(comparison['difference_left_minus_right'])} | "
                    f"{fmt_pvalue(comparison['bootstrap_two_sided_pvalue'])} | "
                    f"{fmt_pvalue(mcnemar_p)} |"
                )
        lines.append("")
    lines.extend(
        [
            "## Interpretation guardrail",
            "",
            "These statistics quantify differences on the evaluated datasets only. They do not establish "
            "generalization to Peruvian Spanish stance data or human-perceived summary quality.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    if args.bootstrap_samples < 100:
        raise SystemExit("--bootstrap-samples must be at least 100.")
    classifier_tasks = {"fakenews", "stance"}.intersection(args.tasks)
    if args.reuse_predictions_csv and len(classifier_tasks) != 1:
        raise SystemExit("--reuse-predictions-csv requires exactly one classifier task.")
    transformers_logging.set_verbosity_error()
    transformers_logging.disable_progress_bar()
    args.results_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "bootstrap_samples": args.bootstrap_samples,
        "seed": args.seed,
        "runtime": {
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "torch": torch.__version__,
        },
        "tasks": {},
    }

    if "fakenews" in args.tasks:
        for path in (args.fakenews_test_path,):
            if not path.exists():
                raise FileNotFoundError(path)
        if args.reuse_predictions_csv:
            predictions = load_predictions(args.reuse_predictions_csv, "fakenews", FAKENEWS_MODELS)
            details = model_details(FAKENEWS_MODELS, max_length_from_config=False, threshold_from_config=True)
        else:
            predictions, details = collect_classifier_predictions(
                models=FAKENEWS_MODELS,
                dataset_factory=lambda tokenizer, max_length: LIARFakeNewsDataset(
                    str(args.fakenews_test_path), tokenizer, max_length=max_length, label_strategy="strict"
                ),
                max_length_from_config=False,
                threshold_from_config=True,
                batch_size=args.batch_size,
            )
        save_predictions(args.results_dir / "fakenews_test_predictions.csv", "fakenews", predictions)
        payload["tasks"]["fakenews"] = {
            "input_sha256": sha256(args.fakenews_test_path),
            "models": details,
            "statistics": classifier_statistics(
                predictions, ["False", "True"], args.bootstrap_samples, args.seed
            ),
        }

    if "stance" in args.tasks:
        for path in (args.stance_test_stances, args.stance_test_bodies):
            if not path.exists():
                raise FileNotFoundError(path)
        if args.reuse_predictions_csv:
            predictions = load_predictions(args.reuse_predictions_csv, "stance", STANCE_MODELS)
            details = model_details(STANCE_MODELS, max_length_from_config=True, threshold_from_config=False)
        else:
            predictions, details = collect_classifier_predictions(
                models=STANCE_MODELS,
                dataset_factory=lambda tokenizer, max_length: FNCDataset(
                    str(args.stance_test_stances), str(args.stance_test_bodies), tokenizer, max_length=max_length
                ),
                max_length_from_config=True,
                threshold_from_config=False,
                batch_size=args.batch_size,
            )
        labels = [label for label, _ in sorted(FNC_LABEL_MAP.items(), key=lambda item: item[1])]
        save_predictions(args.results_dir / "stance_test_predictions.csv", "stance", predictions)
        payload["tasks"]["stance"] = {
            "stances_sha256": sha256(args.stance_test_stances),
            "bodies_sha256": sha256(args.stance_test_bodies),
            "models": details,
            "statistics": classifier_statistics(predictions, labels, args.bootstrap_samples, args.seed),
        }

    if "summarization" in args.tasks:
        payload["tasks"]["summarization"] = {
            "statistics": summary_statistics(args.summarization_csv, args.bootstrap_samples, args.seed)
        }

    json_path = args.results_dir / "paper_statistics.json"
    markdown_path = args.results_dir / "paper_statistics.md"
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    print(f"[OK] wrote {json_path}")
    print(f"[OK] wrote {markdown_path}")


if __name__ == "__main__":
    main()
