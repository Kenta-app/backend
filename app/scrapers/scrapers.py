from app.scrapers.base_scraper import BaseScraper
from typing import List, Dict, Optional
from datetime import datetime
import logging
import requests
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class StructuredPeruNewsScraper(BaseScraper):
    """Shared extractor for Peruvian outlets with stable article pages."""

    article_link_selector = "a[href]"
    article_path_marker = ""
    body_selectors = ("article p", "main p")

    def _discover_urls(self) -> list[str]:
        soup = self.fetch_page(self.base_url)
        if not soup:
            return []
        urls = []
        allowed_host = (urlparse(self.base_url).hostname or "").removeprefix("www.")
        for link in soup.select(self.article_link_selector):
            href = link.get("href")
            if not href:
                continue
            url = urljoin(self.base_url, href).split("#", 1)[0]
            parsed = urlparse(url)
            parsed_host = (parsed.hostname or "").removeprefix("www.")
            if parsed.scheme != "https" or parsed_host != allowed_host:
                continue
            if self.article_path_marker and self.article_path_marker not in parsed.path:
                continue
            if url not in urls:
                urls.append(url)
        return urls

    def _scrape_article(self, article_url: str, scraped_date) -> Optional[Dict]:
        soup = self.fetch_page(article_url)
        if not soup:
            return None
        title_elem = soup.select_one("h1")
        summary_elem = soup.select_one("h2, h5")
        best = ""
        for selector in self.body_selectors:
            nodes = soup.select(selector)
            text = " ".join(self.clean_text(node.get_text(" ", strip=True)) for node in nodes)
            if len(text) > len(best):
                best = text
        if not title_elem or len(best) < 250:
            return None
        time_elem = soup.select_one("time[datetime]")
        return {
            "title": self.clean_text(title_elem.get_text(" ", strip=True)),
            "url": article_url,
            "image_url": self.extract_image_url(soup, article_url),
            "summary": self.clean_text(summary_elem.get_text(" ", strip=True)) if summary_elem else None,
            "content": best,
            "source": self.source_name,
            "published_date": time_elem.get("datetime") if time_elem else None,
            "scraped_date": scraped_date,
            "author": None,
        }

    def scrape(self) -> List[Dict]:
        scraped_date = datetime.now(ZoneInfo("America/Lima")).date()
        articles = []
        try:
            for url in self._discover_urls():
                if len(articles) >= self.max_articles_per_run:
                    break
                article = self._scrape_article(url, scraped_date)
                if article:
                    articles.append(article)
        except Exception as exc:
            logger.error("Error scraping %s: %s", self.source_name, exc)
        return articles

class AndinaScraper(StructuredPeruNewsScraper):
    article_path_marker = "/noticia-"
    body_selectors = (
        "div.col.xl12.no-padding600.columna.linknotas",
        "article p",
        "main p",
    )

    def __init__(self):
        super().__init__("Agencia Andina", "https://andina.pe/agencia/seccion-politica-17.aspx")


class ElPeruanoScraper(StructuredPeruNewsScraper):
    article_path_marker = "/noticia/"
    body_selectors = (".flow-text", "article p", "main p")

    def __init__(self):
        super().__init__("El Peruano", "https://elperuano.pe/")

    def _discover_urls(self) -> list[str]:
        urls = []
        for endpoint in ("_GetPortadaPrincipal", "_GetNoticiasDestacadas", "_GetNoticiasLoUltimo"):
            response = requests.get(
                f"https://elperuano.pe/Portal/{endpoint}", headers=self.headers, timeout=10
            )
            response.raise_for_status()
            payload = response.json()
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                value = item.get("URLFriendLy") if isinstance(item, dict) else None
                if value:
                    url = urljoin(self.base_url, value)
                    if url not in urls:
                        urls.append(url)
        return urls

