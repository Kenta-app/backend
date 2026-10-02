from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Date, case, cast, func
from sqlalchemy.orm import Session

from app.serving.models import (
    NewsClick,
    NewsDetailClick,
    NewsFavorite,
    NewsReaction,
    NewsView,
    PublishedNews,
    User,
    UserAppSession,
)


class AnalyticsService:
    STAFF_ROLES = ("admin", "moderator")

    def __init__(self, db: Session):
        self.db = db

    def _excludeStaff(self, query, user_id_column):
        return (
            query.join(User, User.user_id == user_id_column)
            .filter(User.role.notin_(self.STAFF_ROLES))
        )

    def getEngagementMetrics(
        self,
        fromDate: datetime,
        toDate: datetime,
        newsId: int | None = None,
        includeParticipants: bool = True,
    ) -> dict[str, Any]:
        view_stats = self._viewStats(fromDate, toDate, newsId)
        click_stats = self._clickStats(fromDate, toDate, newsId)
        detail_click_stats = self._detailClickStats(fromDate, toDate, newsId)
        reaction_stats = self._reactionStats(fromDate, toDate, newsId)
        participants = (
            self._participantMetrics(fromDate, toDate)
            if includeParticipants
            else []
        )

        news_ids = set(view_stats) | set(click_stats) | set(detail_click_stats) | set(reaction_stats)
        if newsId is not None:
            news_ids.add(newsId)

        titles = self._newsTitles(news_ids)
        by_news = [
            self._buildNewsMetrics(
                nid,
                titles.get(nid),
                view_stats.get(nid, {}),
                click_stats.get(nid, {}),
                detail_click_stats.get(nid, {}),
                reaction_stats.get(nid, {}),
            )
            for nid in sorted(news_ids)
        ]

        if newsId is not None and not by_news:
            by_news = [self._emptyNewsMetrics(newsId, titles.get(newsId))]

        app_time = self._appSessionStats(fromDate, toDate)

        summary = self._buildSummary(by_news, app_time)
        if includeParticipants:
            summary["uniqueUsers"] = len(participants)
            summary["totalFavorites"] = sum(
                item["totalFavorites"] for item in participants
            )

        return {
            "fromDate": fromDate.isoformat(),
            "toDate": toDate.isoformat(),
            "newsId": newsId,
            "summary": summary,
            "byNews": by_news,
            "participants": participants,
        }

    def getChartMetrics(
        self,
        fromDate: datetime,
        toDate: datetime,
        topLimit: int = 5,
    ) -> dict[str, Any]:
        full = self.getEngagementMetrics(
            fromDate, toDate, includeParticipants=False
        )
        summary = full["summary"]

        top_news = sorted(
            full["byNews"],
            key=lambda item: item["totalDetailClicks"],
            reverse=True,
        )[:topLimit]

        return {
            "fromDate": full["fromDate"],
            "toDate": full["toDate"],
            "kpis": [
                {"key": "views", "label": "Vistas", "value": summary["totalViews"]},
                {"key": "detailClicks", "label": "Aperturas detalle", "value": summary["totalDetailClicks"]},
                {"key": "originalClicks", "label": "Clics URL original", "value": summary["totalClicks"]},
                {"key": "appTimeMin", "label": "Tiempo en app (min)", "value": round(summary["totalAppTimeSec"] / 60, 1)},
                {"key": "sessions", "label": "Sesiones", "value": summary["totalSessions"]},
            ],
            "interactions": [
                {"label": "Vistas", "value": summary["totalViews"]},
                {"label": "Abrir detalle", "value": summary["totalDetailClicks"]},
                {"label": "URL original", "value": summary["totalClicks"]},
            ],
            "reactions": [
                {"label": "Positivas", "value": summary["positiveReactions"]},
                {"label": "Negativas", "value": summary["negativeReactions"]},
            ],
            "topNews": [
                {
                    "newsId": item["newsId"],
                    "label": item["title"] or f"Noticia {item['newsId']}",
                    "value": item["totalDetailClicks"],
                }
                for item in top_news
            ],
            "timeline": self._buildTimeline(fromDate, toDate),
        }

    def getParticipantEvents(
        self,
        fromDate: datetime,
        toDate: datetime,
        userId: int,
        limit: int = 500,
    ) -> dict[str, Any]:
        user = (
            self.db.query(User)
            .filter(User.user_id == userId, User.role.notin_(self.STAFF_ROLES))
            .first()
        )
        if not user:
            return {"participantCode": f"P-{userId:04d}", "events": []}

        events: list[dict[str, Any]] = []

        def append_event(kind: str, timestamp, news_id=None, duration=None, value=None):
            events.append(
                {
                    "type": kind,
                    "occurredAt": timestamp.isoformat(),
                    "newsId": news_id,
                    "durationSec": duration,
                    "value": value,
                }
            )

        for item in self.db.query(NewsView).filter(
            NewsView.user_id == userId,
            NewsView.viewed_at >= fromDate,
            NewsView.viewed_at <= toDate,
        ).all():
            append_event("view", item.viewed_at, item.news_id, item.time_spent_sec)
        for item in self.db.query(NewsDetailClick).filter(
            NewsDetailClick.user_id == userId,
            NewsDetailClick.clicked_at >= fromDate,
            NewsDetailClick.clicked_at <= toDate,
        ).all():
            append_event("detail-click", item.clicked_at, item.news_id)
        for item in self.db.query(NewsClick).filter(
            NewsClick.user_id == userId,
            NewsClick.clicked_at >= fromDate,
            NewsClick.clicked_at <= toDate,
        ).all():
            append_event("original-click", item.clicked_at, item.news_id)
        for item in self.db.query(NewsReaction).filter(
            NewsReaction.user_id == userId,
            NewsReaction.updated_at >= fromDate,
            NewsReaction.updated_at <= toDate,
        ).all():
            append_event("reaction", item.updated_at, item.news_id, value=item.reaction)
        for item in self.db.query(UserAppSession).filter(
            UserAppSession.user_id == userId,
            UserAppSession.ended_at >= fromDate,
            UserAppSession.ended_at <= toDate,
        ).all():
            append_event("session", item.ended_at, duration=item.time_spent_sec)
        for item in self.db.query(NewsFavorite).filter(
            NewsFavorite.user_id == userId,
            NewsFavorite.saved_at >= fromDate,
            NewsFavorite.saved_at <= toDate,
        ).all():
            append_event("favorite", item.saved_at, item.news_id)

        events.sort(key=lambda item: item["occurredAt"], reverse=True)
        return {
            "participantCode": f"P-{userId:04d}",
            "events": events[:limit],
        }

    def _buildTimeline(self, fromDate: datetime, toDate: datetime) -> list[dict[str, Any]]:
        views_by_day = self._countByDay(NewsView, NewsView.viewed_at, fromDate, toDate)
        detail_by_day = self._countByDay(NewsDetailClick, NewsDetailClick.clicked_at, fromDate, toDate)
        original_by_day = self._countByDay(NewsClick, NewsClick.clicked_at, fromDate, toDate)
        sessions_by_day = self._countByDay(UserAppSession, UserAppSession.ended_at, fromDate, toDate)

        all_dates = sorted(
            set(views_by_day)
            | set(detail_by_day)
            | set(original_by_day)
            | set(sessions_by_day)
        )

        return [
            {
                "date": day.isoformat(),
                "views": views_by_day.get(day, 0),
                "detailClicks": detail_by_day.get(day, 0),
                "originalClicks": original_by_day.get(day, 0),
                "sessions": sessions_by_day.get(day, 0),
            }
            for day in all_dates
        ]

    def _countByDay(
        self,
        model,
        timestamp_column,
        fromDate: datetime,
        toDate: datetime,
    ) -> dict[Any, int]:
        day_column = cast(timestamp_column, Date)
        query = self.db.query(day_column.label("day"), func.count().label("total"))
        query = self._excludeStaff(query, model.user_id)
        rows = (
            query.filter(timestamp_column >= fromDate, timestamp_column <= toDate)
            .group_by(day_column)
            .order_by(day_column)
            .all()
        )
        return {row.day: int(row.total or 0) for row in rows}

    def _viewStats(
        self,
        fromDate: datetime,
        toDate: datetime,
        newsId: int | None,
    ) -> dict[int, dict[str, float | int]]:
        query = (
            self.db.query(
                NewsView.news_id,
                func.count(NewsView.view_id).label("total_views"),
                func.avg(NewsView.time_spent_sec).label("avg_time_spent"),
                func.sum(NewsView.time_spent_sec).label("total_time_spent"),
            )
            .filter(NewsView.viewed_at >= fromDate, NewsView.viewed_at <= toDate)
        )
        query = self._excludeStaff(query, NewsView.user_id)
        if newsId is not None:
            query = query.filter(NewsView.news_id == newsId)
        query = query.group_by(NewsView.news_id)

        return {
            row.news_id: {
                "totalViews": int(row.total_views or 0),
                "averageTimeSpentSec": round(float(row.avg_time_spent or 0), 2),
                "totalReadingTimeSec": int(row.total_time_spent or 0),
            }
            for row in query.all()
        }

    def _clickStats(
        self,
        fromDate: datetime,
        toDate: datetime,
        newsId: int | None,
    ) -> dict[int, dict[str, int]]:
        query = (
            self.db.query(
                NewsClick.news_id,
                func.count(NewsClick.click_id).label("total_clicks"),
            )
            .filter(NewsClick.clicked_at >= fromDate, NewsClick.clicked_at <= toDate)
        )
        query = self._excludeStaff(query, NewsClick.user_id)
        if newsId is not None:
            query = query.filter(NewsClick.news_id == newsId)
        query = query.group_by(NewsClick.news_id)

        return {
            row.news_id: {"totalClicks": int(row.total_clicks or 0)}
            for row in query.all()
        }

    def _detailClickStats(
        self,
        fromDate: datetime,
        toDate: datetime,
        newsId: int | None,
    ) -> dict[int, dict[str, int]]:
        query = (
            self.db.query(
                NewsDetailClick.news_id,
                func.count(NewsDetailClick.detail_click_id).label("total_detail_clicks"),
            )
            .filter(NewsDetailClick.clicked_at >= fromDate, NewsDetailClick.clicked_at <= toDate)
        )
        query = self._excludeStaff(query, NewsDetailClick.user_id)
        if newsId is not None:
            query = query.filter(NewsDetailClick.news_id == newsId)
        query = query.group_by(NewsDetailClick.news_id)

        return {
            row.news_id: {"totalDetailClicks": int(row.total_detail_clicks or 0)}
            for row in query.all()
        }

    def _appSessionStats(self, fromDate: datetime, toDate: datetime) -> dict[str, float | int]:
        query = self.db.query(
            func.count(UserAppSession.session_id).label("total_sessions"),
            func.sum(UserAppSession.time_spent_sec).label("total_app_time_sec"),
            func.avg(UserAppSession.time_spent_sec).label("average_session_sec"),
        ).filter(UserAppSession.ended_at >= fromDate, UserAppSession.ended_at <= toDate)
        query = self._excludeStaff(query, UserAppSession.user_id)
        row = query.one()
        return {
            "totalSessions": int(row.total_sessions or 0),
            "totalAppTimeSec": int(row.total_app_time_sec or 0),
            "averageSessionSec": round(float(row.average_session_sec or 0), 2),
        }

    def _reactionStats(
        self,
        fromDate: datetime,
        toDate: datetime,
        newsId: int | None,
    ) -> dict[int, dict[str, int]]:
        positive_case = case((NewsReaction.reaction > 0, 1), else_=0)
        negative_case = case((NewsReaction.reaction < 0, 1), else_=0)

        query = (
            self.db.query(
                NewsReaction.news_id,
                func.sum(positive_case).label("positive_reactions"),
                func.sum(negative_case).label("negative_reactions"),
            )
            .filter(NewsReaction.updated_at >= fromDate, NewsReaction.updated_at <= toDate)
        )
        query = self._excludeStaff(query, NewsReaction.user_id)
        if newsId is not None:
            query = query.filter(NewsReaction.news_id == newsId)
        query = query.group_by(NewsReaction.news_id)

        return {
            row.news_id: {
                "positiveReactions": int(row.positive_reactions or 0),
                "negativeReactions": int(row.negative_reactions or 0),
            }
            for row in query.all()
        }

    def _newsTitles(self, news_ids: set[int]) -> dict[int, str]:
        if not news_ids:
            return {}

        rows = (
            self.db.query(PublishedNews.news_id, PublishedNews.title)
            .filter(PublishedNews.news_id.in_(news_ids))
            .all()
        )
        return {news_id: title for news_id, title in rows}

    def _positiveRatio(self, positive: int, negative: int) -> float:
        total = positive + negative
        if total == 0:
            return 0.0
        return round(positive / total, 4)

    def _buildNewsMetrics(
        self,
        newsId: int,
        title: str | None,
        views: dict[str, float | int],
        clicks: dict[str, int],
        detail_clicks: dict[str, int],
        reactions: dict[str, int],
    ) -> dict[str, Any]:
        positive = int(reactions.get("positiveReactions", 0))
        negative = int(reactions.get("negativeReactions", 0))
        return {
            "newsId": newsId,
            "title": title,
            "totalViews": int(views.get("totalViews", 0)),
            "totalClicks": int(clicks.get("totalClicks", 0)),
            "totalDetailClicks": int(detail_clicks.get("totalDetailClicks", 0)),
            "averageTimeSpentSec": float(views.get("averageTimeSpentSec", 0.0)),
            "totalReadingTimeSec": int(views.get("totalReadingTimeSec", 0)),
            "positiveReactions": positive,
            "negativeReactions": negative,
            "positiveRatio": self._positiveRatio(positive, negative),
        }

    def _emptyNewsMetrics(self, newsId: int, title: str | None) -> dict[str, Any]:
        return self._buildNewsMetrics(newsId, title, {}, {}, {}, {})

    def _buildSummary(
        self,
        by_news: list[dict[str, Any]],
        app_time: dict[str, float | int],
    ) -> dict[str, Any]:
        if not by_news:
            return {
                "totalViews": 0,
                "totalClicks": 0,
                "totalDetailClicks": 0,
                "averageTimeSpentSec": 0.0,
                "totalReadingTimeSec": 0,
                "positiveReactions": 0,
                "negativeReactions": 0,
                "positiveRatio": 0.0,
                "totalSessions": int(app_time["totalSessions"]),
                "totalAppTimeSec": int(app_time["totalAppTimeSec"]),
                "averageSessionSec": float(app_time["averageSessionSec"]),
            }

        total_views = sum(item["totalViews"] for item in by_news)
        total_clicks = sum(item["totalClicks"] for item in by_news)
        total_detail_clicks = sum(item["totalDetailClicks"] for item in by_news)
        total_reading_time = sum(item["totalReadingTimeSec"] for item in by_news)
        positive = sum(item["positiveReactions"] for item in by_news)
        negative = sum(item["negativeReactions"] for item in by_news)

        if total_views:
            weighted_avg = sum(
                item["averageTimeSpentSec"] * item["totalViews"] for item in by_news
            ) / total_views
        else:
            weighted_avg = 0.0

        return {
            "totalViews": total_views,
            "totalClicks": total_clicks,
            "totalDetailClicks": total_detail_clicks,
            "averageTimeSpentSec": round(weighted_avg, 2),
            "totalReadingTimeSec": total_reading_time,
            "positiveReactions": positive,
            "negativeReactions": negative,
            "positiveRatio": self._positiveRatio(positive, negative),
            "totalSessions": int(app_time["totalSessions"]),
            "totalAppTimeSec": int(app_time["totalAppTimeSec"]),
            "averageSessionSec": float(app_time["averageSessionSec"]),
        }

    def _participantMetrics(
        self, fromDate: datetime, toDate: datetime
    ) -> list[dict[str, Any]]:
        metrics: dict[int, dict[str, Any]] = {}

        def participant(user_id: int) -> dict[str, Any]:
            if user_id not in metrics:
                metrics[user_id] = {
                    "userId": user_id,
                    "participantCode": f"P-{user_id:04d}",
                    "totalViews": 0,
                    "totalReadingTimeSec": 0,
                    "totalDetailClicks": 0,
                    "totalClicks": 0,
                    "totalSessions": 0,
                    "totalAppTimeSec": 0,
                    "positiveReactions": 0,
                    "negativeReactions": 0,
                    "totalFavorites": 0,
                    "firstActiveAt": None,
                    "lastActiveAt": None,
                }
            return metrics[user_id]

        def merge_activity(item: dict[str, Any], first, last) -> None:
            if first and (item["firstActiveAt"] is None or first < item["firstActiveAt"]):
                item["firstActiveAt"] = first
            if last and (item["lastActiveAt"] is None or last > item["lastActiveAt"]):
                item["lastActiveAt"] = last

        view_query = self.db.query(
            NewsView.user_id,
            func.count(NewsView.view_id),
            func.sum(NewsView.time_spent_sec),
            func.min(NewsView.viewed_at),
            func.max(NewsView.viewed_at),
        ).filter(NewsView.viewed_at >= fromDate, NewsView.viewed_at <= toDate)
        view_query = self._excludeStaff(view_query, NewsView.user_id)
        for uid, count, seconds, first, last in view_query.group_by(NewsView.user_id).all():
            item = participant(uid)
            item["totalViews"] = int(count or 0)
            item["totalReadingTimeSec"] = int(seconds or 0)
            merge_activity(item, first, last)

        event_specs = (
            (NewsDetailClick, NewsDetailClick.detail_click_id, NewsDetailClick.clicked_at, "totalDetailClicks"),
            (NewsClick, NewsClick.click_id, NewsClick.clicked_at, "totalClicks"),
        )
        for model, id_column, timestamp, key in event_specs:
            query = self.db.query(
                model.user_id,
                func.count(id_column),
                func.min(timestamp),
                func.max(timestamp),
            ).filter(timestamp >= fromDate, timestamp <= toDate)
            query = self._excludeStaff(query, model.user_id)
            for uid, count, first, last in query.group_by(model.user_id).all():
                item = participant(uid)
                item[key] = int(count or 0)
                merge_activity(item, first, last)

        session_query = self.db.query(
            UserAppSession.user_id,
            func.count(UserAppSession.session_id),
            func.sum(UserAppSession.time_spent_sec),
            func.min(UserAppSession.started_at),
            func.max(UserAppSession.ended_at),
        ).filter(UserAppSession.ended_at >= fromDate, UserAppSession.ended_at <= toDate)
        session_query = self._excludeStaff(session_query, UserAppSession.user_id)
        for uid, count, seconds, first, last in session_query.group_by(UserAppSession.user_id).all():
            item = participant(uid)
            item["totalSessions"] = int(count or 0)
            item["totalAppTimeSec"] = int(seconds or 0)
            merge_activity(item, first, last)

        positive_case = case((NewsReaction.reaction > 0, 1), else_=0)
        negative_case = case((NewsReaction.reaction < 0, 1), else_=0)
        reaction_query = self.db.query(
            NewsReaction.user_id,
            func.sum(positive_case),
            func.sum(negative_case),
            func.min(NewsReaction.updated_at),
            func.max(NewsReaction.updated_at),
        ).filter(NewsReaction.updated_at >= fromDate, NewsReaction.updated_at <= toDate)
        reaction_query = self._excludeStaff(reaction_query, NewsReaction.user_id)
        for uid, positive, negative, first, last in reaction_query.group_by(NewsReaction.user_id).all():
            item = participant(uid)
            item["positiveReactions"] = int(positive or 0)
            item["negativeReactions"] = int(negative or 0)
            merge_activity(item, first, last)

        favorite_query = self.db.query(
            NewsFavorite.user_id,
            func.count(NewsFavorite.favorite_id),
            func.min(NewsFavorite.saved_at),
            func.max(NewsFavorite.saved_at),
        ).filter(NewsFavorite.saved_at >= fromDate, NewsFavorite.saved_at <= toDate)
        favorite_query = self._excludeStaff(favorite_query, NewsFavorite.user_id)
        for uid, count, first, last in favorite_query.group_by(NewsFavorite.user_id).all():
            item = participant(uid)
            item["totalFavorites"] = int(count or 0)
            merge_activity(item, first, last)

        output = []
        for item in metrics.values():
            item["firstActiveAt"] = (
                item["firstActiveAt"].isoformat() if item["firstActiveAt"] else None
            )
            item["lastActiveAt"] = (
                item["lastActiveAt"].isoformat() if item["lastActiveAt"] else None
            )
            output.append(item)
        return sorted(output, key=lambda item: item["participantCode"])
