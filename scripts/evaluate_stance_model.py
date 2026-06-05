"""
Evaluate a dedicated stance classifier on FNC-1-style CSV splits.

Expected stance CSV columns:
  Headline, Body ID, Stance

Expected body CSV columns:
  Body ID, articleBody
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import torch
from torch.utils.data import DataLoader
from transformers import AutoModelForSequenceClassification, AutoTokenizer

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ml.training.datasets import FNCDataset, FNC_LABEL_MAP
from app.ml.training.train_stance import STANCE_LABELS, evaluate


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate a stance model on FNC-1 data")
    parser.add_argument("--model_dir", default=os.getenv("STANCE_MODEL_DIR"))
    parser.add_argument("--validation_stances", default="data/fnc-1/competition_test_stances.csv")
    parser.add_argument("--validation_bodies", default="data/fnc-1/competition_test_bodies.csv")
    parser.add_argument("--test_stances", default=None)
    parser.add_argument("--test_bodies", default=None)
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--max_length", type=int, default=None)
    parser.add_argument("--output_json", default=None)
    parser.add_argument("--output_md", default=None)
    return parser


def load_serving_max_length(model_dir: str) -> int | None:
    config_path = os.path.join(model_dir, "serving_config.json")
    if not os.path.exists(config_path):
        return None
    with open(config_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    value = payload.get("max_length")
    return int(value) if value else None


def label_counts_to_names(dataset: FNCDataset) -> dict[str, int]:
    counts = {label: 0 for label in STANCE_LABELS}
    reverse_map = {idx: label for label, idx in FNC_LABEL_MAP.items()}
    for sample in dataset.samples:
        label = reverse_map[int(sample["label"])]
        counts[label] += 1
    return counts


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
    lines.append(f"# Stance evaluation report - {payload['run_date']}")
    lines.append("")
    lines.append("## Setup")
    lines.append("")
    lines.append(f"- model_dir: {payload['model_dir']}")
    lines.append(f"- validation_stances: {payload['validation_stances']}")
    lines.append(f"- validation_bodies: {payload['validation_bodies']}")
    lines.append(f"- test_stances: {payload.get('test_stances')}")
    lines.append(f"- test_bodies: {payload.get('test_bodies')}")
    lines.append(f"- max_length: {payload['max_length']}")
    lines.append("")

    for split_name in ("validation", "test"):
        split = payload.get(split_name)
        if not split:
            continue
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
        for label in STANCE_LABELS:
            lines.append(format_class_report(report, label))
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    args = build_arg_parser().parse_args()
    if not args.model_dir:
        raise SystemExit("model_dir is required (or set STANCE_MODEL_DIR)")

    model_dir = Path(args.model_dir).resolve()
    validation_stances = Path(args.validation_stances)
    validation_bodies = Path(args.validation_bodies)

    if not validation_stances.exists():
        raise SystemExit(f"validation_stances not found: {validation_stances}")
    if not validation_bodies.exists():
        raise SystemExit(f"validation_bodies not found: {validation_bodies}")

    max_length = args.max_length or load_serving_max_length(str(model_dir)) or 512
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
    model.to(device)

    validation_dataset = FNCDataset(
        str(validation_stances),
        str(validation_bodies),
        tokenizer,
        max_length=max_length,
    )
    validation_loader = DataLoader(validation_dataset, batch_size=args.batch_size, shuffle=False)
    validation_metrics = evaluate(model, validation_loader, device)

    payload = {
        "run_date": datetime.now().date().isoformat(),
        "model_dir": str(model_dir),
        "validation_stances": str(validation_stances),
        "validation_bodies": str(validation_bodies),
        "test_stances": args.test_stances,
        "test_bodies": args.test_bodies,
        "max_length": max_length,
        "validation": {
            "num_examples": len(validation_dataset),
            "label_counts": label_counts_to_names(validation_dataset),
            "metrics": validation_metrics,
        },
    }

    if args.test_stances and args.test_bodies:
        test_stances = Path(args.test_stances)
        test_bodies = Path(args.test_bodies)
        if not test_stances.exists():
            raise SystemExit(f"test_stances not found: {test_stances}")
        if not test_bodies.exists():
            raise SystemExit(f"test_bodies not found: {test_bodies}")
        test_dataset = FNCDataset(str(test_stances), str(test_bodies), tokenizer, max_length=max_length)
        test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False)
        payload["test"] = {
            "num_examples": len(test_dataset),
            "label_counts": label_counts_to_names(test_dataset),
            "metrics": evaluate(model, test_loader, device),
        }

    print("Stance evaluation summary")
    print(f"  model_dir          : {payload['model_dir']}")
    print(f"  validation macro_f1: {validation_metrics['macro_f1']:.4f}")
    print(f"  validation accuracy: {validation_metrics['accuracy']:.4f}")

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
