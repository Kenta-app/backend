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

    def recordBatch(self, userId: int, events: list[dict]) -> dict[str, int]:
        """Persiste eventos de analítica en una única transacción."""
        items = []
        counts = {"views": 0, "clicks": 0, "detailClicks": 0, "sessions": 0}

        for event in events:
            event_type = event["type"]
            if event_type == "view":
                item = NewsView(
                    user_id=userId,
                    news_id=event["newsId"],
                    time_spent_sec=event["timeSpentSec"],
                )
                item.registerView()
                counts["views"] += 1
            elif event_type == "click":
                item = NewsClick(user_id=userId, news_id=event["newsId"])
                item.registerClick()
                counts["clicks"] += 1
            elif event_type == "detail-click":
                item = NewsDetailClick(user_id=userId, news_id=event["newsId"])
                item.registerClick()
                counts["detailClicks"] += 1
            elif event_type == "session":
                seconds = event["timeSpentSec"]
                ended_at = datetime.utcnow()
                started_at = event.get("startedAt") or (
                    ended_at - timedelta(seconds=seconds)
                )
                item = UserAppSession(
                    user_id=userId,
                    time_spent_sec=seconds,
                    started_at=started_at,
                    ended_at=ended_at,
                )
                counts["sessions"] += 1
            else:
                raise ValueError(f"Tipo de evento no soportado: {event_type}")
            items.append(item)

        if items:
            self.db.add_all(items)
            self.db.commit()
        counts["total"] = len(items)
        return counts
