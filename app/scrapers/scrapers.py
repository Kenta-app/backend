# python
from sympy.parsing.sympy_parser import null

from bs4 import BeautifulSoup
from app.scrapers.base_scraper import BaseScraper
from typing import List, Dict, Optional
from datetime import datetime
import logging
from zoneinfo import ZoneInfo
import re

logger = logging.getLogger(__name__)

class ElComercioScraper(BaseScraper):
    def __init__(self):
        super().__init__("El Comercio", "https://elcomercio.pe/politica/")

    def _scrape_article(self, article_url: str, fecha_html_date, fecha_actual_date) -> Optional[Dict]:
        if not article_url.startswith('http'):
            article_url = f"https://elcomercio.pe{article_url}"
        article_soup = self.fetch_page(article_url)

        print("article_soup: ", article_url)

        if not article_soup:
            return None
        if article_soup.select_one('div.story-header-headsubscription__text') == "Solo para suscriptores":
            return None

        title_elem = article_soup.select_one('h1')
        summary_elem = article_soup.select_one('h2')
        contents = article_soup.select('p.sc__font-paragraph')
        content_text = " ".join([self.clean_text(p.get_text()) for p in contents])
        author = article_soup.select_one('a.sc__author-nd-a')

        fecha_html=article_soup.find("time")

        if fecha_html:
            raw_datetime = fecha_html.get("datetime")

            if raw_datetime:
                fecha_html_date = raw_datetime.split("T")[0]

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
            containers = soup.select('div.story-item')

            for container in containers:
                #if len(articles) >= 5:
                #    return articles


                #fecha_html_date = datetime.strptime(fecha_html.text.strip(), "%d/%m/%Y").date()

                #if fecha_html_date != fecha_actual_date:
                #    continue

                link = container.select_one('a.story-item__title')
                if not link or not link.get('href'):
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
            other_news = soup.select('div.ListSection_list__section--item__zeP_z')
            for container in other_news:
                link = container.select_one('a.extend-link')
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
            containers = soup.select('div.mt-3')
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
            # containers = soup.select('div.grid-news div.col')

            big_container = soup.select_one('div.column-fluid')
            containers = big_container.select('article.news') if big_container else []

            for container in containers:
                #if len(articles) >= 5:
                #    return articles
                link = container.select_one('a')

                if not link or not link.get('href'):
                    continue

                article = self._scrape_article(link.get('href'), fecha_actual_date)
                if article:
                    articles.append(article)

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")

        return articles

    '''
class ElPeruanoScraper(BaseScraper):
    def __init__(self):
        super().__init__("El Peruano", "https://elperuano.pe/politica/")

    def scrape(self) -> Optional[Dict]:
        articles=[]
        try:
            print("Scraping El Peruano...")
            soup = self.fetch_page(self.base_url)
            fecha_actual_date = datetime.now(ZoneInfo("America/Lima")).date()
            containers = soup.select('div.nota')[:3]

            for container in containers:
                link = container.select_one('a')
                print(container.select('div.skseccionnota'))
                if link:
                    print(link['href'])
                if not link or not link.get('href'):
                    continue

                article_url = link.get('href')

                print(article_url)

                if not article_url.startswith('http'):
                    article_url = f"https://elperuano.pe{article_url}"
                article_soup = self.fetch_page(article_url)
                if not article_soup:
                    continue

                title_elem = article_soup.select_one('h1')
                summary_elem = article_soup.select_one('h5')

                content_div = soup.select_one('#contenido')

                fecha_html_date = None
                content_text = None

                if content_div:
                    fecha_tag = content_div.select_one('strong.red-text')
                    if fecha_tag:
                        raw_fecha = fecha_tag.get_text(strip=True)  # ej: 15/02/2026
                        fecha_html_date = datetime.strptime(raw_fecha, "%d/%m/%Y").date()
                        fecha_tag.decompose()

                    content_text = " ".join(content_div.stripped_strings)


                author = 'Desconocido'


                #if author:
                #    author = author.get_text(strip=True)

                if not title_elem:
                    continue

                articles.append({
                    'title': self.clean_text(title_elem.get_text()),
                    'url': article_url,
                    'summary': self.clean_text(summary_elem.get_text()) if summary_elem else None,
                    'content': content_text,
                    'source': self.source_name,
                    'published_date': fecha_html_date,
                    'scraped_date': fecha_actual_date,
                    'author': author
                })

        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")
    
    '''
