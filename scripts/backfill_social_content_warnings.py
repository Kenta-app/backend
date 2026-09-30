"""Recalculate warnings for existing X posts; dry-run unless --apply is supplied.

This updates only the warning flag. It never changes or removes the original text.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.database import SessionLocal
from app.serving.content_normalization import detect_content_warning
from app.serving.models import PublishedNews


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist changes after reviewing the dry run")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        posts = db.query(PublishedNews).filter(PublishedNews.content_type == "social_post").all()
        changed = []
        flagged = 0
        for post in posts:
            warning = detect_content_warning(post.display_text)
            flagged += warning == "strong_language"
            if post.content_warning != warning:
                changed.append((post.news_id, post.content_warning, warning))
                if args.apply:
                    post.content_warning = warning

        print(f"X posts reviewed: {len(posts)}")
        print(f"X posts flagged by current rules: {flagged}")
        print(f"Warnings to update: {len(changed)}")
        print(f"IDs to update (first 50): {[item[0] for item in changed[:50]]}")
        if args.apply:
            db.commit()
            print("Changes committed. Post text was not modified.")
        else:
            db.rollback()
            print("Dry run only. Rerun with --apply after review.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

