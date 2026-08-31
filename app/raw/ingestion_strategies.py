from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any
from urllib.parse import quote, urljoin, urlparse

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
                image_url=item.get("image_url"),
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
                        "image_url": item.get("image_url"),
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
    API_BASE_URL = "https://api.x.com/2"

    def __init__(
        self,
        db: Session,
        apiKey: str | None = None,
        account: str | None = None,
        httpClient: requests.Session | None = None,
    ):
        self.db = db
        self.apiKey = apiKey or os.getenv("TWITTER_API_KEY") or os.getenv("TWITTER_BEARER_TOKEN")
        self.account = account
        self.httpClient = httpClient or requests.Session()

    def ingest(self, source_id: int) -> list[RawNews]:
        source = self.db.query(Source).filter(Source.source_id == source_id).first()
        if not source:
            raise ValueError(f"Source {source_id} no existe.")
        if not self.supports(source.type):
            raise ValueError(f"Source {source_id} no es compatible con TwitterApiIngestion.")
        if not source.is_active:
            return []

        account = (
            self.account
            or source.source_account
            or self._account_from_url(source.base_url)
            or source.name
        )
        search_query = " ".join((source.search_query or "").split())
        tweets = self.searchRecentPosts(search_query) if search_query else self.fetchTweets(account)
        raw_items: list[RawNews] = []
        for tweet in tweets:
            tweet_account = str(tweet.get("account") or account).lstrip("@")
            raw_items.append(
                RawNews(
                    source_id=source.source_id,
                    log_id=0,
                    platform="twitter",
                    source_account=tweet_account[:50],
                    original_url=tweet.get("url") or source.base_url,
                    image_url=tweet.get("image_url"),
                    title_raw=(
                        f"Publicación de @{tweet_account}"
                        if tweet_account
                        else "Publicación en X"
                    ),
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
            raise ValueError("TWITTER_BEARER_TOKEN no esta configurado.")

        username = account.strip().lstrip("@")
        headers = {"Authorization": f"Bearer {self.apiKey}"}
        user_response = self.httpClient.get(
            f"{self.API_BASE_URL}/users/by/username/{quote(username, safe='')}",
            headers=headers,
            timeout=20,
        )
        user_response.raise_for_status()
        user_data = user_response.json().get("data") or {}
        user_id = user_data.get("id")
        resolved_username = user_data.get("username") or username
        if not user_id:
            raise ValueError(f"La cuenta de X @{username} no existe o no es accesible.")

        max_results = self._max_results()
        timeline_response = self.httpClient.get(
            f"{self.API_BASE_URL}/users/{quote(str(user_id), safe='')}/tweets",
            headers=headers,
            params={
                "max_results": max_results,
                "exclude": "retweets,replies",
                "tweet.fields": "created_at,attachments",
                "expansions": "attachments.media_keys",
                "media.fields": "media_key,type,url,preview_image_url",
            },
            timeout=20,
        )
        timeline_response.raise_for_status()
        payload = timeline_response.json()
        media_by_key = {
            media.get("media_key"): media
            for media in (payload.get("includes") or {}).get("media", [])
            if media.get("media_key")
        }

        tweets: list[dict[str, Any]] = []
        for item in payload.get("data") or []:
            tweet_id = item.get("id")
            text = " ".join((item.get("text") or "").split())
            if not tweet_id or not text:
                continue
            media_keys = (item.get("attachments") or {}).get("media_keys") or []
            tweets.append(
                {
                    "id": str(tweet_id),
                    "title": text,
                    "text": text,
                    "author": f"@{resolved_username}",
                    "account": resolved_username,
                    "url": f"https://x.com/{resolved_username}/status/{tweet_id}",
                    "published_at": item.get("created_at"),
                    "image_url": self._first_media_image(media_keys, media_by_key),
                }
            )
        return tweets

    def searchRecentPosts(self, query: str) -> list[dict[str, Any]]:
        """Busca una página reciente para mantener el gasto y el ruido acotados."""
        if not self.apiKey:
            raise ValueError("TWITTER_BEARER_TOKEN no esta configurado.")

        normalized_query = " ".join((query or "").split())
        if not normalized_query:
            return []
        if len(normalized_query) > 512:
            raise ValueError("La consulta de X no puede superar 512 caracteres.")

        response = self.httpClient.get(
            f"{self.API_BASE_URL}/tweets/search/recent",
            headers={"Authorization": f"Bearer {self.apiKey}"},
            params={
                "query": normalized_query,
                "max_results": self._search_max_results(),
                "tweet.fields": "created_at,attachments,author_id,lang,public_metrics",
                "expansions": "author_id,attachments.media_keys",
                "user.fields": "username,name,verified",
                "media.fields": "media_key,type,url,preview_image_url",
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        media_by_key = {
            media.get("media_key"): media
            for media in (payload.get("includes") or {}).get("media", [])
            if media.get("media_key")
        }
        username_by_author_id = {
            user.get("id"): user.get("username")
            for user in (payload.get("includes") or {}).get("users", [])
            if user.get("id") and user.get("username")
        }

        tweets: list[dict[str, Any]] = []
        for item in payload.get("data") or []:
            tweet_id = item.get("id")
            text = " ".join((item.get("text") or "").split())
            if not tweet_id or not text:
                continue
            username = username_by_author_id.get(item.get("author_id"))
            media_keys = (item.get("attachments") or {}).get("media_keys") or []
            tweets.append(
                {
                    "id": str(tweet_id),
                    "title": text,
                    "text": text,
                    "author": f"@{username}" if username else "X",
                    "account": username,
                    "url": (
                        f"https://x.com/{username}/status/{tweet_id}"
                        if username
                        else f"https://x.com/i/web/status/{tweet_id}"
                    ),
                    "published_at": item.get("created_at"),
                    "image_url": self._first_media_image(media_keys, media_by_key),
                }
            )
        return tweets

    @staticmethod
    def _first_media_image(
        media_keys: list[str],
        media_by_key: dict[str, dict[str, Any]],
    ) -> str | None:
        for media_key in media_keys:
            media = media_by_key.get(media_key) or {}
            media_type = media.get("type")
            if media_type == "photo" and media.get("url"):
                return str(media["url"])
            if media_type in {"video", "animated_gif"} and media.get("preview_image_url"):
                return str(media["preview_image_url"])
        return None

    @staticmethod
    def _account_from_url(value: str | None) -> str | None:
        if not value:
            return None
        parsed = urlparse(value)
        if parsed.netloc.lower() not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
            return None
        path_parts = [part for part in parsed.path.split("/") if part]
        return path_parts[0].lstrip("@") if path_parts else None

    @staticmethod
    def _max_results() -> int:
        try:
            configured = int(os.getenv("TWITTER_MAX_RESULTS", "10"))
        except ValueError:
            configured = 10
        return min(max(configured, 5), 100)

    @staticmethod
    def _search_max_results() -> int:
        return min(max(TwitterApiIngestion._max_results(), 10), 100)
