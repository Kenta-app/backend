from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.scrapers.scraper_manager  import ScraperManager
from app.db.database import  SessionLocal
import logging
import os

logger = logging.getLogger(__name__)


class ScrapingScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.scraper_manager = ScraperManager()

    def scheduled_scraping_job(self):
        """Tarea programada que ejecuta el scraping"""
        logger.info("Starting scheduled scraping job...")
        db = SessionLocal()
        try:
            logs = self.scraper_manager.run_all_scrapers(db)
            logger.info(f"Scraping job completed. Processed {len(logs)} sources.")
        except Exception as e:
            logger.error(f"Error in scheduled scraping: {str(e)}")
        finally:
            db.close()

    def start(self):
        """Inicia el scheduler"""
        hour = int(os.getenv("SCRAPING_SCHEDULE_HOUR", "6"))
        minute = int(os.getenv("SCRAPING_SCHEDULE_MINUTE", "0"))

        # Ejecutar todos los días a la hora configurada
        self.scheduler.add_job(
            self.scheduled_scraping_job,
            CronTrigger(hour=hour, minute=minute),
            id='daily_scraping',
            name='Daily news scraping',
            replace_existing=True
        )

        self.scheduler.start()
        logger.info(f"Scheduler started. Scraping will run daily at {hour:02d}:{minute:02d}")

    def shutdown(self):
        """Detiene el scheduler"""
        self.scheduler.shutdown()
        logger.info("Scheduler shutdown")
