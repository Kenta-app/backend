from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.processed.models import Summary


class ISummarizerService(ABC):
    @abstractmethod
    def generateSummary(
        self,
        representativeNewsProcessedId: int,
        force: bool = False,
    ) -> "Summary":
        """Generate or update the summary for a representative processed news item."""

    @abstractmethod
    def getModelVersion(self) -> str:
        """Return the model version used by the summarizer."""
