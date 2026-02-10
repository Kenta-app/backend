# python
from app.scrapers.base_scraper import BaseScraper
from typing import List, Dict, Optional
from datetime import datetime
import logging
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

class ElComercioScraper(BaseScraper):
    def __init__(self):
        super().__init__("El Comercio", "https://elcomercio.pe/politica/")

    def _scrape_article(self, article_url: str, fecha_html_date, fecha_actual_date) -> Optional[Dict]:
        if not article_url.startswith('http'):
            article_url = f"https://elcomercio.pe{article_url}"
        article_soup = self.fetch_page(article_url)
        if not article_soup:
            return None
        if article_soup.select_one('div.story-header-headsubscription__text') == "Solo para suscriptores":
            return None

        title_elem = article_soup.select_one('h1.sht__title')
        summary_elem = article_soup.select_one('h2.sht__summary')
        contents = article_soup.select('p.story-contents__font-paragraph')
        content_text = " ".join([self.clean_text(p.get_text()) for p in contents])
        author = article_soup.select_one('a.s-aut__n')
        if author:
            author = author.get_text(strip=True)

        if not title_elem:
            return None

        return {
            'title': self.clean_text(title_elem.get_text()),
            'url': article_url,
            'summary': self.clean_text(summary_elem.get_text()) if summary_elem else None,
            'content': content_text,
            'source': self.source_name,
            'published_date': fecha_html_date,
            'scraped_date': fecha_actual_date,
            'author': author
        }

    def scrape(self) -> List[Dict]:
        articles = []
        try:

            soup = self.fetch_page(self.base_url)
            fecha_actual_date = datetime.now(ZoneInfo("America/Lima")).date()
            containers = soup.select('div.story-item')[:20]

            for container in containers:
                if len(articles) >= 5:
                    return articles

                fecha_html = container.select_one('.story-item__date-time')
                if not fecha_html:
                    continue
                fecha_html_date = datetime.strptime(fecha_html.text.strip(), "%d/%m/%Y").date()
                if fecha_html_date != fecha_actual_date:
                    continue

                link = container.select_one('a.story-item__title')
                if not link or not link.get('href'):
                    continue

                article = self._scrape_article(link.get('href'), fecha_html_date, fecha_actual_date)
                if article:
                    articles.append(article)

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")

        return articles


class LaRepublicaScraper(BaseScraper):
    def __init__(self):
        super().__init__("La Republica", "https://larepublica.pe/politica/")

    def _scrape_article(self, article_url: str, fecha_actual_date) -> Optional[Dict]:
        if not article_url.startswith('http'):
            article_url = f"https://larepublica.pe{article_url}"
        article_soup = self.fetch_page(article_url)
        if not article_soup:
            return None

        title_elem = article_soup.select_one('h1')
        summary_elem = article_soup.select_one('h2')
        contents = article_soup.select('div.MainContent_main__body__i6gEa p')
        published_date = None
        time_elem = article_soup.select_one('time')
        if time_elem:
            published_date = time_elem.get('datetime')
        author = article_soup.select_one('a.Author_author__redSocial_link__ZcaC8')
        if author:
            author = author.get_text(strip=True)
        content_text = " ".join([self.clean_text(p.get_text()) for p in contents])

        if not title_elem:
            return None

        return {
            'title': self.clean_text(title_elem.get_text()),
            'url': article_url,
            'summary': self.clean_text(summary_elem.get_text()) if summary_elem else None,
            'content': content_text,
            'source': self.source_name,
            'published_date': published_date,
            'scraped_date': fecha_actual_date,
            'author': author
        }

    def scrape(self) -> List[Dict]:
        articles = []
        try:
            soup = self.fetch_page(self.base_url)
            fecha_actual_date = datetime.now(ZoneInfo("America/Lima")).date()

            # Main story
            spotlight_new = soup.select_one('div.extend-link--outside')
            if spotlight_new:
                link = spotlight_new.select_one('a')
                if link and link.get('href'):
                    article = self._scrape_article(link.get('href'), fecha_actual_date)
                    if article:
                        articles.append(article)

            # Other news
            other_news = soup.select('div.ListSmallSection_list__small--item__ilSNu ')[:4]
            for container in other_news:
                link = container.select_one('a')
                if not link or not link.get('href'):
                    continue
                article = self._scrape_article(link.get('href'), fecha_actual_date)
                if article:
                    articles.append(article)

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")

        return articles


