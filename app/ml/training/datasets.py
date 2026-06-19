"""Dataset loader for dedicated FNC-1 stance detection."""

from __future__ import annotations

import csv

import torch
from torch.utils.data import Dataset


FNC_LABEL_MAP = {"unrelated": 0, "discuss": 1, "agree": 2, "disagree": 3}


def _build_model_inputs(encoded_batch):
    batch = {
        "input_ids": encoded_batch["input_ids"].squeeze(0),
        "attention_mask": encoded_batch["attention_mask"].squeeze(0),
    }
    if "token_type_ids" in encoded_batch:
        batch["token_type_ids"] = encoded_batch["token_type_ids"].squeeze(0)
    return batch


class FNCDataset(Dataset):
    """FNC-1 stance dataset: headline/body -> stance label."""

    def __init__(self, stances_path, bodies_path, tokenizer, max_length=512):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.samples = []

        bodies = {}
        with open(bodies_path, "r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                bodies[int(row["Body ID"])] = row["articleBody"]

        with open(stances_path, "r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                self.samples.append(
                    {
                        "headline": row["Headline"],
                        "body": bodies[int(row["Body ID"])],
                        "label": FNC_LABEL_MAP[row["Stance"]],
                    }
                )

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        sample = self.samples[idx]
        encoded = self.tokenizer(
            sample["headline"],
            sample["body"],
            max_length=self.max_length,
            truncation="only_second",
            padding="max_length",
            return_tensors="pt",
        )
        batch = _build_model_inputs(encoded)
        batch["labels"] = torch.tensor(sample["label"], dtype=torch.long)
        return batch
