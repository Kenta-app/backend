from __future__ import annotations

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text


def main() -> None:
    load_dotenv(encoding="utf-8-sig")
    database_url = os.getenv("DATABASE_URL") or os.getenv("MYSQL_DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL o MYSQL_DATABASE_URL es obligatoria para ejecutar la migración.")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        if engine.dialect.name != "postgresql":
            print("Migración omitida: solo se necesita para PostgreSQL.")
            return
        if not inspect(engine).has_table("news_raw", schema="raw"):
            print("Migración omitida: raw.news_raw se creará al iniciar la API.")
            return

        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE raw.news_raw "
                    "ADD COLUMN IF NOT EXISTS social_context JSONB"
                )
            )
        print("Migración de contexto social completada.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
