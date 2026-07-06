"""
Evaluate a dedicated fake-news classifier on TSV splits.

Expected TSV columns:
  id, label, claim_text, source, url, verdict_raw, date
Labels must be "true" or "false" (case-insensitive).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from transformers import AutoModelForSequenceClassification, AutoTokenizer

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ml.training.fakenews_data import FAKENEWS_LABELS, LIARFakeNewsDataset
from app.ml.training.train_fakenews import evaluate


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate a fake-news model on TSV data")
    parser.add_argument("--model_dir", default=os.getenv("FAKENEWS_MODEL_DIR"))
    parser.add_argument("--validation_path", required=True)
    parser.add_argument("--test_path", required=True)
    parser.add_argument("--label_strategy", default="strict")
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--max_length", type=int, default=128)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--output_json", default=None)
    parser.add_argument("--output_md", default=None)
    return parser


def load_serving_threshold(model_dir: str) -> float | None:
    config_path = os.path.join(model_dir, "serving_config.json")
    if not os.path.exists(config_path):
        return None
    with open(config_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return float(payload.get("decision_threshold", 0.5))


def label_counts_to_names(counts: dict[int, int]) -> dict[str, int]:
    named: dict[str, int] = {}
    for label, count in counts.items():
        if 0 <= int(label) < len(FAKENEWS_LABELS):
            named[FAKENEWS_LABELS[int(label)]] = int(count)
    return named


def format_class_report(report: dict, label: str) -> str:
    entry = report.get(label) or {}
    if not entry:
        return f"- {label}: n/a"
    return (
        f"- {label}: precision={entry.get('precision'):.4f} "
        f"recall={entry.get('recall'):.4f} f1={entry.get('f1-score'):.4f} "
        f"support={int(entry.get('support', 0))}"
    )


def render_report(payload: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Evaluation report - {payload['run_date']}")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- model_dir: {payload['model_dir']}")
    lines.append(f"- validation_path: {payload['validation_path']}")
    lines.append(f"- test_path: {payload['test_path']}")
    lines.append(f"- label_strategy: {payload['label_strategy']}")
    lines.append(f"- max_length: {payload['max_length']}")
    lines.append(f"- decision_threshold: {payload['decision_threshold']}")
    lines.append("")

    for split_name in ("validation", "test"):
        split = payload.get(split_name) or {}
        metrics = split.get("metrics") or {}
        report = metrics.get("classification_report") or {}
        lines.append(f"## {split_name.title()} set")
        lines.append("")
        lines.append(f"- examples: {split.get('num_examples')}")
        lines.append(f"- label_counts: {split.get('label_counts')}")
        lines.append(f"- macro_f1: {metrics.get('macro_f1'):.4f}")
        lines.append(f"- accuracy: {metrics.get('accuracy'):.4f}")
        lines.append(f"- confusion_matrix: {metrics.get('confusion_matrix')}")
        lines.append("")
        lines.append("Per-class metrics")
        lines.append("")
        lines.append(format_class_report(report, "False"))
        lines.append(format_class_report(report, "True"))
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    args = build_arg_parser().parse_args()
    if not args.model_dir:
        raise SystemExit("model_dir is required (or set FAKENEWS_MODEL_DIR)")

    model_dir = Path(args.model_dir).resolve()
    validation_path = Path(args.validation_path)
    test_path = Path(args.test_path)

    if not validation_path.exists():
        raise SystemExit(f"validation_path not found: {validation_path}")
    if not test_path.exists():
        raise SystemExit(f"test_path not found: {test_path}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
    model.to(device)

    validation_dataset = LIARFakeNewsDataset(
        str(validation_path),
        tokenizer,
        max_length=args.max_length,
        label_strategy=args.label_strategy,
    )
    test_dataset = LIARFakeNewsDataset(
        str(test_path),
        tokenizer,
        max_length=args.max_length,
        label_strategy=args.label_strategy,
    )

    validation_loader = DataLoader(validation_dataset, batch_size=args.batch_size, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False)

    threshold = args.threshold
    if threshold is None:
        threshold = load_serving_threshold(str(model_dir))
    if threshold is None:
        threshold = 0.5

    validation_metrics = evaluate(model, validation_loader, device, threshold=threshold)
    test_metrics = evaluate(model, test_loader, device, threshold=threshold)

    payload = {
        "run_date": "2026-05-27",
        "model_dir": str(model_dir),
        "validation_path": str(validation_path),
        "test_path": str(test_path),
        "label_strategy": args.label_strategy,
        "max_length": args.max_length,
        "decision_threshold": float(threshold),
        "validation": {
            "num_examples": len(validation_dataset),
            "label_counts": label_counts_to_names(validation_dataset.label_counts),
            "metrics": validation_metrics,
        },
        "test": {
            "num_examples": len(test_dataset),
            "label_counts": label_counts_to_names(test_dataset.label_counts),
            "metrics": test_metrics,
        },
    }

    print("Evaluation summary")
    print(f"  model_dir        : {payload['model_dir']}")
    print(f"  decision_threshold: {payload['decision_threshold']}")
    print(f"  validation macro_f1: {validation_metrics['macro_f1']:.4f}")
    print(f"  test macro_f1      : {test_metrics['macro_f1']:.4f}")

    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with output_json.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2)

    if args.output_md:
        output_md = Path(args.output_md)
        output_md.parent.mkdir(parents=True, exist_ok=True)
        output_md.write_text(render_report(payload), encoding="utf-8")


if __name__ == "__main__":
    main()
