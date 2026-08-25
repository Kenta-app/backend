"""Verifica que exista processed.justification_sources."""
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import inspect, text

from app.db.database import engine

inspector = inspect(engine)
schemas = inspector.get_schema_names()
print("Schemas:", [s for s in schemas if s not in ("information_schema", "pg_catalog")])

if "processed" in schemas:
    tables = inspector.get_table_names(schema="processed")
    print("Tablas en processed:", tables)
    if "justification_sources" in tables:
        cols = inspector.get_columns("justification_sources", schema="processed")
        print("--- Columnas de processed.justification_sources ---")
        for col in cols:
            print(f"  {col['name']}: {col['type']} nullable={col['nullable']}")
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM processed.justification_sources")
            ).scalar()
            print(f"--- Registros: {count} ---")
    else:
        print("NO existe processed.justification_sources")
else:
    print("Schema processed no encontrado")
    print("Todas las tablas:", inspector.get_table_names())
