from __future__ import annotations

from sqlalchemy.orm import Session

from app.serving.models import NewsClick, NewsReaction, NewsView


class InteractionService:
    def __init__(self, db: Session):
        self.db = db

    def recordReaction(self, userId: int, newsId: int, reaction: int) -> NewsReaction:
        item = (
            self.db.query(NewsReaction)
            .filter(NewsReaction.user_id == userId, NewsReaction.news_id == newsId)
            .first()
        )
        if not item:
            item = NewsReaction(user_id=userId, news_id=newsId, reaction=reaction)
            item.setReaction(reaction)
        else:
            item.changeReaction(reaction)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def removeReaction(self, userId: int, newsId: int) -> None:
        item = (
            self.db.query(NewsReaction)
            .filter(NewsReaction.user_id == userId, NewsReaction.news_id == newsId)
            .first()
        )
        if item:
            self.db.delete(item)
            self.db.commit()

    def recordView(self, userId: int, newsId: int, timeSpentSec: int) -> NewsView:
        item = NewsView(user_id=userId, news_id=newsId, time_spent_sec=timeSpentSec)
        item.registerView()
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def recordClick(self, userId: int, newsId: int) -> NewsClick:
        item = NewsClick(user_id=userId, news_id=newsId)
        item.registerClick()
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item
