from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.processed.logging import create_processing_log
from app.processed.models import ClusterMember, NewsCluster, ProcessedNews
from app.raw.models import RawNews


@dataclass(frozen=True)
class _NewsTextContext:
    title_tokens: tuple[str, ...]
    lead_tokens: tuple[str, ...]
    body_tokens: tuple[str, ...]


class ClusteringService:
    STOPWORDS = {
        "ante",
        "como",
        "con",
        "contra",
        "cual",
        "cuales",
        "cuando",
        "de",
        "del",
        "desde",
        "donde",
        "el",
        "ella",
        "ellas",
        "ellos",
        "en",
        "entre",
        "era",
        "eran",
        "es",
        "esa",
        "esas",
        "ese",
        "eso",
        "esos",
        "esta",
        "estaba",
        "estaban",
        "estado",
        "estados",
        "estas",
        "este",
        "estos",
        "fue",
        "fueron",
        "ha",
        "han",
        "hasta",
        "hoy",
        "la",
        "las",
        "lo",
        "los",
        "mas",
        "mientras",
        "muy",
        "para",
        "pero",
        "por",
        "que",
        "quien",
        "quienes",
        "se",
        "segun",
        "ser",
        "sin",
        "sobre",
        "su",
        "sus",
        "tambien",
        "tras",
        "un",
        "una",
        "uno",
        "unos",
        "unas",
        "ya",
    }
    TITLE_BOOST_THRESHOLD = 0.35
    TITLE_WEIGHT = 0.65
    LEAD_TOKEN_LIMIT = 120

    def __init__(self, db: Session, similarity_threshold: float | None = None):
        self.db = db
        if similarity_threshold is None:
            similarity_threshold = float(
                os.getenv("CLUSTERING_SIMILARITY_THRESHOLD", "0.40")
            )
        self.similarity_threshold = float(similarity_threshold)
        self._news_context_cache: dict[int, _NewsTextContext] = {}

    def clusterProcessedNews(self, sourceId: int | None, crossSource: bool = True) -> list[NewsCluster]:
        processed_query = self.db.query(ProcessedNews).filter(
            ProcessedNews.status.in_(["ok", "processed"])
        )
        if sourceId is not None and not crossSource:
            processed_query = processed_query.filter(ProcessedNews.source_id == sourceId)

        processed_items = processed_query.order_by(ProcessedNews.processed_at.asc()).all()
        if len(processed_items) < 2:
            for processed in processed_items:
                create_processing_log(
                    self.db,
                    news_processed_id=processed.news_processed_id,
                    stage="clustering",
                    status="failed",
                    message="No hay suficientes articulos para clustering.",
                    model_version=f"hybrid:{self.similarity_threshold}",
                    execution_time_ms=0,
                )
            return []

        members_query = self.db.query(ClusterMember)
        clusters_query = self.db.query(NewsCluster)
        if sourceId is not None and not crossSource:
            members_query = members_query.filter(ClusterMember.source_id == sourceId)
            clusters_query = clusters_query.filter(NewsCluster.source_id == sourceId)

        existing_members = {member.news_processed_id: member for member in members_query.all()}
        clusters = {cluster.cluster_id: cluster for cluster in clusters_query.all()}

        touched_cluster_ids: set[int] = set()

        for processed in processed_items:
            if processed.news_processed_id in existing_members:
                touched_cluster_ids.add(existing_members[processed.news_processed_id].cluster_id)
                continue

            best_cluster, best_score = self._find_best_cluster(processed, list(clusters.values()))
            if best_cluster and best_score >= self.similarity_threshold:
                member = self.addClusterMember(best_cluster.cluster_id, processed.news_processed_id)
                touched_cluster_ids.add(member.cluster_id)
                best_cluster.updateClusterScore(max(float(best_cluster.cluster_score), best_score))
                self.db.add(best_cluster)
            else:
                cluster = NewsCluster(
                    representative_news_processed_id=processed.news_processed_id,
                    source_id=processed.source_id,
                )
                cluster.updateClusterScore(1.0)
                self.db.add(cluster)
                self.db.commit()
                self.db.refresh(cluster)
                self.addClusterMember(cluster.cluster_id, processed.news_processed_id)
                clusters[cluster.cluster_id] = cluster
                touched_cluster_ids.add(cluster.cluster_id)

        self.db.commit()

        finalized: list[NewsCluster] = []
        for cluster_id in touched_cluster_ids:
            representative = self.assignRepresentative(cluster_id)
            cluster = clusters.get(cluster_id) or self.db.query(NewsCluster).filter(NewsCluster.cluster_id == cluster_id).first()
            if cluster and representative:
                finalized.append(cluster)
                create_processing_log(
                    self.db,
                    news_processed_id=representative.news_processed_id,
                    stage="clustering",
                    status="success",
                    message=f"Cluster {cluster.cluster_id} generado con score {float(cluster.cluster_score):.3f}.",
                    model_version=f"hybrid:{self.similarity_threshold}",
                    execution_time_ms=0,
                )

        return finalized

    def calculateSimilarity(self, newsAId: int, newsBId: int) -> float:
        news_a = self._get_news_context(newsAId)
        news_b = self._get_news_context(newsBId)
        if not news_a or not news_b:
            return 0.0

        title_score = self._overlap_score(news_a.title_tokens, news_b.title_tokens)
        lead_score = self._jaccard_score(news_a.lead_tokens, news_b.lead_tokens)
        body_score = self._jaccard_score(news_a.body_tokens, news_b.body_tokens)
        content_score = max(lead_score, body_score)

        if title_score >= self.TITLE_BOOST_THRESHOLD:
            hybrid_score = (self.TITLE_WEIGHT * title_score) + (
                (1 - self.TITLE_WEIGHT) * content_score
            )
        else:
            hybrid_score = content_score

        return round(max(body_score, hybrid_score), 4)

    def assignRepresentative(self, clusterId: int) -> ProcessedNews | None:
        member_ids = [
            member.news_processed_id
            for member in self.db.query(ClusterMember).filter(ClusterMember.cluster_id == clusterId).all()
        ]
        if not member_ids:
            return None

        processed_items = (
            self.db.query(ProcessedNews)
            .filter(ProcessedNews.news_processed_id.in_(member_ids))
            .all()
        )
        if not processed_items:
            return None

        representative = max(
            processed_items,
            key=lambda item: self._average_similarity(item.news_processed_id, member_ids),
        )
        cluster = self.db.query(NewsCluster).filter(NewsCluster.cluster_id == clusterId).first()
        if cluster:
            cluster.assignRepresentative(representative.news_processed_id)
            cluster.updateClusterScore(self._cluster_average_score(clusterId))
            self.db.add(cluster)
            self.db.commit()
            self.db.refresh(cluster)
        return representative

    def addClusterMember(self, clusterId: int, newsProcessedId: int) -> ClusterMember:
        processed = (
            self.db.query(ProcessedNews)
            .filter(ProcessedNews.news_processed_id == newsProcessedId)
            .first()
        )
        if not processed:
            raise ValueError(f"ProcessedNews {newsProcessedId} no existe.")

        member = (
            self.db.query(ClusterMember)
            .filter(ClusterMember.news_processed_id == newsProcessedId)
            .first()
        )
        if not member:
            member = ClusterMember(
                cluster_id=clusterId,
                news_processed_id=newsProcessedId,
                source_id=processed.source_id,
            )
        else:
            member.attachToCluster(clusterId)

        self.db.add(member)
        self.db.commit()
        self.db.refresh(member)
        return member

    def _find_best_cluster(self, processed: ProcessedNews, clusters: list[NewsCluster]) -> tuple[NewsCluster | None, float]:
        best_cluster = None
        best_score = 0.0
        for cluster in clusters:
            if not cluster.representative_news_processed_id:
                continue
            score = self.calculateSimilarity(
                processed.news_processed_id,
                cluster.representative_news_processed_id,
            )
            if score > best_score:
                best_cluster = cluster
                best_score = score
        return best_cluster, best_score

    def _cluster_average_score(self, clusterId: int) -> float:
        member_ids = [
            member.news_processed_id
            for member in self.db.query(ClusterMember).filter(ClusterMember.cluster_id == clusterId).all()
        ]
        if len(member_ids) <= 1:
            return 1.0

        cluster = self.db.query(NewsCluster).filter(NewsCluster.cluster_id == clusterId).first()
        if not cluster or not cluster.representative_news_processed_id:
            return 0.0

        scores = [
            self.calculateSimilarity(cluster.representative_news_processed_id, member_id)
            for member_id in member_ids
            if member_id != cluster.representative_news_processed_id
        ]
        return round(sum(scores) / len(scores), 4) if scores else 1.0

    def _average_similarity(self, newsProcessedId: int, member_ids: list[int]) -> float:
        peer_ids = [member_id for member_id in member_ids if member_id != newsProcessedId]
        if not peer_ids:
            return 1.0
        scores = [self.calculateSimilarity(newsProcessedId, member_id) for member_id in peer_ids]
        return round(sum(scores) / len(scores), 4) if scores else 0.0

    def _get_news_context(self, newsProcessedId: int) -> _NewsTextContext | None:
        if newsProcessedId in self._news_context_cache:
            return self._news_context_cache[newsProcessedId]

        processed = (
            self.db.query(ProcessedNews)
            .filter(ProcessedNews.news_processed_id == newsProcessedId)
            .first()
        )
        if not processed:
            return None

        raw_news = (
            self.db.query(RawNews)
            .filter(RawNews.news_raw_id == processed.news_raw_id)
            .first()
        )
        title = raw_news.title_raw if raw_news else ""
        clean_text = processed.clean_text or ""

        context = _NewsTextContext(
            title_tokens=tuple(self._tokenize_text(title)),
            lead_tokens=tuple(self._tokenize_text(clean_text, limit=self.LEAD_TOKEN_LIMIT)),
            body_tokens=tuple(self._tokenize_text(clean_text)),
        )
        self._news_context_cache[newsProcessedId] = context
        return context

    @classmethod
    def _tokenize_text(cls, text: str, limit: int | None = None) -> list[str]:
        normalized = cls._normalize_text(text)
        if not normalized:
            return []

        tokens: list[str] = []
        seen: set[str] = set()
        for token in normalized.split():
            if token in cls.STOPWORDS:
                continue
            if len(token) <= 2 and not any(char.isdigit() for char in token):
                continue
            if token in seen:
                continue
            seen.add(token)
            tokens.append(token)
            if limit is not None and len(tokens) >= limit:
                break
        return tokens

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text or "")
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"(?<=\w)-(?=\w)", "", normalized)
        normalized = re.sub(r"[^\w\s]", " ", normalized.lower())
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    @staticmethod
    def _jaccard_score(tokensA: tuple[str, ...], tokensB: tuple[str, ...]) -> float:
        if not tokensA or not tokensB:
            return 0.0

        set_a = set(tokensA)
        set_b = set(tokensB)
        union = set_a | set_b
        if not union:
            return 0.0
        return len(set_a & set_b) / len(union)

    @staticmethod
    def _overlap_score(tokensA: tuple[str, ...], tokensB: tuple[str, ...]) -> float:
        if not tokensA or not tokensB:
            return 0.0

        set_a = set(tokensA)
        set_b = set(tokensB)
        min_size = min(len(set_a), len(set_b))
        if min_size == 0:
            return 0.0
        return len(set_a & set_b) / min_size
