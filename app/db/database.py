from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv(
    "MYSQL_DATABASE_URL",
    "sqlite:///./kenta.db",
)

SQLITE_SCHEMA_TRANSLATE_MAP = {
    "raw": None,
    "processed": None,
    "serving": None,
}

engine_kwargs = {}
if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True


def apply_sqlite_schema_translation(engine):
    if engine.dialect.name != "sqlite":
        return engine
    return engine.execution_options(schema_translate_map=SQLITE_SCHEMA_TRANSLATE_MAP)


engine = apply_sqlite_schema_translation(create_engine(DATABASE_URL, **engine_kwargs))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
