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
        if not inspect(engine).has_table("justification_sources", schema="processed"):
            print("Migración omitida: la tabla se creará al iniciar la API.")
            return

        statements = [
            "ALTER TABLE processed.justification_sources ADD COLUMN IF NOT EXISTS claim TEXT",
            "ALTER TABLE processed.justification_sources ADD COLUMN IF NOT EXISTS evidence_stance VARCHAR(20) NOT NULL DEFAULT 'discusses'",
            "ALTER TABLE processed.justification_sources ADD COLUMN IF NOT EXISTS relevance_score NUMERIC(5, 4)",
            "ALTER TABLE processed.justification_sources ADD COLUMN IF NOT EXISTS independence_key VARCHAR(255)",
            "ALTER TABLE processed.justification_sources ADD COLUMN IF NOT EXISTS assessment_method VARCHAR(50) NOT NULL DEFAULT 'legacy_related_source'",
            "ALTER TABLE processed.justification_sources ADD COLUMN IF NOT EXISTS assessment_version VARCHAR(50) NOT NULL DEFAULT 'evidence-policy-2026-10-25-v4'",
            "ALTER TABLE processed.justification_sources ALTER COLUMN assessment_version SET DEFAULT 'evidence-policy-2026-10-25-v4'",
            "CREATE INDEX IF NOT EXISTS ix_justification_sources_evidence_stance ON processed.justification_sources (evidence_stance)",
            "CREATE INDEX IF NOT EXISTS ix_justification_sources_independence_key ON processed.justification_sources (independence_key)",
        ]
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
        print("Migración de evaluación de evidencia completada.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
