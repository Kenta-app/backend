from __future__ import annotations

import json
import logging
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import joblib
import numpy as np
import torch
from sklearn.metrics.pairwise import paired_cosine_distances
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
    architecture: str = "single_transformer"

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
            architecture=str(payload.get("architecture", "single_transformer")),
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
            "architecture": self.architecture,
        }


class StanceClassifier:
    def __init__(self, model_dir: str, device: torch.device | None = None):
        self.model_dir = model_dir
        self.device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.tokenizer = None
        self.relevance_package = None
        self.relevance_base_model = None
        self.relevance_base_tokenizer = None
        self.loaded = False
        self.load_error: str | None = None
        self.serving_config = StanceServingConfig()

    @property
    def config_path(self) -> str:
        return os.path.join(self.model_dir, "serving_config.json")

    @property
    def checkpoint_exists(self) -> bool:
        if os.path.exists(os.path.join(self.model_dir, "config.json")):
            return True
        return all(
            os.path.exists(os.path.join(self.model_dir, relative_path))
            for relative_path in (
                "serving_config.json",
                "stage_a_relevance.joblib",
                os.path.join("stage_a_base_nli", "config.json"),
                os.path.join("stage_b_relation", "config.json"),
            )
        )

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
            if self.serving_config.architecture == "hierarchical_stance_v2":
                self._load_hierarchical()
            else:
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

        if self.serving_config.architecture == "hierarchical_stance_v2":
            return self._hierarchical_inference(headline, body)["probabilities"]

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
        if not self.loaded and not self.load():
            raise RuntimeError(self.load_error or "El clasificador dedicado no esta listo.")
        if self.serving_config.architecture == "hierarchical_stance_v2":
            return self._predict_hierarchical(headline, body)

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

    def _load_hierarchical(self) -> None:
        relevance_path = os.path.join(self.model_dir, "stage_a_relevance.joblib")
        base_dir = os.path.join(self.model_dir, "stage_a_base_nli")
        relation_dir = os.path.join(self.model_dir, "stage_b_relation")
        self.relevance_package = joblib.load(relevance_path)
        self.relevance_base_tokenizer = AutoTokenizer.from_pretrained(base_dir)
        self.relevance_base_model = AutoModelForSequenceClassification.from_pretrained(base_dir)
        self.relevance_base_model.to(self.device)
        self.relevance_base_model.eval()
        self.tokenizer = AutoTokenizer.from_pretrained(relation_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(relation_dir)
        self.model.to(self.device)
        self.model.eval()

    @staticmethod
    def _normalized_tokens(text: str) -> set[str]:
        value = unicodedata.normalize("NFKD", text or "").casefold()
        value = "".join(char for char in value if unicodedata.category(char) != "Mn")
        return {token for token in re.findall(r"\b\w+\b", value) if len(token) > 2}

    @staticmethod
    def _numbers(text: str) -> set[str]:
        return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b", text or ""))

    def _stage_a_features(self, claim: str, context: str, nli_probabilities: np.ndarray) -> np.ndarray:
        claim_tokens = self._normalized_tokens(claim)
        context_tokens = self._normalized_tokens(context)
        overlap = len(claim_tokens & context_tokens)
        union = len(claim_tokens | context_tokens)
        claim_numbers = self._numbers(claim)
        context_numbers = self._numbers(context)
        ordered = np.sort(nli_probabilities)
        entropy = -float(sum(value * math.log(max(float(value), 1e-12)) for value in nli_probabilities))
        scalar = np.asarray([[
            overlap / max(1, union),
            overlap / max(1, len(claim_tokens)),
            overlap / max(1, len(context_tokens)),
            min(len(claim_tokens), len(context_tokens)) / max(1, max(len(claim_tokens), len(context_tokens))),
            len(claim_numbers & context_numbers) / max(1, len(claim_numbers)),
            1.0 if claim_numbers and claim_numbers <= context_numbers else 0.0,
            float(nli_probabilities[0]),
            float(nli_probabilities[1]),
            float(nli_probabilities[2]),
            entropy,
            float(ordered[-1]),
            float(ordered[-1] - ordered[-2]),
        ]], dtype=float)
        word = self.relevance_package["word_vectorizer"]
        char = self.relevance_package["char_vectorizer"]
        word_cosine = 1.0 - paired_cosine_distances(word.transform([claim]), word.transform([context]))
        char_cosine = 1.0 - paired_cosine_distances(char.transform([claim]), char.transform([context]))
        return np.hstack([scalar, word_cosine.reshape(-1, 1), char_cosine.reshape(-1, 1)])

    def _model_probabilities(self, model, tokenizer, context: str, claim: str) -> torch.Tensor:
        encoded = tokenizer(
            context,
            claim,
            return_tensors="pt",
            truncation="only_first",
            max_length=self.serving_config.max_length,
            padding=True,
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}
        with torch.no_grad():
            return torch.softmax(model(**encoded).logits, dim=-1)[0].detach().cpu()

    def _hierarchical_inference(self, claim: str, context: str) -> dict[str, Any]:
        base_probabilities = self._model_probabilities(
            self.relevance_base_model, self.relevance_base_tokenizer, context, claim
        )
        features = self._stage_a_features(claim, context, base_probabilities.numpy())
        related_probability = float(
            self.relevance_package["classifier"].predict_proba(features)[0, 1]
        )
        relation_probabilities = self._model_probabilities(self.model, self.tokenizer, context, claim)
        combined = torch.tensor([
            1.0 - related_probability,
            related_probability * float(relation_probabilities[1]),
            related_probability * float(relation_probabilities[2]),
            related_probability * float(relation_probabilities[0]),
        ], dtype=torch.float32)
        return {
            "probabilities": combined,
            "related_probability": related_probability,
            "relation_probabilities": relation_probabilities,
        }

    def _predict_hierarchical(self, claim: str, context: str) -> dict[str, Any]:
        inference = self._hierarchical_inference(claim, context)
        probabilities = inference["probabilities"]
        relation_probabilities = inference["relation_probabilities"]
        related_probability = inference["related_probability"]
        threshold = float(self.relevance_package.get("threshold", self.serving_config.decision_threshold))
        relation_labels = ("disagree", "discuss", "agree")
        if related_probability < threshold:
            label = "unrelated"
            decision_path = "stage_a_unrelated"
        else:
            label = relation_labels[int(relation_probabilities.argmax().item())]
            decision_path = "stage_a_related_then_stage_b"
        index = self.serving_config.label_names.index(label)
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
            "label": label,
            "confidence": round(float(probabilities[index].item()), 4),
            "probabilities": probabilities_map,
            "ranking": ranking,
            "related_probability": round(related_probability, 4),
            "stage_b_probabilities": {
                label_name: round(float(relation_probabilities[idx].item()), 4)
                for idx, label_name in enumerate(relation_labels)
            },
            "decision_threshold": round(threshold, 4),
            "decision_path": decision_path,
            "label_strategy": "hierarchical_gate",
            "source": "hierarchical_stance_v2",
        }

    def _load_serving_config(self) -> StanceServingConfig:
        if not os.path.exists(self.config_path):
            return StanceServingConfig()

        with open(self.config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return StanceServingConfig.from_dict(payload)
