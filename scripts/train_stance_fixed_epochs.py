"""Train the frozen final stance model on all development data for fixed epochs."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Direct file execution places the scripts directory on sys.path. Add the
# repository root so the local app package resolves consistently.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import torch
from torch.optim import AdamW
from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

from app.ml.stance_classifier import StanceServingConfig
from app.ml.training.datasets import FNCDataset
from app.ml.training.losses import FocalLoss
from app.ml.training.train_stance import (
    STANCE_LABELS,
    autocast_context,
    build_train_loader,
    compute_class_weights,
    compute_label_counts,
    create_grad_scaler,
    resolve_model_source,
    resolve_serving_model_name,
    save_checkpoint,
    set_seed,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_name", default="bert-base-multilingual-cased")
    parser.add_argument("--train_stances", required=True)
    parser.add_argument("--train_bodies", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--max_length", type=int, default=192)
    parser.add_argument("--weight_decay", type=float, default=0.01)
    parser.add_argument("--warmup_ratio", type=float, default=0.1)
    parser.add_argument("--max_grad_norm", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    set_seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    use_amp = device.type == "cuda"
    scaler = create_grad_scaler(use_amp)
    model_source = resolve_model_source(args.model_name)
    tokenizer = AutoTokenizer.from_pretrained(model_source)
    dataset = FNCDataset(args.train_stances, args.train_bodies, tokenizer, max_length=args.max_length)
    loader = build_train_loader(dataset, batch_size=args.batch_size, sampling="shuffle", seed=args.seed)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_source, num_labels=len(STANCE_LABELS),
    ).to(device)
    criterion = FocalLoss(gamma=2.0, weight=compute_class_weights(dataset, device=device))
    optimizer = AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    total_steps = len(loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_steps * args.warmup_ratio),
        num_training_steps=total_steps,
    )
    history = []
    for epoch in range(1, args.epochs + 1):
        model.train()
        running_loss = 0.0
        for batch in loader:
            optimizer.zero_grad()
            labels = batch["labels"].to(device)
            inputs = {key: value.to(device) for key, value in batch.items() if key != "labels"}
            if use_amp:
                with autocast_context(use_amp):
                    loss = criterion(model(**inputs).logits, labels)
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                scaler.step(optimizer)
                scaler.update()
            else:
                loss = criterion(model(**inputs).logits, labels)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_grad_norm)
                optimizer.step()
            scheduler.step()
            running_loss += loss.item()
        history.append({"epoch": epoch, "train_loss": round(running_loss / max(1, len(loader)), 6)})
        print(json.dumps(history[-1]))

    serving_config = StanceServingConfig(
        label_names=tuple(STANCE_LABELS),
        label_strategy="strict",
        decision_threshold=0.5,
        max_length=args.max_length,
        model_name=resolve_serving_model_name(model_source),
        validation_metrics=None,
        test_metrics=None,
    )
    save_checkpoint(
        model=model,
        tokenizer=tokenizer,
        output_dir=args.output_dir,
        serving_config=serving_config,
        metrics={},
        history=history,
    )
    run_manifest = {
        "status": "FINAL_MODEL_TRAINED_NOT_YET_PROSPECTIVELY_EVALUATED",
        "model_family": "bert-base-multilingual-cased",
        "representation": "retrieved_evidence",
        "records": len(dataset),
        "label_counts_by_index": compute_label_counts(dataset),
        "fixed_epochs": args.epochs,
        "seed": args.seed,
        "batch_size": args.batch_size,
        "learning_rate": args.lr,
        "max_length": args.max_length,
        "loss": "focal_gamma_2_with_class_weights",
        "selection_basis": "Median best epoch across retrieved_evidence development seeds 42, 123, 2026 (4, 4, 5).",
        "prospective_evaluation_used": False,
    }
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    (Path(args.output_dir) / "final_training_manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )


if __name__ == "__main__":
    main()
