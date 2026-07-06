from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.serving.models import NewsClick, NewsDetailClick, NewsReaction, NewsView, UserAppSession


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
            item.created_at = datetime.utcnow()
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

    def recordDetailClick(self, userId: int, newsId: int) -> NewsDetailClick:
        item = NewsDetailClick(user_id=userId, news_id=newsId)
        item.registerClick()
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def recordSession(
        self,
        userId: int,
        timeSpentSec: int,
        startedAt: datetime | None = None,
    ) -> UserAppSession:
        if timeSpentSec < 0:
            raise ValueError("timeSpentSec debe ser mayor o igual a 0.")

        ended_at = datetime.utcnow()
        resolved_started = startedAt or (ended_at - timedelta(seconds=timeSpentSec))
        item = UserAppSession(
            user_id=userId,
            time_spent_sec=timeSpentSec,
            started_at=resolved_started,
            ended_at=ended_at,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item
