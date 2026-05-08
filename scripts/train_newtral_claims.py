"""
Train the dedicated fake-news classifier using Newtral claims.

This is a thin wrapper around app.ml.training.train_fakenews.

Usage:
    python scripts/train_newtral_claims.py --epochs 5 --batch_size 16
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train fake-news model on Newtral claims")
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from app.ml.training.fakenews_data import available_label_strategies
    parser.add_argument("--model_name", default="xlm-roberta-base")
    parser.add_argument("--train_path", default="data/newtral/train.tsv")
    parser.add_argument("--validation_path", default="data/newtral/validation.tsv")
    parser.add_argument("--test_path", default="data/newtral/test.tsv")
    parser.add_argument("--output_dir", default="output/fakenews_newtral")
    parser.add_argument("--label_strategy", default="strict", choices=available_label_strategies())
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--max_length", type=int, default=128)
    parser.add_argument("--weight_decay", type=float, default=0.01)
    parser.add_argument("--warmup_ratio", type=float, default=0.1)
    parser.add_argument("--max_grad_norm", type=float, default=1.0)
    parser.add_argument("--patience", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    command = [
        sys.executable,
        "-m",
        "app.ml.training.train_fakenews",
        "--model_name",
        args.model_name,
        "--train_path",
        args.train_path,
        "--validation_path",
        args.validation_path,
        "--test_path",
        args.test_path,
        "--output_dir",
        args.output_dir,
        "--label_strategy",
        args.label_strategy,
        "--batch_size",
        str(args.batch_size),
        "--lr",
        str(args.lr),
        "--epochs",
        str(args.epochs),
        "--max_length",
        str(args.max_length),
        "--weight_decay",
        str(args.weight_decay),
        "--warmup_ratio",
        str(args.warmup_ratio),
        "--max_grad_norm",
        str(args.max_grad_norm),
        "--patience",
        str(args.patience),
        "--seed",
        str(args.seed),
    ]

    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
