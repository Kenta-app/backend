"""
Collect Newtral fact-check URLs using browser automation.

Usage:
    python scripts/collect_newtral_urls.py --output data/newtral/urls.txt

Notes:
- Requires Playwright (pip install playwright; python -m playwright install)
- The script clicks the filters and load-more button to gather links.
"""

from __future__ import annotations

import argparse
import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


FILTER_BUTTON_SELECTOR = "a.btn.btn-outline-light.btn-filter.btn-filter-icon-left"
APPLY_FILTER_SELECTOR = "div.form-submit input.btn.btn-submit.fullwidth"
LOAD_MORE_SELECTOR = "#vog-newtral-es-verification-list-load-more-btn"
LINK_SELECTOR = "h2.card-title-2 a"

RATING_LABEL_SELECTORS = {
    "false": "label.pill.add-option.red[for='checkbox-rating-false']",
    "true": "label.pill.add-option.green[for='checkbox-rating-true']",
}

RATING_INPUT_SELECTORS = {
    "false": "#checkbox-rating-false",
    "true": "#checkbox-rating-true",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Newtral fact-check URLs")
    parser.add_argument(
        "--base_url",
        default="https://www.newtral.es/zona-verificacion/fact-check/",
    )
    parser.add_argument("--output", default="data/newtral/urls.txt")
    parser.add_argument("--ratings", default="false,true")
    parser.add_argument("--load_more_clicks", type=int, default=0, help="0=all")
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--headless", action="store_true")
    return parser


def accept_cookies(page) -> None:
    selectors = [
        "button:has-text('Agree and close')",
        "button:has-text('Disagree and close')",
        "button:has-text('Aceptar')",
        "button:has-text('Aceptar y cerrar')",
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


def open_filters(page) -> None:
    try:
        page.locator(FILTER_BUTTON_SELECTOR).first.click()
        page.wait_for_selector("section.offcanvas.show, div.offcanvas.show", timeout=3000)
    except Exception:
        return


def apply_filter(page, sleep: float) -> None:
    previous_first = _get_first_link(page)
    page.locator(APPLY_FILTER_SELECTOR).first.click()
    wait_for_results_change(page, previous_first, sleep)


def select_rating(page, rating: str) -> None:
    label_selector = RATING_LABEL_SELECTORS.get(rating)
    input_selector = RATING_INPUT_SELECTORS.get(rating)
    if not label_selector or not input_selector:
        raise ValueError(f"Unsupported rating: {rating}")

    page.wait_for_selector(input_selector, state="attached", timeout=3000)

    page.evaluate(
        """
        (selectors) => {
          selectors.forEach((selector) => {
            const input = document.querySelector(selector);
            if (!input) return;
            input.checked = false;
            input.dispatchEvent(new Event('change', { bubbles: true }));
          });
        }
        """,
        list(RATING_INPUT_SELECTORS.values()),
    )

    try:
        page.locator(label_selector).first.click(force=True)
    except Exception:
        pass

    if not page.locator(input_selector).first.is_checked():
        page.evaluate(
            """
            (selector) => {
              const input = document.querySelector(selector);
              if (!input) return;
              input.checked = true;
              input.dispatchEvent(new Event('change', { bubbles: true }));
            }
            """,
            input_selector,
        )


def load_more(page, clicks: int, sleep: float) -> None:
    click_count = 0
    while True:
        button = page.locator(LOAD_MORE_SELECTOR).first
        if not button or not button.is_visible():
            break
        if is_load_more_disabled(button):
            break

        previous_first = _get_first_link(page)
        try:
            button.click()
        except Exception:
            break

        wait_for_results_change(page, previous_first, sleep)
        click_count += 1
        if clicks and click_count >= clicks:
            break


def collect_links(page) -> list[str]:
    links = page.locator(LINK_SELECTOR).evaluate_all(
        "els => els.map(el => el.href).filter(Boolean)"
    )
    return sorted(set(links))


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
        page.wait_for_selector(LINK_SELECTOR, timeout=6000)
    except Exception:
        pass

    if sleep:
        time.sleep(sleep)


def is_load_more_disabled(button) -> bool:
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


def main() -> None:
    args = build_arg_parser().parse_args()
    ratings = [item.strip() for item in args.ratings.split(",") if item.strip()]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        page = browser.new_page()
        page.goto(args.base_url, wait_until="networkidle")
        accept_cookies(page)

        all_links: list[str] = []

        for rating in ratings:
            open_filters(page)
            select_rating(page, rating)
            apply_filter(page, args.sleep)
            time.sleep(args.sleep)
            load_more(page, args.load_more_clicks, args.sleep)
            links = collect_links(page)
            all_links.extend(links)

        browser.close()

    unique_links = sorted(set(all_links))
    if not unique_links:
        raise SystemExit("No links collected. Check selectors and filters.")

    with open(args.output, "w", encoding="utf-8") as handle:
        for url in unique_links:
            handle.write(url + "\n")

    print(f"Saved {len(unique_links)} URLs to {args.output}")


if __name__ == "__main__":
    main()
