from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text

from app.db.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "serving"}

    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False, unique=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="user", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def register(self) -> None:
        if not self.created_at:
            self.created_at = datetime.utcnow()

    def authenticate(self, passwordHash: str) -> bool:
        return self.password_hash == passwordHash

    def changeRole(self, role: str) -> None:
        self.role = role

    def canModerate(self) -> bool:
        return self.role in {"admin", "moderator"}


class PublishedNews(Base):
    __tablename__ = "news"
    __table_args__ = {"schema": "serving"}

    news_id = Column(Integer, primary_key=True, index=True)
    representative_news_processed_id = Column(
        "representative_news_processed",
        Integer,
        ForeignKey("processed.news_processed.news_processed_id"),
        nullable=False,
        unique=True,
        index=True,
    )
    source_id = Column(Integer, ForeignKey("raw.source.source_id"), nullable=False, index=True)
    title = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    original_url = Column(Text, nullable=False)
    sentiment_label = Column(String(20), nullable=True, index=True)
    sentiment_score = Column(Numeric(5, 4), nullable=False, default=Decimal("0.0000"))
    fake_score = Column(Numeric(5, 4), nullable=False, default=Decimal("0.0000"))
    published_at = Column(DateTime, nullable=True, index=True)

    def publish(self) -> None:
        self.published_at = datetime.utcnow()

    def updateSummary(self, summary: str) -> None:
        self.summary = summary

    def updatePrediction(
        self,
        sentimentLabel: str,
        sentimentScore: float,
        fakeScore: float,
    ) -> None:
        self.sentiment_label = sentimentLabel
        self.sentiment_score = Decimal(str(round(float(sentimentScore), 4)))
        self.fake_score = Decimal(str(round(float(fakeScore), 4)))

    def refreshSnapshot(self) -> None:
        if self.published_at is None:
            self.published_at = datetime.utcnow()

    def isPublished(self) -> bool:
        return self.published_at is not None


class NewsReaction(Base):
    __tablename__ = "news_reactions"
    __table_args__ = (
        Index("idx_user_news_reaction", "user_id", "news_id", unique=True),
        {"schema": "serving"},
    )

    reaction_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("serving.users.user_id"), nullable=False, index=True)
    news_id = Column(Integer, ForeignKey("serving.news.news_id"), nullable=False, index=True)

    def setReaction(self, value: int) -> None:
        self.reaction = value

    def changeReaction(self, value: int) -> None:
        self.reaction = value

    def removeReaction(self) -> None:
        self.reaction = 0

    def isPositive(self) -> bool:
        return self.reaction > 0


class NewsView(Base):
    __tablename__ = "news_views"
    __table_args__ = {"schema": "serving"}

    view_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("serving.users.user_id"), nullable=False, index=True)
    news_id = Column(Integer, ForeignKey("serving.news.news_id"), nullable=False, index=True)
    viewed_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    time_spent_sec = Column(Integer, nullable=False, default=0)

    def registerView(self) -> None:
        self.viewed_at = datetime.utcnow()

    def updateTimeSpent(self, seconds: int) -> None:
        self.time_spent_sec = int(seconds)

    def isEngagedView(self, minSeconds: int) -> bool:
        return self.time_spent_sec >= int(minSeconds)


class NewsClick(Base):
    __tablename__ = "news_click"
    __table_args__ = {"schema": "serving"}

    click_id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("serving.users.user_id"), nullable=False, index=True)
    news_id = Column(Integer, ForeignKey("serving.news.news_id"), nullable=False, index=True)
    clicked_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def registerClick(self) -> None:
        self.clicked_at = datetime.utcnow()
