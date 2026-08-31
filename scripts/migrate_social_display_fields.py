from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect, text


def main() -> None:
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL es obligatoria para ejecutar la migración.")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        if engine.dialect.name != "postgresql":
            print("Migración omitida: solo se necesita para PostgreSQL.")
            return
        if not inspect(engine).has_table("news", schema="serving"):
            print("Migración omitida: la tabla serving.news se creará al iniciar la API.")
            return

        statements = [
            "ALTER TABLE serving.news ADD COLUMN IF NOT EXISTS source_account VARCHAR(100)",
            "ALTER TABLE serving.news ADD COLUMN IF NOT EXISTS display_text TEXT",
            "ALTER TABLE serving.news ADD COLUMN IF NOT EXISTS content_type VARCHAR(30) NOT NULL DEFAULT 'article'",
            "ALTER TABLE serving.news ADD COLUMN IF NOT EXISTS content_warning VARCHAR(50)",
            "ALTER TABLE serving.news ADD COLUMN IF NOT EXISTS external_links JSONB",
            "CREATE INDEX IF NOT EXISTS ix_serving_news_content_type ON serving.news (content_type)",
            "CREATE INDEX IF NOT EXISTS ix_serving_news_content_warning ON serving.news (content_warning)",
        ]
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
        print("Migración de campos de presentación social completada.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
