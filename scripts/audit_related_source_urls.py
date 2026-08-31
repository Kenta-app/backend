from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import requests

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
    return parser.parse_args()


def check_url(url: str, timeout: float) -> tuple[bool, int | None, str | None]:
    try:
        response = requests.head(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers=HEADERS,
        )
        if response.status_code in {405, 429}:
            response = requests.get(
                url,
                allow_redirects=True,
                timeout=timeout,
                headers=HEADERS,
                stream=True,
            )
        status = response.status_code
        ok = 200 <= status < 400 or status in {401, 403}
        return ok, status, response.url
    except requests.RequestException as exc:
        return False, None, str(exc)


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
            ok, status, final_url = check_url(source.url, args.timeout)
            if ok:
                continue

            broken += 1
            print("---")
            print(f"justification_source_id={source.justification_source_id}")
            print(f"news_id={news.news_id} prediction_id={source.prediction_id}")
            print(f"status={status} detail={final_url}")
            print(f"news={news.title[:140]}")
            print(f"source={source.source}")
            print(f"title={source.title[:180]}")
            print(f"url={source.url}")

            if args.delete_broken:
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
