from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, apply_sqlite_schema_translation
from app.processed.models import JustificationRun, JustificationSource, MlPrediction
from app.raw.models import Source
from app.serving.models import PublishedNews
from scripts.generate_related_sources import classify_attempt, load_targets


def test_preserved_sources_do_not_turn_an_empty_search_into_a_success():
    result = {
        "search_status": "no_sources_preserved",
        "sources": [{"url": "https://andina.pe/previous"}],
    }

    assert classify_attempt(result) == ("no_sources", 0)


def test_new_sources_are_counted_as_a_success():
    result = {
        "search_status": "success",
        "sources": [{"url": "https://rpp.pe/new"}],
    }

    assert classify_attempt(result) == ("success", 1)


def test_recovery_targets_only_previous_successes_now_missing_sources():
    engine = apply_sqlite_schema_translation(create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    ))
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        source = Source(name="Fuente prueba", base_url="https://example.com", type="web")
        db.add(source)
        db.flush()
        for index in range(1, 4):
            prediction = MlPrediction(
                representative_news_processed_id=index,
                model_version="test", sentiment_score=0, fake_score=0,
            )
            db.add(prediction)
            db.flush()
            db.add(PublishedNews(
                representative_news_processed_id=index,
                source_id=source.source_id,
                title=f"Noticia {index}", original_url=f"https://example.com/{index}",
                published_at=datetime.utcnow(), fake_score=0.1,
            ))
            if index in (1, 3):
                db.add(JustificationRun(
                    prediction_id=prediction.prediction_id,
                    status="success", source_count=1, model_used="test",
                ))
            if index == 3:
                db.add(JustificationSource(
                    prediction_id=prediction.prediction_id,
                    url="https://andina.pe/test", source="Andina", title="Noticia",
                    excerpt="Cobertura", model_used="test",
                ))
        db.commit()

        targets = load_targets(db, 10, False, None, False, None, True)

        assert len(targets) == 1
        assert targets[0][0] == 1
    finally:
        db.close()
        engine.dispose()
