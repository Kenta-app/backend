import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api_controllers import admin_router, auth_router, news_router
from app.db.database import Base, apply_sqlite_schema_translation, get_db
from app.raw.models import Source
from app.serving.models import PublishedNews, User


class ApiControllersTests(unittest.TestCase):
    def setUp(self):
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
        app.include_router(admin_router)

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_auth_register_and_login(self):
        register_response = self.client.post(
            "/auth/register",
            json={
                "username": "bob",
                "email": "bob@example.com",
                "password": "123456",
            },
        )
        login_response = self.client.post(
            "/auth/login",
            json={"email": "bob@example.com", "password": "123456"},
        )

        self.assertEqual(register_response.status_code, 200)
        self.assertEqual(register_response.json()["data"]["username"], "bob")
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.json()["data"]["email"], "bob@example.com")

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

        filtered_response = self.client.get("/news?sourceName=Fuente%20Demo")

        self.assertEqual(filtered_response.status_code, 200)
        self.assertEqual(filtered_response.json()["data"]["count"], 1)
        self.assertEqual(
            filtered_response.json()["data"]["items"][0]["sourceName"],
            "Fuente Demo",
        )

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
            headers={"X-User-Id": str(admin.user_id)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["name"], "Fuente Nueva")


if __name__ == "__main__":
    unittest.main()
