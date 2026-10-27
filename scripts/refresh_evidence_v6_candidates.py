"""Ingest and process fresh publications for the v6 confirmatory sample.

This command may take a long time because it runs scraping, preprocessing,
clustering, summarization and prediction. It deliberately disables automatic
evidence generation so the new predictions remain eligible for the blind test.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.database import SessionLocal
from app.raw.ingestion_strategies import TwitterApiIngestion
from app.raw.models import Source
from app.raw.source_catalog import seed_default_sources
from app.tasks.scheduler import ScrapingScheduler


DEFAULT_SOURCES = (
    "El Comercio",
    "RPP Noticias",
    "La Republica",
    "Agencia Andina",
    "El Peruano",
    "X - Política Perú",
)
DEFAULT_X_QUERY = "(Perú OR Lima) (política OR gobierno OR Congreso OR elecciones) lang:es -is:retweet"


def configure_x_source(db, query: str) -> Source:
    if not os.getenv("TWITTER_BEARER_TOKEN"):
        raise RuntimeError("TWITTER_BEARER_TOKEN no está configurado.")
    source = db.query(Source).filter(Source.name == "X - Política Perú").first()
    if source is None:
        source = Source(
            name="X - Política Perú",
            base_url="https://x.com/search/kenta-politica-peru",
            type="twitter",
            search_query=query,
            is_active=True,
        )
        source.register()
        db.add(source)
    else:
        source.type = "twitter"
        source.search_query = query
        source.is_active = True
    db.commit()
    db.refresh(source)
    return source


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-name",
        action="append",
        default=[],
        help="Limita la corrida a una fuente; puede repetirse.",
    )
    parser.add_argument("--x-query", default=os.getenv("TWITTER_SEARCH_QUERY") or DEFAULT_X_QUERY)
    parser.add_argument("--skip-x", action="store_true")
    parser.add_argument(
        "--check-x-only",
        action="store_true",
        help="Valida token y consulta de X sin guardar ni procesar publicaciones.",
    )
    args = parser.parse_args()

    requested = tuple(args.source_name) if args.source_name else DEFAULT_SOURCES
    if args.skip_x:
        requested = tuple(name for name in requested if name != "X - Política Perú")

    db = SessionLocal()
    results: list[dict] = []
    try:
        seed_default_sources(db)
        if "X - Política Perú" in requested:
            configure_x_source(db, " ".join(args.x_query.split()))
        if args.check_x_only:
            posts = TwitterApiIngestion(db).searchRecentPosts(" ".join(args.x_query.split()))
            referenced = sum(
                bool((post.get("social_context") or {}).get("references"))
                for post in posts
            )
            print(json.dumps({
                "x_api": "ok",
                "returned_post_n": len(posts),
                "posts_with_reference_context_n": referenced,
                "database_news_written": 0,
            }, ensure_ascii=False, indent=2))
            return
        sources = db.query(Source).filter(Source.name.in_(requested)).all()
        by_name = {source.name: source for source in sources}
        missing = [name for name in requested if name not in by_name]
        if missing:
            raise RuntimeError(f"Fuentes no registradas: {missing}")

        orchestrator = ScrapingScheduler._build_orchestrator(
            db,
            justification_service=None,
            max_auto_justifications=0,
        )
        for name in requested:
            source = by_name[name]
            if not source.is_active:
                results.append({"source": name, "status": "skipped_inactive"})
                continue
            print(f"Iniciando {name}...", flush=True)
            try:
                result = orchestrator.run_source_pipeline(source.source_id)
                results.append({"source": name, "status": "completed", **result})
                print(json.dumps(results[-1], ensure_ascii=False), flush=True)
            except Exception as exc:
                db.rollback()
                results.append({
                    "source": name,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    finally:
        db.close()

    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    if any(row["status"] == "error" for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
