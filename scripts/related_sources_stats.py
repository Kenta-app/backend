from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import case, func

from app.db.database import SessionLocal
from app.processed.models import JustificationRun, JustificationSource, MlPrediction
from app.raw.models import Source
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
        rows = (
            db.query(
                PublishedNews.content_type,
                Source.name,
                func.count(PublishedNews.news_id).label("total"),
                func.sum(
                    case((run_counts.c.attempts.isnot(None), 1), else_=0)
                ).label("attempted"),
                func.sum(
                    case((func.coalesce(source_counts.c.source_count, 0) > 0, 1), else_=0)
                ).label("with_sources"),
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
            .filter(PublishedNews.published_at.isnot(None))
            .group_by(PublishedNews.content_type, Source.name)
            .order_by(Source.name)
            .all()
        )

        total = sum(int(row.total or 0) for row in rows)
        attempted = sum(int(row.attempted or 0) for row in rows)
        with_sources = sum(int(row.with_sources or 0) for row in rows)
        without_sources = sum(int(row.searched_without_sources or 0) for row in rows)
        failed = sum(int(row.failed or 0) for row in rows)
        pending = total - attempted

        print("Related sources coverage")
        print(f"total_published={total}")
        print(f"attempted={attempted} ({pct(attempted, total)}%)")
        print(f"with_sources={with_sources} ({pct(with_sources, total)}% of total, {pct(with_sources, attempted)}% of attempted)")
        print(f"searched_without_sources={without_sources} ({pct(without_sources, attempted)}% of attempted)")
        print(f"failed={failed} ({pct(failed, attempted)}% of attempted)")
        print(f"pending={pending} ({pct(pending, total)}%)")
        print("")
        print("By source")
        for row in rows:
            row_total = int(row.total or 0)
            row_attempted = int(row.attempted or 0)
            row_with_sources = int(row.with_sources or 0)
            row_without_sources = int(row.searched_without_sources or 0)
            row_failed = int(row.failed or 0)
            row_pending = row_total - row_attempted
            print(
                f"{row.content_type or 'unknown'} | {row.name}: "
                f"total={row_total}, attempted={row_attempted}, "
                f"with_sources={row_with_sources}, no_sources={row_without_sources}, "
                f"failed={row_failed}, pending={row_pending}, "
                f"avg_sources={float(row.avg_sources or 0):.2f}"
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
