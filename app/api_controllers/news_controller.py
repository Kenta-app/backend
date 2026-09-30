from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_published_news, serialize_source
from app.application_services.publishing_service import PublishingService
from app.db.database import get_db
from app.dependencies import build_justification_reader, get_current_user, get_publishing_service
from app.interfaces.justification_service import IJustificationService
from app.processed.models import MlPrediction
from app.raw.models import Source
from app.serving.models import PublishedNews, User

router = APIRouter(prefix="/news", tags=["News"])


def _encode_feed_cursor(news: PublishedNews) -> str:
    payload = json.dumps([news.published_at.isoformat(), news.news_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_feed_cursor(value: str | None) -> tuple[datetime, int] | None:
    if not value:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError("invalid cursor")
        timestamp = datetime.fromisoformat(payload[0])
        news_id = int(payload[1])
        if timestamp.tzinfo is not None or news_id <= 0:
            raise ValueError("invalid cursor")
        return timestamp, news_id
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="Cursor de noticias inválido.") from exc


def _feed_since(time_range: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if time_range == "today":
        lima_today = now.astimezone(ZoneInfo("America/Lima")).date()
        return datetime.combine(lima_today, datetime.min.time(), ZoneInfo("America/Lima")).astimezone(timezone.utc).replace(tzinfo=None)
    if time_range == "week":
        return (now - timedelta(days=7)).replace(tzinfo=None)
    if time_range == "month":
        return (now - timedelta(days=30)).replace(tzinfo=None)
    return None


class NewsController(BaseController):
    def __init__(
        self,
        publishingService: PublishingService,
        db: Session,
        justificationService: IJustificationService | None = None,
        current_user: User | None = None,
    ):
        super().__init__(current_user)
        self.publishingService = publishingService
        self.db = db
        self.justificationService = justificationService

    def _source_name_map(self, news_items: list[PublishedNews]) -> dict[int, str]:
        source_ids = {item.source_id for item in news_items}
        if not source_ids:
            return {}

        rows = (
            self.db.query(Source.source_id, Source.name)
            .filter(Source.source_id.in_(source_ids))
            .all()
        )
        return {source_id: name for source_id, name in rows}

    def getSources(self) -> dict:
        sources = (
            self.db.query(Source)
            .filter(Source.is_active.is_(True))
            .order_by(Source.name)
            .all()
        )
        return self.successResponse([serialize_source(source) for source in sources])

    def getNewsFeed(self, page: int, pageSize: int, filters: dict) -> dict:
        source_id = filters.get("sourceId")
        source_name = filters.get("sourceName")
        items, total = self.publishingService.newsRepository.findFeed(
            page=page,
            pageSize=pageSize,
            sourceId=source_id,
            sourceName=source_name,
            title=(filters.get("title") or "").strip() or None,
            since=_feed_since(filters.get("timeRange") or "all"),
            before=_decode_feed_cursor(filters.get("cursor")),
        )
        published_items = items[:pageSize]
        serialized = [serialize_published_news(item) for item in published_items]
        payload = self.paginate(serialized, page, pageSize, total)
        payload["nextCursor"] = _encode_feed_cursor(published_items[-1]) if len(items) > pageSize else None
        return self.successResponse(payload)

    def getNewsDetail(self, newsId: int) -> dict:
        news = self.publishingService.newsRepository.findById(newsId)
        if not news:
            raise HTTPException(status_code=404, detail="Noticia publicada no encontrada.")

        source = self.db.query(Source).filter(Source.source_id == news.source_id).first()
        evidence_sources: list[dict] = []
        if self.justificationService is not None:
            evidence_sources = self.justificationService.get_sources_by_news_id(newsId)
        prediction = (
            self.db.query(MlPrediction)
            .filter(
                MlPrediction.representative_news_processed_id
                == news.representative_news_processed_id
            )
            .first()
        )

        return self.successResponse(
            serialize_published_news(
                news,
                sources=evidence_sources,
                source_name=source.name if source else None,
                prediction_id=prediction.prediction_id if prediction else None,
            )
        )


def get_news_controller(
    publishing_service: PublishingService = Depends(get_publishing_service),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
) -> NewsController:
    return NewsController(
        publishing_service,
        db,
        build_justification_reader(db),
        current_user,
    )


@router.get("/sources")
def get_sources(controller: NewsController = Depends(get_news_controller)):
    return controller.getSources()


@router.get("")
def get_news_feed(
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=10, ge=1, le=100),
    sourceId: int | None = Query(default=None),
    sourceName: str | None = Query(default=None),
    title: str | None = Query(default=None, max_length=200),
    timeRange: str = Query(default="all", pattern="^(all|today|week|month)$"),
    cursor: str | None = Query(default=None, max_length=200),
    controller: NewsController = Depends(get_news_controller),
):
    return controller.getNewsFeed(
        page,
        pageSize,
        {"sourceId": sourceId, "sourceName": sourceName, "title": title, "timeRange": timeRange, "cursor": cursor},
    )


@router.get("/{news_id}")
def get_news_detail(
    news_id: int,
    controller: NewsController = Depends(get_news_controller),
):
    return controller.getNewsDetail(news_id)
