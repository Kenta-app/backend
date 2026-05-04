from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.interfaces.ingestion_strategy import IIngestionStrategy
from app.raw.models import RawNews, Source
from app.scrapers.scrapers import (
    ElComercioScraper,
    LaRepublicaScraper,
    Peru21Scraper,
    RPPNoticiasScraper,
)

logger = logging.getLogger(__name__)


class WebScraperIngestion(IIngestionStrategy):
    def __init__(self, db: Session, httpClient: requests.Session | None = None):
        self.db = db
        self.httpClient = httpClient or requests.Session()
        self._current_source: Source | None = None
        self._scraper_registry = {
            "elcomercio.pe": ElComercioScraper(),
            "rpp.pe": RPPNoticiasScraper(),
            "larepublica.pe": LaRepublicaScraper(),
            "peru21.pe": Peru21Scraper(),
            "el comercio": ElComercioScraper(),
            "rpp noticias": RPPNoticiasScraper(),
            "la republica": LaRepublicaScraper(),
            "peru21": Peru21Scraper(),
        }

    def ingest(self, source_id: int) -> list[RawNews]:
        source = self.db.query(Source).filter(Source.source_id == source_id).first()
        if not source:
            raise ValueError(f"Source {source_id} no existe.")
        if not self.supports(source.type):
            raise ValueError(f"Source {source_id} no es compatible con WebScraperIngestion.")
        if not source.is_active:
            return []

        self._current_source = source
        raw_items = self._extract_items(source)

        ingested: list[RawNews] = []
        for item in raw_items:
            raw_news = RawNews(
                source_id=source.source_id,
                log_id=0,
                platform="web",
                source_account=source.name[:50],
                original_url=item.get("original_url") or source.base_url,
                title_raw=item.get("title_raw"),
                content_raw=self._coerce_text(item.get("content_raw")),
                author_raw=item.get("author_raw"),
                published_at=self._coerce_datetime(item.get("published_at")),
                scraped_at=self._coerce_datetime(item.get("scraped_at")) or datetime.utcnow(),
                status="pending",
            )
            if raw_news.validateContent():
                ingested.append(raw_news)

        return ingested

    def supports(self, source_type: str) -> bool:
        return source_type.lower() == "web"

    def fetchPage(self, url: str) -> str:
        response = self.httpClient.get(url, timeout=20)
        response.raise_for_status()
        return response.text

    def parseArticles(self, html: str) -> list[dict[str, Any]]:
        if not self._current_source:
            return []

        soup = BeautifulSoup(html, "html.parser")
        articles: list[dict[str, Any]] = []
        for link in soup.select("article a, h2 a, h3 a"):
            href = link.get("href")
            if not href:
                continue
            title = " ".join(link.get_text(" ", strip=True).split())
            if not title:
                continue
            articles.append(
                {
                    "original_url": urljoin(self._current_source.base_url, href),
                    "title_raw": title,
                    "content_raw": title,
                    "scraped_at": datetime.utcnow(),
                }
            )

        return articles[:10]

    def _extract_items(self, source: Source) -> list[dict[str, Any]]:
        scraper = self._resolve_scraper(source)
        if scraper is not None:
            extracted = scraper.scrape()
            normalized: list[dict[str, Any]] = []
            for item in extracted:
                normalized.append(
                    {
                        "original_url": item.get("url"),
                        "title_raw": item.get("title"),
                        "content_raw": self._coerce_text(item.get("content")),
                        "author_raw": item.get("author"),
                        "published_at": item.get("published_date"),
                        "scraped_at": item.get("scraped_date"),
                    }
                )
            return normalized

        html = self.fetchPage(source.base_url)
        return self.parseArticles(html)

    def _resolve_scraper(self, source: Source):
        base_url = (source.base_url or "").lower()
        name = (source.name or "").lower()
        for key, scraper in self._scraper_registry.items():
            if key in base_url or key == name:
                return scraper
        return None

    @staticmethod
    def _coerce_text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, list):
            value = " ".join(str(item) for item in value)
        return " ".join(str(value).split()) or None

    @staticmethod
    def _coerce_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        for parser in (
            datetime.fromisoformat,
            lambda v: datetime.strptime(v, "%Y-%m-%d"),
            lambda v: datetime.strptime(v, "%Y-%m-%d %H:%M:%S"),
        ):
            try:
                return parser(text)
            except ValueError:
                continue
        return None


class TwitterApiIngestion(IIngestionStrategy):
    def __init__(self, db: Session, apiKey: str | None = None, account: str | None = None):
        self.db = db
        self.apiKey = apiKey or os.getenv("TWITTER_API_KEY") or os.getenv("TWITTER_BEARER_TOKEN")
        self.account = account

    def ingest(self, source_id: int) -> list[RawNews]:
        source = self.db.query(Source).filter(Source.source_id == source_id).first()
        if not source:
            raise ValueError(f"Source {source_id} no existe.")
        if not self.supports(source.type):
            raise ValueError(f"Source {source_id} no es compatible con TwitterApiIngestion.")
        if not source.is_active:
            return []

        account = self.account or source.name
        tweets = self.fetchTweets(account)
        raw_items: list[RawNews] = []
        for tweet in tweets:
            raw_items.append(
                RawNews(
                    source_id=source.source_id,
                    log_id=0,
                    platform="twitter",
                    source_account=account[:50],
                    original_url=tweet.get("url") or source.base_url,
                    title_raw=tweet.get("title") or tweet.get("text"),
                    content_raw=tweet.get("text"),
                    author_raw=tweet.get("author") or account,
                    published_at=WebScraperIngestion._coerce_datetime(tweet.get("published_at")),
                    scraped_at=datetime.utcnow(),
                    status="pending",
                )
            )
        return raw_items

    def supports(self, source_type: str) -> bool:
        return source_type.lower() in {"social", "twitter"}

    def fetchTweets(self, account: str) -> list[dict[str, Any]]:
        if not account:
            return []
        if not self.apiKey:
            logger.warning("Twitter API key no configurada. Se devuelve una lista vacia.")
            return []
        logger.info(
            "Twitter ingestion is configured for account %s but no live client is wired yet.",
            account,
        )
        return []
