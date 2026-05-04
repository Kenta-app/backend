from __future__ import annotations

from app.interfaces.summarizer_service import ISummarizerService
from app.processed.models import Summary


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

    def regenerateSummary(self, representativeNewsProcessedId: int, modelVersion: str) -> Summary:
        summary = self.summarizer.generateSummary(
            representativeNewsProcessedId,
            force=True,
        )
        summary.model_version = modelVersion
        return summary
