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
        inspector = inspect(engine)
        if not inspector.has_table("users", schema="serving"):
            print("Migración omitida: la tabla serving.users se creará al iniciar la API.")
            return

        statements = [
            # Migraciones históricas requeridas por los modelos actuales.
            "ALTER TABLE raw.source ADD COLUMN IF NOT EXISTS source_account VARCHAR(100)",
            "ALTER TABLE raw.source ADD COLUMN IF NOT EXISTS search_query VARCHAR(512)",
            "ALTER TABLE raw.news_raw ADD COLUMN IF NOT EXISTS image_url TEXT",
            "ALTER TABLE serving.news ADD COLUMN IF NOT EXISTS image_url TEXT",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS birth_date DATE",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS gender VARCHAR(50)",
            # Verificación de correo y evidencia de aceptación de documentos.
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMP",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS email_verification_code_hash VARCHAR(128)",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS email_verification_expires_at TIMESTAMP",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS email_verification_sent_at TIMESTAMP",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS email_verification_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS terms_version VARCHAR(32)",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMP",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS privacy_policy_version VARCHAR(32)",
            "ALTER TABLE serving.users ADD COLUMN IF NOT EXISTS privacy_policy_accepted_at TIMESTAMP",
            "CREATE INDEX IF NOT EXISTS ix_users_email_verified_at ON serving.users (email_verified_at)",
            "UPDATE serving.users SET email_verified_at = created_at WHERE email_verified_at IS NULL",
        ]
        telemetry_migrations = {
            "news_views": [
                "ALTER TABLE serving.news_views ADD COLUMN IF NOT EXISTS client_event_id VARCHAR(64)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_view_event ON serving.news_views (user_id, client_event_id)",
            ],
            "news_click": [
                "ALTER TABLE serving.news_click ADD COLUMN IF NOT EXISTS client_event_id VARCHAR(64)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_click_event ON serving.news_click (user_id, client_event_id)",
            ],
            "news_detail_clicks": [
                "ALTER TABLE serving.news_detail_clicks ADD COLUMN IF NOT EXISTS client_event_id VARCHAR(64)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_detail_event ON serving.news_detail_clicks (user_id, client_event_id)",
            ],
            "user_app_sessions": [
                "ALTER TABLE serving.user_app_sessions ADD COLUMN IF NOT EXISTS client_session_id VARCHAR(64)",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_client_session ON serving.user_app_sessions (user_id, client_session_id)",
            ],
            "news_reactions": [
                "ALTER TABLE serving.news_reactions ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
                "UPDATE serving.news_reactions SET updated_at = created_at WHERE updated_at IS NULL",
                "ALTER TABLE serving.news_reactions ALTER COLUMN updated_at SET NOT NULL",
            ],
        }
        for table_name, table_statements in telemetry_migrations.items():
            if inspector.has_table(table_name, schema="serving"):
                statements.extend(table_statements)
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
        print("Migraciones de autenticación y telemetría completadas.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
