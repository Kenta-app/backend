from app.scrapers.base_scraper import BaseScraper
from typing import List, Dict
from datetime import datetime
import logging
logger = logging.getLogger(__name__)
class BBCNewsScraper(BaseScraper):
    def __init__(self):
        super().__init__("BBC News", "https://www.bbc.com/news")

    def scrape(self) -> List[Dict]:
        """Ejemplo de scraper para BBC (adaptar según estructura real)"""
        articles = []
        try:
            soup = self.fetch_page(self.base_url)

            # Esto es un ejemplo - ajustar selectores según la página real
            article_elements = soup.select('article.gs-c-promo')[:10]

            for element in article_elements:
                try:
                    title_elem = element.select_one('h3')
                    link_elem = element.select_one('a')
                    summary_elem = element.select_one('p')

                    if title_elem and link_elem:
                        url = link_elem.get('href', '')
                        if not url.startswith('http'):
                            url = f"https://www.bbc.com{url}"

                        article = {
                            'title': self.clean_text(title_elem.get_text()),
                            'url': url,
                            'summary': self.clean_text(summary_elem.get_text()) if summary_elem else None,
                            'source': self.source_name,
                            'published_date': datetime.utcnow(),
                            'scraped_date': datetime.utcnow()
                        }
                        articles.append(article)
                except Exception as e:
                    logger.error(f"Error parsing article: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")

        return articles
class ElComercioScraper(BaseScraper):
    def __init__(self):
        super().__init__("El Comercio", "https://elcomercio.pe/politica/jose-jeri-dice-que-ministro-del-interior-lo-acompano-a-chifa-y-ofrece-disculpas-publicas-por-ingresar-encapuchado-noticia/")

    def scrape(self) -> List[Dict]:
        """Ejemplo de scraper para El Comercio (adaptar según estructura real)"""
        articles = []
        try:
            soup = self.fetch_page(self.base_url)

            title_elem = soup.select_one('h1')
            summary_elem = soup.select_one('h2')
            contents=soup.select('p.story-contents__font-paragraph')
            published_date=soup.select_one('time')
            content_text = " ".join([self.clean_text(p.get_text()) for p in contents])

            if title_elem:
                article = {
                    'title': self.clean_text(title_elem.get_text()),
                    'url': self.base_url,
                    'summary': self.clean_text(summary_elem.get_text()) if summary_elem else None,
                    'content': content_text,
                    'source': self.source_name,
                    'published_date': published_date,
                    'scraped_date': datetime.now()
                }
                articles.append(article)

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")

        return articles