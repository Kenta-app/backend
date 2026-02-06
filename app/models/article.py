from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index
from datetime import datetime
# app/models/article.py
from app.db.database import Base

class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    url = Column(String(1000), unique=True, nullable=False, index=True)
    content = Column(Text)
    summary = Column(Text)
    author = Column(String(200))
    source = Column(String(100), nullable=False, index=True)
    published_date = Column(DateTime)
    scraped_date = Column(DateTime, default=datetime.now(), index=True)
    category = Column(String(100))
    tags = Column(String(500))
    image_url = Column(String(1000))
    is_active = Column(Boolean, default=True)

    __table_args__ = (
        Index('idx_source_date', 'source', 'scraped_date'),
    )