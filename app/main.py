from fastapi import FastAPI
import logging

from app.db.database import engine, get_db, Base
from app.tasks.scheduler import ScrapingScheduler
from app.ml.roberta_loader import load_model
from app.routers.ml_router import router as ml_router
from app.controllers.article_controller import router as article_router


# Crear tablas
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Kenta App", version="1.0.0")

app.include_router(ml_router, prefix="/ml", tags=["ML"])
app.include_router(article_router, prefix="/articles", tags=["Articles"])


# Inicializar scheduler
scheduler = ScrapingScheduler()

@app.on_event("startup")
async def startup_event():
    """Inicia el scheduler al arrancar la aplicación"""
    scheduler.start()
    load_model()
    logging.info("Application started, scheduler is running")

@app.on_event("shutdown")
async def shutdown_event():
    """Detiene el scheduler al cerrar la aplicación"""
    scheduler.shutdown()
    logging.info("Application shutdown")
