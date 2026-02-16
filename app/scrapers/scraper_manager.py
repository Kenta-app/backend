from typing import List
from sqlalchemy.orm import Session
from app.models.article import Article
from app.models.scrapinglog import ScrapingLog
from app.scrapers.scrapers import ElComercioScraper, RPPNoticiasScraper, LaRepublicaScraper, Peru21Scraper, AndinaScraper
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
                AndinaScraper(),
            #ElPeruanoScraper()
            # Agregar más scrapers aquí
        ]

    def run_all_scrapers(self, db: Session) -> List[ScrapingLog]:
        """Ejecuta todos los scrapers configurados. Si uno falla, se sigue con el siguiente."""
        logs = []
        for scraper in self.scrapers:
            logger.info(f"Ejecutando scraper: {scraper.source_name}")
            try:
                log = self._run_single_scraper(scraper, db)
                logs.append(log)
            except Exception as e:
                logger.error(f"Scraper {scraper.source_name} falló por completo: {e}")
                log = ScrapingLog(
                    source=scraper.source_name,
                    status="error",
                    error_message=str(e),
                    started_at=datetime.now(),
                    finished_at=datetime.now(),
                )
                db.add(log)
                db.commit()
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
            seen_urls = set()  # evita duplicados dentro del mismo lote (ej. La República repite URLs)

            # 1️⃣ Insertar solo artículos nuevos
            for article_data in articles_data:
                url = article_data.get('url')
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                existing = db.query(Article).filter(Article.url == url).first()
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
            num_summaries = len(new_articles)
            if num_summaries > 0:
                logger.info(f"Generating {num_summaries} summaries for {scraper.source_name}...")
            for i, article in enumerate(new_articles):
                summary_text = summarize(article.content)
                summary = Summary(
                    article_id=article.id,
                    summary_text=summary_text,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                db.add(summary)
                if (i + 1) % 5 == 0 or (i + 1) == num_summaries:
                    logger.info(f"  {scraper.source_name}: summary {i + 1}/{num_summaries} done")
            if num_summaries > 0:
                logger.info(f"Summaries done for {scraper.source_name}")
            db.commit()

        except Exception as e:
            db.rollback()
            log.status = "error"
            log.error_message = str(e)
            log.finished_at = datetime.now()
            logger.error(f"Error in {scraper.source_name}: {str(e)}")
            db.add(log)  # re-asociar tras rollback para que el commit guarde el estado
            db.commit()
            return log

        db.commit()
        db.refresh(log)
        return log