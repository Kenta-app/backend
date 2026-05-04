from __future__ import annotations

import logging
import os

import requests
from sqlalchemy.orm import Session

from app.interfaces.summarizer_service import ISummarizerService
from app.ml.summarizer import summarizer_service
from app.processed.models import ProcessedNews, Summary

logger = logging.getLogger(__name__)


class _SummaryPersistenceMixin:
    def _get_existing_summary(self, representativeNewsProcessedId: int) -> Summary | None:
        return (
            self.db.query(Summary)
            .filter(Summary.representative_news_processed_id == representativeNewsProcessedId)
            .first()
        )

    @staticmethod
    def _can_reuse_summary(summary: Summary | None, force: bool) -> bool:
        return bool(
            summary
            and not force
            and (summary.summary_text or "").strip()
        )

    def _save_summary(self, representativeNewsProcessedId: int, summary_text: str) -> Summary:
        summary = self._get_existing_summary(representativeNewsProcessedId)
        if not summary:
            summary = Summary(
                representative_news_processed_id=representativeNewsProcessedId,
                summary_text=summary_text,
                model_version=self.getModelVersion(),
            )
        else:
            summary.updateText(summary_text)
            summary.model_version = self.getModelVersion()

        self.db.add(summary)
        self.db.commit()
        self.db.refresh(summary)
        return summary


class OpenAISummarizer(_SummaryPersistenceMixin, ISummarizerService):
    def __init__(self, db: Session, apiKey: str | None = None, modelName: str | None = None):
        self.db = db
        self.apiKey = apiKey or os.getenv("OPENAI_API_KEY")
        self.modelName = modelName or os.getenv("OPENAI_SUMMARIZER_MODEL", "gpt-4.1-mini")
        self.apiBase = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1/responses")

    def generateSummary(
        self,
        representativeNewsProcessedId: int,
        force: bool = False,
    ) -> Summary:
        existing = self._get_existing_summary(representativeNewsProcessedId)
        if self._can_reuse_summary(existing, force):
            return existing

        processed = self._get_processed_news(representativeNewsProcessedId)
        prompt = self.buildPrompt(processed.clean_text or "")
        summary_text = self.callApi(prompt)
        return self._save_summary(representativeNewsProcessedId, summary_text)

    def getModelVersion(self) -> str:
        return self.modelName

    def buildPrompt(self, cleanText: str) -> str:
        return (
            "Resume la siguiente noticia politica en espanol claro, neutral y breve. "
            "Conserva actores, hecho principal y contexto. Texto:\n\n"
            f"{cleanText}"
        )

    def callApi(self, prompt: str) -> str:
        if not self.apiKey:
            raise RuntimeError("OPENAI_API_KEY no esta configurada.")

        response = requests.post(
            self.apiBase,
            headers={
                "Authorization": f"Bearer {self.apiKey}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.modelName,
                "input": prompt,
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("output_text"):
            return payload["output_text"].strip()

        output_parts = payload.get("output", [])
        for item in output_parts:
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    return text.strip()

        raise RuntimeError("No se pudo extraer texto del resumen generado por OpenAI.")

    def _get_processed_news(self, representativeNewsProcessedId: int) -> ProcessedNews:
        processed = (
            self.db.query(ProcessedNews)
            .filter(ProcessedNews.news_processed_id == representativeNewsProcessedId)
            .first()
        )
        if not processed or not processed.clean_text:
            raise ValueError("No existe texto procesado para resumir.")
        return processed


class LocalModelSummarizer(_SummaryPersistenceMixin, ISummarizerService):
    def __init__(self, db: Session, modelPath: str | None = None, maxTokens: int = 120):
        self.db = db
        self.modelPath = modelPath or summarizer_service.model_name
        self.maxTokens = maxTokens

    def generateSummary(
        self,
        representativeNewsProcessedId: int,
        force: bool = False,
    ) -> Summary:
        existing = self._get_existing_summary(representativeNewsProcessedId)
        if self._can_reuse_summary(existing, force):
            return existing

        processed = (
            self.db.query(ProcessedNews)
            .filter(ProcessedNews.news_processed_id == representativeNewsProcessedId)
            .first()
        )
        if not processed or not processed.clean_text:
            raise ValueError("No existe texto procesado para resumir.")

        summary_text = self.runInference(processed.clean_text)
        return self._save_summary(representativeNewsProcessedId, summary_text)

    def getModelVersion(self) -> str:
        return summarizer_service.model_name

    def loadModel(self) -> None:
        if not summarizer_service.load():
            raise RuntimeError(
                f"No se pudo cargar el resumidor local: {summarizer_service.load_error}"
            )

    def runInference(self, text: str) -> str:
        if not text.strip():
            return ""
        if summarizer_service.should_summarize(text):
            self.loadModel()
            return summarizer_service.summarize(text)
        return text[: min(len(text), self.maxTokens * 5)]