class Peru21Scraper(BaseScraper):
    def __init__(self):
        super().__init__("Peru21", "https://peru21.pe/politica/")

    def _scrape_article(self, article_url: str, fecha_html_date, fecha_actual_date) -> Optional[Dict]:
        if not article_url.startswith('http'):
            article_url = f"https://peru21.pe{article_url}"
        article_soup = self.fetch_page(article_url)
        if not article_soup:
            return None

        title_elem = article_soup.select_one('h1')
        summary_elem = article_soup.select_one('div.entradilla-full p')
        contents = article_soup.select('div.cuerpo-full')
        paragraphs = []
        for content_block in contents:
            for p in content_block.find_all('p'):
                if not p.find_parent("article.embedded-entity"):
                    paragraphs.append(p)
        content_text = [p.get_text(strip=True) for p in paragraphs]
        author = article_soup.select_one('div.firma-s1 div.field__item').get_text(strip=True)

        if not title_elem:
            return None

        return {
            'title': self.clean_text(title_elem.get_text()),
            'url': article_url,
            'summary': self.clean_text(summary_elem.get_text()) if summary_elem else None,
            'content': content_text,
            'source': self.source_name,
            'published_date': fecha_html_date,
            'scraped_date': fecha_actual_date,
            'author': author
        }

    def scrape(self) -> List[Dict]:
        articles = []
        try:
            soup = self.fetch_page(self.base_url)
            containers = soup.select('div.mt-3')[:5]
            fecha_actual_date = datetime.now(ZoneInfo("America/Lima")).date()


            for container in containers:
                fecha_html = container.select_one('.field--name-field-fecha-actualizacion')
                if not fecha_html:
                    continue
                fecha_html_date = datetime.strptime(fecha_html.text.strip()[:10], "%Y-%m-%d").date()
                if fecha_html_date != fecha_actual_date:
                    continue

                link = container.select_one('a')
                if not link or not link.get('href'):
                    continue


                article = self._scrape_article(link.get('href'), fecha_html_date, fecha_actual_date)
                if article:
                    articles.append(article)

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")

        return articles


class RPPNoticiasScraper(BaseScraper):
    def __init__(self):
        super().__init__("RPP Noticias", "https://rpp.pe/politica/")

    def _scrape_article(self, article_url: str, fecha_actual_date) -> Optional[Dict]:
        if not article_url.startswith('http'):
            article_url = f"https://rpp.pe{article_url}"
        article_soup = self.fetch_page(article_url)
        if not article_soup:
            return None

        title_elem = article_soup.select_one('h1.article__title')
        summary_elem = article_soup.select_one('h2')
        contents = article_soup.select('div.body p')
        published_date = None
        time_elem = article_soup.select_one('time')
        if time_elem:
            published_date = time_elem.get('datetime')
            if published_date:
                published_date = published_date.split("T")[0] # Extract date part only (2026-02-05T16:03:25-05:00)
        author = article_soup.select_one('div.article__author div a')
        if author:
            author = author.get_text(strip=True)
        content_text = " ".join([self.clean_text(p.get_text()) for p in contents])

        if not title_elem:
            return None

        return {
            'title': self.clean_text(title_elem.get_text()),
            'url': article_url,
            'summary': self.clean_text(summary_elem.get_text()) if summary_elem else None,
            'content': content_text,
            'source': self.source_name,
            'published_date': published_date,
            'scraped_date': fecha_actual_date,
            'author': author
        }

    def scrape(self) -> List[Dict]:
        articles = []
        try:

            soup = self.fetch_page(self.base_url)
            fecha_actual_date = datetime.now(ZoneInfo("America/Lima")).date()

            # Main story
            spotlight_new = soup.select_one('h2.news__title')
            if spotlight_new:
                link = spotlight_new.select_one('a')
                if link and link.get('href'):
                    article = self._scrape_article(link.get('href'), fecha_actual_date)
                    if article:
                        articles.append(article)

            # Other news
            containers = soup.select('div.grid-news div.col')

            for container in containers:
                if len(articles) >= 5:
                    return articles
                link = container.select_one('a')

                if not link or not link.get('href'):
                    continue

                article = self._scrape_article(link.get('href'), fecha_actual_date)
                if article:
                    articles.append(article)

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")

        return articles
