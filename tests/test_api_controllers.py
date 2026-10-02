import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api_controllers import admin_router, auth_router, interaction_router, news_router
from app.api_controllers.justification_controller import JustificationController
from app.db.database import Base, apply_sqlite_schema_translation, get_db
from app.dependencies import get_email_sender
from app.processed.models import MlPrediction
from app.raw.models import Source
from app.serving.models import PublishedNews, User
from app.services.session_token_service import SessionTokenService


class FakeEmailSender:
    def __init__(self):
        self.messages = []

    def sendVerificationCode(self, email: str, code: str) -> None:
        self.messages.append({"email": email, "code": code})


class ReadOnlyJustificationService:
    def __init__(self):
        self.generated = False

    def get_persisted_justification(self, prediction_id: int):
        return None

    def generate_justification(self, *args, **kwargs):
        self.generated = True
        raise AssertionError("GET must not generate Gemini sources")


class ApiControllersTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "EMAIL_VERIFICATION_SECRET": "test-verification-secret",
                "AUTH_SESSION_SECRET": "test-session-secret-with-at-least-32-characters",
                "AUTH_COOKIE_SECURE": "false",
            },
        )
        self.environment.start()
        self.engine = apply_sqlite_schema_translation(
            create_engine(
                "sqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

        app = FastAPI()
        app.include_router(auth_router)
        app.include_router(news_router)
        app.include_router(interaction_router)
        app.include_router(admin_router)

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.emailSender = FakeEmailSender()
        app.dependency_overrides[get_email_sender] = lambda: self.emailSender
        self.client = TestClient(app)

    def auth_cookies(self, user: User) -> dict[str, str]:
        service = SessionTokenService()
        token, _ = service.issue(user, False)
        return {service.cookie_name: token}

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()
        self.environment.stop()

    def test_auth_register_and_login(self):
        register_response = self.client.post(
            "/auth/register",
            json={
                "username": "bob",
                "email": "bob@example.com",
                "password": "123456",
                "acceptedTerms": True,
                "termsVersion": "2026-08-28",
                "privacyPolicyVersion": "2026-08-28",
            },
        )
        unverified_login_response = self.client.post(
            "/auth/login",
            json={"email": "bob@example.com", "password": "123456"},
        )
        verification_response = self.client.post(
            "/auth/verify-email",
            json={"email": "bob@example.com", "code": self.emailSender.messages[-1]["code"]},
        )
        login_response = self.client.post(
            "/auth/login",
            json={"email": "bob@example.com", "password": "123456"},
        )

        self.assertEqual(register_response.status_code, 200)
        self.assertTrue(register_response.json()["data"]["verificationRequired"])
        self.assertEqual(unverified_login_response.status_code, 403)
        self.assertEqual(verification_response.status_code, 200)
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.json()["data"]["email"], "bob@example.com")
        self.assertEqual(self.client.get("/auth/me").status_code, 200)

        wrong_password_response = self.client.post(
            "/auth/change-password",
            json={"currentPassword": "wrong", "newPassword": "new-secret-123"},
        )
        self.assertEqual(wrong_password_response.status_code, 400)
        change_response = self.client.post(
            "/auth/change-password",
            json={"currentPassword": "123456", "newPassword": "new-secret-123"},
        )
        self.assertEqual(change_response.status_code, 200)
        self.assertEqual(
            self.client.post("/auth/login", json={"email": "bob@example.com", "password": "123456"}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post("/auth/login", json={"email": "bob@example.com", "password": "new-secret-123"}).status_code,
            200,
        )
        self.assertEqual(self.client.post("/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/auth/me").status_code, 401)

    def test_news_feed_returns_published_news(self):
        source = Source(
            name="Fuente Demo",
            base_url="https://example.com",
            type="web",
        )
        source.register()
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)

        news = PublishedNews(
            representative_news_processed_id=1,
            source_id=source.source_id,
            title="Noticia publicada",
            summary="Resumen",
            original_url="https://example.com/news",
            sentiment_label="discuss",
            sentiment_score=0.8,
            fake_score=0.2,
        )
        news.publish()
        self.db.add(news)
        self.db.commit()

        response = self.client.get("/news")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 1)
        self.assertEqual(response.json()["data"]["items"][0]["title"], "Noticia publicada")
        self.assertEqual(response.json()["data"]["items"][0]["sourceName"], "Fuente Demo")
        self.assertIsNone(response.json()["data"]["items"][0]["sentimentLabel"])
        self.assertIsNone(response.json()["data"]["items"][0]["sentimentScore"])
        self.assertFalse(response.json()["data"]["items"][0]["stanceAvailable"])

        filtered_response = self.client.get("/news?sourceName=Fuente%20Demo")

        self.assertEqual(filtered_response.status_code, 200)
        self.assertEqual(filtered_response.json()["data"]["count"], 1)
        self.assertEqual(
            filtered_response.json()["data"]["items"][0]["sourceName"],
            "Fuente Demo",
        )

    def test_reaction_can_be_read_without_405(self):
        user = User(username="reaction-user", email="reaction@example.com", password_hash="unused", role="user")
        source = Source(name="Reaction Source", base_url="https://reaction.example", type="web")
        self.db.add_all([user, source])
        self.db.commit()
        news = PublishedNews(
            representative_news_processed_id=9001,
            source_id=source.source_id,
            title="Reaction article",
            original_url="https://reaction.example/article",
            fake_score=0.2,
        )
        news.publish()
        self.db.add(news)
        self.db.commit()
        cookies = self.auth_cookies(user)
        path = f"/interactions/reaction/{news.news_id}"
        self.assertEqual(
            self.client.get(path, headers={"X-User-Id": str(user.user_id)}).status_code,
            401,
        )
        self.assertIsNone(self.client.get(path, cookies=cookies).json()["data"])
        self.assertEqual(
            self.client.post(
                "/interactions/reaction",
                cookies=cookies,
                json={"newsId": news.news_id, "reaction": 1},
            ).status_code,
            200,
        )
        response = self.client.get(path, cookies=cookies)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["reaction"], 1)
        self.assertEqual(self.client.delete(path, cookies=cookies).status_code, 200)
        self.assertIsNone(self.client.get(path, cookies=cookies).json()["data"])

    def test_news_feed_serializes_social_display_fields(self):
        source = Source(
            name="Cuenta X",
            base_url="https://x.com/cuenta",
            source_account="cuenta",
            type="twitter",
        )
        source.register()
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)

        news = PublishedNews(
            representative_news_processed_id=3,
            source_id=source.source_id,
            source_account="cuenta",
            title="Publicación de @cuenta",
            summary="Resumen generado del post.",
            display_text="Texto limpio sin enlace.",
            content_type="social_post",
            content_warning="strong_language",
            external_links=["https://example.com/contexto"],
            original_url="https://x.com/cuenta/status/1",
            sentiment_label="discuss",
            sentiment_score=0.8,
            fake_score=0.2,
        )
        news.publish()
        self.db.add(news)
        self.db.commit()

        response = self.client.get("/news")
        item = response.json()["data"]["items"][0]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(item["title"], "Publicación de @cuenta")
        self.assertEqual(item["displayText"], "Texto limpio sin enlace.")
        self.assertEqual(item["contentType"], "social_post")
        self.assertEqual(item["contentWarning"], "strong_language")
        self.assertEqual(item["externalLinks"], ["https://example.com/contexto"])
        self.assertEqual(item["sourceAccount"], "cuenta")

    def test_feed_cursor_filters_and_stable_ties(self):
        source = Source(name="Fuente Cursor", base_url="https://cursor.example", type="web")
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        timestamp = datetime.utcnow()
        for index, title in enumerate(("Economía local", "Economía nacional", "Deporte"), 1):
            self.db.add(PublishedNews(
                representative_news_processed_id=100 + index,
                source_id=source.source_id,
                title=title,
                original_url=f"https://cursor.example/{index}",
                published_at=timestamp,
                fake_score=0.1,
            ))
        self.db.commit()

        first = self.client.get("/news?pageSize=1&title=Econom%C3%ADa")
        self.assertEqual(first.status_code, 200)
        first_data = first.json()["data"]
        self.assertEqual(first_data["count"], 2)
        self.assertIsNotNone(first_data["nextCursor"])
        self.assertEqual(self.client.get("/news?title=economia").json()["data"]["count"], 2)
        second = self.client.get("/news", params={"pageSize": 1, "title": "Economía", "cursor": first_data["nextCursor"]})
        second_data = second.json()["data"]
        self.assertEqual(second_data["count"], 2)
        self.assertNotEqual(first_data["items"][0]["newsId"], second_data["items"][0]["newsId"])
        self.assertIsNone(second_data["nextCursor"])
        self.assertEqual(self.client.get("/news?cursor=invalid!").status_code, 422)
        offset_page = self.client.get("/news?page=2&pageSize=1&title=Econom%C3%ADa")
        self.assertEqual(offset_page.status_code, 200)
        self.assertEqual(offset_page.json()["data"]["items"][0]["newsId"], second_data["items"][0]["newsId"])

    def test_feed_time_range_is_applied_before_pagination(self):
        source = Source(name="Fuente Tiempo", base_url="https://time.example", type="web")
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        for index, days_ago in enumerate((1, 40), 1):
            self.db.add(PublishedNews(
                representative_news_processed_id=200 + index,
                source_id=source.source_id,
                title=f"Noticia {index}",
                original_url=f"https://time.example/{index}",
                published_at=datetime.utcnow() - timedelta(days=days_ago),
                fake_score=0.1,
            ))
        self.db.commit()
        response = self.client.get("/news?timeRange=week&pageSize=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["count"], 1)

    def test_news_detail_returns_published_news_with_empty_evidence(self):
        source = Source(
            name="Fuente Detalle",
            base_url="https://example.com",
            type="web",
        )
        source.register()
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)

        news = PublishedNews(
            representative_news_processed_id=2,
            source_id=source.source_id,
            title="Noticia de detalle",
            summary="Resumen de detalle",
            original_url="https://example.com/detail",
            sentiment_label="discuss",
            sentiment_score=0.8,
            fake_score=0.2,
        )
        news.publish()
        self.db.add(news)
        self.db.commit()
        self.db.refresh(news)

        prediction = MlPrediction(
            representative_news_processed_id=2,
            sentiment_label="discuss",
            sentiment_score=0.8,
            fake_score=0.2,
            model_version="test",
        )
        self.db.add(prediction)
        self.db.commit()
        self.db.refresh(prediction)

        response = self.client.get(f"/news/{news.news_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["newsId"], news.news_id)
        self.assertEqual(response.json()["data"]["predictionId"], prediction.prediction_id)
        self.assertEqual(response.json()["data"]["sources"], [])

    def test_get_justification_does_not_generate_when_missing(self):
        service = ReadOnlyJustificationService()
        controller = JustificationController(service)

        with self.assertRaises(HTTPException) as ctx:
            controller.get_justification(42)

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertFalse(service.generated)

    def test_admin_can_create_source(self):
        admin = User(
            username="admin",
            email="admin@example.com",
            password_hash="hash",
            role="admin",
        )
        admin.register()
        self.db.add(admin)
        self.db.commit()
        self.db.refresh(admin)

        response = self.client.post(
            "/admin/sources",
            json={
                "name": "Fuente Nueva",
                "baseUrl": "https://example.com",
                "type": "web",
                "parserKey": "generic",
            },
            cookies=self.auth_cookies(admin),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["name"], "Fuente Nueva")


if __name__ == "__main__":
    unittest.main()