class ElComercioScraper(BaseScraper):
    def __init__(self):
        super().__init__("El Comercio", "https://elcomercio.pe/politica/")

    def _scrape_article(self, article_url: str, fecha_html_date, fecha_actual_date) -> Optional[Dict]:
        if not article_url.startswith('http'):
            article_url = f"https://elcomercio.pe{article_url}"
        if '/ecdata/' in article_url:
            return None

        article_soup = self.fetch_page(article_url)

        if not article_soup:
            return None

        subscription_notice = article_soup.select_one('div.story-header-headsubscription__text')
        if subscription_notice and "Solo para suscriptores" in subscription_notice.get_text(" ", strip=True):
            return None

        title_elem = article_soup.select_one('h1')
        summary_elem = article_soup.select_one('h2')
        contents = article_soup.select(
            'p.sc__font-paragraph, '
            'article p.sc__font-paragraph, '
            'article div.story-content p, '
            'article section p'
        )
        if not contents:
            contents = article_soup.select('article p')
        paragraphs = [self.clean_text(p.get_text()) for p in contents if self.clean_text(p.get_text())]
        content_text = " ".join(paragraphs)
        author = article_soup.select_one('a.sc__author-nd-a')

        fecha_html=article_soup.find("time")

        if fecha_html:
            raw_datetime = fecha_html.get("datetime")

            if raw_datetime:
                fecha_html_date = raw_datetime.split("T")[0]

        if author:
            author = author.get_text(strip=True)

        if not title_elem or len(content_text) < 80:
            return None

        return {
            'title': self.clean_text(title_elem.get_text()),
            'url': article_url,
            'image_url': self.extract_image_url(article_soup, article_url),
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
            containers = soup.select('div.story-item')

            for container in containers:
                if len(articles) >= self.max_articles_per_run:
                    break
                link = container.select_one('a.story-item__title')
                if not link or not link.get('href'):
                    continue
                if '/ecdata/' in link.get('href'):
                    continue

                article = self._scrape_article(link.get('href'), None, fecha_actual_date)
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
        contents = article_soup.select(
            'div.MainContent_main__body__i6gEa p, '
            'article p, main article p, div[class*="MainContent_main__body"] p'
        )
        published_date = None
        time_elem = article_soup.select_one('time')
        if time_elem:
            published_date = time_elem.get('datetime')
        author = article_soup.select_one('a.Author_author__redSocial_link__ZcaC8')
        if author:
            author = author.get_text(strip=True)
        content_text = " ".join([self.clean_text(p.get_text()) for p in contents])

        if not title_elem or len(content_text) < 80:
            return None

        return {
            'title': self.clean_text(title_elem.get_text()),
            'url': article_url,
            'image_url': self.extract_image_url(article_soup, article_url),
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
            other_news = soup.select('div.ListSection_list__section--item__zeP_z')
            for container in other_news:
                if len(articles) >= self.max_articles_per_run:
                    break
                link = container.select_one('a.extend-link')
                if not link or not link.get('href'):
                    continue
                article = self._scrape_article(link.get('href'), fecha_actual_date)
                if article:
                    articles.append(article)

            # CSS-module class names change frequently. Use semantic political
            # article links as a stable fallback and deduplicate by URL.
            seen_urls = {item["url"] for item in articles}
            for link in soup.select('a[href*="/politica/"]'):
                if len(articles) >= self.max_articles_per_run:
                    break
                href = link.get('href')
                if not href:
                    continue
                article_url = urljoin(self.base_url, href).split('#', 1)[0]
                if article_url.rstrip('/') == self.base_url.rstrip('/') or article_url in seen_urls:
                    continue
                article = self._scrape_article(article_url, fecha_actual_date)
                if article:
                    articles.append(article)
                    seen_urls.add(article_url)

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
        if not paragraphs:
            paragraphs = article_soup.select('article p, main p')
        content_text = [p.get_text(strip=True) for p in paragraphs]
        author_elem = article_soup.select_one('div.firma-s1 div.field__item')
        author = author_elem.get_text(strip=True) if author_elem else None

        if not title_elem or len(content_text) < 80:
            return None

        return {
            'title': self.clean_text(title_elem.get_text()),
            'url': article_url,
            'image_url': self.extract_image_url(article_soup, article_url),
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
            containers = soup.select('div.mt-3')
            fecha_actual_date = datetime.now(ZoneInfo("America/Lima")).date()


            for container in containers:
                if len(articles) >= self.max_articles_per_run:
                    break
                fecha_html = container.select_one('.field--name-field-fecha-actualizacion')
                if not fecha_html:
                    continue
                fecha_html_date = datetime.strptime(fecha_html.text.strip()[:10], "%Y-%m-%d").date()
                if fecha_html_date != fecha_actual_date:
                    continue

                link = container.select_one('a')
                if not link or not link.get('href'):
                    continue


                try:
                    article = self._scrape_article(link.get('href'), fecha_html_date, fecha_actual_date)
                except Exception as article_error:
                    logger.warning(f"Error parsing article {link.get('href')}: {article_error}")
                    continue
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

        if not title_elem or len(content_text) < 80:
            return None

        return {
            'title': self.clean_text(title_elem.get_text()),
            'url': article_url,
            'image_url': self.extract_image_url(article_soup, article_url),
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
            # containers = soup.select('div.grid-news div.col')

            big_container = soup.select_one('div.column-fluid')
            containers = big_container.select('article.news') if big_container else []

            for container in containers:
                if len(articles) >= self.max_articles_per_run:
                    break
                link = container.select_one('a')

                if not link or not link.get('href'):
                    continue

                article = self._scrape_article(link.get('href'), fecha_actual_date)
                if article:
                    articles.append(article)

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")

        return articles
