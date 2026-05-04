import logging
import os
from threading import Lock
from typing import Any

import torch
from transformers import AutoTokenizer

from app.ml.fakenews_classifier import FakeNewsClassifier
from app.ml.multitask_model import MultiTaskBert
from app.ml.summarizer import summarizer_service

logger = logging.getLogger(__name__)


class ModelNotReadyError(RuntimeError):
    """Raised when the fine-tuned classifier checkpoint is not available."""


class NewsAnalysisPipeline:
    STANCE_METADATA = {
        "unrelated": {
            "display": "sin relacion",
            "description": "El texto no toma postura frente al titular o tema principal.",
        },
        "discuss": {
            "display": "discusion",
            "description": "El texto discute el tema sin posicion clara a favor o en contra.",
        },
        "agree": {
            "display": "a favor",
            "description": "El contenido apoya o refuerza la afirmacion principal.",
        },
        "disagree": {
            "display": "en contra",
            "description": "El contenido contradice o rechaza la afirmacion principal.",
        },
    }

    VERACITY_METADATA = {
        # Binary classification: 0 = False (fake), 1 = True (real)
        "False": {
            "display": "falso",
            "bucket": "fake",
            "is_fake": True,
        },
        "True": {
            "display": "verdadero",
            "bucket": "real",
            "is_fake": False,
        },
    }

    def __init__(self):
        self.model_dir = os.getenv(
            "MULTITASK_MODEL_DIR",
            os.path.join("output", "multitask_bert", "best_model"),
        )
        self.fake_news_model_dir = os.getenv(
            "FAKENEWS_MODEL_DIR",
            os.path.join("output", "fakenews_bert", "best_model"),
        )
        self.base_model_name = os.getenv("MULTITASK_BASE_MODEL", "bert-base-uncased")
        self.max_seq_length = int(os.getenv("MULTITASK_MAX_SEQ_LENGTH", "512"))
        self.max_seq_length_liar = int(
            os.getenv("MULTITASK_MAX_SEQ_LENGTH_LIAR", "128")
        )
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._lock = Lock()
        self._loaded = False
        self.model = None
        self.tokenizer = None
        self.load_error = None
        self.fake_news_classifier = FakeNewsClassifier(
            model_dir=self.fake_news_model_dir,
            device=self.device,
        )

    @property
    def checkpoint_path(self) -> str:
        return os.path.join(self.model_dir, "model.pt")

    def load(self) -> bool:
        if self._loaded:
            return True

        with self._lock:
            if self._loaded:
                return True

            if not os.path.exists(self.checkpoint_path):
                self.load_error = (
                    "No se encontro el checkpoint entrenado del modelo multitarea en "
                    f"'{self.checkpoint_path}'. Ejecuta el training y guarda best_model."
                )
                logger.warning(self.load_error)
                return False

            tokenizer_source = (
                self.model_dir
                if os.path.exists(os.path.join(self.model_dir, "tokenizer_config.json"))
                else self.base_model_name
            )

            try:
                self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_source)
                if os.path.exists(os.path.join(self.model_dir, "config.json")):
                    self.model = MultiTaskBert(
                        encoder_config_path=self.model_dir,
                        load_pretrained_encoder=False,
                    )
                else:
                    self.model = MultiTaskBert(model_name=self.base_model_name)
                state_dict = torch.load(self.checkpoint_path, map_location=self.device)
                self.model.load_state_dict(state_dict)
                self.model.to(self.device)
                self.model.eval()
                self._loaded = True
                self.load_error = None
                self.base_model_name = (
                    getattr(self.model.encoder.config, "_name_or_path", None)
                    or getattr(self.model.encoder.config, "model_type", self.base_model_name)
                )
                self.fake_news_classifier.load()
                logger.info("Multi-task classifier loaded from %s", self.checkpoint_path)
                return True
            except Exception as exc:
                self.load_error = (
                    "No se pudo cargar el modelo multitarea. Verifica que el checkpoint "
                    "incluya su config y tokenizer, o configura MULTITASK_BASE_MODEL si "
                    "estas cargando un checkpoint antiguo. "
                    f"Detalle: {exc}"
                )
                logger.exception("Error loading multi-task classifier")
                return False

    def warm_up(self, include_summarizer: bool = False) -> dict[str, Any]:
        classifier_ready = self.load()
        if include_summarizer:
            summarizer_service.load()
        return self.get_status(classifier_ready=classifier_ready)

    def get_status(self, classifier_ready: bool | None = None) -> dict[str, Any]:
        if classifier_ready is None:
            classifier_ready = self._loaded or os.path.exists(self.checkpoint_path)

        return {
            "classifier_ready": bool(classifier_ready and self._loaded),
            "classifier_checkpoint_exists": os.path.exists(self.checkpoint_path),
            "classifier_checkpoint_path": self.checkpoint_path,
            "classifier_load_error": self.load_error,
            "classifier_base_model": self.base_model_name,
            "fake_news_classifier_ready": self.fake_news_classifier.loaded,
            "fake_news_classifier_checkpoint_exists": self.fake_news_classifier.checkpoint_exists,
            "fake_news_classifier_checkpoint_path": self.fake_news_model_dir,
            "fake_news_classifier_load_error": self.fake_news_classifier.load_error,
            "fake_news_classifier_source": (
                self.fake_news_classifier.model_name
                if self.fake_news_classifier.loaded
                else "multitask_fallback"
            ),
            "summarizer_loaded": summarizer_service.loaded,
            "summarizer_model_name": summarizer_service.model_name,
            "summarizer_load_error": summarizer_service.load_error,
        }

    def analyze_news(
        self,
        *,
        title: str | None = None,
        content: str | None = None,
        text: str | None = None,
        include_summary: bool = True,
        force_summary: bool = False,
        allow_partial: bool = False,
    ) -> dict[str, Any]:
        normalized_title = self._normalize_text(title)
        normalized_content = self._normalize_text(content)
        normalized_text = self._normalize_text(text)

        article_text = normalized_content or normalized_text or normalized_title
        if not article_text:
            raise ValueError("Se requiere al menos un campo con texto para analizar.")

        headline = normalized_title or self._infer_headline(article_text)
        body = normalized_content or normalized_text or article_text
        warnings: list[str] = []

        classifier_ready = self.load()
        stance_result = None
        fake_news_result = None

        if classifier_ready:
            stance_result = self._predict_stance(headline, body)
            fake_news_result = self._predict_fake_news(article_text)
        elif not allow_partial:
            raise ModelNotReadyError(self.load_error or "El clasificador no esta listo.")
        else:
            warnings.append(self.load_error or "El clasificador multitarea no esta listo.")

        summary_text = None
        if include_summary and (force_summary or summarizer_service.should_summarize(body)):
            try:
                summary_text = summarizer_service.summarize(body)
            except Exception as exc:
                logger.exception("Error generating summary")
                warnings.append(f"No se pudo generar el resumen: {exc}")

        return {
            "input": {
                "title": normalized_title,
                "content_length": len(body),
                "summary_requested": include_summary,
                "summary_generated": bool(summary_text),
            },
            "fake_news": fake_news_result,
            "stance": stance_result,
            "summary": summary_text,
            "models": {
                "classifier": "MultiTaskBert",
                "classifier_checkpoint": self.checkpoint_path,
                "classifier_base_model": self.base_model_name,
                "fake_news_classifier": (
                    self.fake_news_classifier.model_name
                    if self.fake_news_classifier.loaded
                    else "multitask_fallback"
                ),
                "fake_news_classifier_checkpoint": (
                    self.fake_news_model_dir
                    if self.fake_news_classifier.loaded
                    else self.checkpoint_path
                ),
                "summarizer": summarizer_service.model_name,
            },
            "warnings": warnings,
        }

    def _predict_stance(self, headline: str, body: str) -> dict[str, Any]:
        encoded = self.tokenizer(
            headline,
            body,
            return_tensors="pt",
            truncation="only_second",
            max_length=self.max_seq_length,
            padding=True,
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}

        with torch.no_grad():
            outputs = self.model(task="stance", **encoded)
            probabilities = torch.softmax(outputs["stance_logits"], dim=-1)[0].cpu()

        return self._format_prediction(
            label_names=self.model.STANCE_LABELS,
            predicted_index=int(probabilities.argmax().item()),
            probabilities=probabilities,
            metadata=self.STANCE_METADATA,
        )

    def _predict_fake_news(self, text: str) -> dict[str, Any]:
        if self.fake_news_classifier.loaded:
            prediction = self.fake_news_classifier.predict(text)
            selected = self.VERACITY_METADATA[prediction["label"]]
            prediction["display_label"] = selected["display"]
            for item in prediction.get("ranking", []):
                item["display"] = self.VERACITY_METADATA[item["label"]]["display"]
            prediction["bucket"] = selected["bucket"]
            prediction["is_fake"] = selected["is_fake"]
            return prediction

        return self._predict_fake_news_multitask(text)

    def _predict_fake_news_multitask(self, text: str) -> dict[str, Any]:
        encoded = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=self.max_seq_length_liar,
            padding=True,
        )
        encoded = {key: value.to(self.device) for key, value in encoded.items()}

        with torch.no_grad():
            outputs = self.model(task="fakenews", **encoded)
            probabilities = torch.softmax(outputs["fakenews_logits"], dim=-1)[0].cpu()

        prediction = self._format_prediction(
            label_names=self.model.FAKENEWS_LABELS,
            predicted_index=int(probabilities.argmax().item()),
            probabilities=probabilities,
            metadata=self.VERACITY_METADATA,
        )
        selected = self.VERACITY_METADATA[prediction["label"]]
        prediction["bucket"] = selected["bucket"]
        prediction["is_fake"] = selected["is_fake"]
        prediction["source"] = "multitask_fallback"
        return prediction

    def _format_prediction(
        self,
        *,
        label_names: list[str],
        predicted_index: int,
        probabilities: torch.Tensor,
        metadata: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        label = label_names[predicted_index]
        selected_metadata = metadata[label]
        probabilities_map = {
            label_name: round(float(score), 4)
            for label_name, score in zip(label_names, probabilities.tolist())
        }
        ranking = [
            {
                "label": label_name,
                "score": round(float(probabilities[idx].item()), 4),
                "display": metadata[label_name]["display"],
            }
            for idx, label_name in sorted(
                enumerate(label_names),
                key=lambda item: probabilities[item[0]].item(),
                reverse=True,
            )
        ]

        return {
            "label": label,
            "display_label": selected_metadata["display"],
            "description": selected_metadata.get("description"),
            "confidence": round(float(probabilities[predicted_index].item()), 4),
            "probabilities": probabilities_map,
            "ranking": ranking,
        }

    @staticmethod
    def _normalize_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    @staticmethod
    def _infer_headline(text: str) -> str:
        first_sentence = text.split(".")[0].strip()
        if first_sentence:
            return first_sentence[:160]
        return text[:160]


news_analysis_pipeline = NewsAnalysisPipeline()
