from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, Index, Integer, String

from app.db.database import Base


class ArticleAnalysis(Base):
    __tablename__ = "article_analyses"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, nullable=False, unique=True, index=True)
    fake_news_label = Column(String(50), nullable=False)
    fake_news_bucket = Column(String(20), nullable=False)
    fake_news_confidence = Column(Float, nullable=False)
    fake_news_probabilities = Column(JSON, nullable=False)
    stance_label = Column(String(50), nullable=False)
    stance_confidence = Column(Float, nullable=False)
    stance_probabilities = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_article_analysis_created", "article_id", "created_at"),
    )
