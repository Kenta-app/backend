from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.interfaces.news_repository import INewsRepository
from app.serving.models import PublishedNews


class NewsRepository(INewsRepository):
    def __init__(self, db: Session):
        self.db = db

    def findById(self, newsId: int) -> PublishedNews | None:
        return self.db.query(PublishedNews).filter(PublishedNews.news_id == newsId).first()

    def findAll(self, page: int, pageSize: int) -> List[PublishedNews]:
        offset = max(page - 1, 0) * pageSize
        return (
            self.db.query(PublishedNews)
            .order_by(PublishedNews.published_at.desc())
            .offset(offset)
            .limit(pageSize)
            .all()
        )

    def save(self, news: PublishedNews) -> PublishedNews:
        self.db.add(news)
        self.db.commit()
        self.db.refresh(news)
        return news

    def findBySourceId(self, sourceId: int) -> List[PublishedNews]:
        return (
            self.db.query(PublishedNews)
            .filter(PublishedNews.source_id == sourceId)
            .order_by(PublishedNews.published_at.desc())
            .all()
        )
