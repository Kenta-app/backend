from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.processed.text_utils import clip_readable, normalize_summary_text
from app.raw.models import RawNews

URL_RE = re.compile(r"https?://[^\s)>\]]+|www\.[^\s)>\]]+", re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")

STRONG_LANGUAGE_RE = re.compile(
    r"\b("
    r"carajo|concha|conchudo|conchuda|cojudo|cojuda|cojudos|cojudas|"
    r"huevon|huevón|huevona|huevones|huevón|huevones|webon|webón|"
    r"mierda|puta|puto|putos|putas|pendejo|pendeja|pendejos|pendejas|"
    r"imbecil|imbécil|idiota|baboso|babosa|corrupto de mierda"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DisplayContent:
    content_type: str
    display_title: str
    display_text: str
    external_links: list[str] = field(default_factory=list)
    content_warning: str | None = None


def build_display_content(raw_news: RawNews, clean_text: str | None = None) -> DisplayContent:
    if _is_social_post(raw_news):
        return _build_social_display_content(raw_news, clean_text)
    return _build_article_display_content(raw_news, clean_text)


def _build_article_display_content(raw_news: RawNews, clean_text: str | None = None) -> DisplayContent:
    title = normalize_summary_text(raw_news.title_raw) or clip_readable(clean_text, 160)
    text = normalize_summary_text(clean_text or raw_news.content_raw)
    return DisplayContent(
        content_type="article",
        display_title=title or "Noticia",
        display_text=text,
        external_links=extract_links(raw_news.content_raw),
        content_warning=detect_content_warning(text),
    )


def _build_social_display_content(raw_news: RawNews, clean_text: str | None = None) -> DisplayContent:
    raw_text = raw_news.content_raw or raw_news.title_raw or clean_text or ""
    display_text = clean_social_text(raw_text)
    account = (raw_news.source_account or raw_news.author_raw or "").strip().lstrip("@")
    display_title = f"Publicación de @{account}" if account else "Publicación en X"
    links = extract_links(raw_text)
    return DisplayContent(
        content_type="social_post",
        display_title=display_title,
        display_text=display_text,
        external_links=links,
        content_warning=detect_content_warning(raw_text),
    )


def clean_social_text(text: str | None) -> str:
    value = str(text or "").replace("\xa0", " ")
    value = URL_RE.sub(" ", value)
    value = re.sub(r"\bpic\.twitter\.com/\S+", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"\bt\.co/\S+", " ", value, flags=re.IGNORECASE)
    value = WHITESPACE_RE.sub(" ", value)
    return value.strip()


def extract_links(text: str | None) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for match in URL_RE.finditer(str(text or "")):
        url = match.group(0).rstrip(".,;:!?")
        if url.lower().startswith("www."):
            url = f"https://{url}"
        parsed = urlparse(url)
        if parsed.netloc.lower() in {"t.co", "pic.twitter.com"}:
            continue
        if url not in seen:
            links.append(url)
            seen.add(url)
    return links[:5]


def detect_content_warning(text: str | None) -> str | None:
    if STRONG_LANGUAGE_RE.search(str(text or "")):
        return "strong_language"
    return None


def _is_social_post(raw_news: RawNews) -> bool:
    platform = (raw_news.platform or "").lower()
    original_url = (raw_news.original_url or "").lower()
    return platform in {"twitter", "x", "social"} or "twitter.com/" in original_url or "x.com/" in original_url
