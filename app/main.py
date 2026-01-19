from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import logging

from app.db.database import engine, get_db, Base
from app.models.article import Article
from app.models.scrapinglog import  ScrapingLog
from app.schemas.articlebase import ArticleResponse, ScrapingLogResponse
from app.scrapers.scraper_manager import ScraperManager
from app.tasks.scheduler import ScrapingScheduler

# Crear tablas
Base.metadata.create_all(bind=engine)

app = FastAPI(title="News Scraper API", version="1.0.0")

# Inicializar scheduler
scheduler = ScrapingScheduler()

@app.on_event("startup")
async def startup_event():
    """Inicia el scheduler al arrancar la aplicación"""
    scheduler.start()
    logging.info("Application started, scheduler is running")

@app.on_event("shutdown")
async def shutdown_event():
    """Detiene el scheduler al cerrar la aplicación"""
    scheduler.shutdown()
    logging.info("Application shutdown")
