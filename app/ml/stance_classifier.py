from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StanceServingConfig:
    label_names: tuple[str, ...] = ("unrelated", "discuss", "agree", "disagree")
    label_strategy: str = "strict"
    decision_threshold: float = 0.5
    max_length: int = 512
    model_name: str | None = None
    validation_metrics: dict[str, Any] | None = None
    test_metrics: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StanceServingConfig":
        label_names = tuple(payload.get("label_names", cls.label_names))
        if len(label_names) < 2:
            label_names = ("unrelated", "discuss", "agree", "disagree")
        return cls(
            label_names=tuple(str(x) for x in label_names),
            label_strategy=str(payload.get("label_strategy", "strict")),
            decision_threshold=float(payload.get("decision_threshold", 0.5)),
            max_length=int(payload.get("max_length", 512)),
            model_name=payload.get("model_name"),
            validation_metrics=payload.get("validation_metrics"),
            test_metrics=payload.get("test_metrics"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label_names": list(self.label_names),
            "label_strategy": self.label_strategy,
            "decision_threshold": self.decision_threshold,
            "max_length": self.max_length,
            "model_name": self.model_name,
            "validation_metrics": self.validation_metrics,
            "test_metrics": self.test_metrics,
        }


class StanceClassifier:
    def __init__(self, model_dir: str, device: torch.device | None = None):
        self.model_dir = model_dir
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.tokenizer = None
        self.loaded = False
        self.load_error: str | None = None
        self.serving_config = StanceServingConfig()

    @property
    def config_path(self) -> str:
        return os.path.join(self.model_dir, "serving_config.json")

    @property
    def checkpoint_exists(self) -> bool:
        return os.path.exists(os.path.join(self.model_dir, "config.json"))

    @property
    def model_name(self) -> str:
        return self.serving_config.model_name or os.path.basename(self.model_dir.rstrip("\\/"))

    def load(self) -> bool:
        if self.loaded:
            return True

        if not self.checkpoint_exists:
            self.load_error = (
                "No se encontro el clasificador dedicado de stance en "
                f"'{self.model_dir}'."
            )
            return False

        try:
            self.serving_config = self._load_serving_config()
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_dir)
            self.model.to(self.device)
            self.model.eval()
            self.loaded = True
            self.load_error = None
            logger.info("Dedicated stance classifier loaded from %s", self.model_dir)
            return True
        except Exception as exc:
            self.load_error = (
                "No se pudo cargar el clasificador dedicado de stance. "
                f"Detalle: {exc}"
            )
            logger.exception("Error loading dedicated stance classifier")
            return False

    def predict_proba(self, headline: str, body: str) -> torch.Tensor:
        if not self.loaded and not self.load():
            raise RuntimeError(self.load_error or "El clasificador dedicado no esta listo.")

        encoded = self.tokenizer(
            headline,
            body,
            return_tensors="pt",
            truncation="only_second",
            max_length=self.serving_config.max_length,
            padding=True,
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}

        with torch.no_grad():
            logits = self.model(**encoded).logits
            probabilities = torch.softmax(logits, dim=-1)[0].detach().cpu()
        return probabilities

    def predict(self, headline: str, body: str) -> dict[str, Any]:
        probabilities = self.predict_proba(headline, body)
        threshold = self.serving_config.decision_threshold
        predicted_index = int(probabilities.argmax().item())
        probabilities_map = {
            label_name: round(float(score), 4)
            for label_name, score in zip(self.serving_config.label_names, probabilities.tolist())
        }
        ranking = [
            {"label": label_name, "score": round(float(probabilities[idx].item()), 4)}
            for idx, label_name in sorted(
                enumerate(self.serving_config.label_names),
                key=lambda item: probabilities[item[0]].item(),
                reverse=True,
            )
        ]

        return {
            "label": self.serving_config.label_names[predicted_index],
            "confidence": round(float(probabilities[predicted_index].item()), 4),
            "probabilities": probabilities_map,
            "ranking": ranking,
            "decision_threshold": round(float(threshold), 4),
            "label_strategy": self.serving_config.label_strategy,
            "source": "dedicated_stance_classifier",
        }

    def _load_serving_config(self) -> StanceServingConfig:
        if not os.path.exists(self.config_path):
            return StanceServingConfig()

        with open(self.config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return StanceServingConfig.from_dict(payload)
