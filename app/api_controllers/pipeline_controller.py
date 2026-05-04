from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api_controllers.base_controller import BaseController
from app.api_controllers.serializers import serialize_published_news
from app.application_services.clustering_service import ClusteringService
from app.application_services.prediction_service import PredictionService
from app.application_services.preprocessing_service import PreprocessingService
from app.application_services.publishing_service import PublishingService
from app.application_services.summarization_service import SummarizationService
from app.db.database import get_db
from app.dependencies import (
    get_clustering_service,
    get_current_user,
    get_prediction_service,
    get_preprocessing_service,
    get_publishing_service,
    get_summarization_service,
)
from app.ml.pipeline import ModelNotReadyError
from app.processed.models import ClusterMember, NewsCluster, ProcessedNews
from app.raw.models import RawNews
from app.serving.models import User

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])
logger = logging.getLogger(__name__)


class PipelineController(BaseController):
    def __init__(
        self,
        db: Session,
        preprocessingService: PreprocessingService,
        clusteringService: ClusteringService,
        summarizationService: SummarizationService,
        predictionService: PredictionService,
        publishingService: PublishingService,
        current_user: User | None = None,
    ):
        super().__init__(current_user)
        self.db = db
        self.preprocessingService = preprocessingService
        self.clusteringService = clusteringService
        self.summarizationService = summarizationService
        self.predictionService = predictionService
        self.publishingService = publishingService

    def postRunPipeline(self, sourceId: int) -> dict:
        self._require_moderator()

        raw_items = (
            self.db.query(RawNews)
            .filter(
                RawNews.source_id == sourceId,
                RawNews.status.in_(["pending", "failed"]),
            )
            .all()
        )
        processed_items = [
            self.preprocessingService.preprocess(raw_news.news_raw_id)
            for raw_news in raw_items
        ]
        clusters = self.clusteringService.clusterProcessedNews(sourceId, crossSource=True)
        try:
            published_items = self._publish_clusters(clusters)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return self.successResponse(
            {
                "sourceId": sourceId,
                "processedCount": len(processed_items),
                "clusterCount": len(clusters),
                "publishedCount": len(published_items),
                "publishedNews": [serialize_published_news(item) for item in published_items],
            }
        )

    def postReprocessNews(self, rawNewsId: int) -> dict:
        self._require_moderator()

        try:
            processed = self.preprocessingService.preprocess(rawNewsId)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        clusters = self.clusteringService.clusterProcessedNews(
            processed.source_id,
            crossSource=True,
        )
        representative_ids = self._collect_representative_ids(processed, clusters)
        published_items = []
        predictions_enabled = True
        try:
            for representative_id in representative_ids:
                self.summarizationService.generateSummary(representative_id)
                predictions_enabled = self._predict_if_available(
                    representative_id,
                    predictions_enabled,
                )
                published_items.append(self.publishingService.publishRepresentative(representative_id))
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return self.successResponse(
            {
                "rawNewsId": rawNewsId,
                "processedNewsId": processed.news_processed_id,
                "publishedNews": [serialize_published_news(item) for item in published_items],
            }
        )

    def _publish_clusters(self, clusters: list[NewsCluster]) -> list:
        published_items = []
        predictions_enabled = True
        for cluster in clusters:
            if not cluster or not cluster.representative_news_processed_id:
                continue
            representative_id = cluster.representative_news_processed_id
            self.summarizationService.generateSummary(representative_id)
            predictions_enabled = self._predict_if_available(
                representative_id,
                predictions_enabled,
            )
            published_items.append(self.publishingService.publishRepresentative(representative_id))
        return published_items

    def _predict_if_available(self, representative_id: int, predictions_enabled: bool) -> bool:
        if not predictions_enabled:
            return False
        try:
            self.predictionService.predictAll(representative_id)
            return True
        except ModelNotReadyError as exc:
            logger.warning(
                "Predicciones omitidas para los clusters restantes porque el clasificador no esta listo: %s",
                exc,
            )
            return False

    def _collect_representative_ids(self, processed: ProcessedNews, clusters: list[NewsCluster]) -> set[int]:
        representative_ids = {
            cluster.representative_news_processed_id
            for cluster in clusters
            if cluster.representative_news_processed_id
        }
        member = (
            self.db.query(ClusterMember)
            .filter(ClusterMember.news_processed_id == processed.news_processed_id)
            .first()
        )
        if member:
            cluster = (
                self.db.query(NewsCluster)
                .filter(NewsCluster.cluster_id == member.cluster_id)
                .first()
            )
            if cluster and cluster.representative_news_processed_id:
                representative_ids.add(cluster.representative_news_processed_id)
        return representative_ids

    def _require_moderator(self) -> User:
        user = self.requireAuth()
        if not user.canModerate():
            raise HTTPException(status_code=403, detail="Permisos insuficientes.")
        return user


def get_pipeline_controller(
    db: Session = Depends(get_db),
    preprocessing_service: PreprocessingService = Depends(get_preprocessing_service),
    clustering_service: ClusteringService = Depends(get_clustering_service),
    summarization_service: SummarizationService = Depends(get_summarization_service),
    prediction_service: PredictionService = Depends(get_prediction_service),
    publishing_service: PublishingService = Depends(get_publishing_service),
    current_user: User | None = Depends(get_current_user),
) -> PipelineController:
    return PipelineController(
        db,
        preprocessing_service,
        clustering_service,
        summarization_service,
        prediction_service,
        publishing_service,
        current_user,
    )


@router.post("/run/{source_id}")
def post_run_pipeline(
    source_id: int,
    controller: PipelineController = Depends(get_pipeline_controller),
):
    return controller.postRunPipeline(source_id)


@router.post("/reprocess/{raw_news_id}")
def post_reprocess_news(
    raw_news_id: int,
    controller: PipelineController = Depends(get_pipeline_controller),
):
    return controller.postReprocessNews(raw_news_id)
