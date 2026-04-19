"""
Multi-task BERT model for simultaneous stance detection and fake news classification.

Architecture:
    Input → BERT Encoder → [CLS] → Dropout
                                      ↓
                        ┌─────────────┴─────────────┐
                        ↓                           ↓
                Stance Head (4)          FakeNews Head (6)
                {unrelated, discuss,     {pants-fire, false, barely-true,
                 agree, disagree}         half-true, mostly-true, true}

Supports uncertainty-weighted multi-task loss (Kendall et al., 2018):
    L_total = (1/2σ₁²)·L₁ + (1/2σ₂²)·L₂ + log(σ₁) + log(σ₂)
"""

import torch
import torch.nn as nn
from transformers import BertModel


class FocalLoss(nn.Module):
    """Focal Loss for handling class imbalance (Lin et al., 2017).

    Useful for FNC-1's skewed distribution:
    73% unrelated, 17% discuss, 7% agree, 1.7% disagree.
    """

    def __init__(self, gamma=2.0, weight=None, reduction="mean"):
        super().__init__()
        self.gamma = gamma
        self.weight = weight
        self.reduction = reduction

    def forward(self, inputs, targets):
        ce_loss = nn.functional.cross_entropy(
            inputs, targets, weight=self.weight, reduction="none"
        )
        pt = torch.exp(-ce_loss)
        focal_loss = ((1 - pt) ** self.gamma) * ce_loss
        if self.reduction == "mean":
            return focal_loss.mean()
        elif self.reduction == "sum":
            return focal_loss.sum()
        return focal_loss


class MultiTaskBert(nn.Module):
    """BERT multi-task model with two classification heads."""

    STANCE_LABELS = ["unrelated", "discuss", "agree", "disagree"]
    FAKENEWS_LABELS = [
        "pants-fire", "false", "barely-true",
        "half-true", "mostly-true", "true",
    ]

    def __init__(
        self,
        model_name="bert-base-uncased",
        num_stance_labels=4,
        num_fakenews_labels=6,
        dropout=0.1,
        use_uncertainty_weighting=True,
    ):
        super().__init__()
        self.bert = BertModel.from_pretrained(model_name)
        hidden_size = self.bert.config.hidden_size
        self.dropout = nn.Dropout(dropout)

        self.stance_head = nn.Sequential(
            nn.Linear(hidden_size, 256),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(256, num_stance_labels),
        )

        self.fakenews_head = nn.Sequential(
            nn.Linear(hidden_size, 256),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(256, num_fakenews_labels),
        )

        self.use_uncertainty_weighting = use_uncertainty_weighting
        if use_uncertainty_weighting:
            # Learnable log-variance parameters: s = log(σ²)
            self.log_var_stance = nn.Parameter(torch.zeros(1))
            self.log_var_fakenews = nn.Parameter(torch.zeros(1))

    def forward(self, input_ids, attention_mask, token_type_ids=None, task=None):
        outputs = self.bert(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
        )
        pooled = self.dropout(outputs.pooler_output)

        result = {}
        if task in ("stance", None):
            result["stance_logits"] = self.stance_head(pooled)
        if task in ("fakenews", None):
            result["fakenews_logits"] = self.fakenews_head(pooled)
        return result

    def compute_weighted_loss(self, raw_loss, task):
        """Apply uncertainty weighting: L = (1/2)·exp(-s)·L_raw + (1/2)·s"""
        if not self.use_uncertainty_weighting:
            return raw_loss
        log_var = (
            self.log_var_stance if task == "stance" else self.log_var_fakenews
        )
        return (0.5 * (torch.exp(-log_var) * raw_loss + log_var)).squeeze()
