"""
Build a claims dataset from Maldita desinfo pages.

Usage:
    python scripts/build_maldita_claims.py --urls data/maldita/urls.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import time
import unicodedata
from dataclasses import dataclass
from typing import Iterable

import requests
from bs4 import BeautifulSoup


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class ClaimRecord:
    record_id: str
    claim_text: str
    label: str
    verdict_raw: str
    url: str
    source: str
    date: str | None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Maldita claims dataset")
    parser.add_argument("--urls", required=True, help="Text file with one URL per line")
    parser.add_argument("--output_dir", default="data/maldita", help="Output directory")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train_ratio", type=float, default=0.8)
    parser.add_argument("--val_ratio", type=float, default=0.1)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--max_items", type=int, default=0, help="Limit number of pages (0=all)")
    parser.add_argument("--dedupe", action="store_true", default=True)
    parser.add_argument("--no_dedupe", action="store_true")
    return parser


def load_urls(path: str) -> list[str]:
    urls: list[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            urls.append(raw)
    return urls


def fetch_html(url: str) -> str | None:
    try:
        response = requests.get(url, timeout=30, headers=DEFAULT_HEADERS)
        response.raise_for_status()
        return response.text
    except Exception as exc:  # pragma: no cover - network failures
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return " ".join(stripped.lower().split())


def _find_claim_container(soup: BeautifulSoup):
    for div in soup.find_all("div", class_=lambda value: value and "mb-4" in value):
        if div.find("h2"):
            return div
    return None


def _extract_claim_text(container) -> str | None:
    if not container:
        return None
    h2 = container.find("h2")
    if h2:
        text = h2.get_text(" ", strip=True)
        if text:
            return text
    return None


def _extract_context_text(container) -> str | None:
    if not container:
        return None
    context = container.find(
        "div",
        class_=lambda value: value
        and "text-sm" in value
        and "italic" in value
        and "text-theme-text-secondary" in value,
    )
    if context:
        text = context.get_text(" ", strip=True)
        if text:
            return text
    return None


def _find_verdict(text: str) -> str | None:
    if not text:
        return None
    normalized = normalize_text(text)
    if "falso" in normalized or "bulo" in normalized:
        return "Falso"
    if "verdadero" in normalized or "cierto" in normalized:
        return "Verdadero"
    if "alerta" in normalized:
        return "Alerta"
    if "contexto" in normalized:
        return "Contexto"
    return None


def extract_rating(soup: BeautifulSoup, container) -> str | None:
    search_root = container or soup
    for tag in search_root.find_all(["span", "strong", "p", "div", "h3", "h4"], limit=60):
        text = tag.get_text(" ", strip=True)
        if not text or len(text.split()) > 3:
            continue
        verdict = _find_verdict(text)
        if verdict:
            return verdict
    return None


def extract_date(soup: BeautifulSoup) -> str | None:
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta and meta.get("content"):
        return meta["content"]
    time_tag = soup.find("time")
    if time_tag:
        datetime_value = time_tag.get("datetime")
        if datetime_value:
            return datetime_value
        text = time_tag.get_text(strip=True)
        if text:
            return text
    return None


def map_rating_to_label(rating: str | None) -> str | None:
    if not rating:
        return None
    normalized = normalize_text(rating)
    if "verdadero" in normalized:
        return "true"
    if "falso" in normalized:
        return "false"
    return None


def build_record(url: str, claim: str, rating: str, date: str | None, record_id: int) -> ClaimRecord:
    label = map_rating_to_label(rating)
    if label is None:
        raise ValueError("Unsupported rating")
    return ClaimRecord(
        record_id=str(record_id),
        claim_text=claim,
        label=label,
        verdict_raw=rating,
        url=url,
        source="maldita",
        date=date,
    )


def dedupe_records(records: list[ClaimRecord]) -> list[ClaimRecord]:
    seen: set[str] = set()
    output: list[ClaimRecord] = []
    for record in records:
        key = normalize_text(record.claim_text)
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


def split_records(records: list[ClaimRecord], train_ratio: float, val_ratio: float, seed: int):
    rng = random.Random(seed)
    items = list(records)
    rng.shuffle(items)

    total = len(items)
    train_end = int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)

    train = items[:train_end]
    val = items[train_end:val_end]
    test = items[val_end:]
    return train, val, test


def write_tsv(path: str, records: list[ClaimRecord]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        for record in records:
            writer.writerow(
                [
                    record.record_id,
                    record.label,
                    record.claim_text,
                    record.source,
                    record.url,
                    record.verdict_raw,
                    record.date or "",
                ]
            )


def write_jsonl(path: str, records: list[ClaimRecord]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            payload = {
                "id": record.record_id,
                "claim_text": record.claim_text,
                "label": record.label,
                "verdict_raw": record.verdict_raw,
                "url": record.url,
                "source": record.source,
                "date": record.date,
            }
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> None:
    args = build_arg_parser().parse_args()
    urls = load_urls(args.urls)
    if args.max_items and args.max_items > 0:
        urls = urls[: args.max_items]

    records: list[ClaimRecord] = []
    skipped = 0

    for idx, url in enumerate(urls, start=1):
        html = fetch_html(url)
        if not html:
            skipped += 1
            continue

        soup = BeautifulSoup(html, "html.parser")
        container = _find_claim_container(soup)
        claim = _extract_claim_text(container) or _extract_context_text(container)
        rating = extract_rating(soup, container)
        date = extract_date(soup)

        if not claim or not rating:
            logger.warning("Missing claim or rating: %s", url)
            skipped += 1
            continue

        try:
            record = build_record(url, claim.strip(), rating.strip(), date, idx)
        except ValueError:
            logger.warning("Unsupported rating '%s' for %s", rating, url)
            skipped += 1
            continue

        records.append(record)
        if args.sleep:
            time.sleep(args.sleep)

    if args.no_dedupe:
        deduped = records
    else:
        deduped = dedupe_records(records)

    if not deduped:
        raise SystemExit("No records extracted. Check URLs and HTML structure.")

    os.makedirs(args.output_dir, exist_ok=True)

    train, val, test = split_records(deduped, args.train_ratio, args.val_ratio, args.seed)

    write_tsv(os.path.join(args.output_dir, "train.tsv"), train)
    write_tsv(os.path.join(args.output_dir, "validation.tsv"), val)
    write_tsv(os.path.join(args.output_dir, "test.tsv"), test)
    write_jsonl(os.path.join(args.output_dir, "claims.jsonl"), deduped)

    logger.info(
        "Done. total=%s train=%s val=%s test=%s skipped=%s",
        len(deduped),
        len(train),
        len(val),
        len(test),
        skipped,
    )


if __name__ == "__main__":
    main()
