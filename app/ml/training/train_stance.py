"""
Entry point for dedicated stance fine-tuning on FNC-1.

Usage:
    python -m app.ml.training.train_stance
    python -m app.ml.training.train_stance --epochs 8 --batch_size 8
    python -m app.ml.training.train_stance --model_name bert-base-multilingual-cased
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import random
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from torch.optim import AdamW
from torch.utils.data import DataLoader, WeightedRandomSampler
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

from app.ml.stance_classifier import StanceServingConfig
from app.ml.training.datasets import FNCDataset, FNC_LABEL_MAP
from app.ml.training.losses import FocalLoss

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

STANCE_LABELS = [
    label for label, _ in sorted(FNC_LABEL_MAP.items(), key=lambda item: item[1])
]


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dedicated stance fine-tuning on FNC-1")
    parser.add_argument("--model_name", default="xlm-roberta-base")
    parser.add_argument("--fnc_dir", default="data/fnc-1")
    parser.add_argument("--train_stances", default=None)
    parser.add_argument("--train_bodies", default=None)
    parser.add_argument("--val_stances", default=None)
    parser.add_argument("--val_bodies", default=None)
    parser.add_argument("--test_stances", default=None)
    parser.add_argument("--test_bodies", default=None)
    parser.add_argument("--output_dir", default="output/stance_bert")
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--max_length", type=int, default=512)
    parser.add_argument("--weight_decay", type=float, default=0.01)
    parser.add_argument("--warmup_ratio", type=float, default=0.1)
    parser.add_argument("--max_grad_norm", type=float, default=1.0)
    parser.add_argument("--patience", type=int, default=2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--train_sampling",
        default="shuffle",
        choices=("shuffle", "weighted"),
        help="How to sample the training set. 'weighted' oversamples the minority class without discarding data.",
    )
    parser.add_argument("--no_focal_loss", action="store_true")
    return parser


def resolve_model_source(model_name_or_path: str) -> str:
    candidate = Path(model_name_or_path)
    if candidate.exists():
        return str(candidate.resolve())
    if os.path.isabs(model_name_or_path) or model_name_or_path.startswith("."):
        raise FileNotFoundError(
            f"No se encontro el checkpoint local indicado en '{model_name_or_path}'."
        )
    return model_name_or_path


def resolve_serving_model_name(model_source: str) -> str:
    source_path = Path(model_source)
    if not source_path.exists():
        return model_source

    config_path = source_path / "serving_config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            model_name = payload.get("model_name")
            if model_name:
                return str(model_name)
        except (OSError, ValueError, TypeError):
            logger.warning("No se pudo leer serving_config.json desde %s", source_path)

    return str(source_path.resolve())


def create_grad_scaler(use_amp: bool):
    if not use_amp:
        return None

    try:
        return torch.amp.GradScaler("cuda")
    except (AttributeError, TypeError):
        return torch.cuda.amp.GradScaler()


def autocast_context(use_amp: bool):
    if not use_amp:
        return nullcontext()

    try:
        return torch.amp.autocast("cuda")
    except (AttributeError, TypeError):
        return torch.cuda.amp.autocast()


def compute_label_counts(dataset: FNCDataset) -> dict[int, int]:
    counts = {idx: 0 for idx in range(len(STANCE_LABELS))}
    for sample in dataset.samples:
        counts[int(sample["label"])] += 1
    return counts


def compute_class_weights(dataset: FNCDataset, device: torch.device) -> torch.Tensor:
    counts = compute_label_counts(dataset)
    total = sum(counts.values())
    num_classes = len(STANCE_LABELS)
    weights = []
    for label in range(num_classes):
        count = max(counts.get(label, 0), 1)
        weights.append(total / (num_classes * count))
    return torch.tensor(weights, dtype=torch.float, device=device)


def build_train_loader(
    dataset: FNCDataset,
    *,
    batch_size: int,
    sampling: str,
    seed: int,
) -> DataLoader:
    if sampling != "weighted":
        return DataLoader(dataset, batch_size=batch_size, shuffle=True)

    counts = compute_label_counts(dataset)
    total = sum(counts.values())
    sample_weights = []
    for sample in dataset.samples:
        count = max(counts.get(sample["label"], 0), 1)
        sample_weights.append(total / count)

    generator = torch.Generator()
    generator.manual_seed(seed)
    sampler = WeightedRandomSampler(
        weights=torch.tensor(sample_weights, dtype=torch.double),
        num_samples=len(sample_weights),
        replacement=True,
        generator=generator,
    )
    return DataLoader(dataset, batch_size=batch_size, sampler=sampler)


def evaluate(model, dataloader, device: torch.device) -> dict:
    model.eval()
    labels: list[int] = []
    predictions: list[int] = []

    with torch.no_grad():
        for batch in dataloader:
            labels.extend(batch["labels"].tolist())
            inputs = {
                key: value.to(device)
                for key, value in batch.items()
                if key != "labels"
            }
            logits = model(**inputs).logits
            predictions.extend(logits.argmax(dim=-1).cpu().tolist())

    report = classification_report(
        labels,
        predictions,
        target_names=STANCE_LABELS,
        output_dict=True,
        zero_division=0,
    )

    return {
        "macro_f1": float(f1_score(labels, predictions, average="macro", zero_division=0)),
        "accuracy": float(accuracy_score(labels, predictions)),
        "confusion_matrix": confusion_matrix(labels, predictions).tolist(),
        "classification_report": report,
    }


def resolve_fnc_paths(args) -> tuple[str, str, str, str, str | None, str | None]:
    train_stances = args.train_stances or os.path.join(args.fnc_dir, "train_stances.csv")
    train_bodies = args.train_bodies or os.path.join(args.fnc_dir, "train_bodies.csv")
    val_stances = args.val_stances or os.path.join(args.fnc_dir, "competition_test_stances.csv")
    val_bodies = args.val_bodies or os.path.join(args.fnc_dir, "competition_test_bodies.csv")
    test_stances = args.test_stances
    test_bodies = args.test_bodies
    return train_stances, train_bodies, val_stances, val_bodies, test_stances, test_bodies


def save_checkpoint(
    *,
    model,
    tokenizer,
    output_dir: str,
    serving_config: StanceServingConfig,
    metrics: dict[str, dict],
    history: list[dict],
) -> None:
    best_dir = os.path.join(output_dir, "best_model")
    os.makedirs(best_dir, exist_ok=True)
    model.save_pretrained(best_dir)
    tokenizer.save_pretrained(best_dir)

    payload = serving_config.to_dict()
    payload["validation_metrics"] = metrics.get("validation")
    payload["test_metrics"] = metrics.get("test")

    with open(os.path.join(best_dir, "serving_config.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)

    with open(os.path.join(output_dir, "training_history.json"), "w", encoding="utf-8") as handle:
        json.dump(history, handle, ensure_ascii=True, indent=2)


def main() -> None:
    args = build_arg_parser().parse_args()
    set_seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = torch.cuda.is_available() and device.type == "cuda"
    scaler = create_grad_scaler(use_amp)

    model_source = resolve_model_source(args.model_name)
    serving_model_name = resolve_serving_model_name(model_source)

    tokenizer = AutoTokenizer.from_pretrained(model_source)
    (
        train_stances,
        train_bodies,
        val_stances,
        val_bodies,
        test_stances,
        test_bodies,
    ) = resolve_fnc_paths(args)

    train_dataset = FNCDataset(train_stances, train_bodies, tokenizer, max_length=args.max_length)
    validation_dataset = FNCDataset(val_stances, val_bodies, tokenizer, max_length=args.max_length)
    test_dataset = None
    if test_stances and test_bodies:
        test_dataset = FNCDataset(test_stances, test_bodies, tokenizer, max_length=args.max_length)

    train_loader = build_train_loader(
        train_dataset,
        batch_size=args.batch_size,
        sampling=args.train_sampling,
        seed=args.seed,
    )
    validation_loader = DataLoader(validation_dataset, batch_size=args.batch_size)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size) if test_dataset else None

    label_counts = compute_label_counts(train_dataset)
    logger.info(
        "Dataset sizes - train=%s validation=%s test=%s",
        len(train_dataset),
        len(validation_dataset),
        len(test_dataset) if test_dataset else 0,
    )
    logger.info("Training label counts: %s", label_counts)
    logger.info("Training sampling strategy: %s", args.train_sampling)

    model = AutoModelForSequenceClassification.from_pretrained(
        model_source,
        num_labels=len(STANCE_LABELS),
    ).to(device)

    if args.train_sampling == "weighted":
        class_weights = None
        logger.info("Class-weighted loss disabled because weighted sampling is active.")
    else:
        class_weights = compute_class_weights(train_dataset, device=device)

    if args.no_focal_loss:
        criterion = nn.CrossEntropyLoss(weight=class_weights)
    else:
        criterion = FocalLoss(gamma=2.0, weight=class_weights)

    optimizer = AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_steps * args.warmup_ratio),
        num_training_steps=total_steps,
    )

    best_state = None
    best_metrics = None
    best_score = -1.0
    best_epoch = 0
    epochs_without_improvement = 0
    history: list[dict] = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0

        for batch in train_loader:
            optimizer.zero_grad()
            labels = batch["labels"].to(device)
            inputs = {
                key: value.to(device)
                for key, value in batch.items()
                if key != "labels"
            }

            if use_amp:
                with autocast_context(use_amp):
                    logits = model(**inputs).logits
                    loss = criterion(logits, labels)
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                scaler.step(optimizer)
                scaler.update()
            else:
                logits = model(**inputs).logits
                loss = criterion(logits, labels)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                optimizer.step()

            scheduler.step()
            running_loss += loss.item()

        validation_metrics = evaluate(model, validation_loader, device)
        epoch_summary = {
            "epoch": epoch,
            "train_loss": round(running_loss / max(len(train_loader), 1), 6),
            "validation_macro_f1": round(validation_metrics["macro_f1"], 6),
            "validation_accuracy": round(validation_metrics["accuracy"], 6),
        }
        history.append(epoch_summary)
        logger.info("Epoch %s summary: %s", epoch, epoch_summary)

        if validation_metrics["macro_f1"] > best_score:
            best_score = validation_metrics["macro_f1"]
            best_state = copy.deepcopy(model.state_dict())
            best_metrics = {"validation": validation_metrics}
            best_epoch = epoch
            epochs_without_improvement = 0
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= args.patience:
                logger.info("Early stopping at epoch %s", epoch)
                break

    if best_state is None:
        raise RuntimeError("Training finished without producing a valid checkpoint.")

    model.load_state_dict(best_state)
    test_metrics = evaluate(model, test_loader, device) if test_loader else None
    if best_metrics is None:
        best_metrics = {"validation": validation_metrics}
    if test_metrics:
        best_metrics["test"] = test_metrics

    logger.info("Best validation macro F1: %.4f at epoch %s", best_score, best_epoch)
    logger.info("Validation report:\n%s", json.dumps(best_metrics["validation"]["classification_report"], indent=2))
    if test_metrics:
        logger.info("Test report:\n%s", json.dumps(best_metrics["test"]["classification_report"], indent=2))

    serving_config = StanceServingConfig(
        label_names=tuple(STANCE_LABELS),
        label_strategy="strict",
        decision_threshold=0.5,
        max_length=args.max_length,
        model_name=serving_model_name,
        validation_metrics=best_metrics.get("validation"),
        test_metrics=best_metrics.get("test"),
    )
    save_checkpoint(
        model=model,
        tokenizer=tokenizer,
        output_dir=args.output_dir,
        serving_config=serving_config,
        metrics=best_metrics,
        history=history,
    )


if __name__ == "__main__":
    main()
