from typing import List
from sqlalchemy.orm import Session
from app.models.article import Article
from app.models.scrapinglog import ScrapingLog
from app.scrapers.scrapers import ElComercioScraper, RPPNoticiasScraper, LaRepublicaScraper, Peru21Scraper
from datetime import datetime
import logging
from app.models.summaries import Summary
from app.ml.summarizer import summarize


logger = logging.getLogger(__name__)


class ScraperManager:
    def __init__(self):
        self.scrapers = [
           ElComercioScraper(),
              RPPNoticiasScraper(),
              LaRepublicaScraper(),
                Peru21Scraper(),
            #ElPeruanoScraper()
            # Agregar más scrapers aquí
        ]

    def run_all_scrapers(self, db: Session) -> List[ScrapingLog]:
        """Ejecuta todos los scrapers configurados"""
        logs = []

        for scraper in self.scrapers:
            log = self._run_single_scraper(scraper, db)
            logs.append(log)

        return logs

    def _run_single_scraper(self, scraper, db: Session) -> ScrapingLog:
        """Ejecuta un scraper individual y registra resultados"""
        log = ScrapingLog(
            source=scraper.source_name,
            status="running",
            started_at=datetime.now()
        )
        db.add(log)
        db.commit()

        try:
            articles_data = scraper.scrape()
            saved_count = 0
            new_articles = []

            # 1️⃣ Insertar solo artículos nuevos
            for article_data in articles_data:
                existing = db.query(Article).filter(
                    Article.url == article_data['url']
                ).first()

                if not existing:
                    article = Article(**article_data)
                    db.add(article)
                    new_articles.append(article)
                    saved_count += 1

            db.commit()  # Necesario para que los nuevos tengan ID

            log.status = "success"
            log.articles_scraped = saved_count
            log.finished_at = datetime.now()

            logger.info(f"Scraped {saved_count} new articles from {scraper.source_name}")

            # 2️⃣ Generar resumen SOLO de los nuevos
            for article in new_articles:
                summary_text = summarize(article.content)

                summary = Summary(
                    article_id=article.id,
                    summary_text=summary_text,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )

                db.add(summary)

            db.commit()

        except Exception as e:
            db.rollback()
            log.status = "error"
            log.error_message = str(e)
            log.finished_at = datetime.now()
            logger.error(f"Error in {scraper.source_name}: {str(e)}")

        db.commit()
        db.refresh(log)
        return log