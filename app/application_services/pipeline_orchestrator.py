from __future__ import annotations

import logging

from app.application_services.clustering_service import ClusteringService
from app.application_services.ingestion_service import IngestionService
from app.application_services.prediction_service import PredictionService
from app.application_services.preprocessing_service import PreprocessingService
from app.application_services.publishing_service import PublishingService
from app.application_services.summarization_service import SummarizationService
from app.ml.pipeline import ModelNotReadyError
from app.processed.models import ClusterMember, NewsCluster, ProcessedNews

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(
        self,
        ingestionService: IngestionService,
        preprocessingService: PreprocessingService,
        clusteringService: ClusteringService,
        summarizationService: SummarizationService,
        predictionService: PredictionService,
        publishingService: PublishingService,
    ):
        self.ingestionService = ingestionService
        self.preprocessingService = preprocessingService
        self.clusteringService = clusteringService
        self.summarizationService = summarizationService
        self.predictionService = predictionService
        self.publishingService = publishingService

    def run_source_pipeline(self, sourceId: int) -> dict:
        raw_news_items = self.ingestionService.ingestFromSource(sourceId)
        processed_items = [
            self.preprocessingService.preprocess(raw_news.news_raw_id)
            for raw_news in raw_news_items
        ]
        clusters = self.clusteringService.clusterProcessedNews(sourceId, crossSource=True)
        published_news = self._publish_clusters(clusters)

        return {
            "source_id": sourceId,
            "raw_news_count": len(raw_news_items),
            "processed_count": len(processed_items),
            "cluster_count": len(clusters),
            "published_count": len(published_news),
            "published_news_ids": [item.news_id for item in published_news],
        }

    def reprocess_raw_news(self, rawNewsId: int) -> dict:
        processed = self.preprocessingService.preprocess(rawNewsId)
        clusters = self.clusteringService.clusterProcessedNews(
            processed.source_id,
            crossSource=True,
        )

        target_cluster = (
            self.clusteringService.db.query(ClusterMember)
            .filter(ClusterMember.news_processed_id == processed.news_processed_id)
            .first()
        )
        cluster_ids = {cluster.cluster_id for cluster in clusters}
        if target_cluster:
            cluster_ids.add(target_cluster.cluster_id)

        selected_clusters = [
            self.clusteringService.db.query(NewsCluster)
            .filter(NewsCluster.cluster_id == cluster_id)
            .first()
            for cluster_id in cluster_ids
        ]
        published_news = self._publish_clusters([cluster for cluster in selected_clusters if cluster])

        return {
            "raw_news_id": rawNewsId,
            "processed_news_id": processed.news_processed_id,
            "cluster_count": len(selected_clusters),
            "published_count": len(published_news),
            "published_news_ids": [item.news_id for item in published_news],
        }

    def _publish_clusters(self, clusters: list[NewsCluster]) -> list:
        published_news = []
        predictions_enabled = True
        for cluster in clusters:
            if not cluster or not cluster.representative_news_processed_id:
                continue
            representative_id = cluster.representative_news_processed_id
            self.summarizationService.generateSummary(representative_id)

            if predictions_enabled:
                try:
                    self.predictionService.predictAll(representative_id)
                except ModelNotReadyError as exc:
                    predictions_enabled = False
                    logger.warning(
                        "Predicciones omitidas para los clusters restantes porque el clasificador no esta listo: %s",
                        exc,
                    )

            published_news.append(self.publishingService.publishRepresentative(representative_id))
        return published_news
