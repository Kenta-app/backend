from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_published_news
from app.application_services.publishing_service import PublishingService
from app.dependencies import get_current_user, get_publishing_service
from app.serving.models import User

router = APIRouter(prefix="/news", tags=["News"])


class NewsController(BaseController):
    def __init__(self, publishingService: PublishingService, current_user: User | None = None):
        super().__init__(current_user)
        self.publishingService = publishingService

    def getNewsFeed(self, page: int, pageSize: int, filters: dict) -> dict:
        source_id = filters.get("sourceId")
        if source_id:
            items = self.publishingService.newsRepository.findBySourceId(int(source_id))
        else:
            items = self.publishingService.newsRepository.findAll(page, pageSize)

        published_items = [item for item in items if item.isPublished()]
        if source_id:
            offset = max(page - 1, 0) * pageSize
            published_items = published_items[offset : offset + pageSize]

        serialized = [serialize_published_news(item) for item in published_items]
        return self.successResponse(self.paginate(serialized, page, pageSize))

    def getNewsDetail(self, newsId: int) -> dict:
        news = self.publishingService.newsRepository.findById(newsId)
        if not news:
            raise HTTPException(status_code=404, detail="Noticia publicada no encontrada.")
        return self.successResponse(serialize_published_news(news))


def get_news_controller(
    publishing_service: PublishingService = Depends(get_publishing_service),
    current_user: User | None = Depends(get_current_user),
) -> NewsController:
    return NewsController(publishing_service, current_user)


@router.get("")
def get_news_feed(
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=10, ge=1, le=100),
    sourceId: int | None = Query(default=None),
    controller: NewsController = Depends(get_news_controller),
):
    return controller.getNewsFeed(page, pageSize, {"sourceId": sourceId})


@router.get("/{news_id}")
def get_news_detail(
    news_id: int,
    controller: NewsController = Depends(get_news_controller),
):
    return controller.getNewsDetail(news_id)
