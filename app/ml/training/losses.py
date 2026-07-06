from __future__ import annotations

import torch
import torch.nn as nn


class FocalLoss(nn.Module):
    """Focal loss for imbalanced classification datasets."""

    def __init__(self, gamma: float = 2.0, weight=None, reduction: str = "mean"):
        super().__init__()
        self.gamma = gamma
        self.weight = weight
        self.reduction = reduction

    def forward(self, inputs, targets):
        ce_loss = nn.functional.cross_entropy(
            inputs,
            targets,
            weight=self.weight,
            reduction="none",
        )
        pt = torch.exp(-ce_loss)
        focal_loss = ((1 - pt) ** self.gamma) * ce_loss
        if self.reduction == "mean":
            return focal_loss.mean()
        if self.reduction == "sum":
            return focal_loss.sum()
        return focal_loss
