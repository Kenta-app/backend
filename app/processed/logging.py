from __future__ import annotations

from sqlalchemy.orm import Session

from app.processed.models import ProcessingLog


def create_processing_log(
    db: Session,
    *,
    news_processed_id: int,
    stage: str,
    status: str,
    message: str,
    model_version: str | None = None,
    execution_time_ms: int | None = None,
) -> ProcessingLog:
    log = ProcessingLog(
        news_processed_id=news_processed_id,
        stage=stage,
        status=status,
        message=message[:150] if message else None,
        model_version=(model_version or "")[:50] or None,
        execution_time_ms=execution_time_ms,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
