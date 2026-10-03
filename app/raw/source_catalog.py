from __future__ import annotations

from sqlalchemy.orm import Session

from app.raw.models import Source

DEFAULT_SOURCES: list[dict[str, object]] = [
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
        # The publisher currently returns Cloudflare 403 responses from the
        # production droplet. Keep it registered but inactive until a
        # permitted feed or stable endpoint is available.
        "is_active": False,
    },
    {
        "name": "Agencia Andina",
        "base_url": "https://andina.pe/agencia/seccion-politica-17.aspx",
        "type": "web",
    },
    {
        "name": "El Peruano",
        "base_url": "https://elperuano.pe/",
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
        elif source_data.get("is_active") is False and source.is_active:
            source.is_active = False
            db.add(source)
        created_or_existing.append(source)

    db.commit()
    return created_or_existing
