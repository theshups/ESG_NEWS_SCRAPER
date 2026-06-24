from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseScraper(ABC):

    @abstractmethod
    def parse(self) -> list:
        """fetch and parse articles from one source"""

    def run(self) -> list:
        return self.parse()


class BaseClassifier(ABC):

    ESG_LABELS = ["Environmental", "Social", "Governance"]

    @abstractmethod
    def load(self) -> None:
        """load the model into memory — once at startup"""

    @abstractmethod
    def classify_one(self, text: str) -> dict[str, Any]:
        """return {category, confidence, scores} for one text"""

    def classify_batch(self, texts: list[str]) -> list[dict[str, Any]]:
        """default is sequential — subclasses override for native batch"""
        return [self.classify_one(t) for t in texts]

    @staticmethod
    def pick_winner(scores: dict[str, float], threshold: float = 0.35) -> str:
        if not scores:
            return "Mixed"
        top = max(scores, key=scores.get)
        return top if scores[top] >= threshold else "Mixed"


class BaseStorage(ABC):

    @abstractmethod
    def setup(self) -> None:
        """create schema — idempotent"""

    @abstractmethod
    def save(self, articles: list) -> int:
        """insert new articles, skip duplicates, return inserted count"""

    @abstractmethod
    def recent(self, n: int = 20) -> list[dict]:
        """most recently published articles"""

    @abstractmethod
    def summary(self) -> dict[str, Any]:
        """totals, per-source counts, category breakdown"""
