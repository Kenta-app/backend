"""
Build a claims dataset from Newtral fact-check pages.

Usage:
    python scripts/build_newtral_claims.py --urls data/newtral/urls.txt

The script extracts ClaimReview JSON-LD data to get the claim text and rating,
then writes LIAR-style TSV files for training.
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
from typing import Any, Iterable

import requests
from bs4 import BeautifulSoup

try:
    import cloudscraper
except ImportError:  # pragma: no cover
    cloudscraper = None


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
    parser = argparse.ArgumentParser(description="Build Newtral claims dataset")
    parser.add_argument("--urls", required=True, help="Text file with one URL per line")
    parser.add_argument("--output_dir", default="data/newtral", help="Output directory")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train_ratio", type=float, default=0.8)
    parser.add_argument("--val_ratio", type=float, default=0.1)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--max_items", type=int, default=0, help="Limit number of pages (0=all)")
    parser.add_argument("--use_cloudscraper", action="store_true")
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


def get_session(use_cloudscraper: bool):
    if use_cloudscraper and cloudscraper is not None:
        return cloudscraper.create_scraper()
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    return session


def fetch_html(session: requests.Session, url: str) -> str | None:
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as exc:  # pragma: no cover - network failures
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def iter_jsonld_objects(payload: Any) -> Iterable[dict[str, Any]]:
    if isinstance(payload, dict):
        yield payload
    elif isinstance(payload, list):
        for item in payload:
            yield from iter_jsonld_objects(item)


def extract_claim_review(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    return extract_claim_review_from_soup(soup)


def extract_claim_review_from_soup(soup: BeautifulSoup) -> dict[str, Any] | None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for obj in iter_jsonld_objects(payload):
            if is_claim_review(obj):
                return obj
    return None


def is_claim_review(obj: dict[str, Any]) -> bool:
    obj_type = obj.get("@type")
    if isinstance(obj_type, list):
        return "ClaimReview" in obj_type
    return obj_type == "ClaimReview"


def extract_claim_fields(claim_review: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    claim = claim_review.get("claimReviewed")
    date = claim_review.get("datePublished") or claim_review.get("dateCreated")
    rating = None
    rating_obj = claim_review.get("reviewRating") or {}
    if isinstance(rating_obj, dict):
        rating = rating_obj.get("alternateName") or rating_obj.get("ratingValue")
    return claim, rating, date


def extract_claim_from_soup(soup: BeautifulSoup) -> tuple[str | None, str | None, str | None]:
    card = _find_factcheck_card(soup)
    claim_text = _extract_claim_from_card(card)
    rating_text = _extract_rating_from_card(card, claim_text)
    date = _extract_date_from_soup(soup)
    return claim_text, rating_text, date


def _find_factcheck_card(soup: BeautifulSoup):
    card = soup.find(class_=lambda value: value and "card-factchecks-single" in value)
    if card:
        return card
    return soup.find(class_=lambda value: value and "factchecks-single" in value)


def _extract_claim_from_card(card) -> str | None:
    if not card:
        return None
    mark = card.find("mark")
    if mark:
        return mark.get_text(" ", strip=True)
    for tag in card.find_all(["h2", "h3", "p"], limit=3):
        text = tag.get_text(" ", strip=True)
        if text:
            return text
    return None


def _extract_rating_from_card(card, claim_text: str | None) -> str | None:
    if not card:
        return None

    for node in card.find_all(class_=lambda value: value and _has_rating_hint(value)):
        rating = _find_verdict(node.get_text(" ", strip=True))
        if rating:
            return rating

    for node in card.find_all(["span", "strong", "p", "h3", "h4"]):
        text = node.get_text(" ", strip=True)
        if not text:
            continue
        if len(text.split()) <= 3:
            rating = _find_verdict(text)
            if rating:
                return rating

    fallback_text = card.get_text(" ", strip=True)
    if claim_text:
        fallback_text = fallback_text.replace(claim_text, " ")
    return _find_verdict(fallback_text)


def _has_rating_hint(value: str) -> bool:
    lowered = value.lower()
    return any(key in lowered for key in ("veredic", "factcheck", "rating", "resultado"))


def _find_verdict(text: str) -> str | None:
    if not text:
        return None
    normalized = normalize_text(text)
    patterns = [
        ("Verdad a medias", ["verdad a medias", "media verdad"]),
        ("Enganoso", ["enganoso", "enganosa", "enga", "manip", "tergivers"]),
        ("Falso", ["falso", "falsa", "bulo", "mentira"]),
        ("Verdadero", ["verdadero", "verdadera", "cierto", "correcto"]),
    ]
    for verdict, keys in patterns:
        if any(key in normalized for key in keys):
            return verdict
    return None


def _extract_date_from_soup(soup: BeautifulSoup) -> str | None:
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta and meta.get("content"):
        return meta["content"]
    meta = soup.find("meta", attrs={"name": "date"})
    if meta and meta.get("content"):
        return meta["content"]
    date_div = soup.find("div", class_=lambda value: value and "pot-author-date" in value)
    if date_div:
        text = date_div.get_text(strip=True)
        if text:
            return text
    time_tag = soup.find("time")
    if time_tag:
        datetime_value = time_tag.get("datetime")
        if datetime_value:
            return datetime_value
        text = time_tag.get_text(strip=True)
        if text:
            return text
    return None


def normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return " ".join(stripped.lower().split())


def map_rating_to_label(rating: str | None) -> str | None:
    if not rating:
        return None
    normalized = normalize_text(rating)
    if not normalized:
        return None

    if "verdad" in normalized and "media" in normalized:
        return None
    if "verdadero" in normalized or normalized == "true":
        return "true"
    if "falso" in normalized or "bulo" in normalized:
        return "false"
    if "enganoso" in normalized or "enga" in normalized or "manip" in normalized:
        return None
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
        source="newtral",
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

    session = get_session(args.use_cloudscraper)

    records: list[ClaimRecord] = []
    skipped = 0

    for idx, url in enumerate(urls, start=1):
        html = fetch_html(session, url)
        if not html:
            skipped += 1
            continue

        soup = BeautifulSoup(html, "html.parser")
        claim_review = extract_claim_review_from_soup(soup)
        if claim_review:
            claim, rating, date = extract_claim_fields(claim_review)
        else:
            claim, rating, date = extract_claim_from_soup(soup)
            if not claim:
                logger.warning("No ClaimReview found and no fallback claim: %s", url)
                skipped += 1
                continue
            logger.info("Fallback claim extracted for %s", url)
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
