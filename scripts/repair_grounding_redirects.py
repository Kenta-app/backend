"""Replace persisted Google grounding redirects with direct publisher URLs.

Dry-run by default. This does not call Gemini or alter source titles/excerpts.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.application_services.justification_service import GeminiJustificationService
from app.db.database import SessionLocal
from app.processed.models import JustificationSource

REDIRECT_PREFIX = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"


def resolve_publisher_url(service, redirect_url: str, expected_source: str) -> tuple[str | None, str]:
    target = service._resolve_grounding_url(redirect_url)
    if not target:
        return None, "redirect_not_resolved"
    parsed = urlparse(target)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return None, "unsafe_destination"
    actual_source = service._source_name_from_url(target)
    if actual_source.casefold() != expected_source.casefold():
        return None, "publisher_mismatch"
    if not service._is_allowed_source({"url": target, "source": actual_source}):
        return None, "publisher_not_allowed"
    return target, "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist reviewed URL changes")
    parser.add_argument("--limit", type=int, default=20, help="Maximum redirects to inspect")
    parser.add_argument("--after-id", type=int, default=0, help="Inspect only source IDs greater than this value")
    parser.add_argument("--prediction-id", type=int, default=None, help="Restrict to one prediction")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 100 or args.after_id < 0:
        parser.error("--limit must be 1..100 and --after-id must be nonnegative")

    db = SessionLocal()
    try:
        query = db.query(JustificationSource).filter(
            JustificationSource.url.like(f"{REDIRECT_PREFIX}%"),
            JustificationSource.justification_source_id > args.after_id,
        )
        if args.prediction_id is not None:
            query = query.filter(JustificationSource.prediction_id == args.prediction_id)
        rows = query.order_by(JustificationSource.justification_source_id).limit(args.limit).all()
        service = GeminiJustificationService(db)
        resolved = 0
        skipped = 0
        for row in rows:
            target, reason = resolve_publisher_url(service, row.url, row.source)
            if not target:
                skipped += 1
                print(f"SKIP id={row.justification_source_id} prediction={row.prediction_id} reason={reason}")
                continue
            duplicate = db.query(JustificationSource.justification_source_id).filter(
                JustificationSource.prediction_id == row.prediction_id,
                JustificationSource.justification_source_id != row.justification_source_id,
                JustificationSource.url == target,
            ).first()
            if duplicate:
                skipped += 1
                print(f"SKIP id={row.justification_source_id} prediction={row.prediction_id} reason=duplicate_direct_url")
                continue
            resolved += 1
            print(f"DIRECT id={row.justification_source_id} prediction={row.prediction_id} source={row.source} url={target}")
            if args.apply:
                row.url = target

        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(f"RESULT inspected={len(rows)} resolved={resolved} skipped={skipped} applied={args.apply} last_id={rows[-1].justification_source_id if rows else args.after_id}")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
