from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import logging

from app.db.database import engine, get_db, Base
from app.models.article import Article
from app.models.scrapinglog import ScrapingLog
from app.schemas.articlebase import ArticleResponse, ScrapingLogResponse
from app.scrapers.scraper_manager import ScraperManager
from app.tasks.scheduler import ScrapingScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="News Scraper API", version="1.0.0")

# Inicializar scheduler
scheduler = ScrapingScheduler()

@app.on_event("startup")
async def startup_event():
    """Inicia el scheduler y crea las tablas al arrancar"""
    try:
        logger.info("DB URL -> %s", engine.url.render_as_string(hide_password=True))
        Base.metadata.create_all(bind=engine, checkfirst=True)
        logger.info("Tablas creadas o ya existentes")
    except Exception as e:
        logger.error(f"Error al crear tablas: {e}")

    scheduler.start()
    logger.info("Application started, scheduler is running")

@app.on_event("shutdown")
async def shutdown_event():
    """Detiene el scheduler al cerrar la aplicación"""
    scheduler.shutdown()
    logger.info("Application shutdown")

@app.get("/health")
async def health_check():
    """Endpoint de prueba para verificar que la API está activa"""
    return {"status": "ok", "message": "API is running"}