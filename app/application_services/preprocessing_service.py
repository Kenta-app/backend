from __future__ import annotations

import re
import time

from sqlalchemy.orm import Session

from app.processed.logging import create_processing_log
from app.processed.models import ProcessedNews, ProcessingLog
from app.raw.models import RawNews


class PreprocessingService:
    def __init__(self, db: Session):
        self.db = db

    def preprocess(self, rawNewsId: int) -> ProcessedNews:
        raw_news = self.db.query(RawNews).filter(RawNews.news_raw_id == rawNewsId).first()
        if not raw_news:
            raise ValueError(f"RawNews {rawNewsId} no existe.")

        start_time = time.perf_counter()
        processed = (
            self.db.query(ProcessedNews)
            .filter(ProcessedNews.news_raw_id == rawNewsId)
            .first()
        )
        if not processed:
            processed = ProcessedNews(
                news_raw_id=raw_news.news_raw_id,
                source_id=raw_news.source_id,
            )

        raw_text = "\n".join(filter(None, [raw_news.title_raw, raw_news.content_raw]))
        clean_text = self.cleanText(raw_text)
        language = self.detectLanguage(clean_text)
        token_count = self.countTokens(clean_text)

        processed.updateCleanText(clean_text)
        processed.updateLanguage(language)
        processed.updateTokenCount(token_count)

        self.db.add(processed)
        self.db.commit()
        self.db.refresh(processed)

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        self._delete_previous_stage_logs(processed.news_processed_id, "preprocessing")

        if token_count < 50:
            processed.markRejected()
            raw_news.markRejected("Texto insuficiente")
            self.db.add(processed)
            self.db.add(raw_news)
            self.db.commit()
            create_processing_log(
                self.db,
                news_processed_id=processed.news_processed_id,
                stage="preprocessing",
                status="failed",
                message="Texto rechazado por tener menos de 50 tokens.",
                model_version="preprocess:v1",
                execution_time_ms=elapsed_ms,
            )
            return processed

        processed.markProcessed()
        raw_news.markProcessed()
        self.db.add(processed)
        self.db.add(raw_news)
        self.db.commit()

        create_processing_log(
            self.db,
            news_processed_id=processed.news_processed_id,
            stage="preprocessing",
            status="success",
            message="Texto limpio, normalizado y listo para NLP.",
            model_version="preprocess:v1",
            execution_time_ms=elapsed_ms,
        )
        return processed

    def cleanText(self, rawText: str) -> str:
        text = rawText or ""
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"https?://\S+|www\.\S+", " ", text)
        text = re.sub(r"[@#]\w+", " ", text)
        text = re.sub(r"[^\w\s.,;:!?áéíóúÁÉÍÓÚñÑ-]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def detectLanguage(self, text: str) -> str:
        lower = f" {text.lower()} "
        spanish_markers = [" el ", " la ", " de ", " que ", " para ", " congreso ", " politica "]
        english_markers = [" the ", " and ", " for ", " news "]
        if sum(marker in lower for marker in spanish_markers) >= 2:
            return "es"
        if sum(marker in lower for marker in english_markers) >= 2:
            return "en"
        if lower.strip():
            return "unknown"
        return "empty"

    def countTokens(self, text: str) -> int:
        return len([token for token in text.split(" ") if token])

    def logProcessing(self, processedId: int, stage: str, status: str, executionTimeMs: int, message: str | None = None) -> None:
        create_processing_log(
            self.db,
            news_processed_id=processedId,
            stage=stage,
            status=status,
            message=message or f"Stage {stage} completed with status {status}.",
            model_version="preprocess:v1",
            execution_time_ms=executionTimeMs,
        )

    def _delete_previous_stage_logs(self, processedId: int, stage: str) -> None:
        (
            self.db.query(ProcessingLog)
            .filter(
                ProcessingLog.news_processed_id == processedId,
                ProcessingLog.stage == stage,
            )
            .delete()
        )
        self.db.commit()
