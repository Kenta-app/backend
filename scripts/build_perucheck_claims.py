"""
Build a claims dataset from PerúCheck verification articles.

Usage:
    python scripts/build_perucheck_claims.py --urls data/perucheck/urls.txt
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
from urllib.parse import urlparse

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


@dataclass
class SkipRecord:
    """Record of a skipped URL with reason and details."""
    url: str
    reason: str
    details: str | None = None


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build PerúCheck claims dataset")
    parser.add_argument("--urls", required=True, help="Text file with one URL per line")
    parser.add_argument("--output_dir", default="data/perucheck", help="Output directory")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train_ratio", type=float, default=0.8)
    parser.add_argument("--val_ratio", type=float, default=0.1)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--max_items", type=int, default=0, help="Limit number of pages (0=all)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed skip reasons")
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
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None


def normalize_text(text: str) -> str:
    """Normalize text: lowercase, remove accents."""
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return " ".join(stripped.lower().split())


def clean_claim_text(text: str) -> str:
    """
    Remove verdict prefixes and suffixes from claim text while preserving the core claim.
    
    Maneja múltiples patrones:
    - "Es falso que X" -> "X"
    - "Es falsa la encuesta..." -> "La encuesta..."
    - "Es falso lo que dijo" -> "Lo que dijo"
    - "¿X? Es falso..." -> "X"
    - "X, pero es falso" -> "X"
    - "¿X? Lo que dijo... es falso y mortal" -> "X" o "Lo que dijo..."
    - "Es falso el comunicado..." -> "El comunicado..."
    - "Debate Municipal: Es falso que..." -> "Es falso que..." o versión limpia
    """
    import re
    
    # Remove question marks at the end
    text_to_process = text.rstrip("?").strip()
    normalized = text_to_process.lower()
    
    # Patrón 0: Si hay "Contexto: Es falso que...", mantener todo como está
    # El patrón "Es falso que" será capturado después
    # No intentamos remover el prefijo del contexto aquí
    
    # Patrón 1: "¿PREGUNTA? Es falso/verdadero..." o "¿PREGUNTA? Lo que... es falso..."
    # Prioridad máxima: si hay pregunta, extraerla primero
    if "?" in text_to_process:
        parts = text_to_process.split("?", 1)
        if len(parts) == 2:
            question = parts[0].strip().lstrip("¿").strip()
            suffix = parts[1].strip()
            suffix_lower = suffix.lower()
            
            # Caso A: "¿PREGUNTA? Es falso/verdadero..."
            verdict_starts = [
                "es falso", "es falsa", "es verdadero", "es verdadera",
                "es cierto", "es cierta", "es impreciso", "es imprecisa",
                "es inexacto", "es inexacta"
            ]
            for pattern in verdict_starts:
                if suffix_lower.startswith(pattern):
                    if question:
                        return question[0].upper() + question[1:] if len(question) > 1 else question.upper()
            
            # Caso B: "¿PREGUNTA? Lo que dijo... es falso..."
            # Si no empieza con veredicto pero contiene "es falso/verdadero" después, retornar la pregunta
            if any(v in suffix_lower for v in verdict_starts):
                if question:
                    return question[0].upper() + question[1:] if len(question) > 1 else question.upper()
    
    # Patrón 2: Veredicto al final (ej: "X, pero es falso" o "X es falso y mortal")
    # Buscar patrones como ", pero es falso" o " es falso y"
    verdict_suffixes = [
        ", pero es falso", ", pero es falsa", ", pero es verdadero", ", pero es verdadera",
        " pero es falso", " pero es falsa", " pero es verdadero", " pero es verdadera",
        " es falso y", " es falsa y", " es verdadero y", " es verdadera y",
        " es falso.", " es falsa.", " es verdadero.", " es verdadera.",
    ]
    
    for suffix in verdict_suffixes:
        if suffix.lower() in normalized:
            result = text_to_process.split(suffix)[0].strip()
            if result:
                return result[0].upper() + result[1:] if len(result) > 1 else result.upper()
    
    # Patrón 3: Veredicto al principio
    # Estrategia: remover solo "Es falso/verdadero/etc" y dejar el resto
    # IMPORTANTE: Orden importa - verificar patrones más específicos primero
    verdict_prefixes = [
        # Con "que"
        ("es falso que ", ""),
        ("es falsa que ", ""),
        ("es verdadero que ", ""),
        ("es verdadera que ", ""),
        ("es cierto que ", ""),
        ("es cierta que ", ""),
        ("es impreciso que ", ""),
        ("es imprecisa que ", ""),
        ("es inexacto que ", ""),
        ("es inexacta que ", ""),
        ("son falsas ", ""),
        ("son falsos ", ""),
        # Sin "que" - casos como "Es falsa encuesta" o "Es falsa afirmación"
        ("es falso ", ""),
        ("es falsa ", ""),
        ("es verdadero ", ""),
        ("es verdadera ", ""),
        ("es cierto ", ""),
        ("es cierta ", ""),
        ("es impreciso ", ""),
        ("es imprecisa ", ""),
        ("es inexacto ", ""),
        ("es inexacta ", ""),
        # Con interrogación
        ("¿es falso que ", ""),
        ("¿es falsa que ", ""),
        ("¿es verdadero que ", ""),
        ("¿es cierto que ", ""),
        ("¿es falso ", ""),
        ("¿es falsa ", ""),
        ("¿es verdadero ", ""),
        ("¿es cierto ", ""),
    ]
    
    for prefix, replacement in verdict_prefixes:
        if normalized.startswith(prefix):
            # Remover el prefijo
            result = text_to_process[len(prefix):].strip()
            if result:
                # Capitalizar
                result = result[0].upper() + result[1:] if len(result) > 1 else result.upper()
            return result
    
    # Si no hay veredicto detectado, retornar el texto limpio
    return text_to_process


def extract_claim_text(soup: BeautifulSoup) -> str | None:
    """
    Extract claim text from PerúCheck article.
    PerúCheck articles have the main claim in a prominent <h1> or headline.
    Removes verdict prefixes like "Es falso que" to get the clean claim.
    """
    # Try to find the main headline/h1
    h1 = soup.find("h1")
    if h1:
        text = h1.get_text(" ", strip=True)
        if text:
            # Limpiar el texto removiendo prefijos de veredicto
            cleaned = clean_claim_text(text)
            return cleaned
    
    # Fallback: find the first strong/bold text in article-content
    article = soup.find("article")
    if article:
        strong = article.find("strong")
        if strong:
            text = strong.get_text(" ", strip=True)
            if text:
                # Limpiar el texto removiendo prefijos de veredicto
                cleaned = clean_claim_text(text)
                return cleaned
    
    return None


def extract_verdict_from_url(url: str) -> str | None:
    """
    Extract verdict from PerúCheck URL slug.
    URLs follow pattern: .../es-falso-que-..., es-verdadero-que-..., etc.
    Also detects embedded verdict keywords like "apocrifa", "miente", "contrario", etc.
    """
    url_lower = url.lower()

    # Skip obvious meta/explainer pages
    if "/explicador" in url_lower or "/perucheck-" in url_lower:
        return None

    # Explicit verdict indicators in the slug
    if "es-falso" in url_lower or "-falso-" in url_lower or "-falsa-" in url_lower or "son-falsas" in url_lower:
        return "Falso"
    if "es-verdadero" in url_lower or "es-cierto" in url_lower or "-verdadero-" in url_lower:
        return "Verdadero"
    if "es-impreciso" in url_lower or "-impreciso-" in url_lower or "-imprecisa-" in url_lower:
        return "Impreciso"
    if "sin-evidencia" in url_lower:
        return "Sin Evidencia"

    # Heuristic: many PeruCheck debunks use URLs starting with 'no-*' ("No, X no hizo Y")
    # treat these as Falso (the page denies a circulated claim)
    path = urlparse(url_lower).path
    last = path.rsplit("/", 1)[-1]
    if last.startswith("no-") or "/no-" in path:
        return "Falso"

    # Hidden verdict keywords embedded in the slug
    # Words that indicate a FALSO verdict
    false_keywords = [
        "apocrifa",  # es apócrifa (es falsa)
        "apocrifa",
        "miente",    # X miente (lo que dice es falso)
        "manipulada",  # encuesta manipulada
        "no-es-asi",   # pero no es así
        "no-es-verdad",
        "es-falso",
        "-falsa-",
        "inverosimil",  # claim inverosímil
        "incierto",     # lo que dijo es incierto
        "-no-",         # Acción: X hace Y, pero no es así → Falso
    ]
    
    # Words that indicate a VERDADERO verdict
    true_keywords = [
        "si-tiene",  # "X sí tiene/tuvo"
        "si-fue",    # "X sí fue"
        "si-es",     # "X sí es"
        "es-cierto",
        "es-verdad",
        "es-verdadero",
    ]

    slug = last.lower()
    
    for kw in false_keywords:
        if kw in slug:
            return "Falso"
    
    for kw in true_keywords:
        if kw in slug:
            return "Verdadero"

    return None


def extract_verdict_from_jsonld(soup: BeautifulSoup) -> str | None:
    """Try to extract headline/description from JSON-LD and infer verdict."""
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        try:
            data = json.loads(script.string or "{}")
        except Exception:
            continue

        # data can be a list or single object
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if not isinstance(c, dict):
                continue
            for key in ("headline", "name", "description", "articleBody"):
                txt = c.get(key)
                if not txt:
                    continue
                verdict = extract_verdict_from_title(str(txt))
                if verdict:
                    return verdict

    return None


def extract_verdict_from_title(text: str) -> str | None:
    """
    PerúCheck includes verdict in the title like:
    "¿CLAIM?" followed by verdict on next line
    or "CLAIM is VERDICT"
    
    Common patterns:
    - "Es falso"
    - "Es verdadero"
    - "Es parcialmente falso"
    - "Sin evidencia"
    """
    if not text:
        return None

    normalized = normalize_text(text)

    # Check for FALSE (highest priority)
    if "es falso" in normalized or "es falsa" in normalized or "false" in normalized:
        return "Falso"
    # Check for TRUE
    elif "es verdadero" in normalized or "es verdadera" in normalized or "es cierto" in normalized or "es cierta" in normalized or "true" in normalized:
        return "Verdadero"
    # Check for IMPRECISE
    elif "es impreciso" in normalized or "es imprecisa" in normalized or "impreciso" in normalized or "imprecisa" in normalized:
        return "Impreciso"
    elif "es inexacta" in normalized or "es inexacto" in normalized or "inexacta" in normalized or "inexacto" in normalized:
        return "Impreciso"
    # plural pattern: "Son falsas las ..."
    elif normalized.startswith("son ") or "son falsas" in normalized or "son falsos" in normalized:
        return "Falso"
    # leading negation like "No, X no hizo Y" -> treat as Falso
    elif normalized.startswith("no ") or normalized.startswith("no,") or (len(normalized) >= 4 and " no " in normalized[:6]):
        return "Falso"
    elif "parcialmente falso" in normalized or "parcialmente cierto" in normalized:
        return "Falso"
    elif "sin evidencia" in normalized:
        return "Sin Evidencia"
    # Additional patterns for "no" or negation
    elif " no " in normalized and ("fue" in normalized or "fue" in normalized or "es" in normalized):
        return "Falso"

    return None


def extract_verdict_from_content(soup: BeautifulSoup) -> str | None:
    """
    Look for verdict in article content.
    PerúCheck may include it in a verdict box or special section.
    More aggressive search: check all text, not just paragraphs.
    """
    article = soup.find("article")
    if not article:
        return None
    
    # Get all text from article (more comprehensive)
    full_text = article.get_text(" ", strip=True)
    if full_text:
        normalized = normalize_text(full_text)
        
        # Check for verdict indicators (more aggressive)
        if "es falso" in normalized or "false" in normalized:
            return "Falso"
        elif "es verdadero" in normalized or "es cierto" in normalized or "true" in normalized:
            return "Verdadero"
        elif "parcialmente falso" in normalized:
            return "Parcialmente Falso"
        elif "sin evidencia" in normalized:
            return "Sin Evidencia"
        elif "impreciso" in normalized:
            return "Impreciso"
    
    return None


def extract_verdict(soup: BeautifulSoup, claim_title: str | None, url: str | None = None) -> str | None:
    """Extract verdict from PerúCheck article."""
    # First try from URL (most reliable for PeruCheck)
    if url:
        # If URL looks like a meta/explainer page, avoid false positives
        try:
            verdict = extract_verdict_from_url(url)
        except Exception:
            verdict = None
        if verdict:
            return verdict

    # Then try from title
    if claim_title:
        verdict = extract_verdict_from_title(claim_title)
        if verdict:
            return verdict

    # Then try structured JSON-LD data
    verdict = extract_verdict_from_jsonld(soup)
    if verdict:
        return verdict

    # Finally try from article content
    verdict = extract_verdict_from_content(soup)
    return verdict


def extract_date(soup: BeautifulSoup) -> str | None:
    """Extract publication date from PerúCheck article."""
    # Try meta tag
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta and meta.get("content"):
        return meta["content"]
    
    # Try time tag
    time_tag = soup.find("time")
    if time_tag:
        datetime_value = time_tag.get("datetime")
        if datetime_value:
            return datetime_value
        text = time_tag.get_text(strip=True)
        if text:
            return text
    
    # Try finding date in article content (common pattern: "Redacción: Author - YYYY-MM-DD")
    article = soup.find("article")
    if article:
        for p in article.find_all("p"):
            text = p.get_text(strip=True)
            if "Redacción:" in text:
                # Extract date part (YYYY-MM-DD format)
                import re
                match = re.search(r"(\d{4}-\d{2}-\d{2})", text)
                if match:
                    return match.group(1)
    
    return None


def map_rating_to_label(rating: str | None) -> str | None:
    """Map verdict text to binary label."""
    if not rating:
        return None
    
    normalized = normalize_text(rating)
    
    if "verdadero" in normalized or "cierto" in normalized:
        return "true"
    elif "falso" in normalized:
        return "false"
    elif "impreciso" in normalized:
        # Treat "impreciso" (imprecise claims) as neither clearly true nor false
        # For now, map to false as it indicates claim is not fully supported
        return "false"
    elif "parcialmente falso" in normalized:
        return "false"  # Treat partial false as false
    elif "sin evidencia" in normalized:
        return None  # Skip items without clear verdict
    
    return None


def build_record(
    url: str,
    claim: str,
    rating: str,
    date: str | None,
    record_id: int,
) -> ClaimRecord:
    """Build a ClaimRecord from extracted data."""
    label = map_rating_to_label(rating)
    if label is None:
        raise ValueError(f"Unsupported rating: {rating}")
    
    return ClaimRecord(
        record_id=str(record_id),
        claim_text=claim,
        label=label,
        verdict_raw=rating,
        url=url,
        source="perucheck",
        date=date,
    )


def dedupe_records(records: list[ClaimRecord]) -> list[ClaimRecord]:
    """Remove duplicate records (by normalized claim text)."""
    seen: set[str] = set()
    output: list[ClaimRecord] = []
    
    for record in records:
        key = normalize_text(record.claim_text)
        if key in seen:
            continue
        seen.add(key)
        output.append(record)
    
    return output


def split_records(
    records: list[ClaimRecord],
    train_ratio: float,
    val_ratio: float,
    seed: int,
):
    """Split records into train/val/test sets."""
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
    """Write records to TSV file."""
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        for record in records:
            writer.writerow([
                record.record_id,
                record.label,
                record.claim_text,
                record.source,
                record.url,
                record.verdict_raw,
                record.date or "",
            ])


def write_jsonl(path: str, records: list[ClaimRecord]) -> None:
    """Write records to JSONL file."""
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
    
    logger.info("Processing %d URLs", len(urls))
    
    records: list[ClaimRecord] = []
    skip_records: list[SkipRecord] = []
    skipped = 0
    skip_reasons = {
        "fetch_error": 0,
        "missing_claim": 0,
        "missing_rating": 0,
        "meta_explainer": 0,
        "invalid_rating": 0,
    }
    
    for idx, url in enumerate(urls, start=1):
        html = fetch_html(url)
        if not html:
            skipped += 1
            skip_reasons["fetch_error"] += 1
            skip_records.append(SkipRecord(url, "fetch_error", "Failed to fetch HTML"))
            if args.verbose:
                logger.info("SKIP [fetch_error] %s", url)
            continue
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract claim (title/h1) and date first
        claim = extract_claim_text(soup)
        date = extract_date(soup)
        
        if not claim:
            skipped += 1
            skip_reasons["missing_claim"] += 1
            skip_records.append(SkipRecord(url, "missing_claim", "No claim text found"))
            if args.verbose:
                logger.info("SKIP [missing_claim] %s", url)
            continue

        # Filter meta/explainer pages early (explicador, site/meta posts)
        slug = urlparse(url.lower()).path.rsplit("/", 1)[-1]
        if "explicador" in slug or slug.startswith("perucheck") or claim.lower().startswith("explicador"):
            skipped += 1
            skip_reasons["meta_explainer"] += 1
            skip_records.append(SkipRecord(url, "meta_explainer", f"Meta/explicador page: {slug}"))
            if args.verbose:
                logger.info("SKIP [meta_explainer] %s (slug: %s)", url, slug)
            continue

        # Now extract verdict (after filtering meta pages)
        rating = extract_verdict(soup, claim, url)  # Pass URL for better verdict extraction
        
        if not rating:
            skipped += 1
            skip_reasons["missing_rating"] += 1
            skip_records.append(SkipRecord(url, "missing_rating", f"Claim: {claim[:50]}..."))
            if args.verbose:
                logger.info("SKIP [missing_rating] %s (claim: %s)", url, claim[:50])
            continue
        
        try:
            record = build_record(url, claim.strip(), rating.strip(), date, idx)
        except ValueError as e:
            skipped += 1
            skip_reasons["invalid_rating"] += 1
            skip_records.append(SkipRecord(url, "invalid_rating", str(e)))
            if args.verbose:
                logger.info("SKIP [invalid_rating] %s: %s", url, e)
            continue
        
        records.append(record)
        
        if idx % 10 == 0:
            logger.info("Processed %d/%d articles (%d records)", idx, len(urls), len(records))
        
        if args.sleep:
            time.sleep(args.sleep)
    
    logger.info("Extracted %d records (%d skipped)", len(records), skipped)
    logger.info("  Skip reasons: fetch_error=%d, missing_claim=%d, missing_rating=%d, invalid_rating=%d",
                skip_reasons["fetch_error"],
                skip_reasons["missing_claim"],
                skip_reasons["missing_rating"],
                skip_reasons["invalid_rating"])
    
    # Deduplication
    if args.no_dedupe:
        deduped = records
    else:
        deduped = dedupe_records(records)
        logger.info("After deduplication: %d records", len(deduped))
    
    if not deduped:
        raise SystemExit("No records extracted. Check URLs and HTML structure.")
    
    # Split into train/val/test
    train, val, test = split_records(deduped, args.train_ratio, args.val_ratio, args.seed)
    logger.info(
        "Split: train=%d (%.1f%%), val=%d (%.1f%%), test=%d (%.1f%%)",
        len(train),
        100 * len(train) / len(deduped),
        len(val),
        100 * len(val) / len(deduped),
        len(test),
        100 * len(test) / len(deduped),
    )
    
    # Write output files
    os.makedirs(args.output_dir, exist_ok=True)
    
    train_path = os.path.join(args.output_dir, "train.tsv")
    val_path = os.path.join(args.output_dir, "validation.tsv")
    test_path = os.path.join(args.output_dir, "test.tsv")
    jsonl_path = os.path.join(args.output_dir, "claims.jsonl")
    skips_path = os.path.join(args.output_dir, "skips.csv")
    
    write_tsv(train_path, train)
    write_tsv(val_path, val)
    write_tsv(test_path, test)
    write_jsonl(jsonl_path, deduped)
    
    # Write skipped records analysis
    with open(skips_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["url", "reason", "details"])
        for skip in skip_records:
            writer.writerow([skip.url, skip.reason, skip.details or ""])
    
    logger.info("✓ Output files created:")
    logger.info("  - %s", train_path)
    logger.info("  - %s", val_path)
    logger.info("  - %s", test_path)
    logger.info("  - %s", jsonl_path)
    logger.info("  - %s (skip analysis)", skips_path)


if __name__ == "__main__":
    main()