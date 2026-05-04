from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from app.serving.models import PublishedNews


class INewsRepository(ABC):
    @abstractmethod
    def findById(self, newsId: int) -> "PublishedNews | None":
        """Find a published news item by identifier."""

    @abstractmethod
    def findAll(self, page: int, pageSize: int) -> List["PublishedNews"]:
        """Return a paginated collection of published news items."""

    @abstractmethod
    def save(self, news: "PublishedNews") -> "PublishedNews":
        """Persist a published news item."""
