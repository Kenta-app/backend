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

from app.ml.fakenews_classifier import FakeNewsServingConfig
from app.ml.training.fakenews_data import FAKENEWS_LABELS, LIARFakeNewsDataset, available_label_strategies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


MODEL_ALIASES = {
    "PlanTL-GOB-ES/roberta-base-bne": "xlm-roberta-base",
}


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dedicated fake-news fine-tuning on LIAR")
    parser.add_argument("--model_name", default="xlm-roberta-base")
    parser.add_argument("--train_path", default="data/liar/train.tsv")
    parser.add_argument("--validation_path", default="data/liar/validation.tsv")
    parser.add_argument("--test_path", default="data/liar/test.tsv")
    parser.add_argument("--output_dir", default="output/fakenews_bert")
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
    parser.add_argument(
        "--train_sampling",
        default="shuffle",
        choices=("shuffle", "weighted"),
        help="How to sample the training set. 'weighted' oversamples the minority class without discarding data.",
    )
    return parser


def compute_class_weights(dataset: LIARFakeNewsDataset, device: torch.device) -> torch.Tensor:
    total = sum(dataset.label_counts.values())
    num_classes = len(FAKENEWS_LABELS)
    weights = []
    for label in range(num_classes):
        count = max(dataset.label_counts.get(label, 0), 1)
        weights.append(total / (num_classes * count))
    return torch.tensor(weights, dtype=torch.float, device=device)


def _looks_like_local_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return (
        os.path.isabs(value)
        or value.startswith(".")
        or "\\" in value
        or normalized.startswith(("output/", "data/", "app/", "scripts/"))
        or normalized.count("/") >= 2
    )


def _discover_local_checkpoints(output_root: str = "output") -> list[str]:
    root = Path(output_root)
    if not root.exists():
        return []
    checkpoints = []
    for config_path in root.glob("**/best_model/serving_config.json"):
        checkpoints.append(str(config_path.parent.resolve()))
    return sorted(checkpoints)


