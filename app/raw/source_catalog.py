from __future__ import annotations

from sqlalchemy.orm import Session

from app.raw.models import Source

DEFAULT_SOURCES: list[dict[str, str]] = [
    {
        "name": "El Comercio",
        "base_url": "https://elcomercio.pe/politica/",
        "type": "web",
    },
    {
        "name": "RPP Noticias",
        "base_url": "https://rpp.pe/politica/",
        "type": "web",
    },
    {
        "name": "La Republica",
        "base_url": "https://larepublica.pe/politica/",
        "type": "web",
    },
    {
        "name": "Peru21",
        "base_url": "https://peru21.pe/politica/",
        "type": "web",
    },
]


def seed_default_sources(db: Session) -> list[Source]:
    created_or_existing: list[Source] = []

    for source_data in DEFAULT_SOURCES:
        source = db.query(Source).filter(Source.name == source_data["name"]).first()
        if not source:
            source = Source(**source_data)
            source.register()
            db.add(source)
            db.flush()
        created_or_existing.append(source)

    db.commit()
    return created_or_existing
