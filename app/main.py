from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from app.api_controllers import (
    admin_router,
    auth_router,
    interaction_router,
    news_router,
    pipeline_router,
)
from app.db.database import Base, SessionLocal, engine
from app.ml.pipeline import news_analysis_pipeline
from app.processed.models import ClusterMember, MlPrediction, NewsCluster, ProcessedNews, ProcessingLog, Summary
from app.raw.models import IngestionLog, RawNews, Source
from app.raw.source_catalog import seed_default_sources
from app.routers.ml_router import router as ml_router
from app.serving.models import NewsClick, NewsReaction, NewsView, PublishedNews, User
from app.tasks.scheduler import ScrapingScheduler

# Register SQLAlchemy models before create_all.
_ = (
    ClusterMember,
    IngestionLog,
    MlPrediction,
    NewsClick,
    NewsCluster,
    NewsReaction,
    NewsView,
    ProcessedNews,
    ProcessingLog,
    PublishedNews,
    RawNews,
    Source,
    Summary,
    User,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Kenta Backend", version="2.0.0")

app.include_router(auth_router)
app.include_router(news_router)
app.include_router(interaction_router)
app.include_router(admin_router)
app.include_router(pipeline_router)
app.include_router(ml_router, prefix="/ml", tags=["ML"])

ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "true").lower() in {"1", "true", "yes"}
WARM_UP_CLASSIFIER = os.getenv("ML_WARMUP_ON_STARTUP", "false").lower() in {"1", "true", "yes"}
SEED_DEFAULT_SOURCES = os.getenv("SEED_DEFAULT_SOURCES", "true").lower() in {"1", "true", "yes"}

scheduler = ScrapingScheduler() if ENABLE_SCHEDULER else None


@app.get("/health")
def healthcheck():
    return {
        "status": "ok",
        "classifierReady": news_analysis_pipeline.get_status()["classifier_ready"],
        "schedulerEnabled": scheduler is not None,
    }


@app.on_event("startup")
async def startup_event():
    """Initialize optional services on startup."""
    if SEED_DEFAULT_SOURCES:
        db = SessionLocal()
        try:
            seed_default_sources(db)
        finally:
            db.close()

    if scheduler is not None:
        scheduler.start()

    if WARM_UP_CLASSIFIER:
        news_analysis_pipeline.warm_up(include_summarizer=False)

    logger.info("Application started")


@app.on_event("shutdown")
async def shutdown_event():
    """Shutdown optional services."""
    if scheduler is not None:
        scheduler.shutdown()

    logger.info("Application shutdown")
