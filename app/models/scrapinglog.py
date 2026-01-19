from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index
from datetime import datetime
# app/models/article.py
from app.db.database import Base


class ScrapingLog(Base):
    __tablename__ = "scraping_logs"

    id = Column(Integer, primary_key=True, index=True)
    source = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False)  # success, error, partial
    articles_scraped = Column(Integer, default=0)
    error_message = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)