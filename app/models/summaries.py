from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index
from datetime import datetime
from app.db.database import Base

class Summary(Base):
    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, nullable=False, index=True)
    summary_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.now(), index=True)
    updated_at = Column(DateTime, default=datetime.now(), onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_article_created', 'article_id', 'created_at'),
    )
