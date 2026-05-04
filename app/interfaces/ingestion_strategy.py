from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from app.raw.models import RawNews


class IIngestionStrategy(ABC):
    @abstractmethod
    def ingest(self, source_id: int) -> List["RawNews"]:
        """Ingest raw news items for the given source."""

    @abstractmethod
    def supports(self, source_type: str) -> bool:
        """Return True when the strategy can handle the source type."""
