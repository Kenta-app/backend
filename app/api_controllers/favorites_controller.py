from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_favorite
from app.application_services.favorite_service import FavoriteService
from app.db.database import get_db
from app.dependencies import get_current_user, get_favorite_service
from app.raw.models import Source
from app.serving.models import User

router = APIRouter(prefix="/favorites", tags=["Favorites"])


class FavoriteRequest(BaseModel):
    newsId: int


class FavoritesController(BaseController):
    def __init__(
        self,
        favoriteService: FavoriteService,
        db: Session,
        current_user: User | None = None,
    ):
        super().__init__(current_user)
        self.favoriteService = favoriteService
        self.db = db

    def _source_name_map(self, news_items: list) -> dict[int, str]:
        source_ids = {item.source_id for item in news_items}
        if not source_ids:
            return {}

        rows = (
            self.db.query(Source.source_id, Source.name)
            .filter(Source.source_id.in_(source_ids))
            .all()
        )
        return {source_id: name for source_id, name in rows}

    def postFavorite(self, newsId: int) -> dict:
        user = self.requireAuth()
        try:
            item = self.favoriteService.addFavorite(user.user_id, newsId)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return self.successResponse(serialize_favorite(item))

    def getFavorites(self, page: int, pageSize: int) -> dict:
        user = self.requireAuth()
        rows = self.favoriteService.listFavorites(user.user_id, page, pageSize)
        news_items = [news for _, news in rows]
        source_names = self._source_name_map(news_items)
        serialized = [
            serialize_favorite(
                favorite,
                news,
                source_name=source_names.get(news.source_id),
            )
            for favorite, news in rows
        ]
        return self.successResponse(self.paginate(serialized, page, pageSize))

    def getFavoriteStatus(self, newsId: int) -> dict:
        user = self.requireAuth()
        is_favorite = self.favoriteService.isFavorite(user.user_id, newsId)
        return self.successResponse({"newsId": newsId, "isFavorite": is_favorite})

    def deleteFavorite(self, newsId: int) -> dict:
        user = self.requireAuth()
        self.favoriteService.removeFavorite(user.user_id, newsId)
        return self.successResponse({"newsId": newsId, "removed": True})


def get_favorites_controller(
    favorite_service: FavoriteService = Depends(get_favorite_service),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user),
) -> FavoritesController:
    return FavoritesController(favorite_service, db, current_user)


@router.post("")
def post_favorite(
    payload: FavoriteRequest,
    controller: FavoritesController = Depends(get_favorites_controller),
):
    return controller.postFavorite(payload.newsId)


@router.get("")
def get_favorites(
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=10, ge=1, le=100),
    controller: FavoritesController = Depends(get_favorites_controller),
):
    return controller.getFavorites(page, pageSize)


@router.get("/{news_id}")
def get_favorite_status(
    news_id: int,
    controller: FavoritesController = Depends(get_favorites_controller),
):
    return controller.getFavoriteStatus(news_id)


@router.delete("/{news_id}")
def delete_favorite(
    news_id: int,
    controller: FavoritesController = Depends(get_favorites_controller),
):
    return controller.deleteFavorite(news_id)
