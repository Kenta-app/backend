from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.interfaces.ingestion_strategy import IIngestionStrategy
from app.raw.models import IngestionLog, RawNews, Source

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, db: Session, strategies: list[IIngestionStrategy]):
        self.db = db
        self.strategies = strategies
        self.strategy: IIngestionStrategy | None = None

    def ingestFromSource(self, sourceId: int) -> list[RawNews]:
        source = self.db.query(Source).filter(Source.source_id == sourceId).first()
        if not source:
            raise ValueError(f"Source {sourceId} no existe.")
        if not source.is_active:
            logger.info("Source %s is inactive and will be skipped.", sourceId)
            return []

        strategy = self._resolve_strategy(source.type)
        self.strategy = strategy
        log = self.createIngestionLog(sourceId, source.type)

        saved_items: list[RawNews] = []
        duplicates = 0
        incomplete = 0
        try:
            raw_news_items = strategy.ingest(sourceId)
            for raw_news in raw_news_items:
                if not self._normalize_raw_news(raw_news):
                    incomplete += 1
                    continue
                if self.deduplicateBySourceAndUrl(sourceId, raw_news.original_url):
                    duplicates += 1
                    continue
                raw_news.log_id = log.log_id
                raw_news.markPending()
                self.db.add(raw_news)
                saved_items.append(raw_news)

            self.db.commit()
            for raw_news in saved_items:
                self.db.refresh(raw_news)

            log.markSuccess(
                f"{len(saved_items)} noticias almacenadas. "
                f"{duplicates} duplicados descartados. "
                f"{incomplete} incompletas descartadas."
            )
            self.db.add(log)
            self.db.commit()
            self.db.refresh(log)
            return saved_items
        except Exception as exc:
            self.db.rollback()
            logger.exception("Error ingesting source %s", sourceId)
            log.markFailed(str(exc))
            self.db.add(log)
            self.db.commit()
            raise

    @staticmethod
    def _normalize_raw_news(raw_news: RawNews) -> bool:
        raw_news.title_raw = " ".join((raw_news.title_raw or "").split()) or None
        raw_news.content_raw = " ".join((raw_news.content_raw or "").split()) or None
        return bool(raw_news.title_raw and raw_news.content_raw)

    def createIngestionLog(self, sourceId: int, ingestionType: str) -> IngestionLog:
        log = IngestionLog(
            source_id=sourceId,
            ingestion_type=ingestionType,
            status="pending",
        )
        log.start()
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)
        return log

    def saveRawNews(self, rawNews: RawNews) -> RawNews:
        self.db.add(rawNews)
        self.db.commit()
        self.db.refresh(rawNews)
        return rawNews

    def deduplicateBySourceAndUrl(self, sourceId: int, originalUrl: str) -> bool:
        return (
            self.db.query(RawNews)
            .filter(
                RawNews.source_id == sourceId,
                RawNews.original_url == originalUrl,
            )
            .first()
            is not None
        )

    def _resolve_strategy(self, source_type: str) -> IIngestionStrategy:
        for strategy in self.strategies:
            if strategy.supports(source_type):
                return strategy
        raise ValueError(f"No existe estrategia para el tipo de fuente '{source_type}'.")
