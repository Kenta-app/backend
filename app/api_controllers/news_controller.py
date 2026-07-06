from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_published_news, serialize_source
from app.application_services.publishing_service import PublishingService
from app.db.database import get_db
from app.dependencies import build_justification_reader, get_current_user, get_publishing_service
from app.interfaces.justification_service import IJustificationService
from app.raw.models import Source
from app.serving.models import PublishedNews, User

router = APIRouter(prefix="/news", tags=["News"])


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
        if source_id:
            items = self.publishingService.newsRepository.findBySourceId(int(source_id))
        elif source_name:
            items = self.publishingService.newsRepository.findBySourceName(source_name)
        else:
            items = self.publishingService.newsRepository.findAll(page, pageSize)

        published_items = [item for item in items if item.isPublished()]
        if source_id or source_name:
            offset = max(page - 1, 0) * pageSize
            published_items = published_items[offset : offset + pageSize]

        source_names = self._source_name_map(published_items)
        serialized = [
            serialize_published_news(item, source_name=source_names.get(item.source_id))
            for item in published_items
        ]
        return self.successResponse(self.paginate(serialized, page, pageSize))

    def getNewsDetail(self, newsId: int) -> dict:
        news = self.publishingService.newsRepository.findById(newsId)
        if not news:
            raise HTTPException(status_code=404, detail="Noticia publicada no encontrada.")

        source = self.db.query(Source).filter(Source.source_id == news.source_id).first()
        evidence_sources: list[dict] = []
        if self.justificationService is not None:
            evidence_sources = self.justificationService.get_sources_by_news_id(newsId)

        return self.successResponse(
            serialize_published_news(
                news,
                sources=evidence_sources,
                source_name=source.name if source else None,
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
    controller: NewsController = Depends(get_news_controller),
):
    return controller.getNewsFeed(
        page,
        pageSize,
        {"sourceId": sourceId, "sourceName": sourceName},
    )


@router.get("/{news_id}")
def get_news_detail(
    news_id: int,
    controller: NewsController = Depends(get_news_controller),
):
    return controller.getNewsDetail(news_id)
