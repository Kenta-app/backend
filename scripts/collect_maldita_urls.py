"""
Collect Maldita fact-check URLs using browser automation.

Usage:
    python scripts/collect_maldita_urls.py --output data/maldita/urls.txt

Notes:
- Requires Playwright (pip install playwright; python -m playwright install)
"""

from __future__ import annotations

import argparse
import os
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


GRID_SELECTOR = "div.grid.grid-cols-1.md\\:grid-cols-2.lg\\:grid-cols-3.gap-4"
LINK_SELECTOR = f"{GRID_SELECTOR} a"
NEXT_BUTTON_SELECTOR = "button[type='button'][data-live-action-param='nextPreviousPage']"

RATING_INPUT_SELECTORS = {
    "false": "input[type='checkbox'][value='1']",
    "true": "input[type='checkbox'][value='3']",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Maldita URLs")
    parser.add_argument(
        "--base_url",
        default="https://maldita.es/area/desinfo/",
    )
    parser.add_argument("--output", default="data/maldita/urls.txt")
    parser.add_argument("--ratings", default="false,true")
    parser.add_argument("--max_pages", type=int, default=0, help="0=all")
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--headless", action="store_true")
    return parser


def accept_cookies(page) -> None:
    selectors = [
        "button:has-text('Aceptar')",
        "button:has-text('Aceptar todo')",
        "button:has-text('Aceptar y cerrar')",
        "button:has-text('Agree')",
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button and button.is_visible():
                button.click()
                return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue


def set_rating_filter(page, rating: str, sleep: float) -> None:
    if rating not in RATING_INPUT_SELECTORS:
        raise ValueError(f"Unsupported rating: {rating}")

    previous_first = _get_first_link(page)

    selectors = list(RATING_INPUT_SELECTORS.values())
    page.wait_for_selector(selectors[0], state="attached", timeout=5000)

    page.evaluate(
        """
        (allSelectors) => {
          allSelectors.forEach((selector) => {
            const input = document.querySelector(selector);
            if (!input) return;
            input.checked = false;
            input.dispatchEvent(new Event('change', { bubbles: true }));
          });
        }
        """,
        selectors,
    )

    page.evaluate(
        """
        (selector) => {
          const input = document.querySelector(selector);
          if (!input) return;
          input.checked = true;
          input.dispatchEvent(new Event('change', { bubbles: true }));
        }
        """,
        RATING_INPUT_SELECTORS[rating],
    )

    wait_for_results_change(page, previous_first, sleep)


def collect_links(page) -> list[str]:
    page.wait_for_selector(GRID_SELECTOR, timeout=5000)
    return page.locator(LINK_SELECTOR).evaluate_all(
        "els => els.map(el => el.href).filter(Boolean)"
    )


def _get_first_link(page) -> str | None:
    try:
        link = page.locator(LINK_SELECTOR).first
        if link and link.is_visible():
            return link.get_attribute("href")
    except Exception:
        return None
    return None


def wait_for_results_change(page, previous_first: str | None, sleep: float) -> None:
    if previous_first:
        try:
            page.wait_for_function(
                """
                (selector, prev) => {
                  const el = document.querySelector(selector);
                  return el && el.href && el.href !== prev;
                }
                """,
                arg=(LINK_SELECTOR, previous_first),
                timeout=6000,
            )
            return
        except Exception:
            pass

    try:
        page.wait_for_selector(GRID_SELECTOR, timeout=6000)
    except Exception:
        pass

    if sleep:
        time.sleep(sleep)


def is_next_disabled(button) -> bool:
    try:
        if button.is_disabled():
            return True
    except Exception:
        pass
    try:
        attr = button.get_attribute("disabled")
        if attr is not None:
            return True
        aria_disabled = button.get_attribute("aria-disabled")
        if aria_disabled == "true":
            return True
    except Exception:
        pass
    return False


def click_next(page, sleep: float) -> bool:
    buttons = page.locator("button[type='button']")
    selected = None

    try:
        for index in range(buttons.count()):
            candidate = buttons.nth(index)
            text = (candidate.text_content() or "").strip()
            if text == ">":
                selected = candidate
                break
    except Exception:
        selected = None

    if selected is None:
        selected = page.locator(NEXT_BUTTON_SELECTOR).last

    if not selected or not selected.is_visible():
        return False
    if is_next_disabled(selected):
        return False
    try:
        previous_first = _get_first_link(page)
        selected.click()
    except Exception:
        return False
    wait_for_results_change(page, previous_first, sleep)
    return True


def collect_for_rating(page, rating: str, max_pages: int, sleep: float) -> list[str]:
    set_rating_filter(page, rating, sleep)

    links: set[str] = set()
    page_count = 0

    while True:
        page_count += 1
        current_links = collect_links(page)
        links.update(current_links)

        if max_pages and page_count >= max_pages:
            break
        if not click_next(page, sleep):
            break

    return sorted(links)


def main() -> None:
    args = build_arg_parser().parse_args()
    ratings = [item.strip() for item in args.ratings.split(",") if item.strip()]

    all_links: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_page()
        page.goto(args.base_url, wait_until="networkidle")
        accept_cookies(page)

        for rating in ratings:
            page.goto(args.base_url, wait_until="networkidle")
            accept_cookies(page)
            links = collect_for_rating(page, rating, args.max_pages, args.sleep)
            all_links.extend(links)

        browser.close()

    unique_links = sorted(set(all_links))
    if not unique_links:
        raise SystemExit("No links collected. Check selectors.")

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w", encoding="utf-8") as handle:
        for url in unique_links:
            handle.write(url + "\n")

    print(f"Saved {len(unique_links)} URLs to {args.output}")


if __name__ == "__main__":
    main()
