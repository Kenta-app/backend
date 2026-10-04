from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import case, func
from sqlalchemy.orm import aliased

from app.db.database import SessionLocal
from app.processed.models import (
    ClusterMember,
    JustificationRun,
    JustificationSource,
    MlPrediction,
    NewsCluster,
    ProcessedNews,
)
from app.raw.models import RawNews, Source
from app.serving.models import PublishedNews


def pct(value: int, total: int) -> float:
    return round(100 * value / total, 2) if total else 0.0


def ensure_run_table(db) -> None:
    JustificationRun.__table__.create(bind=db.get_bind(), checkfirst=True)


def main() -> int:
    db = SessionLocal()
    try:
        ensure_run_table(db)
        source_counts = (
            db.query(
                JustificationSource.prediction_id.label("prediction_id"),
                func.count(JustificationSource.justification_source_id).label("source_count"),
            )
            .group_by(JustificationSource.prediction_id)
            .subquery()
        )
        run_counts = (
            db.query(
                JustificationRun.prediction_id.label("prediction_id"),
                func.count(JustificationRun.run_id).label("attempts"),
                func.max(JustificationRun.created_at).label("last_attempt_at"),
                func.max(
                    case(
                        (JustificationRun.status == "success", 1),
                        else_=0,
                    )
                ).label("has_success"),
                func.max(
                    case(
                        (JustificationRun.status == "no_sources", 1),
                        else_=0,
                    )
                ).label("has_no_sources"),
                func.max(
                    case(
                        (JustificationRun.status == "failed", 1),
                        else_=0,
                    )
                ).label("has_failed"),
            )
            .group_by(JustificationRun.prediction_id)
            .subquery()
        )
        representative = aliased(ClusterMember)
        alternative = aliased(ClusterMember)
        alternative_processed = aliased(ProcessedNews)
        alternative_raw = aliased(RawNews)
        alternative_source = aliased(Source)
        try:
            cluster_min_score = float(os.getenv("RELATED_CLUSTER_MIN_SCORE", "0.60"))
        except ValueError:
            cluster_min_score = 0.60
        cluster_min_score = min(1.0, max(0.0, cluster_min_score))
        local_counts = (
            db.query(
                PublishedNews.news_id.label("news_id"),
                func.count(alternative.news_processed_id).label("local_source_count"),
            )
            .join(
                representative,
                representative.news_processed_id
                == PublishedNews.representative_news_processed_id,
            )
            .join(NewsCluster, NewsCluster.cluster_id == representative.cluster_id)
            .join(
                alternative,
                (alternative.cluster_id == representative.cluster_id)
                & (alternative.news_processed_id != representative.news_processed_id)
                & (alternative.source_id != PublishedNews.source_id),
            )
            .join(
                alternative_processed,
                alternative_processed.news_processed_id
                == alternative.news_processed_id,
            )
            .join(
                alternative_raw,
                alternative_raw.news_raw_id == alternative_processed.news_raw_id,
            )
            .join(
                alternative_source,
                alternative_source.source_id == alternative_raw.source_id,
            )
            .filter(
                NewsCluster.cluster_score >= cluster_min_score,
                alternative_source.type == "web",
                alternative_raw.original_url.isnot(None),
                alternative_raw.original_url != "",
                alternative_raw.original_url != PublishedNews.original_url,
            )
            .group_by(PublishedNews.news_id)
            .subquery()
        )
        rows = (
            db.query(
                PublishedNews.content_type,
                Source.name,
                func.count(PublishedNews.news_id).label("total"),
                func.sum(
                    case(
                        (
                            (run_counts.c.attempts.isnot(None))
                            | (func.coalesce(source_counts.c.source_count, 0) > 0),
                            1,
                        ),
                        else_=0,
                    )
                ).label("attempted"),
                func.sum(
                    case((func.coalesce(source_counts.c.source_count, 0) > 0, 1), else_=0)
                ).label("with_grounded_sources"),
                func.sum(
                    case(
                        (func.coalesce(local_counts.c.local_source_count, 0) > 0, 1),
                        else_=0,
                    )
                ).label("with_cluster_sources"),
                func.sum(
                    case(
                        (
                            (func.coalesce(source_counts.c.source_count, 0) > 0)
                            | (func.coalesce(local_counts.c.local_source_count, 0) > 0),
                            1,
                        ),
                        else_=0,
                    )
                ).label("with_displayable_sources"),
                func.sum(
                    case(
                        (
                            (func.coalesce(source_counts.c.source_count, 0) == 0)
                            & (run_counts.c.has_no_sources == 1),
                            1,
                        ),
                        else_=0,
                    )
                ).label("searched_without_sources"),
                func.sum(
                    case((run_counts.c.has_failed == 1, 1), else_=0)
                ).label("failed"),
                func.avg(func.coalesce(source_counts.c.source_count, 0)).label("avg_sources"),
            )
            .join(
                MlPrediction,
                MlPrediction.representative_news_processed_id
                == PublishedNews.representative_news_processed_id,
            )
            .join(Source, Source.source_id == PublishedNews.source_id)
            .outerjoin(source_counts, source_counts.c.prediction_id == MlPrediction.prediction_id)
            .outerjoin(run_counts, run_counts.c.prediction_id == MlPrediction.prediction_id)
            .outerjoin(local_counts, local_counts.c.news_id == PublishedNews.news_id)
            .filter(PublishedNews.published_at.isnot(None))
            .group_by(PublishedNews.content_type, Source.name)
            .order_by(Source.name)
            .all()
        )

        total = sum(int(row.total or 0) for row in rows)
        attempted = sum(int(row.attempted or 0) for row in rows)
        with_grounded_sources = sum(int(row.with_grounded_sources or 0) for row in rows)
        with_cluster_sources = sum(int(row.with_cluster_sources or 0) for row in rows)
        with_displayable_sources = sum(int(row.with_displayable_sources or 0) for row in rows)
        without_sources = sum(int(row.searched_without_sources or 0) for row in rows)
        failed = sum(int(row.failed or 0) for row in rows)
        pending = total - attempted

        print("Related sources coverage")
        print(f"total_published={total}")
        print(f"attempted={attempted} ({pct(attempted, total)}%)")
        print(
            f"with_grounded_sources={with_grounded_sources} "
            f"({pct(with_grounded_sources, total)}% of total, "
            f"{pct(with_grounded_sources, attempted)}% of attempted)"
        )
        print(
            f"with_cluster_sources={with_cluster_sources} "
            f"({pct(with_cluster_sources, total)}% of total)"
        )
        print(
            f"displayable_with_sources={with_displayable_sources} "
            f"({pct(with_displayable_sources, total)}% of total)"
        )
        print(
            f"displayable_without_sources={total - with_displayable_sources} "
            f"({pct(total - with_displayable_sources, total)}% of total)"
        )
        print(f"searched_without_sources={without_sources} ({pct(without_sources, attempted)}% of attempted)")
        print(f"failed={failed} ({pct(failed, attempted)}% of attempted)")
        print(f"pending={pending} ({pct(pending, total)}%)")
        print("")
        print("By source")
        for row in rows:
            row_total = int(row.total or 0)
            row_attempted = int(row.attempted or 0)
            row_with_grounded = int(row.with_grounded_sources or 0)
            row_with_cluster = int(row.with_cluster_sources or 0)
            row_displayable = int(row.with_displayable_sources or 0)
            row_without_sources = int(row.searched_without_sources or 0)
            row_failed = int(row.failed or 0)
            row_pending = row_total - row_attempted
            print(
                f"{row.content_type or 'unknown'} | {row.name}: "
                f"total={row_total}, attempted={row_attempted}, "
                f"grounded={row_with_grounded}, cluster={row_with_cluster}, "
                f"displayable={row_displayable}, no_sources={row_without_sources}, "
                f"failed={row_failed}, pending={row_pending}, "
                f"avg_sources={float(row.avg_sources or 0):.2f}"
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
