from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text

from app.db.database import Base


class ProcessedNews(Base):
    __tablename__ = "news_processed"
    __table_args__ = {"schema": "processed"}

    news_processed_id = Column(Integer, primary_key=True, index=True)
    news_raw_id = Column(Integer, ForeignKey("raw.news_raw.news_raw_id"), nullable=False, unique=True, index=True)
    source_id = Column(Integer, ForeignKey("raw.source.source_id"), nullable=False, index=True)
    clean_text = Column(Text, nullable=True)
    language = Column(String(10), nullable=True, index=True)
    token_count = Column(Integer, nullable=False, default=0)
    processed_at = Column(DateTime, default=datetime.utcnow, nullable=True, index=True)
    status = Column(String(50), nullable=False, default="ok", index=True)

    def isProcessable(self) -> bool:
        return bool(self.clean_text and self.clean_text.strip() and self.token_count >= 50)

    def updateCleanText(self, cleanText: str) -> None:
        self.clean_text = cleanText

    def updateLanguage(self, language: str) -> None:
        self.language = language

    def updateTokenCount(self, tokenCount: int) -> None:
        self.token_count = tokenCount

    def markProcessed(self) -> None:
        self.status = "ok"
        self.processed_at = datetime.utcnow()

    def markRejected(self) -> None:
        self.status = "error"
        self.processed_at = datetime.utcnow()

    def markDuplicate(self) -> None:
        self.status = "duplicate"
        self.processed_at = datetime.utcnow()


class ProcessingLog(Base):
    __tablename__ = "processing_logs"
    __table_args__ = {"schema": "processed"}

    log_id = Column(Integer, primary_key=True, index=True)
    news_processed_id = Column(Integer, ForeignKey("processed.news_processed.news_processed_id"), nullable=False, index=True)
    stage = Column(String(50), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="running", index=True)
    message = Column(String(150), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    model_version = Column(String(50), nullable=True)
    execution_time_ms = Column(Integer, nullable=True)

    def startStage(self, stage: str, modelVersion: str) -> None:
        self.stage = stage
        self.status = "running"
        self.model_version = modelVersion
        self.message = None
        self.execution_time_ms = None

    def markSuccess(self, message: str, executionTimeMs: int) -> None:
        self.status = "success"
        self.message = message
        self.execution_time_ms = executionTimeMs

    def markFailed(self, message: str, executionTimeMs: int) -> None:
        self.status = "failed"
        self.message = message
        self.execution_time_ms = executionTimeMs


class NewsCluster(Base):
    __tablename__ = "news_clusters"
    __table_args__ = {"schema": "processed"}

    cluster_id = Column(Integer, primary_key=True, index=True)
    representative_news_processed_id = Column(
        "representative_news_processed",
        Integer,
        ForeignKey("processed.news_processed.news_processed_id"),
        nullable=False,
        index=True,
    )
    source_id = Column(Integer, ForeignKey("raw.source.source_id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    cluster_score = Column(Numeric(4, 3), nullable=False, default=Decimal("0.000"))

    def assignRepresentative(self, newsProcessedId: int) -> None:
        self.representative_news_processed_id = newsProcessedId

    def updateClusterScore(self, score: float | Decimal) -> None:
        self.cluster_score = Decimal(str(round(float(score), 3)))

    def isValidCluster(self) -> bool:
        return self.representative_news_processed_id is not None


class ClusterMember(Base):
    __tablename__ = "cluster_members"
    __table_args__ = (
        Index("idx_cluster_news", "cluster_id", "news_processed_id", unique=True),
        {"schema": "processed"},
    )

    cluster_members_id = Column(Integer, primary_key=True, index=True)
    cluster_id = Column(Integer, ForeignKey("processed.news_clusters.cluster_id"), nullable=False, index=True)
    news_processed_id = Column(
        Integer,
        ForeignKey("processed.news_processed.news_processed_id"),
        nullable=False,
        unique=True,
        index=True,
    )
    source_id = Column(Integer, ForeignKey("raw.source.source_id"), nullable=False, index=True)

    def attachToCluster(self, clusterId: int) -> None:
        self.cluster_id = clusterId

    def detachFromCluster(self) -> None:
        self.cluster_id = None

    def belongsToCluster(self, clusterId: int) -> bool:
        return self.cluster_id == clusterId


class Summary(Base):
    __tablename__ = "summaries"
    __table_args__ = {"schema": "processed"}

    summary_id = Column(Integer, primary_key=True, index=True)
    representative_news_processed_id = Column(
        "representative_news_processed",
        Integer,
        ForeignKey("processed.news_processed.news_processed_id"),
        nullable=False,
        unique=True,
        index=True,
    )
    summary_text = Column(Text, nullable=False)
    model_version = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def updateText(self, summaryText: str) -> None:
        self.summary_text = summaryText

    def isEmpty(self) -> bool:
        return len((self.summary_text or "").split()) < 20


class MlPrediction(Base):
    __tablename__ = "ml_predictions"
    __table_args__ = {"schema": "processed"}

    prediction_id = Column(Integer, primary_key=True, index=True)
    representative_news_processed_id = Column(
        "representative_news_processed",
        Integer,
        ForeignKey("processed.news_processed.news_processed_id"),
        nullable=False,
        unique=True,
        index=True,
    )
    sentiment_label = Column(String(20), nullable=True, index=True)
    sentiment_score = Column(Numeric(5, 4), nullable=False, default=Decimal("0.0000"))
    model_version = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    fake_score = Column(Numeric(5, 4), nullable=False, default=Decimal("0.0000"))

    def updateSentiment(self, label: str, score: float) -> None:
        self.sentiment_label = label
        self.sentiment_score = Decimal(str(round(float(score), 4)))

    def updateFakeScore(self, fakeScore: float) -> None:
        self.fake_score = Decimal(str(round(float(fakeScore), 4)))

    def isHighRisk(self, threshold: float) -> bool:
        return float(self.fake_score) >= float(threshold)
