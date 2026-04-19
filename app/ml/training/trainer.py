"""
Multi-task trainer with alternating batch strategy and uncertainty-weighted loss.

Strategy:
    1. Alternate batches: FNC-1 (stance) → LIAR (fakenews) → FNC-1 → ...
    2. Each batch only activates its corresponding task head (implicit loss masking)
    3. Shared BERT encoder receives gradients from both tasks
    4. Uncertainty weighting auto-balances task contributions
"""

import logging
import os

import numpy as np
import torch
import torch.nn as nn
from sklearn.metrics import accuracy_score, classification_report, f1_score
from torch.optim import AdamW
from transformers import get_linear_schedule_with_warmup

from app.ml.multitask_model import FocalLoss

logger = logging.getLogger(__name__)


class MultiTaskTrainer:
    def __init__(self, model, config):
        self.config = config
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = model.to(self.device)
        logger.info(f"Device: {self.device}")

        if config.use_focal_loss:
            self.stance_criterion = FocalLoss(gamma=config.focal_gamma)
            self.fakenews_criterion = FocalLoss(gamma=config.focal_gamma)
        else:
            self.stance_criterion = nn.CrossEntropyLoss()
            self.fakenews_criterion = nn.CrossEntropyLoss()

    def _build_optimizer_and_scheduler(self, total_steps):
        """Differential learning rates: lower for BERT, higher for task heads."""
        bert_params = list(self.model.bert.parameters())
        head_params = list(self.model.stance_head.parameters()) + list(
            self.model.fakenews_head.parameters()
        )

        param_groups = [
            {"params": bert_params, "lr": self.config.learning_rate},
            {
                "params": head_params,
                "lr": self.config.learning_rate * self.config.head_lr_multiplier,
            },
        ]

        if self.model.use_uncertainty_weighting:
            param_groups.append(
                {
                    "params": [
                        self.model.log_var_stance,
                        self.model.log_var_fakenews,
                    ],
                    "lr": self.config.learning_rate * self.config.head_lr_multiplier,
                }
            )

        optimizer = AdamW(param_groups, weight_decay=self.config.weight_decay)
        scheduler = get_linear_schedule_with_warmup(
            optimizer,
            num_warmup_steps=int(total_steps * self.config.warmup_ratio),
            num_training_steps=total_steps,
        )
        return optimizer, scheduler

    def train(self, fnc_train_loader, fnc_val_loader, liar_train_loader, liar_val_loader):
        steps_per_epoch = len(fnc_train_loader) + len(liar_train_loader)
        total_steps = steps_per_epoch * self.config.num_epochs

        optimizer, scheduler = self._build_optimizer_and_scheduler(total_steps)

        best_score = 0.0
        history = []

        for epoch in range(1, self.config.num_epochs + 1):
            logger.info(f"{'='*20} Epoch {epoch}/{self.config.num_epochs} {'='*20}")

            train_metrics = self._train_epoch(
                fnc_train_loader, liar_train_loader, optimizer, scheduler
            )
            logger.info(
                f"Train - Stance Loss: {train_metrics['stance_loss']:.4f}, "
                f"FakeNews Loss: {train_metrics['fakenews_loss']:.4f}"
            )

            if self.model.use_uncertainty_weighting:
                s2_stance = torch.exp(self.model.log_var_stance).item()
                s2_fakenews = torch.exp(self.model.log_var_fakenews).item()
                logger.info(f"  σ²_stance={s2_stance:.4f}, σ²_fakenews={s2_fakenews:.4f}")

            if epoch % self.config.eval_epochs == 0:
                val_metrics = self.evaluate(fnc_val_loader, liar_val_loader)
                logger.info(
                    f"Val - Stance F1: {val_metrics['stance_f1']:.4f}, "
                    f"FakeNews F1: {val_metrics['fakenews_f1']:.4f}"
                )

                combined = (val_metrics["stance_f1"] + val_metrics["fakenews_f1"]) / 2
                if combined > best_score:
                    best_score = combined
                    self._save_checkpoint("best_model")
                    logger.info(f"  >> New best model! Combined F1: {combined:.4f}")

                train_metrics.update(val_metrics)

            train_metrics["epoch"] = epoch
            history.append(train_metrics)

        self._save_checkpoint("final_model")
        return history

    def _train_epoch(self, fnc_loader, liar_loader, optimizer, scheduler):
        self.model.train()
        fnc_iter = iter(fnc_loader)
        liar_iter = iter(liar_loader)

        total_stance_loss = 0.0
        total_fakenews_loss = 0.0
        stance_steps = 0
        fakenews_steps = 0
        global_step = 0

        fnc_done = False
        liar_done = False

        while not (fnc_done and liar_done):
            # --- Stance batch (FNC-1) ---
            if not fnc_done:
                try:
                    batch = next(fnc_iter)
                    loss = self._train_step(batch, "stance", optimizer, scheduler)
                    total_stance_loss += loss
                    stance_steps += 1
                    global_step += 1
                except StopIteration:
                    fnc_done = True

            # --- FakeNews batch (LIAR) ---
            if not liar_done:
                try:
                    batch = next(liar_iter)
                    loss = self._train_step(batch, "fakenews", optimizer, scheduler)
                    total_fakenews_loss += loss
                    fakenews_steps += 1
                    global_step += 1
                except StopIteration:
                    liar_done = True

            if global_step > 0 and global_step % self.config.log_steps == 0:
                avg_s = total_stance_loss / max(stance_steps, 1)
                avg_f = total_fakenews_loss / max(fakenews_steps, 1)
                lr = scheduler.get_last_lr()[0]
                logger.info(
                    f"  Step {global_step} - "
                    f"Stance: {avg_s:.4f}, FakeNews: {avg_f:.4f}, LR: {lr:.2e}"
                )

        return {
            "stance_loss": total_stance_loss / max(stance_steps, 1),
            "fakenews_loss": total_fakenews_loss / max(fakenews_steps, 1),
        }

    def _train_step(self, batch, task, optimizer, scheduler):
        optimizer.zero_grad()

        input_ids = batch["input_ids"].to(self.device)
        attention_mask = batch["attention_mask"].to(self.device)
        token_type_ids = batch["token_type_ids"].to(self.device)
        labels = batch["labels"].to(self.device)

        outputs = self.model(input_ids, attention_mask, token_type_ids, task=task)

        if task == "stance":
            raw_loss = self.stance_criterion(outputs["stance_logits"], labels)
        else:
            raw_loss = self.fakenews_criterion(outputs["fakenews_logits"], labels)

        loss = self.model.compute_weighted_loss(raw_loss, task)

        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            self.model.parameters(), self.config.max_grad_norm
        )
        optimizer.step()
        scheduler.step()

        return raw_loss.item()

    @torch.no_grad()
    def evaluate(self, fnc_val_loader, liar_val_loader):
        self.model.eval()

        # --- Stance ---
        s_preds, s_labels = [], []
        for batch in fnc_val_loader:
            outputs = self.model(
                batch["input_ids"].to(self.device),
                batch["attention_mask"].to(self.device),
                batch["token_type_ids"].to(self.device),
                task="stance",
            )
            s_preds.extend(outputs["stance_logits"].argmax(dim=-1).cpu().numpy())
            s_labels.extend(batch["labels"].numpy())

        # --- FakeNews ---
        f_preds, f_labels = [], []
        for batch in liar_val_loader:
            outputs = self.model(
                batch["input_ids"].to(self.device),
                batch["attention_mask"].to(self.device),
                batch["token_type_ids"].to(self.device),
                task="fakenews",
            )
            f_preds.extend(outputs["fakenews_logits"].argmax(dim=-1).cpu().numpy())
            f_labels.extend(batch["labels"].numpy())

        self.model.train()

        stance_f1 = f1_score(s_labels, s_preds, average="macro")
        fakenews_f1 = f1_score(f_labels, f_preds, average="macro")

        logger.info(
            "Stance Classification Report:\n"
            + classification_report(
                s_labels, s_preds,
                target_names=self.model.STANCE_LABELS,
                zero_division=0,
            )
        )
        logger.info(
            "FakeNews Classification Report:\n"
            + classification_report(
                f_labels, f_preds,
                target_names=self.model.FAKENEWS_LABELS,
                zero_division=0,
            )
        )

        return {
            "stance_f1": stance_f1,
            "stance_acc": accuracy_score(s_labels, s_preds),
            "fakenews_f1": fakenews_f1,
            "fakenews_acc": accuracy_score(f_labels, f_preds),
        }

    def _save_checkpoint(self, name):
        path = os.path.join(self.config.output_dir, name)
        os.makedirs(path, exist_ok=True)
        torch.save(self.model.state_dict(), os.path.join(path, "model.pt"))
        self.model.bert.config.save_pretrained(path)
        logger.info(f"Checkpoint saved to {path}")
