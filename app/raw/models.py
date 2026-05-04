from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.db.database import Base


class Source(Base):
    __tablename__ = "source"
    __table_args__ = {"schema": "raw"}

    source_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    base_url = Column(String(500), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    type = Column(String(50), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)

    def register(self) -> None:
        if not self.created_at:
            self.created_at = datetime.utcnow()

    def updateMetadata(self, name: str, baseUrl: str, type: str) -> None:
        self.name = name
        self.base_url = baseUrl
        self.type = type.lower()

    def activate(self) -> None:
        self.is_active = True

    def deactivate(self) -> None:
        self.is_active = False

    def isWebSource(self) -> bool:
        return self.type.lower() == "web"

    def isSocialSource(self) -> bool:
        return self.type.lower() in {"social", "twitter"}


class IngestionLog(Base):
    __tablename__ = "ingestion_logs"
    __table_args__ = {"schema": "raw"}

    log_id = Column(Integer, primary_key=True, index=True)
    ingestion_type = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False, default="pending", index=True)
    message = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("raw.source.source_id"), nullable=False, index=True)

    def start(self) -> None:
        self.status = "running"
        self.message = "Ingestion started"

    def markSuccess(self, message: str) -> None:
        self.close("success", message)

    def markFailed(self, message: str) -> None:
        self.close("failed", message)

    def close(self, status: str, message: str) -> None:
        self.status = status
        self.message = message


class RawNews(Base):
    __tablename__ = "news_raw"
    __table_args__ = (
        Index("idx_raw_source_url", "source_id", "original_url", unique=True),
        {"schema": "raw"},
    )

    news_raw_id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("raw.source.source_id"), nullable=False, index=True)
    log_id = Column(Integer, ForeignKey("raw.ingestion_logs.log_id"), nullable=False, index=True)
    platform = Column(String(50), nullable=False, default="web")
    source_account = Column(String(50), nullable=True)
    original_url = Column(String(500), nullable=False, index=True)
    title_raw = Column(Text, nullable=True)
    content_raw = Column(Text, nullable=False)
    author_raw = Column(String(255), nullable=True)
    published_at = Column(DateTime, nullable=True, index=True)
    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending", index=True)

    def validateContent(self) -> bool:
        return self.hasContent()

    def hasContent(self) -> bool:
        text = " ".join(filter(None, [self.title_raw, self.content_raw]))
        return bool(text.strip())

    def markPending(self) -> None:
        self.status = "pending"

    def markProcessed(self) -> None:
        self.status = "processed"

    def markRejected(self, reason: str) -> None:
        del reason
        self.status = "rejected"

    def markFailed(self, reason: str) -> None:
        del reason
        self.status = "failed"
