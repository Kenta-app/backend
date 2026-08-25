from __future__ import annotations

import logging
import os

from app.interfaces.summarizer_service import ISummarizerService
from app.processed.models import Summary

logger = logging.getLogger(__name__)


def is_inline_summary_enabled() -> bool:
    return os.getenv("SUMMARY_INLINE_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class SummarizationService:
    def __init__(self, summarizer: ISummarizerService):
        self.summarizer = summarizer

    def generateSummary(
        self,
        representativeNewsProcessedId: int,
        force: bool = False,
    ) -> Summary:
        return self.summarizer.generateSummary(
            representativeNewsProcessedId,
            force=force,
        )

    def generateSummaryForPipeline(
        self,
        representativeNewsProcessedId: int,
        force: bool = False,
    ) -> Summary | None:
        if not is_inline_summary_enabled():
            return None

        try:
            return self.generateSummary(
                representativeNewsProcessedId,
                force=force,
            )
        except Exception as exc:
            logger.warning(
                "Resumen omitido para noticia procesada %s: %s",
                representativeNewsProcessedId,
                exc,
            )
            return None

    def regenerateSummary(self, representativeNewsProcessedId: int, modelVersion: str) -> Summary:
        summary = self.summarizer.generateSummary(
            representativeNewsProcessedId,
            force=True,
        )
        summary.model_version = modelVersion
        return summary
