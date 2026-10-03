from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.serving.models import (
    NewsClick,
    NewsDetailClick,
    NewsReaction,
    NewsRelatedSourceClick,
    NewsView,
    UserAppSession,
)


class InteractionService:
    def __init__(self, db: Session):
        self.db = db

    def getReaction(self, userId: int, newsId: int) -> NewsReaction | None:
        return (
            self.db.query(NewsReaction)
            .filter(NewsReaction.user_id == userId, NewsReaction.news_id == newsId)
            .first()
        )

    def recordReaction(self, userId: int, newsId: int, reaction: int) -> NewsReaction:
        if reaction not in {-1, 1}:
            raise ValueError("reaction debe ser -1 o 1.")
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
        self._validateDuration(timeSpentSec)
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
        self._validateDuration(timeSpentSec)

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
        pending_events: dict[tuple[type, str], object] = {}
        pending_sessions: dict[str, UserAppSession] = {}
        counts = {
            "views": 0,
            "clicks": 0,
            "detailClicks": 0,
            "relatedClicks": 0,
            "sessions": 0,
            "deduplicated": 0,
        }

        for event in events:
            event_type = event["type"]
            event_id = event.get("eventId")
            if event_type == "view":
                item = self._findByEvent(
                    NewsView, userId, event_id, pending_events
                )
                if item:
                    item.time_spent_sec = max(
                        int(item.time_spent_sec or 0), int(event["timeSpentSec"])
                    )
                    counts["deduplicated"] += 1
                else:
                    item = NewsView(
                        user_id=userId,
                        news_id=event["newsId"],
                        time_spent_sec=event["timeSpentSec"],
                        client_event_id=event_id,
                    )
                    item.registerView()
                    self._rememberPending(
                        pending_events, NewsView, event_id, item
                    )
                counts["views"] += 1
            elif event_type == "click":
                item = self._findByEvent(
                    NewsClick, userId, event_id, pending_events
                )
                if item:
                    counts["deduplicated"] += 1
                else:
                    item = NewsClick(
                        user_id=userId,
                        news_id=event["newsId"],
                        client_event_id=event_id,
                    )
                    item.registerClick()
                    self._rememberPending(
                        pending_events, NewsClick, event_id, item
                    )
                counts["clicks"] += 1
            elif event_type == "detail-click":
                item = self._findByEvent(
                    NewsDetailClick, userId, event_id, pending_events
                )
                if item:
                    counts["deduplicated"] += 1
                else:
                    item = NewsDetailClick(
                        user_id=userId,
                        news_id=event["newsId"],
                        client_event_id=event_id,
                    )
                    item.registerClick()
                    self._rememberPending(
                        pending_events, NewsDetailClick, event_id, item
                    )
                counts["detailClicks"] += 1
            elif event_type == "related-click":
                item = self._findByEvent(
                    NewsRelatedSourceClick, userId, event_id, pending_events
                )
                if item:
                    counts["deduplicated"] += 1
                else:
                    item = NewsRelatedSourceClick(
                        user_id=userId,
                        news_id=event["newsId"],
                        target_url=event["targetUrl"],
                        source_name=event.get("sourceName"),
                        client_event_id=event_id,
                    )
                    item.registerClick()
                    self._rememberPending(
                        pending_events, NewsRelatedSourceClick, event_id, item
                    )
                counts["relatedClicks"] += 1
            elif event_type == "session":
                seconds = event["timeSpentSec"]
                ended_at = datetime.utcnow()
                started_at = self._asUtcNaive(event.get("startedAt")) or (
                    ended_at - timedelta(seconds=seconds)
                )
                session_id = event.get("sessionId")
                item = pending_sessions.get(session_id) if session_id else None
                if item is None and session_id:
                    item = (
                        self.db.query(UserAppSession)
                        .filter(
                            UserAppSession.user_id == userId,
                            UserAppSession.client_session_id == session_id,
                        )
                        .first()
                    )
                if item:
                    item.time_spent_sec = max(int(item.time_spent_sec or 0), int(seconds))
                    item.started_at = min(item.started_at, started_at)
                    item.ended_at = ended_at
                    counts["deduplicated"] += 1
                else:
                    item = UserAppSession(
                        user_id=userId,
                        time_spent_sec=seconds,
                        started_at=started_at,
                        ended_at=ended_at,
                        client_session_id=session_id,
                    )
                    if session_id:
                        pending_sessions[session_id] = item
                counts["sessions"] += 1
            else:
                raise ValueError(f"Tipo de evento no soportado: {event_type}")
            if item not in items:
                items.append(item)

        if items:
            self.db.add_all(items)
            self.db.commit()
        counts["total"] = len(items)
        return counts

    def _findByEvent(
        self,
        model,
        userId: int,
        eventId: str | None,
        pending: dict[tuple[type, str], object],
    ):
        if not eventId:
            return None
        pending_item = pending.get((model, eventId))
        if pending_item is not None:
            return pending_item
        return (
            self.db.query(model)
            .filter(model.user_id == userId, model.client_event_id == eventId)
            .first()
        )

    @staticmethod
    def _rememberPending(
        pending: dict[tuple[type, str], object],
        model,
        eventId: str | None,
        item,
    ) -> None:
        if eventId:
            pending[(model, eventId)] = item

    @staticmethod
    def _asUtcNaive(value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is None:
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _validateDuration(value: int) -> None:
        if value < 0 or value > 86_400:
            raise ValueError("timeSpentSec debe estar entre 0 y 86400 segundos.")