class AndinaScraper(BaseScraper):
    # Patrones para limpiar HTML del cuerpo (scripts, embeds, "Lea también" + enlace)
    _CHUNK_STRIP = (
        r'<script[^>]*>[\s\S]*?</script>',
        r'<iframe[^>]*>[\s\S]*?</iframe>',
        r'<div[^>]*class="[^"]*twitter[^"]*"[^>]*>[\s\S]*?</div>',
        r'<div[^>]*>\s*\[?(?:Lea|Lee|Lease) también:?\s*&nbsp;?\s*<a\s[^>]*>[\s\S]*?</a>\s*\]?\s*</div>',
        r'<div[^>]*>\s*<strong>(?:Lea|Lee|Lease) también:?</strong>\s*<a\s[^>]*>[\s\S]*?</a>\s*</div>',
        r'\[?(?:Lea|Lee|Lease) también:?\s*&nbsp;?\s*<a\s[^>]*>[\s\S]*?</a>\s*\]?',
        r'<strong>(?:Lea|Lee|Lease) también:?</strong>\s*<a\s[^>]*>[\s\S]*?</a>',
    )
    _CONTENT_STRIP = (
        r'\[(?:Lea|Lee|Lease) también:[^\]]*\]',
        r'(?:Lea|Lee|Lease) también:\s*\[[^\]]*\]',
    )
    _MESES_ES = {'ene': 1, 'enero': 1, 'feb': 2, 'febrero': 2, 'mar': 3, 'marzo': 3, 'abr': 4, 'abril': 4,
                 'may': 5, 'mayo': 5, 'jun': 6, 'junio': 6, 'jul': 7, 'julio': 7, 'ago': 8, 'agosto': 8,
                 'sep': 9, 'sept': 9, 'septiembre': 9, 'oct': 10, 'octubre': 10, 'nov': 11, 'noviembre': 11,
                 'dic': 12, 'diciembre': 12}

    def __init__(self):
        super().__init__("Andina", "https://andina.pe")

    def _parse_spanish_date(self, date_text: str, current_year: int) -> Optional[str]:
        """Parsea fecha en español 'feb. 15.' o 'febrero 15' a formato YYYY-MM-DD"""
        try:
            match = re.search(r'(\w+)\.?\s+(\d{1,2})', date_text)
            if match:
                mes_str, dia_str = match.group(1).lower(), match.group(2)
                if mes_str in self._MESES_ES and dia_str.isdigit():
                    mes, dia = self._MESES_ES[mes_str], int(dia_str)
                    return str(datetime(current_year, mes, dia).date())
        except Exception as e:
            logger.warning(f"Error parsing date '{date_text}': {str(e)}")
        return None

    def _scrape_article(self, article_url: str, fecha_actual_date) -> Optional[Dict]:
        """Extrae los datos de un artículo individual"""
        if not article_url.startswith('http'):
            article_url = article_url.lstrip('/')
            article_url = f"https://andina.pe/{article_url}" if article_url.startswith('agencia/') else f"https://andina.pe/agencia/{article_url}"

        article_soup = self.fetch_page(article_url)
        if not article_soup:
            return None

        # Extraer título
        title_elem = article_soup.select_one('h1')
        if not title_elem:
            return None

        # Resumen: puede venir de h2 o de la zona DESCRIPCION
        summary_elem = article_soup.select_one('h2')

        # Extraer fecha: "12:12 | Lima, feb. 15." -> YYYY-MM-DD
        published_date = None
        all_text = article_soup.get_text()
        date_pattern = r'(\d{1,2}):(\d{2})\s*\|\s*(\w+),\s*(\w+)\.?\s*(\d{1,2})'
        match = re.search(date_pattern, all_text)
        if match:
            mes_str = match.group(4).lower()
            dia_str = match.group(5)
            published_date = self._parse_spanish_date(f"{mes_str} {dia_str}", fecha_actual_date.year)
        if not published_date:
            time_elem = article_soup.select_one('time')
            if time_elem and time_elem.get('datetime'):
                published_date = time_elem.get('datetime', '').split('T')[0]

        # Descripción y cuerpo usando comentarios HTML
        description_text = ""
        body_text = ""
        html_str = str(article_soup)
        idx_desc = html_str.find('DESCRIPCION')
        idx_cont = html_str.find('CONTENIDO DE LA NOTICIA')
        idx_fin = html_str.upper().find('(FIN)')

        if idx_desc != -1 and idx_cont != -1 and idx_cont > idx_desc:
            end_desc = html_str.find('-->', idx_desc) + 3
            start_cont_comment = html_str.rfind('<!--', 0, idx_cont + 1)
            desc_html = html_str[end_desc:start_cont_comment]
            description_text = self.clean_text(BeautifulSoup(desc_html, 'html.parser').get_text(separator=' ', strip=True))

        if idx_cont != -1 and idx_fin != -1 and idx_fin > idx_cont:
            end_cont = html_str.find('-->', idx_cont) + 3
            chunk = html_str[end_cont:idx_fin]
            for pat in self._CHUNK_STRIP:
                chunk = re.sub(pat, '', chunk, flags=re.I)
            body_soup = BeautifulSoup(chunk, 'html.parser')
            for tag in body_soup.find_all(['nav', 'footer', 'header', 'aside']):
                tag.decompose()
            body_text = self.clean_text(body_soup.get_text(separator=' ', strip=True))

        content_text = f"{description_text}\n\n{body_text}".strip() if (description_text or body_text) else (self.clean_text(summary_elem.get_text()) if summary_elem else "")
        for pat in self._CONTENT_STRIP:
            content_text = re.sub(pat, ' ', content_text, flags=re.I)
        content_text = re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t]+', ' ', content_text)).strip()

        author = "Andina"

        return {
            'title': self.clean_text(title_elem.get_text()),
            'url': article_url,
            'summary': self.clean_text(summary_elem.get_text()) if summary_elem else (description_text or None),
            'content': content_text,
            'source': self.source_name,
            'published_date': published_date,
            'scraped_date': fecha_actual_date,
            'author': author
        }

    def scrape(self) -> List[Dict]:
        """Scraper principal que obtiene la lista de artículos de la sección de política"""
        articles = []
        try:
            soup = self.fetch_page("https://andina.pe/agencia/seccion-politica-17.aspx")
            if not soup:
                return articles
            fecha_actual_date = datetime.now(ZoneInfo("America/Lima")).date()
            base_agencia = "https://andina.pe/agencia"
            skip = {'facebook', 'twitter', 'sharer', 'linkedin', 'whatsapp'}

            def norm(href: str) -> str:
                href = (href or "").strip()
                if not href or "noticia-" not in href.lower() or any(x in href.lower() for x in skip):
                    return ""
                if href.startswith("http"):
                    return href if "andina.pe" in href and "noticia" in href else ""
                return f"https://andina.pe{href}" if href.startswith("/") else f"{base_agencia}/{href}"

            urls = (norm(a.get('href', '')) for a in soup.select('a[href*="noticia-"]'))
            article_urls = list(dict.fromkeys(u for u in urls if u))[:5]
            logger.info(f"Encontradas {len(article_urls)} URLs potenciales de artículos")
            for url in article_urls:
                try:
                    article = self._scrape_article(url, fecha_actual_date)
                    if article and article.get('content') and article.get('published_date'):
                        articles.append(article)
                except Exception as e:
                    logger.debug(f"Error scraping article {url}: {str(e)}")
        except Exception as e:
            logger.error(f"Error scraping {self.source_name}: {str(e)}")
        return articles

