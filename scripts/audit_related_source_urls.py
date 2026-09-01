from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import requests
from bs4 import BeautifulSoup

from app.db.database import SessionLocal
from app.processed.models import JustificationSource, MlPrediction
from app.serving.models import PublishedNews


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audita URLs guardadas como fuentes relacionadas.")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=8)
    parser.add_argument(
        "--delete-broken",
        action="store_true",
        help="Elimina de la base las fuentes claramente rotas.",
    )
    parser.add_argument(
        "--delete-invalid",
        action="store_true",
        help="Elimina fuentes rotas o cuyo título real no coincide con el guardado.",
    )
    return parser.parse_args()


def title_overlap(left: str, right: str) -> float:
    import re

    left_tokens = {
        token
        for token in re.findall(r"\w+", (left or "").casefold())
        if len(token) >= 4
    }
    right_tokens = {
        token
        for token in re.findall(r"\w+", (right or "").casefold())
        if len(token) >= 4
    }
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), 1)


def extract_page_title(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for selector in (
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
        "h1",
        "title",
    ):
        element = soup.select_one(selector)
        if not element:
            continue
        value = element.get("content") if element.name == "meta" else element.get_text(" ")
        value = " ".join((value or "").split())
        if value:
            return value
    return ""


def check_url(url: str, expected_title: str, timeout: float) -> tuple[bool, int | None, str | None, float | None]:
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers=HEADERS,
            stream=True,
        )
        response._content = response.raw.read(120_000, decode_content=True)
        status = response.status_code
        if status in {401, 403}:
            return True, status, response.url, None
        if not 200 <= status < 400:
            return False, status, response.url, None

        page_title = extract_page_title(response.text)
        if not page_title:
            return True, status, "no_page_title", None

        overlap = title_overlap(expected_title, page_title)
        return overlap >= 0.35, status, page_title[:220], overlap
    except requests.RequestException as exc:
        return False, None, str(exc), None


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    try:
        rows = (
            db.query(JustificationSource, PublishedNews)
            .join(MlPrediction, MlPrediction.prediction_id == JustificationSource.prediction_id)
            .join(
                PublishedNews,
                PublishedNews.representative_news_processed_id
                == MlPrediction.representative_news_processed_id,
            )
            .order_by(JustificationSource.created_at.desc())
            .limit(max(1, args.limit))
            .all()
        )

        checked = 0
        broken = 0
        deleted = 0
        for source, news in rows:
            checked += 1
            ok, status, detail, overlap = check_url(source.url, source.title, args.timeout)
            if ok:
                continue

            broken += 1
            print("---")
            print(f"justification_source_id={source.justification_source_id}")
            print(f"news_id={news.news_id} prediction_id={source.prediction_id}")
            print(f"status={status} overlap={overlap} detail={detail}")
            print(f"news={news.title[:140]}")
            print(f"source={source.source}")
            print(f"title={source.title[:180]}")
            print(f"url={source.url}")

            if args.delete_invalid or (args.delete_broken and (status is None or status >= 400)):
                db.delete(source)
                deleted += 1

        if args.delete_broken and deleted:
            db.commit()

        print("")
        print(f"checked={checked} broken={broken} deleted={deleted}")
        return 0 if broken == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
