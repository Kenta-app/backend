from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.processed.models import MlPrediction


class IPredictionService(ABC):
    @abstractmethod
    def predictAll(self, representativeNewsProcessedId: int) -> "MlPrediction":
        """Run the full prediction workflow for the representative news item."""

    @abstractmethod
    def getModelVersion(self) -> str:
        """Return the prediction model version."""
