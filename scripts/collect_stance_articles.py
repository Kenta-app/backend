"""Collect auditable Peruvian political-news article snapshots for stance pairing.

The collector accepts existing research CSVs and/or live source listings. It
stores the text snapshot and hashes used for annotation so later page changes
cannot silently alter the corpus.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO_ROOT / "data/stance_es_pe_v1/source_registry.json"
USER_AGENT = "KentaStanceResearch/1.0 (+academic corpus; Peru)"


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_for_url(url: str, sources: list[dict[str, str]]) -> dict[str, str] | None:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return next((source for source in sources if source["host"] in host), None)


def iter_jsonld(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_jsonld(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_jsonld(child)


def parse_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            output.extend(iter_jsonld(json.loads(node.get_text(strip=True))))
        except (json.JSONDecodeError, TypeError):
            continue
    return output


def extract_article(html: str, url: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    jsonld_items = parse_jsonld(soup)
    for tag in soup.select("script, style, noscript, nav, footer, aside"):
        tag.decompose()
    title = ""
    body = ""
    published_at = ""
    for item in jsonld_items:
        candidate_body = clean_text(item.get("articleBody"))
        if len(candidate_body) > len(body):
            body = candidate_body
            title = clean_text(item.get("headline") or item.get("name")) or title
            published_at = clean_text(item.get("datePublished")) or published_at
    if not title:
        h1 = soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "")
    if not title:
        meta = soup.select_one('meta[property="og:title"]')
        title = clean_text(meta.get("content") if meta else "")
    if not published_at:
        time_node = soup.select_one("time[datetime]")
        published_at = clean_text(time_node.get("datetime") if time_node else "")
    if len(body) < 500:
        best = ""
        selectors = (
            "article p", "main p", "[itemprop='articleBody'] p", ".article-content p",
            ".story-content p", ".body p", ".nota p", ".content p", ".flow-text",
            "div.col.xl12.no-padding600.columna.linknotas",
        )
        for selector in selectors:
            paragraphs = [clean_text(p.get_text(" ", strip=True)) for p in soup.select(selector)]
            text = " ".join(p for p in paragraphs if len(p) >= 35)
            if len(text) > len(best):
                best = text
        body = best if len(best) > len(body) else body
    if len(title) < 20:
        raise ValueError("missing usable title")
    if len(body) < 500:
        raise ValueError(f"article body under 500 characters ({len(body)})")
    return {"title": title, "article": body, "published_at": published_at, "original_url": url}


def get_json(session: requests.Session, url: str) -> Any:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def discover_elperuano(session: requests.Session, limit: int) -> list[str]:
    endpoints = (
        "https://elperuano.pe/Portal/_GetPortadaPrincipal",
        "https://elperuano.pe/Portal/_GetNoticiasDestacadas",
        "https://elperuano.pe/Portal/_GetNoticiasLoUltimo",
    )
    urls: list[str] = []
    for endpoint in endpoints:
        payload = get_json(session, endpoint)
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            section = clean_text(item.get("vchSeccion") or item.get("Seccion") or item.get("intSeccionId"))
            title = clean_text(item.get("vchTitulo"))
            if section and section not in {"1", "Política", "Politica"} and not re.search(
                r"congreso|gobierno|president|ministro|elecci|pol[ií]tic|jne|onpe", title, re.I
            ):
                continue
            value = clean_text(item.get("URLFriendLy"))
            if value:
                urls.append(urljoin("https://elperuano.pe/", value))
            if len(dict.fromkeys(urls)) >= limit:
                break
    return list(dict.fromkeys(urls))[:limit]


def discover_listing(session: requests.Session, source: dict[str, str], limit: int) -> list[str]:
    if source["host"] == "elperuano.pe":
        return discover_elperuano(session, limit)
    response = session.get(source["listing_url"], timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    urls: list[str] = []
    for link in soup.select("a[href]"):
        candidate = urljoin(source["listing_url"], clean_text(link.get("href"))).split("#", 1)[0]
        parsed = urlparse(candidate)
        host = parsed.netloc.lower().removeprefix("www.")
        path = parsed.path.lower()
        if source["host"] not in host:
            continue
        if path.rstrip("/") == urlparse(source["listing_url"]).path.rstrip("/").lower():
            continue
        is_article = (
            "/noticia/" in path
            or "/politica/" in path and len(path.strip("/").split("/")) >= 2
            or source["host"] == "andina.pe" and "/noticia-" in path
        )
        if is_article and candidate not in urls:
            urls.append(candidate)
        if len(urls) >= limit:
            break
    return urls


def read_seed_csv(path: Path, sources: list[dict[str, str]]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output = []
    for row in rows:
        url = clean_text(row.get("original_url") or row.get("url"))
        article = clean_text(row.get("article") or row.get("content") or row.get("articleBody"))
        title = clean_text(row.get("title") or row.get("headline"))
        source = source_for_url(url, sources)
        if source and len(article) >= 500 and len(title) >= 20:
            output.append({
                "source_name": source["name"], "ownership_group": source.get("ownership_group", ""),
                "title": title, "original_url": url, "published_at": clean_text(row.get("published_at")),
                "article": article, "collection_method": f"seed_csv:{path.name}",
            })
    return output


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = (
        "article_id", "group_id", "source_name", "ownership_group", "title", "original_url",
        "published_at", "article", "article_sha256", "collected_at", "collection_method",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--seed-csv", action="append", type=Path, default=[])
    parser.add_argument("--exclude-csv", action="append", type=Path, default=[])
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-per-source", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    sources = registry["sources"]
    excluded_urls: set[str] = set()
    excluded_hashes: set[str] = set()
    for path in args.exclude_csv:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if clean_text(row.get("original_url")):
                    excluded_urls.add(clean_text(row.get("original_url")))
                article = clean_text(row.get("article"))
                if article:
                    excluded_hashes.add(sha256(article))

    candidates = [row for path in args.seed_csv for row in read_seed_csv(path, sources)]
    failures: list[dict[str, str]] = []
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-PE,es;q=0.9"})
    if args.live:
        for source in sources:
            try:
                urls = discover_listing(session, source, args.max_per_source * 10)
            except Exception as exc:  # per-source fault isolation is intentional
                failures.append({"source": source["name"], "url": source["listing_url"], "error": str(exc)})
                continue
            accepted = 0
            for url in urls:
                if accepted >= args.max_per_source or url in excluded_urls:
                    continue
                try:
                    response = session.get(url, timeout=30)
                    response.raise_for_status()
                    article = extract_article(response.text, response.url)
                    article.update({
                        "source_name": source["name"], "ownership_group": source.get("ownership_group", ""),
                        "collection_method": "live_listing",
                    })
                    candidates.append(article)
                    accepted += 1
                except Exception as exc:
                    failures.append({"source": source["name"], "url": url, "error": str(exc)})
                time.sleep(max(args.delay, 0.0))

    now = datetime.now(timezone.utc).isoformat()
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set(excluded_hashes)
    rows: list[dict[str, str]] = []
    for item in candidates:
        article = clean_text(item["article"])
        url = clean_text(item["original_url"])
        digest = sha256(article)
        if url in excluded_urls or url in seen_urls or digest in seen_hashes:
            continue
        article_id = f"art_{digest[:16]}"
        rows.append({
            "article_id": article_id, "group_id": f"article:{article_id}",
            "source_name": clean_text(item["source_name"]),
            "ownership_group": clean_text(item.get("ownership_group")),
            "title": clean_text(item["title"]), "original_url": url,
            "published_at": clean_text(item.get("published_at")), "article": article,
            "article_sha256": digest, "collected_at": now,
            "collection_method": clean_text(item.get("collection_method")),
        })
        seen_urls.add(url)
        seen_hashes.add(digest)

    write_csv(args.output, rows)
    report = {
        "corpus_version": registry["corpus_version"], "articles": len(rows),
        "source_counts": {source["name"]: sum(r["source_name"] == source["name"] for r in rows) for source in sources},
        "excluded_url_count": len(excluded_urls), "failures": failures,
        "output": str(args.output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "failures"}, ensure_ascii=False, indent=2))
    if failures:
        print(f"[WARN] {len(failures)} fetch/extraction failures; see {args.report}")


if __name__ == "__main__":
    main()
