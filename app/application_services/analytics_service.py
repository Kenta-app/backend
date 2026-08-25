from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Date, case, cast, func
from sqlalchemy.orm import Session

from app.serving.models import (
    NewsClick,
    NewsDetailClick,
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
    ) -> dict[str, Any]:
        view_stats = self._viewStats(fromDate, toDate, newsId)
        click_stats = self._clickStats(fromDate, toDate, newsId)
        detail_click_stats = self._detailClickStats(fromDate, toDate, newsId)
        reaction_stats = self._reactionStats(fromDate, toDate, newsId)

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

        return {
            "fromDate": fromDate.isoformat(),
            "toDate": toDate.isoformat(),
            "newsId": newsId,
            "summary": self._buildSummary(by_news, app_time),
            "byNews": by_news,
        }

    def getChartMetrics(
        self,
        fromDate: datetime,
        toDate: datetime,
        topLimit: int = 5,
    ) -> dict[str, Any]:
        full = self.getEngagementMetrics(fromDate, toDate)
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
            .filter(NewsReaction.created_at >= fromDate, NewsReaction.created_at <= toDate)
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
            "positiveReactions": positive,
            "negativeReactions": negative,
            "positiveRatio": self._positiveRatio(positive, negative),
            "totalSessions": int(app_time["totalSessions"]),
            "totalAppTimeSec": int(app_time["totalAppTimeSec"]),
            "averageSessionSec": float(app_time["averageSessionSec"]),
        }
