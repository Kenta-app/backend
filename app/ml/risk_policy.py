from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_LOW_THRESHOLD = 0.35
DEFAULT_HIGH_THRESHOLD = 0.75


@dataclass(frozen=True)
class FakeNewsRiskPolicy:
    """Canonical three-way policy used by inference, API responses and UI."""

    low_threshold: float = DEFAULT_LOW_THRESHOLD
    high_threshold: float = DEFAULT_HIGH_THRESHOLD

    @classmethod
    def from_environment(cls) -> "FakeNewsRiskPolicy":
        try:
            low = float(os.getenv("FAKENEWS_ARTICLE_LOW_THRESHOLD", DEFAULT_LOW_THRESHOLD))
            high = float(os.getenv("FAKENEWS_ARTICLE_HIGH_THRESHOLD", DEFAULT_HIGH_THRESHOLD))
        except (TypeError, ValueError):
            return cls()
        if not 0 <= low < high <= 1:
            return cls()
        return cls(low_threshold=low, high_threshold=high)

    def classify(self, score: float) -> str:
        normalized = min(max(float(score), 0.0), 1.0)
        if normalized >= self.high_threshold:
            return "likely_fake"
        if normalized <= self.low_threshold:
            return "likely_real"
        return "indeterminate"

    def thresholds(self) -> dict[str, float]:
        return {
            "low": round(self.low_threshold, 4),
            "high": round(self.high_threshold, 4),
        }
