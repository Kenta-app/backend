"""
Entry point for multi-task BERT training.

Usage:
    python -m app.ml.training.train
    python -m app.ml.training.train --epochs 10 --batch_size 8 --no_uncertainty
    python -m app.ml.training.train --model_name bert-base-multilingual-cased
"""

import argparse
import logging
import random

import numpy as np
import torch
from transformers import BertTokenizer

from app.ml.multitask_model import MultiTaskBert
from app.ml.training.config import TrainingConfig
from app.ml.training.datasets import create_dataloaders
from app.ml.training.trainer import MultiTaskTrainer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def main():
    parser = argparse.ArgumentParser(description="Multi-task BERT Training")
    parser.add_argument("--model_name", default="bert-base-uncased")
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--max_seq_length", type=int, default=512)
    parser.add_argument("--no_uncertainty", action="store_true")
    parser.add_argument("--no_focal_loss", action="store_true")
    parser.add_argument("--fnc_dir", default="data/fnc-1")
    parser.add_argument("--liar_dir", default="data/liar")
    parser.add_argument("--output_dir", default="output/multitask_bert")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    config = TrainingConfig(
        model_name=args.model_name,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        num_epochs=args.epochs,
        max_seq_length=args.max_seq_length,
        use_uncertainty_weighting=not args.no_uncertainty,
        use_focal_loss=not args.no_focal_loss,
        fnc_data_dir=args.fnc_dir,
        liar_data_dir=args.liar_dir,
        output_dir=args.output_dir,
        seed=args.seed,
    )

    set_seed(config.seed)
    logger.info(f"Config: {config}")

    tokenizer = BertTokenizer.from_pretrained(config.model_name)

    logger.info("Loading datasets...")
    fnc_train, fnc_val, liar_train, liar_val = create_dataloaders(config, tokenizer)
    logger.info(
        f"FNC-1  train={len(fnc_train.dataset):,}  val={len(fnc_val.dataset):,}"
    )
    logger.info(
        f"LIAR   train={len(liar_train.dataset):,}  val={len(liar_val.dataset):,}"
    )

    model = MultiTaskBert(
        model_name=config.model_name,
        num_stance_labels=config.num_stance_labels,
        num_fakenews_labels=config.num_fakenews_labels,
        dropout=config.dropout,
        use_uncertainty_weighting=config.use_uncertainty_weighting,
    )

    total_params = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info(f"Parameters: {total_params:,} total, {trainable:,} trainable")

    trainer = MultiTaskTrainer(model, config)
    history = trainer.train(fnc_train, fnc_val, liar_train, liar_val)

    # Save tokenizer alongside model for inference
    tokenizer.save_pretrained(f"{config.output_dir}/best_model")
    logger.info(f"Training complete. Best model at {config.output_dir}/best_model")


if __name__ == "__main__":
    main()
