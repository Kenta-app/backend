import logging
import os
from threading import BoundedSemaphore, Lock

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from app.processed.text_utils import (
    finish_truncated,
    normalize_summary_text,
    repair_english_intrusions,
)

logger = logging.getLogger(__name__)


class SummarizerService:
    def __init__(self):
        self.model_name = os.getenv("SUMMARIZER_MODEL_NAME", "facebook/bart-large-cnn")
        self.summary_min_chars = int(os.getenv("SUMMARY_MIN_CHARS", "700"))
        self.max_input_length = int(os.getenv("SUMMARY_MAX_INPUT_LENGTH", "1024"))
        self.max_summary_length = int(os.getenv("SUMMARY_MAX_LENGTH", "150"))
        self.min_summary_length = int(os.getenv("SUMMARY_MIN_LENGTH", "60"))
        self.num_beams = int(os.getenv("SUMMARY_NUM_BEAMS", "4"))
        self.max_concurrent_generations = max(
            1,
            int(os.getenv("SUMMARY_MAX_CONCURRENT_GENERATIONS", "1")),
        )
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._lock = Lock()
        self._generation_slots = BoundedSemaphore(self.max_concurrent_generations)
        self.loaded = False
        self.load_error = None
        self.tokenizer = None
        self.model = None

    def should_summarize(self, article: str | None) -> bool:
        if not article:
            return False
        return len(article.strip()) >= self.summary_min_chars

    def load(self) -> bool:
        if self.loaded:
            return True

        with self._lock:
            if self.loaded:
                return True

            try:
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self.model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name)
                self.model.to(self.device)
                self.model.eval()
                self.loaded = True
                self.load_error = None
                logger.info("Summarizer loaded: %s", self.model_name)
                return True
            except Exception as exc:
                self.load_error = str(exc)
                logger.exception("Error loading summarizer")
                return False

    def summarize(self, article: str) -> str:
        if not article or not article.strip():
            raise ValueError("No hay contenido para resumir.")

        if not self.load():
            raise RuntimeError(
                f"No se pudo cargar el resumidor '{self.model_name}': {self.load_error}"
            )

        inputs = self.tokenizer(
            article,
            return_tensors="pt",
            max_length=self.max_input_length,
            truncation=True,
        ).to(self.device)

        with self._generation_slots:
            with torch.no_grad():
                summary_ids = self.model.generate(
                    inputs["input_ids"],
                    attention_mask=inputs.get("attention_mask"),
                    num_beams=self.num_beams,
                    max_length=self.max_summary_length,
                    min_length=self.min_summary_length,
                    no_repeat_ngram_size=3,
                    length_penalty=1.5,
                    early_stopping=True,
                )

        generated_tokens = summary_ids[0]
        summary = normalize_summary_text(
            self.tokenizer.decode(generated_tokens, skip_special_tokens=True)
        )
        summary = repair_english_intrusions(summary, article)

        # BART can force an EOS token when max_length is reached, so checking
        # eos_token_id alone does not prove that generation ended naturally.
        reached_limit = generated_tokens.shape[-1] >= self.max_summary_length
        return finish_truncated(summary) if reached_limit else summary


summarizer_service = SummarizerService()


def summarize(article: str) -> str:
    return summarizer_service.summarize(article)
