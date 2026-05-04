"""
Dataset loaders for FNC-1 (stance detection) and LIAR (fake news detection).

FNC-1: (headline, body) → stance ∈ {unrelated, discuss, agree, disagree}
LIAR:  statement → label ∈ {pants-fire, false, barely-true, half-true, mostly-true, true}
"""

import csv
import os

import torch
from torch.utils.data import DataLoader, Dataset

FNC_LABEL_MAP = {"unrelated": 0, "discuss": 1, "agree": 2, "disagree": 3}

# Binary classification: 0=False (fake), 1=True (real)
LIAR_LABEL_MAP = {
    "pants-fire": 0,  # False
    "false": 0,       # False
    "barely-true": 0, # False
    "half-true": 1,   # True
    "mostly-true": 1, # True
    "true": 1,        # True
}


def _build_model_inputs(encoded_batch):
    batch = {
        "input_ids": encoded_batch["input_ids"].squeeze(0),
        "attention_mask": encoded_batch["attention_mask"].squeeze(0),
    }
    if "token_type_ids" in encoded_batch:
        batch["token_type_ids"] = encoded_batch["token_type_ids"].squeeze(0)
    return batch


class FNCDataset(Dataset):
    """FNC-1 Stance Detection dataset.

    Input format: headline [SEP] body (truncated via `only_second`).
    """

    def __init__(self, stances_path, bodies_path, tokenizer, max_length=512):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.samples = []

        bodies = {}
        with open(bodies_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                bodies[int(row["Body ID"])] = row["articleBody"]

        with open(stances_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
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
        s = self.samples[idx]
        enc = self.tokenizer(
            s["headline"],
            s["body"],
            max_length=self.max_length,
            truncation="only_second",  # Keep full headline, truncate body
            padding="max_length",
            return_tensors="pt",
        )
        batch = _build_model_inputs(enc)
        batch["labels"] = torch.tensor(s["label"], dtype=torch.long)
        return batch


class LIARDataset(Dataset):
    """LIAR Fake News Detection dataset.

    Input format: single statement.
    TSV columns: id, label, statement, subject, speaker, job, state, party, 
                 barely_true, false, half_true, mostly_true, pants_fire, context
    """

    def __init__(self, data_path, tokenizer, max_length=128):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.samples = []

        with open(data_path, "r", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="\t")
            for row in reader:
                if len(row) < 3:
                    continue
                label_str = row[1].strip()
                statement = row[2].strip()
                if label_str in LIAR_LABEL_MAP:
                    self.samples.append(
                        {"statement": statement, "label": LIAR_LABEL_MAP[label_str]}
                    )

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        s = self.samples[idx]
        enc = self.tokenizer(
            s["statement"],
            max_length=self.max_length,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )
        batch = _build_model_inputs(enc)
        batch["labels"] = torch.tensor(s["label"], dtype=torch.long)
        return batch


def create_dataloaders(config, tokenizer):
    """Create train/val DataLoaders for both datasets."""
    fnc_dir = config.fnc_data_dir
    liar_dir = config.liar_data_dir

    fnc_train = FNCDataset(
        os.path.join(fnc_dir, "train_stances.csv"),
        os.path.join(fnc_dir, "train_bodies.csv"),
        tokenizer,
        config.max_seq_length,
    )
    fnc_val = FNCDataset(
        os.path.join(fnc_dir, "competition_test_stances.csv"),
        os.path.join(fnc_dir, "competition_test_bodies.csv"),
        tokenizer,
        config.max_seq_length,
    )
    liar_train = LIARDataset(
        os.path.join(liar_dir, "train.tsv"),
        tokenizer,
        config.max_seq_length_liar,
    )
    liar_val = LIARDataset(
        os.path.join(liar_dir, "validation.tsv"),
        tokenizer,
        config.max_seq_length_liar,
    )

    fnc_train_loader = DataLoader(
        fnc_train, batch_size=config.batch_size, shuffle=True
    )
    fnc_val_loader = DataLoader(fnc_val, batch_size=config.batch_size)
    liar_train_loader = DataLoader(
        liar_train, batch_size=config.batch_size, shuffle=True
    )
    liar_val_loader = DataLoader(liar_val, batch_size=config.batch_size)

    return fnc_train_loader, fnc_val_loader, liar_train_loader, liar_val_loader
