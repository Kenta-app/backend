from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

import torch
from torch.utils.data import Dataset


FAKENEWS_LABELS = ("False", "True")

LIAR_BINARY_LABEL_STRATEGIES: dict[str, dict[str, int | None]] = {
    "strict": {
        "pants-fire": 0,
        "false": 0,
        "barely-true": 0,
        "half-true": None,
        "mostly-true": 1,
        "true": 1,
    },
    "relaxed": {
        "pants-fire": 0,
        "false": 0,
        "barely-true": 0,
        "half-true": 1,
        "mostly-true": 1,
        "true": 1,
    },
}


@dataclass(frozen=True)
class FakeNewsExample:
    text: str
    label: int


def available_label_strategies() -> tuple[str, ...]:
    return tuple(LIAR_BINARY_LABEL_STRATEGIES.keys())


def map_liar_label(label: str, strategy: str = "strict") -> int | None:
    try:
        return LIAR_BINARY_LABEL_STRATEGIES[strategy][label]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported LIAR label strategy '{strategy}'. "
            f"Expected one of: {', '.join(available_label_strategies())}."
        ) from exc


class LIARFakeNewsDataset(Dataset):
    """Binary fake-news dataset built from LIAR with configurable label mapping."""

    def __init__(self, data_path: str, tokenizer, *, max_length: int = 128, label_strategy: str = "strict"):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.label_strategy = label_strategy
        self.examples: list[FakeNewsExample] = []
        self.label_counts: Counter[int] = Counter()
        self.skipped_labels: Counter[str] = Counter()

        with open(data_path, "r", encoding="utf-8") as handle:
            reader = csv.reader(handle, delimiter="\t")
            for row in reader:
                if len(row) < 3:
                    continue

                mapped = map_liar_label(row[1].strip(), strategy=label_strategy)
                if mapped is None:
                    self.skipped_labels[row[1].strip()] += 1
                    continue

                text = row[2].strip()
                if not text:
                    continue

                self.examples.append(FakeNewsExample(text=text, label=mapped))
                self.label_counts[mapped] += 1

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        example = self.examples[index]
        encoded = self.tokenizer(
            example.text,
            max_length=self.max_length,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )
        batch = {
            key: value.squeeze(0)
            for key, value in encoded.items()
        }
        batch["labels"] = torch.tensor(example.label, dtype=torch.long)
        return batch


def count_labels(examples: Iterable[FakeNewsExample]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for example in examples:
        counts[example.label] += 1
    return counts
