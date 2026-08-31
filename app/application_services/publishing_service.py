from __future__ import annotations

from sqlalchemy.orm import Session

from app.interfaces.news_repository import INewsRepository
from app.processed.models import ClusterMember, MlPrediction, NewsCluster, ProcessedNews, Summary
from app.processed.text_utils import clip_readable, finish_truncated, repair_english_intrusions
from app.raw.models import RawNews
from app.serving.content_normalization import build_display_content
from app.serving.models import PublishedNews


class PublishingService:
    def __init__(self, db: Session, newsRepository: INewsRepository):
        self.db = db
        self.newsRepository = newsRepository

    def publishRepresentative(self, representativeNewsProcessedId: int) -> PublishedNews:
        news = self.buildServingNews(representativeNewsProcessedId)
        news.publish()
        return self.newsRepository.save(news)

    def buildServingNews(self, representativeNewsProcessedId: int) -> PublishedNews:
        processed = (
            self.db.query(ProcessedNews)
            .filter(ProcessedNews.news_processed_id == representativeNewsProcessedId)
            .first()
        )
        if not processed:
            raise ValueError("ProcessedNews representativa no existe.")

        raw_news = self.db.query(RawNews).filter(RawNews.news_raw_id == processed.news_raw_id).first()
        if not raw_news:
            raise ValueError("RawNews asociada no existe.")

        summary = (
            self.db.query(Summary)
            .filter(Summary.representative_news_processed_id == representativeNewsProcessedId)
            .first()
        )
        prediction = (
            self.db.query(MlPrediction)
            .filter(MlPrediction.representative_news_processed_id == representativeNewsProcessedId)
            .first()
        )

        news = (
            self.db.query(PublishedNews)
            .filter(PublishedNews.representative_news_processed_id == representativeNewsProcessedId)
            .first()
        )
        display = build_display_content(raw_news, processed.clean_text)
        if not news:
            news = PublishedNews(
                representative_news_processed_id=representativeNewsProcessedId,
                source_id=processed.source_id,
                title=display.display_title,
                original_url=raw_news.original_url,
            )

        news.source_id = processed.source_id
        news.source_account = raw_news.source_account
        news.title = display.display_title
        news.display_text = display.display_text
        news.content_type = display.content_type
        news.content_warning = display.content_warning
        news.external_links = display.external_links
        news.original_url = raw_news.original_url
        news.image_url = raw_news.image_url
        news.updateSummary(
            finish_truncated(
                repair_english_intrusions(summary.summary_text, processed.clean_text)
            )
            if summary
            else clip_readable(processed.clean_text, 900)
        )

        if prediction:
            news.updatePrediction(
                prediction.sentiment_label or "unknown",
                float(prediction.sentiment_score),
                float(prediction.fake_score),
            )

        news.refreshSnapshot()
        return news

    def refreshPublishedNews(self, newsId: int) -> PublishedNews:
        news = self.newsRepository.findById(newsId)
        if not news:
            raise ValueError(f"PublishedNews {newsId} no existe.")

        refreshed = self.buildServingNews(news.representative_news_processed_id)
        refreshed.news_id = news.news_id
        refreshed.published_at = news.published_at
        return self.newsRepository.save(refreshed)

    def unpublish(self, newsId: int) -> None:
        news = self.newsRepository.findById(newsId)
        if not news:
            raise ValueError(f"PublishedNews {newsId} no existe.")
        news.published_at = None
        self.newsRepository.save(news)

    def findSimilarPublishedNews(self, newsId: int, limit: int = 5) -> list[PublishedNews]:
        current = self.newsRepository.findById(newsId)
        if not current:
            return []

        member = (
            self.db.query(ClusterMember)
            .filter(ClusterMember.news_processed_id == current.representative_news_processed_id)
            .first()
        )
        if not member:
            return []

        cluster_members = (
            self.db.query(ClusterMember)
            .filter(ClusterMember.cluster_id == member.cluster_id)
            .all()
        )
        processed_ids = [
            item.news_processed_id
            for item in cluster_members
            if item.news_processed_id != current.representative_news_processed_id
        ]
        if not processed_ids:
            return []

        candidates = (
            self.db.query(PublishedNews)
            .filter(PublishedNews.representative_news_processed_id.in_(processed_ids))
            .filter(PublishedNews.news_id != current.news_id)
            .filter(PublishedNews.published_at.isnot(None))
            .limit(limit)
            .all()
        )
        return candidates

    def getNewsDetailPayload(self, newsId: int) -> dict:
        news = self.newsRepository.findById(newsId)
        if not news:
            raise ValueError(f"PublishedNews {newsId} no existe.")

        similar_news = self.findSimilarPublishedNews(newsId)
        cluster = (
            self.db.query(NewsCluster)
            .filter(NewsCluster.representative_news_processed_id == news.representative_news_processed_id)
            .first()
        )
        return {
            "news": news,
            "similarNews": similar_news,
            "clusterId": cluster.cluster_id if cluster else None,
            "clusterScore": float(cluster.cluster_score) if cluster else None,
            "isHighRisk": float(news.fake_score) >= 0.80,
        }
