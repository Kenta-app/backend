from __future__ import annotations

from sqlalchemy.orm import Session

from app.serving.models import NewsFavorite, PublishedNews


class FavoriteService:
    def __init__(self, db: Session):
        self.db = db

    def _getPublishedNews(self, newsId: int) -> PublishedNews:
        news = self.db.query(PublishedNews).filter(PublishedNews.news_id == newsId).first()
        if not news:
            raise ValueError("Noticia no encontrada.")
        if not news.isPublished():
            raise ValueError("La noticia no está publicada.")
        return news

    def addFavorite(self, userId: int, newsId: int) -> NewsFavorite:
        self._getPublishedNews(newsId)
        existing = (
            self.db.query(NewsFavorite)
            .filter(NewsFavorite.user_id == userId, NewsFavorite.news_id == newsId)
            .first()
        )
        if existing:
            return existing

        item = NewsFavorite(user_id=userId, news_id=newsId)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def removeFavorite(self, userId: int, newsId: int) -> None:
        item = (
            self.db.query(NewsFavorite)
            .filter(NewsFavorite.user_id == userId, NewsFavorite.news_id == newsId)
            .first()
        )
        if item:
            self.db.delete(item)
            self.db.commit()

    def isFavorite(self, userId: int, newsId: int) -> bool:
        return (
            self.db.query(NewsFavorite)
            .filter(NewsFavorite.user_id == userId, NewsFavorite.news_id == newsId)
            .first()
            is not None
        )

    def listFavorites(
        self,
        userId: int,
        page: int = 1,
        pageSize: int = 10,
    ) -> list[tuple[NewsFavorite, PublishedNews]]:
        offset = max(page - 1, 0) * pageSize
        return (
            self.db.query(NewsFavorite, PublishedNews)
            .join(PublishedNews, PublishedNews.news_id == NewsFavorite.news_id)
            .filter(NewsFavorite.user_id == userId)
            .order_by(NewsFavorite.saved_at.desc())
            .offset(offset)
            .limit(pageSize)
            .all()
        )
