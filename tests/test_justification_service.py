import requests
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application_services.justification_service import GeminiJustificationService
from app.db.database import Base, apply_sqlite_schema_translation
from app.processed.models import JustificationSource, MlPrediction


class Value:
    def __init__(self, **values):
        self.__dict__.update(values)


class FakeResponse:
    status_code = 200
    url = (
        "https://andina.pe/agencia/noticia-ministro-defensa-supervisa-puente-aereo-"
        "para-evacuar-varados-derrumbes-arequipa-1088564.aspx"
    )
    text = """
        <html><head><meta property="og:title" content="Ministro de Defensa supervisa puente aéreo para evacuar varados por derrumbes en Arequipa"></head></html>
    """


@pytest.fixture
def saved_source_service(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    engine = apply_sqlite_schema_translation(
        create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    prediction = MlPrediction(
        representative_news_processed_id=1,
        model_version="test",
        sentiment_score=0,
        fake_score=0,
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    original = JustificationSource(
        prediction_id=prediction.prediction_id,
        url="https://andina.pe/agencia/noticia-original-123.aspx",
        source="Andina",
        title="Cobertura original válida",
        excerpt="Andina informó sobre el mismo hecho.",
        model_used="test",
    )
    db.add(original)
    db.commit()
    db.expunge(original)
    service = GeminiJustificationService(db)
    try:
        yield service, db, prediction.prediction_id
    finally:
        db.close()
        engine.dispose()


def test_empty_regeneration_preserves_saved_sources(saved_source_service, monkeypatch):
    service, db, prediction_id = saved_source_service
    monkeypatch.setattr(service, "_generate_with_retries", lambda **kwargs: {"sources": []})

    response = service.generate_justification(
        prediction_id,
        include_context=False,
        regenerate=True,
    )

    assert response["search_status"] == "no_sources_preserved"
    assert len(response["sources"]) == 1
    assert response["sources"][0]["source"] == "Andina"
    assert db.query(JustificationSource).filter_by(prediction_id=prediction_id).count() == 1


def test_persist_sources_rejects_empty_replacement(saved_source_service):
    service, db, prediction_id = saved_source_service

    persisted = service.persist_sources(prediction_id, [], "test")

    assert len(persisted) == 1
    assert db.query(JustificationSource).filter_by(prediction_id=prediction_id).count() == 1


def test_clearing_cache_does_not_delete_saved_sources(saved_source_service):
    service, db, prediction_id = saved_source_service
    service._cache[prediction_id] = {"sources": []}

    result = service.clear_cache()

    assert result == {"cleared": 1, "db_cleared": 0, "cache_size": 0}
    assert db.query(JustificationSource).filter_by(prediction_id=prediction_id).count() == 1


def test_successful_regeneration_replaces_saved_sources(saved_source_service, monkeypatch):
    service, db, prediction_id = saved_source_service
    replacement = {
        "url": "https://rpp.pe/noticias/tema-nuevo",
        "source": "RPP",
        "title": "Nueva cobertura verificada",
        "excerpt": "RPP publicó una cobertura relacionada.",
    }
    monkeypatch.setattr(
        service,
        "_generate_with_retries",
        lambda **kwargs: {"sources": [replacement]},
    )

    response = service.generate_justification(
        prediction_id,
        include_context=False,
        regenerate=True,
    )

    assert response["search_status"] == "success"
    assert response["sources"] == [replacement]
    rows = db.query(JustificationSource).filter_by(prediction_id=prediction_id).all()
    assert len(rows) == 1
    assert rows[0].url == replacement["url"]


def test_source_allowlist_checks_domain_not_claimed_name(saved_source_service):
    service, _, _ = saved_source_service
    assert service._is_allowed_source({"url": "https://rpp.pe/noticia/1", "source": "RPP"})
    assert not service._is_allowed_source({"url": "https://rpp-falso.example/noticia/1", "source": "RPP"})


def test_grounding_source_uses_resolved_canonical_url(monkeypatch):
    service = object.__new__(GeminiJustificationService)
    monkeypatch.setattr(
        GeminiJustificationService,
        "_fetch_source_response",
        classmethod(lambda cls, url: FakeResponse()),
    )
    monkeypatch.setattr(
        GeminiJustificationService,
        "_resolve_grounding_url",
        classmethod(lambda cls, url: FakeResponse.url),
    )
    response = Value(
        candidates=[
            Value(
                grounding_metadata=Value(
                    grounding_chunks=[
                        Value(
                            web=Value(
                                uri="https://vertexaisearch.cloud.google.com/grounding-api-redirect/example",
                                title="El Comercio",
                            )
                        )
                    ],
                    grounding_supports=[
                        Value(
                            segment=Value(text="Andina informó sobre el puente aéreo para evacuar a las personas varadas."),
                            grounding_chunk_indices=[0],
                        )
                    ],
                )
            )
        ]
    )

    diagnostics = {}
    sources = service._sources_from_grounding(response, diagnostics=diagnostics)

    assert sources == [
        {
            "url": FakeResponse.url,
            "source": "Andina",
            "title": "Ministro de Defensa supervisa puente aéreo para evacuar varados por derrumbes en Arequipa",
            "excerpt": "Andina informó sobre el puente aéreo para evacuar a las personas varadas.",
        }
    ]
    assert diagnostics == {
        "grounding_chunks": 1,
        "candidate_urls": 1,
        "validated_urls": 1,
    }


def test_grounding_diagnostics_count_rejected_domain(monkeypatch):
    service = object.__new__(GeminiJustificationService)
    rejected = FakeResponse()
    rejected.url = "https://example.com/noticia"
    monkeypatch.setattr(
        GeminiJustificationService,
        "_fetch_source_response",
        classmethod(lambda cls, url: rejected),
    )
    response = Value(
        candidates=[Value(grounding_metadata=Value(
            grounding_chunks=[Value(web=Value(uri=rejected.url, title="Noticia"))],
            grounding_supports=[],
        ))]
    )
    diagnostics = {}

    sources = service._sources_from_grounding(response, diagnostics=diagnostics)

    assert sources == []
    assert diagnostics == {
        "grounding_chunks": 1,
        "candidate_urls": 1,
        "domain_not_allowed": 1,
    }


def test_normalization_never_uses_model_written_urls():
    service = object.__new__(GeminiJustificationService)
    service.max_sources = 4

    report = service._normalize_report(
        {
            "sources": [
                {
                    "url": "https://andina.pe/agencia/noticia-inventada-123.html",
                    "source": "Andina",
                    "title": "Título inventado",
                    "excerpt": "Texto inventado",
                }
            ]
        },
        grounding_sources=[],
    )

    assert report == {"sources": []}


def test_url_validation_rejects_a_403_response(monkeypatch):
    blocked = FakeResponse()
    blocked.status_code = 403
    monkeypatch.setattr(
        GeminiJustificationService,
        "_fetch_source_response",
        classmethod(lambda cls, url: blocked),
    )

    assert not GeminiJustificationService._is_valid_source_url(
        "https://andina.pe/agencia/noticia-inventada-123.html",
        "Título inventado",
    )


def test_google_redirect_is_resolved_without_fetching_the_destination(monkeypatch):
    redirect = type(
        "RedirectResponse",
        (),
        {
            "status_code": 302,
            "headers": {
                "Location": "https://elcomercio.pe/opinion/columnistas/un-voto-menos-por-martin-hidalgo-noticia/"
            },
        },
    )()
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: redirect)

    resolved = GeminiJustificationService._resolve_grounding_url(
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example"
    )

    assert resolved == "https://elcomercio.pe/opinion/columnistas/un-voto-menos-por-martin-hidalgo-noticia/"


def test_google_redirect_is_kept_when_a_verified_destination_rate_limits_the_server():
    service = object.__new__(GeminiJustificationService)

    source = service._grounding_redirect_fallback(
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example",
        "https://elcomercio.pe/opinion/columnistas/un-voto-menos-por-martin-hidalgo-noticia/",
        "",
        ["El Comercio publicó una columna relacionada con el tema."],
        429,
    )

    assert source == {
        "url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example",
        "canonical_url": "https://elcomercio.pe/opinion/columnistas/un-voto-menos-por-martin-hidalgo-noticia/",
        "source": "El Comercio",
        "title": "Cobertura relacionada de El Comercio",
        "excerpt": "El Comercio publicó una columna relacionada con el tema.",
    }
