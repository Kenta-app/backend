"""Crea o actualiza la fuente de búsqueda política peruana en X.

La consulta se toma de TWITTER_SEARCH_QUERY o de --query. Este script no llama
a la API de X ni procesa noticias; solo registra la configuración en la base.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.db.database import SessionLocal  # noqa: E402
from app.raw.models import Source  # noqa: E402

DEFAULT_NAME = "X - Política Perú"
DEFAULT_BASE_URL = "https://x.com/search/kenta-politica-peru"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configura una fuente de búsqueda reciente de X.")
    parser.add_argument("--name", default=DEFAULT_NAME)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--query", default=os.getenv("TWITTER_SEARCH_QUERY", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    query = " ".join(args.query.split())
    if not query:
        raise ValueError("Define TWITTER_SEARCH_QUERY o proporciona --query.")
    if len(query) > 512:
        raise ValueError("TWITTER_SEARCH_QUERY no puede superar 512 caracteres.")

    db = SessionLocal()
    try:
        source = db.query(Source).filter(Source.name == args.name).first()
        if source is None:
            source = Source(
                name=args.name,
                base_url=args.base_url,
                type="twitter",
                search_query=query,
                is_active=True,
            )
            source.register()
            db.add(source)
            action = "creada"
        else:
            source.base_url = args.base_url
            source.source_account = None
            source.search_query = query
            source.type = "twitter"
            source.activate()
            action = "actualizada"
        db.commit()
        db.refresh(source)
        print(f"Fuente {action}: id={source.source_id} nombre={source.name}")
        print(f"Consulta: {source.search_query}")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
