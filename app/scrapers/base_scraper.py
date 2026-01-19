from abc import ABC, abstractmethod
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BaseScraper(ABC):
    def __init__(self, source_name: str, base_url: str):
        self.source_name = source_name
        self.base_url = base_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def fetch_page(self, url: str) -> BeautifulSoup:
        """Obtiene y parsea una página"""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            raise

    @abstractmethod
    def scrape(self) -> List[Dict]:
        """Implementar la lógica específica de scraping"""
        pass

    def clean_text(self, text: str) -> str:
        """Limpia el texto extraído"""
        if not text:
            return ""
        return " ".join(text.split()).strip()