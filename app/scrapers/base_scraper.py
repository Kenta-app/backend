from abc import ABC, abstractmethod
from typing import List, Dict
import os
import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin, urlparse

try:
    import cloudscraper
except ImportError:
    cloudscraper = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def extract_representative_image_url(soup: BeautifulSoup, page_url: str) -> str | None:
    """Extrae una URL HTTP(S) representativa desde metadatos sociales."""
    selectors = (
        'meta[property="og:image:secure_url"]',
        'meta[property="og:image"]',
        'meta[name="twitter:image"]',
        'meta[property="twitter:image"]',
    )
    for selector in selectors:
        element = soup.select_one(selector)
        content = element.get("content") if element else None
        if not content:
            continue

        image_url = urljoin(page_url, content.strip())
        parsed = urlparse(image_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue

        if parsed.scheme == "http":
            image_url = parsed._replace(scheme="https").geturl()
        return image_url

    return None

class BaseScraper(ABC):
    def __init__(self, source_name: str, base_url: str):
        self.source_name = source_name
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'es-PE,es;q=0.9,en;q=0.8',
        }
        self._cloudscraper_client = None

    @property
    def max_articles_per_run(self) -> int:
        """Evita que una fuente lenta bloquee el ciclo completo de scraping."""
        try:
            configured = int(os.getenv("SCRAPER_MAX_ARTICLES_PER_SOURCE", "10"))
        except ValueError:
            configured = 10
        return min(max(configured, 1), 50)

    def fetch_page(self, url: str) -> BeautifulSoup:
        """Obtiene y parsea una página"""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            if response.status_code in {403, 429}:
                return self._fetch_page_with_cloudscraper(url)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            return self._fetch_page_with_cloudscraper(url)

    def _fetch_page_with_cloudscraper(self, url: str) -> BeautifulSoup:
        if cloudscraper is None:
            raise RuntimeError(
                "cloudscraper no esta instalado y el sitio bloqueo la solicitud. "
                "Instala cloudscraper para habilitar el fallback anti-bot."
            )
        if self._cloudscraper_client is None:
            self._cloudscraper_client = cloudscraper.create_scraper(
                browser={"browser": "chrome", "platform": "windows", "mobile": False}
            )
        response = self._cloudscraper_client.get(url, headers=self.headers, timeout=15)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')

    @abstractmethod
    def scrape(self) -> List[Dict]:
        """Implementar la lógica específica de scraping"""
        pass

    def clean_text(self, text: str) -> str:
        """Limpia el texto extraído"""
        if not text:
            return ""
        return " ".join(text.split()).strip()

    def extract_image_url(self, soup: BeautifulSoup, page_url: str) -> str | None:
        """Extrae la imagen representativa publicada en los metadatos del artículo."""
        return extract_representative_image_url(soup, page_url)
