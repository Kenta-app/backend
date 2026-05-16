"""
Collect PeruCheck verification URLs by clicking the "Ver mas" button.

Usage:
    python scripts/collect_perucheck_urls_click.py --output data/perucheck/urls.txt
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_URL = "https://perucheck.pe/verificaciones"


def extract_article_urls(page) -> set[str]:
    urls: set[str] = set()
    links = page.locator('a[href*="/articles/verificadas/"]')
    count = links.count()
    for i in range(count):
        href = links.nth(i).get_attribute("href")
        if not href:
            continue
        if href.startswith("http"):
            urls.add(href)
        else:
            urls.add("https://perucheck.pe" + href)
    return urls


def extract_urls_from_next_data(page) -> set[str]:
    """Extract article URLs from the Next.js bootstrap payload."""
    urls: set[str] = set()
    content = page.content()
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        content,
        flags=re.DOTALL,
    )
    if not match:
        return urls

    try:
        payload = json.loads(match.group(1))
    except Exception:
        return urls

    articles = (
        payload.get("props", {})
        .get("pageProps", {})
        .get("dataArticl", {})
        .get("articles", {})
        .get("data", [])
    )

    for item in articles:
        if not isinstance(item, dict):
            continue
        slug = item.get("slug")
        if not slug:
            continue
        if slug.startswith("http"):
            urls.add(slug)
        else:
            urls.add("https://perucheck.pe" + slug)

    return urls


def dismiss_common_banners(page) -> None:
    """Try to close cookie/privacy dialogs that may block interactions."""
    candidates = [
        page.get_by_role("button", name=re.compile(r"acept|accept|entendid", re.IGNORECASE)),
        page.get_by_role("button", name=re.compile(r"ok|cerrar|close", re.IGNORECASE)),
    ]
    for locator in candidates:
        try:
            if locator.count() > 0 and locator.first.is_visible():
                locator.first.click(timeout=2000)
                time.sleep(0.3)
        except Exception:
            continue


def find_ver_mas_button(page):
    # Avoid CSS class selectors because they are dynamic (styled-components hashes).
    candidates = [
        page.locator("div.sc-fBdRDi.fvgcPP >> button.sc-ihgnxF.dWIKEH"),
        page.get_by_role("button", name=re.compile(r"ver\s+m[aá]s", re.IGNORECASE)),
        page.locator("button", has_text=re.compile(r"ver\s+m[aá]s", re.IGNORECASE)),
        page.locator("[role='button']", has_text=re.compile(r"ver\s+m[aá]s", re.IGNORECASE)),
        page.locator("a", has_text=re.compile(r"ver\s+m[aá]s", re.IGNORECASE)),
        page.locator("text=/ver\\s+m[aá]s/i"),
    ]
    for locator in candidates:
        try:
            if locator.count() > 0 and locator.first.is_visible():
                return locator.first
        except Exception:
            continue
    return None


def collect_urls(max_clicks: int, sleep_after_click: float, headless: bool) -> list[str]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2500)
        dismiss_common_banners(page)

        seen = extract_article_urls(page)
        seen.update(extract_urls_from_next_data(page))
        logger.info("Initial URLs found: %d", len(seen))

        click_num = 0
        stale_clicks = 0

        while True:
            if max_clicks > 0 and click_num >= max_clicks:
                logger.info("Reached max_clicks=%d", max_clicks)
                break

            button = find_ver_mas_button(page)
            if button is None:
                logger.info("'Ver mas' button not found or not visible. Stopping.")
                break

            before = len(seen)
            click_num += 1
            logger.info("Clicking 'Ver mas' (%d)", click_num)

            try:
                button.scroll_into_view_if_needed(timeout=5000)
                button.click(timeout=10000, force=True)
            except PlaywrightTimeoutError:
                logger.info("Timeout clicking button. Stopping.")
                break

            time.sleep(sleep_after_click)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                pass

            seen.update(extract_article_urls(page))
            seen.update(extract_urls_from_next_data(page))
            after = len(seen)
            new_count = after - before

            logger.info("After click %d: +%d new URLs (total=%d)", click_num, new_count, after)

            if new_count == 0:
                stale_clicks += 1
                if stale_clicks >= 2:
                    logger.info("No new URLs after consecutive clicks. Stopping.")
                    break
            else:
                stale_clicks = 0

        browser.close()

    return sorted(seen)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect PeruCheck URLs by clicking 'Ver mas'")
    parser.add_argument("--output", required=True, help="Output file with one URL per line")
    parser.add_argument("--max_clicks", type=int, default=0, help="Max clicks (0 = until end)")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds to wait after each click")
    parser.add_argument("--headed", action="store_true", help="Run browser with UI (debug)")
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    urls = collect_urls(max_clicks=args.max_clicks, sleep_after_click=args.sleep, headless=not args.headed)

    with open(args.output, "w", encoding="utf-8") as handle:
        for url in urls:
            handle.write(url + "\n")

    logger.info("Saved %d URLs to %s", len(urls), args.output)


if __name__ == "__main__":
    main()
