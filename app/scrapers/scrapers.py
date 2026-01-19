from app.scrapers.base_scraper import BaseScraper
from typing import List, Dict
from datetime import datetime
import logging
from zoneinfo import ZoneInfo

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
        super().__init__("El Comercio", "https://elcomercio.pe/politica/")

    def scrape(self) -> List[Dict]:
        """Ejemplo de scraper para El Comercio (adaptar según estructura real)"""
        articles = []
        try:
            soup = self.fetch_page(self.base_url)

            containers=soup.select('div.story-item')[:13]

            print(len(containers))

            for container in containers:

                fecha_html=container.select_one('.story-item__date-time').text.strip()
                fecha_html_date = datetime.strptime(fecha_html, "%d/%m/%Y").date()
                fecha_actual_date = datetime.now(ZoneInfo("America/Lima")).date()


                if fecha_html_date != fecha_actual_date:
                    continue
                link= container.select_one('a.story-item__title')

                article_url=link.get('href')
                if not article_url.startswith('http'):
                    article_url = f"https://elcomercio.pe{article_url}"
                article_soup=self.fetch_page(article_url)

                if article_soup:
                    if article_soup.select_one('div.story-header-headsubscription__text')=="Solo para suscriptores":
                        continue

                title_elem = article_soup.select_one('h1.sht__title')
                summary_elem = article_soup.select_one('h2.sht__summary')

                contents=article_soup.select('p.story-contents__font-paragraph')

                content_text = " ".join([self.clean_text(p.get_text()) for p in contents])
                author=article_soup.select_one('a.s-aut__n')
                if title_elem:
                    article = {
                        'title': self.clean_text(title_elem.get_text()),
                        'url': article_url,
                        'summary': self.clean_text(summary_elem.get_text()) if summary_elem else None,
                        'content': content_text,
                        'source': self.source_name,
                        'published_date': fecha_html_date,
                        'scraped_date': fecha_actual_date,
                        'author':author
                    }
                    articles.append(article)

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")

        return articles