def resolve_model_source(model_name_or_path: str) -> str:
    if model_name_or_path in MODEL_ALIASES:
        alias = MODEL_ALIASES[model_name_or_path]
        logger.warning(
            "Model %s is deprecated or missing weights; using %s instead.",
            model_name_or_path,
            alias,
        )
        return alias

    candidate = Path(model_name_or_path)
    if candidate.exists():
        return str(candidate.resolve())

    if _looks_like_local_path(model_name_or_path):
        known_checkpoints = _discover_local_checkpoints()
        suffix = ""
        if known_checkpoints:
            suffix = "\nCheckpoints locales disponibles:\n- " + "\n- ".join(known_checkpoints)
        raise FileNotFoundError(
            "No se encontro el checkpoint local indicado en "
            f"'{model_name_or_path}'.{suffix}"
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


def build_train_loader(
    dataset: LIARFakeNewsDataset,
    *,
    batch_size: int,
    sampling: str,
    seed: int,
) -> DataLoader:
    if sampling != "weighted":
        return DataLoader(dataset, batch_size=batch_size, shuffle=True)

    sample_weights = []
    total = sum(dataset.label_counts.values())
    for example in dataset.examples:
        count = max(dataset.label_counts.get(example.label, 0), 1)
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


def find_best_threshold(labels: list[int], probs_true: list[float]) -> tuple[float, float]:
    candidates = sorted({0.0, 1.0, 0.5, *[float(prob) for prob in probs_true]})
    best_threshold = 0.5
    best_score = -1.0
    for threshold in candidates:
        predictions = [1 if prob >= threshold else 0 for prob in probs_true]
        score = f1_score(labels, predictions, average="macro", zero_division=0)
        if score > best_score or (score == best_score and abs(threshold - 0.5) < abs(best_threshold - 0.5)):
            best_threshold = float(threshold)
            best_score = float(score)
    return best_threshold, best_score


def evaluate(model, dataloader, device: torch.device, *, threshold: float | None = None) -> dict:
    model.eval()
    labels: list[int] = []
    probs_true: list[float] = []

    with torch.no_grad():
        for batch in dataloader:
            labels.extend(batch["labels"].tolist())
            inputs = {
                key: value.to(device)
                for key, value in batch.items()
                if key != "labels"
            }
            logits = model(**inputs).logits
            probabilities = torch.softmax(logits, dim=-1)[:, 1].detach().cpu().tolist()
            probs_true.extend(float(probability) for probability in probabilities)

    selected_threshold, macro_f1 = find_best_threshold(labels, probs_true) if threshold is None else (
        float(threshold),
        f1_score(labels, [1 if prob >= threshold else 0 for prob in probs_true], average="macro", zero_division=0),
    )
    predictions = [1 if prob >= selected_threshold else 0 for prob in probs_true]
    report = classification_report(
        labels,
        predictions,
        target_names=list(FAKENEWS_LABELS),
        output_dict=True,
        zero_division=0,
    )

    return {
        "decision_threshold": float(selected_threshold),
        "macro_f1": float(macro_f1),
        "accuracy": float(accuracy_score(labels, predictions)),
        "confusion_matrix": confusion_matrix(labels, predictions).tolist(),
        "classification_report": report,
    }


def save_checkpoint(
    *,
    model,
    tokenizer,
    output_dir: str,
    serving_config: FakeNewsServingConfig,
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
    train_dataset = LIARFakeNewsDataset(
        args.train_path,
        tokenizer,
        max_length=args.max_length,
        label_strategy=args.label_strategy,
    )
    validation_dataset = LIARFakeNewsDataset(
        args.validation_path,
        tokenizer,
        max_length=args.max_length,
        label_strategy=args.label_strategy,
    )
    test_dataset = LIARFakeNewsDataset(
        args.test_path,
        tokenizer,
        max_length=args.max_length,
        label_strategy=args.label_strategy,
    )

    train_loader = build_train_loader(
        train_dataset,
        batch_size=args.batch_size,
        sampling=args.train_sampling,
        seed=args.seed,
    )
    validation_loader = DataLoader(validation_dataset, batch_size=args.batch_size)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size)

    logger.info(
        "Dataset sizes - train=%s validation=%s test=%s",
        len(train_dataset),
        len(validation_dataset),
        len(test_dataset),
    )
    logger.info(
        "Training label counts - False=%s True=%s skipped=%s",
        train_dataset.label_counts.get(0, 0),
        train_dataset.label_counts.get(1, 0),
        dict(train_dataset.skipped_labels),
    )
    logger.info("Training sampling strategy: %s", args.train_sampling)

    model = AutoModelForSequenceClassification.from_pretrained(
        model_source,
        num_labels=len(FAKENEWS_LABELS),
    ).to(device)
    if args.train_sampling == "weighted":
        criterion = nn.CrossEntropyLoss()
        logger.info("Class-weighted loss disabled because weighted sampling is active.")
    else:
        class_weights = compute_class_weights(train_dataset, device=device)
        criterion = nn.CrossEntropyLoss(weight=class_weights)

    optimizer = AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_steps * args.warmup_ratio),
        num_training_steps=total_steps,
    )

    best_state = None
    best_metrics = None
    best_threshold = 0.5
    best_score = -1.0
    best_epoch = 0
    epochs_without_improvement = 0
    history: list[dict] = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0

        for step, batch in enumerate(train_loader, start=1):
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
            "decision_threshold": round(validation_metrics["decision_threshold"], 6),
        }
        history.append(epoch_summary)
        logger.info("Epoch %s summary: %s", epoch, epoch_summary)

        if validation_metrics["macro_f1"] > best_score:
            best_score = validation_metrics["macro_f1"]
            best_threshold = validation_metrics["decision_threshold"]
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
    test_metrics = evaluate(model, test_loader, device, threshold=best_threshold)
    best_metrics["test"] = test_metrics

    logger.info("Best validation macro F1: %.4f at epoch %s", best_score, best_epoch)
    logger.info("Validation report:\n%s", json.dumps(best_metrics["validation"]["classification_report"], indent=2))
    logger.info("Test report:\n%s", json.dumps(best_metrics["test"]["classification_report"], indent=2))

    serving_config = FakeNewsServingConfig(
        label_names=FAKENEWS_LABELS,
        label_strategy=args.label_strategy,
        decision_threshold=best_threshold,
        max_length=args.max_length,
        model_name=serving_model_name,
        validation_metrics=best_metrics["validation"],
        test_metrics=best_metrics["test"],
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
