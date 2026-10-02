from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application_services.analytics_service import AnalyticsService
from app.application_services.interaction_service import InteractionService
from app.db.database import Base, apply_sqlite_schema_translation
from app.raw.models import Source
from app.serving.models import NewsFavorite, PublishedNews, User, UserAppSession, NewsView


def build_db():
    engine = apply_sqlite_schema_translation(
        create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    Base.metadata.create_all(bind=engine)
    return engine, sessionmaker(bind=engine)()


def seed_news(db):
    user = User(username="participant", email="participant@example.com", password_hash="hash", role="user")
    admin = User(username="staff", email="staff@example.com", password_hash="hash", role="admin")
    source = Source(name="Telemetry source", base_url="https://example.com", type="web")
    db.add_all([user, admin, source])
    db.commit()
    news = PublishedNews(
        representative_news_processed_id=501,
        source_id=source.source_id,
        title="Telemetry article",
        original_url="https://example.com/article",
        fake_score=0.1,
    )
    news.publish()
    db.add(news)
    db.commit()
    return user, admin, news


def test_batch_is_idempotent_and_analytics_are_pseudonymized():
    engine, db = build_db()
    try:
        user, admin, news = seed_news(db)
        service = InteractionService(db)
        first = [
            {"type": "view", "newsId": news.news_id, "timeSpentSec": 15, "eventId": "view-event-0001"},
            {"type": "detail-click", "newsId": news.news_id, "eventId": "detail-event-01"},
            {"type": "click", "newsId": news.news_id, "eventId": "click-event-001"},
            {
                "type": "session",
                "timeSpentSec": 50,
                "startedAt": datetime.utcnow() - timedelta(seconds=50),
                "sessionId": "session-event-1",
                "eventId": "session-snapshot-1",
            },
        ]
        second = [
            {**first[0], "timeSpentSec": 20},
            first[1],
            first[2],
            {**first[3], "timeSpentSec": 60, "eventId": "session-snapshot-2"},
        ]
        # Dos instantáneas del mismo evento pueden llegar juntas desde la cola.
        service.recordBatch(
            user.user_id,
            [first[0], {**first[0], "timeSpentSec": 18}, *first[1:]],
        )
        service.recordBatch(user.user_id, second)
        service.recordReaction(user.user_id, news.news_id, 1)
        db.add(NewsFavorite(user_id=user.user_id, news_id=news.news_id))

        # El tráfico de cuentas administrativas no debe contaminar el estudio.
        service.recordBatch(
            admin.user_id,
            [{"type": "view", "newsId": news.news_id, "timeSpentSec": 99, "eventId": "admin-view-01"}],
        )
        db.commit()

        assert db.query(NewsView).filter(NewsView.user_id == user.user_id).count() == 1
        assert db.query(NewsView).filter(NewsView.user_id == user.user_id).one().time_spent_sec == 20
        assert db.query(UserAppSession).filter(UserAppSession.user_id == user.user_id).count() == 1
        assert db.query(UserAppSession).filter(UserAppSession.user_id == user.user_id).one().time_spent_sec == 60

        metrics = AnalyticsService(db).getEngagementMetrics(
            datetime.utcnow() - timedelta(days=1),
            datetime.utcnow() + timedelta(days=1),
        )
        summary = metrics["summary"]
        assert summary["uniqueUsers"] == 1
        assert summary["totalViews"] == 1
        assert summary["totalReadingTimeSec"] == 20
        assert summary["totalDetailClicks"] == 1
        assert summary["totalClicks"] == 1
        assert summary["totalSessions"] == 1
        assert summary["totalAppTimeSec"] == 60
        assert summary["positiveReactions"] == 1
        assert summary["totalFavorites"] == 1
        assert metrics["participants"] == [
            {
                **metrics["participants"][0],
                "userId": user.user_id,
                "participantCode": f"P-{user.user_id:04d}",
                "totalViews": 1,
                "totalReadingTimeSec": 20,
                "totalDetailClicks": 1,
                "totalClicks": 1,
                "totalSessions": 1,
                "totalAppTimeSec": 60,
                "positiveReactions": 1,
                "negativeReactions": 0,
                "totalFavorites": 1,
            }
        ]
        timeline = AnalyticsService(db).getParticipantEvents(
            datetime.utcnow() - timedelta(days=1),
            datetime.utcnow() + timedelta(days=1),
            user.user_id,
        )
        assert timeline["participantCode"] == f"P-{user.user_id:04d}"
        assert {item["type"] for item in timeline["events"]} == {
            "view",
            "detail-click",
            "original-click",
            "reaction",
            "session",
            "favorite",
        }
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
