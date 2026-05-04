from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_published_news, serialize_raw_news, serialize_source
from app.application_services.ingestion_service import IngestionService
from app.application_services.publishing_service import PublishingService
from app.db.database import get_db
from app.dependencies import get_current_user, get_ingestion_service, get_publishing_service
from app.raw.models import Source
from app.serving.models import User

router = APIRouter(prefix="/admin", tags=["Admin"])


class SourceCreateRequest(BaseModel):
    name: str
    baseUrl: str
    type: str
    parserKey: str | None = None
    sourceAccount: str | None = None


class AdminController(BaseController):
    def __init__(
        self,
        db: Session,
        ingestionService: IngestionService,
        publishingService: PublishingService,
        current_user: User | None = None,
    ):
        super().__init__(current_user)
        self.db = db
        self.ingestionService = ingestionService
        self.publishingService = publishingService

    def postSource(self, name: str, baseUrl: str, type: str, parserKey: str | None = None, sourceAccount: str | None = None) -> dict:
        self._require_moderator()

        normalized_type = type.lower()
        if normalized_type not in {"web", "social", "twitter"}:
            raise HTTPException(status_code=400, detail="Tipo de fuente no soportado.")
        existing = self.db.query(Source).filter(Source.name == name).first()
        if existing:
            raise HTTPException(status_code=400, detail="La fuente ya existe.")

        source = Source(
            name=name,
            base_url=baseUrl,
            type=normalized_type,
            parser_key=parserKey,
            source_account=sourceAccount,
            source_metadata={},
        )
        source.register()
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        return self.successResponse(serialize_source(source))

    def postTriggerIngestion(self, sourceId: int) -> dict:
        self._require_moderator()
        try:
            items = self.ingestionService.ingestFromSource(sourceId)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return self.successResponse([serialize_raw_news(item) for item in items])

    def postRefreshNews(self, newsId: int) -> dict:
        self._require_moderator()
        try:
            news = self.publishingService.refreshPublishedNews(newsId)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return self.successResponse(serialize_published_news(news))

    def _require_moderator(self) -> User:
        user = self.requireAuth()
        if not user.canModerate():
            raise HTTPException(status_code=403, detail="Permisos insuficientes.")
        return user


def get_admin_controller(
    db: Session = Depends(get_db),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
    publishing_service: PublishingService = Depends(get_publishing_service),
    current_user: User | None = Depends(get_current_user),
) -> AdminController:
    return AdminController(db, ingestion_service, publishing_service, current_user)


@router.post("/sources")
def post_source(
    payload: SourceCreateRequest,
    controller: AdminController = Depends(get_admin_controller),
):
    return controller.postSource(
        payload.name,
        payload.baseUrl,
        payload.type,
        payload.parserKey,
        payload.sourceAccount,
    )


@router.post("/ingestion/{source_id}")
def post_trigger_ingestion(
    source_id: int,
    controller: AdminController = Depends(get_admin_controller),
):
    return controller.postTriggerIngestion(source_id)


@router.post("/news/{news_id}/refresh")
def post_refresh_news(
    news_id: int,
    controller: AdminController = Depends(get_admin_controller),
):
    return controller.postRefreshNews(news_id)
