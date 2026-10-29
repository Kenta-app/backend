from datetime import datetime

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application_services.justification_service import GeminiJustificationService
from app.db.database import Base, apply_sqlite_schema_translation
from app.processed.models import (
    ClusterMember,
    JustificationSource,
    MlPrediction,
    NewsCluster,
    ProcessedNews,
)
from app.raw.models import IngestionLog, RawNews, Source
from app.serving.models import PublishedNews


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


def test_justification_response_respects_official_source_risk_withholding(saved_source_service):
    service, db, prediction_id = saved_source_service
    source = Source(name="El Peruano", base_url="https://elperuano.pe", type="web")
    db.add(source)
    db.flush()
    db.add(PublishedNews(
        representative_news_processed_id=1,
        source_id=source.source_id,
        title="Publicación oficial",
        original_url="https://elperuano.pe/noticia/prueba",
        published_at=datetime.utcnow(),
        fake_score=0.95,
    ))
    db.commit()

    response = service.get_persisted_justification(prediction_id)

    assert response["ml_prediction"]["fake_score"] is None
    assert response["ml_prediction"]["analysis_status"] == "withheld_source_policy"


def test_clearing_cache_does_not_delete_saved_sources(saved_source_service):
    service, db, prediction_id = saved_source_service
    service._cache[prediction_id] = {"sources": []}

    result = service.clear_cache()

    assert result == {"cleared": 1, "db_cleared": 0, "cache_size": 0}
    assert db.query(JustificationSource).filter_by(prediction_id=prediction_id).count() == 1


def test_news_read_filters_legacy_same_outlet_sources(saved_source_service):
    service, db, _prediction_id = saved_source_service
    source = Source(name="Andina", base_url="https://andina.pe", type="web")
    db.add(source)
    db.flush()
    published = PublishedNews(
        representative_news_processed_id=1,
        source_id=source.source_id,
        title="Noticia original",
        original_url="https://andina.pe/agencia/noticia-original-distinta-999.aspx",
        published_at=datetime.utcnow(),
        fake_score=0.1,
    )
    db.add(published)
    db.commit()
    db.refresh(published)

    assert service.get_sources_by_news_id(published.news_id) == []
    assert service.get_persisted_justification_by_news_id(published.news_id) is None


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
    assert response["sources"][0]["url"] == replacement["url"]
    assert response["sources"][0]["evidenceStance"] == "discusses"
    assert response["evidence_assessment"]["status"] == "insufficient_evidence"
    rows = db.query(JustificationSource).filter_by(prediction_id=prediction_id).all()
    assert len(rows) == 1
    assert rows[0].url == replacement["url"]


def test_news_sources_fall_back_to_high_confidence_cross_source_cluster(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("RELATED_CLUSTER_MIN_SCORE", "0.60")
    engine = apply_sqlite_schema_translation(
        create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        main_source = Source(
            name="Medio principal",
            base_url="https://principal.example",
            type="web",
        )
        alternative_source = Source(
            name="Medio alternativo",
            base_url="https://alternativo.example",
            type="web",
        )
        db.add_all([main_source, alternative_source])
        db.flush()

        main_log = IngestionLog(
            source_id=main_source.source_id,
            ingestion_type="web",
            status="success",
        )
        alternative_log = IngestionLog(
            source_id=alternative_source.source_id,
            ingestion_type="web",
            status="success",
        )
        db.add_all([main_log, alternative_log])
        db.flush()

        main_raw = RawNews(
            source_id=main_source.source_id,
            log_id=main_log.log_id,
            platform="web",
            original_url="https://principal.example/hecho",
            title_raw="Gobierno anuncia una medida nacional",
            content_raw="Contenido principal suficientemente descriptivo.",
            status="processed",
        )
        alternative_raw = RawNews(
            source_id=alternative_source.source_id,
            log_id=alternative_log.log_id,
            platform="web",
            original_url="https://alternativo.example/hecho",
            title_raw="Otra cobertura de la misma medida nacional",
            content_raw="Cobertura alternativa suficientemente descriptiva.",
            status="processed",
            published_at=datetime.utcnow(),
        )
        db.add_all([main_raw, alternative_raw])
        db.flush()

        main_processed = ProcessedNews(
            news_raw_id=main_raw.news_raw_id,
            source_id=main_source.source_id,
            clean_text=main_raw.content_raw,
            token_count=100,
            status="ok",
        )
        alternative_processed = ProcessedNews(
            news_raw_id=alternative_raw.news_raw_id,
            source_id=alternative_source.source_id,
            clean_text=alternative_raw.content_raw,
            token_count=100,
            status="ok",
        )
        db.add_all([main_processed, alternative_processed])
        db.flush()

        cluster = NewsCluster(
            representative_news_processed_id=main_processed.news_processed_id,
            source_id=main_source.source_id,
            cluster_score=0.75,
        )
        db.add(cluster)
        db.flush()
        db.add_all([
            ClusterMember(
                cluster_id=cluster.cluster_id,
                news_processed_id=main_processed.news_processed_id,
                source_id=main_source.source_id,
            ),
            ClusterMember(
                cluster_id=cluster.cluster_id,
                news_processed_id=alternative_processed.news_processed_id,
                source_id=alternative_source.source_id,
            ),
        ])
        prediction = MlPrediction(
            representative_news_processed_id=main_processed.news_processed_id,
            model_version="test",
            sentiment_score=0,
            fake_score=0,
        )
        published = PublishedNews(
            representative_news_processed_id=main_processed.news_processed_id,
            source_id=main_source.source_id,
            title=main_raw.title_raw,
            original_url=main_raw.original_url,
            published_at=datetime.utcnow(),
            fake_score=0.1,
        )
        db.add_all([prediction, published])
        db.commit()
        db.refresh(published)

        service = GeminiJustificationService(db)
        sources = service.get_sources_by_news_id(published.news_id)

        assert len(sources) == 1
        assert sources[0]["url"] == alternative_raw.original_url
        assert sources[0]["evidenceStance"] == "discusses"
        assert sources[0]["assessmentMethod"] == "cross_source_cluster_similarity"
        assert sources[0]["relevanceScore"] == 0.75

        cluster.cluster_score = 0.59
        db.add(cluster)
        db.commit()
        assert service.get_sources_by_news_id(published.news_id) == []
    finally:
        db.close()
        engine.dispose()


def test_source_allowlist_checks_domain_not_claimed_name(saved_source_service):
    service, _, _ = saved_source_service
    assert service._is_allowed_source({"url": "https://rpp.pe/noticia/1", "source": "RPP"})
    assert service._is_allowed_source(
        {"url": "https://www.tvperu.gob.pe/noticias/politica/1", "source": "TV Perú"}
    )
    assert service._is_allowed_source(
        {
            "url": "https://www.radionacional.gob.pe/noticias/politica/1",
            "source": "Radio Nacional",
        }
    )
    assert not service._is_allowed_source({"url": "https://rpp-falso.example/noticia/1", "source": "RPP"})
    assert service._is_allowed_source(
        {"url": "https://www.gob.pe/institucion/onpe/noticias/1", "source": "ONPE"}
    )
    assert service._is_allowed_source(
        {"url": "https://elperuano.pe/noticia/1", "source": "El Peruano"}
    )
    assert service._is_allowed_source(
        {"url": "https://www.infobae.com/peru/2026/10/03/noticia/", "source": "Infobae"}
    )
    assert service._is_allowed_source(
        {"url": "https://diariocorreo.pe/politica/noticia/", "source": "Correo"}
    )
    assert service._is_allowed_source(
        {"url": "https://canaln.pe/actualidad/cobertura", "source": "Canal N"}
    )
    assert service._is_allowed_source(
        {"url": "https://caretas.pe/politica/cobertura", "source": "Caretas"}
    )
    assert service._is_allowed_source(
        {"url": "https://canalb.pe/noticias/politica/cobertura", "source": "Canal B"}
    )
    assert service._is_allowed_source(
        {"url": "https://voz.pe/social/article/123", "source": "VOZ.PE"}
    )
    assert service._is_allowed_source(
        {"url": "https://willax.pe/politica/cobertura", "source": "Willax"}
    )
    assert service._is_allowed_source(
        {"url": "https://portal.jne.gob.pe/portal/Pagina/Nota/123", "source": "JNE"}
    )
    assert not service._is_allowed_source(
        {"url": "https://firmeasy.legal/blog/noticia", "source": "Firmeasy"}
    )


def test_trusted_related_source_names_are_normalized(saved_source_service):
    service, _, _ = saved_source_service
    assert service._source_name_from_url("https://www.gob.pe/institucion/onpe/noticias/1") == "Gobierno del Perú"
    assert service._source_name_from_url("https://www.elperuano.pe/noticia/1") == "El Peruano"
    assert service._source_name_from_url("https://www.infobae.com/peru/noticia/") == "Infobae Perú"
    assert service._source_name_from_url("https://diariocorreo.pe/politica/noticia/") == "Diario Correo"
    assert service._source_name_from_url("https://canaln.pe/actualidad/noticia/") == "Canal N"
    assert service._source_name_from_url("https://canalb.pe/noticias/politica/noticia/") == "Canal B"
    assert service._source_name_from_url("https://voz.pe/social/article/123") == "VOZ.PE"
    assert service._source_name_from_url("https://willax.pe/politica/noticia/") == "Willax"
    assert service._source_name_from_url("https://portal.jne.gob.pe/portal/Pagina/Nota/123") == "JNE"


def test_related_sources_exclude_original_url_and_same_outlet(saved_source_service):
    service, _, _ = saved_source_service
    original = "https://elcomercio.pe/politica/hecho-original/"
    candidates = [
        {
            "url": original,
            "source": "El Comercio",
            "title": "La misma URL",
            "excerpt": "Duplicado exacto.",
        },
        {
            "url": "https://www.elcomercio.pe/politica/otra-nota/",
            "source": "El Comercio",
            "title": "Otra nota del mismo medio",
            "excerpt": "No aporta contraste editorial independiente.",
        },
        {
            "url": "https://larepublica.pe/politica/cobertura-del-hecho/",
            "source": "La República",
            "title": "Cobertura del mismo hecho en otro medio",
            "excerpt": "Contraste entre medios.",
        },
    ]

    filtered = service._exclude_original_sources(candidates, {original})

    assert [source["source"] for source in filtered] == ["La República"]


def test_original_context_survives_original_url_filter():
    original = "https://rpp.pe/politica/declaracion-original"
    primary_context = {
        "url": original,
        "source": "RPP",
        "title": "Declaración original",
        "excerpt": "Texto de la publicación original.",
        "assessmentMethod": "original_publication_context",
    }

    filtered = GeminiJustificationService._exclude_original_sources(
        [primary_context],
        {original},
    )

    assert filtered == [primary_context]


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

    assert len(sources) == 1
    assert sources[0]["url"] == FakeResponse.url
    assert sources[0]["source"] == "Andina"
    assert sources[0]["excerpt"] == "Andina informó sobre el puente aéreo para evacuar a las personas varadas."
    assert sources[0]["evidenceStance"] == "discusses"
    assert sources[0]["assessmentMethod"] == "gemini_grounded_explicit_label"
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


def test_grounded_explicit_label_is_kept_as_stance_but_removed_from_excerpt(monkeypatch):
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
    response = Value(candidates=[Value(grounding_metadata=Value(
        grounding_chunks=[Value(web=Value(uri=FakeResponse.url, title="Andina"))],
        grounding_supports=[Value(
            segment=Value(text="CONTRADICE: Andina informó que la medida no fue aprobada."),
            grounding_chunk_indices=[0],
        )],
    ))])

    sources = service._sources_from_grounding(response)

    assert sources[0]["evidenceStance"] == "refutes"
    assert sources[0]["excerpt"] == "Andina informó que la medida no fue aprobada."


def test_prompt_uses_conservative_proposition_level_stance_rules():
    service = object.__new__(GeminiJustificationService)
    service.max_sources = 4
    raw_news = Value(
        title_raw="Una afirmación con varios elementos",
        content_raw="Contenido de prueba",
        original_url="https://medio.example/original",
    )

    prompt = service._build_prompt(Value(), raw_news=raw_news)

    assert "actor, acción o hecho, objeto, tiempo, lugar y cantidad" in prompt
    assert "todos los elementos materiales" in prompt
    assert "Coincidir en el tema, actor o evento no basta" in prompt
    assert "cada hecho es material" in prompt
    assert "la acusación carece de pruebas" in prompt
    assert "no aborda el hecho o predicado central" in prompt
    assert "Ante duda entre RESPALDA o CONTRADICE y CONTEXTO, usa CONTEXTO" in prompt
    assert "Un enlace no aumenta por sí solo la credibilidad" in prompt
    assert "no recibe veracidad automática" in prompt


def test_prompt_exposes_article_links_only_as_search_leads():
    service = object.__new__(GeminiJustificationService)
    service.max_sources = 4
    raw_news = Value(
        title_raw="Congreso publica una nueva norma",
        content_raw=(
            "La nota cita https://www.gob.pe/institucion/congreso/noticias/123 "
            "y su propia URL https://medio.example/noticia-original."
        ),
        original_url="https://medio.example/noticia-original",
    )

    prompt = service._build_prompt(Value(), raw_news=raw_news)

    assert "https://www.gob.pe/institucion/congreso/noticias/123" in prompt
    assert "solo pistas de búsqueda" in prompt
    leads_section = prompt.split("- Enlaces citados por la publicación", 1)[1].split(
        "REGLAS DE BÚSQUEDA",
        1,
    )[0]
    assert "https://medio.example/noticia-original" not in leads_section


def test_fallback_prompt_expands_query_and_avoids_existing_domain():
    service = object.__new__(GeminiJustificationService)
    service.max_sources = 4
    service.min_source_target = 2
    raw_news = Value(
        title_raw="JNE emite resolución sobre una candidatura",
        content_raw="El organismo publicó la Resolución 123-2026.",
        original_url="https://medio.example/original",
    )

    prompt = service._build_fallback_prompt(
        Value(),
        raw_news,
        None,
        [{"url": "https://rpp.pe/politica/cobertura"}],
    )

    assert "SEGUNDA PASADA DE RECUPERACIÓN" in prompt
    assert "frase distintiva o cita exacta" in prompt
    assert "denominación oficial, número de norma" in prompt
    assert '"JNE emite resolución sobre una candidatura"' in prompt
    assert "JNE emite resolución sobre una candidatura Perú noticia" in prompt
    assert "rpp.pe" in prompt


def test_empty_retry_prompt_allows_reputable_secondary_coverage_without_relaxing_relevance():
    service = object.__new__(GeminiJustificationService)
    service.max_sources = 4
    service.min_source_target = 2
    raw_news = Value(
        title_raw="Investigación sobre vínculos de parlamentarios",
        content_raw="Contenido de prueba.",
        original_url="https://medio.example/original",
    )

    prompt = service._build_empty_retry_prompt(Value(), raw_news, None)

    assert "ÚLTIMO INTENTO TRAS RESULTADO VACÍO" in prompt
    assert "reseñe, cite o continúe una investigación original" in prompt
    assert "clasifícala como CONTEXTO" in prompt
    assert "No incluyas coincidencias" in prompt


def test_empty_retry_prompt_adds_short_keywords_same_publisher_and_distinctive_anchor():
    service = object.__new__(GeminiJustificationService)
    service.max_sources = 4
    service.min_source_target = 2
    raw_news = Value(
        title_raw="Los votos que necesita Fuerza Popular para lograr gobernabilidad de Fujimori",
        content_raw=(
            "El bloque necesita 31 votos en el Senado y 66 en Diputados. "
            "Las alianzas dependerán de los voceros parlamentarios."
        ),
        original_url="https://peru21.pe/politica/nota-original/",
    )

    prompt = service._build_empty_retry_prompt(Value(), raw_news, None)

    assert "votos necesita Fuerza Popular lograr gobernabilidad Fujimori" in prompt
    assert "site:peru21.pe" in prompt
    assert "site:canaln.pe" in prompt
    assert "site:infobae.com" in prompt
    assert '"El bloque necesita 31 votos en el Senado y 66 en Diputados."' in prompt
    assert "No uses otra nota del mismo editor" in prompt


def test_empty_retry_keywords_remove_interrogative_fillers():
    query = GeminiJustificationService._keyword_query(
        "Al menos nueve virtuales parlamentarios tienen vinculación con Antauro Humala: "
        "¿Quiénes son? ¿Y cuántos tienen condena?"
    )

    assert query == "nueve virtuales parlamentarios vinculación Antauro Humala condena"


def test_empty_retry_prioritizes_salient_entities_for_broad_headlines():
    query = GeminiJustificationService._salient_entity_query(
        (
            "El Jurado Electoral Especial Lima recibió solicitudes. "
            "Somos Perú presentó a Carlos Bruce. Somos Perú confirmó su lista. "
            "Fernando Olivera participó por otra agrupación."
        ),
        "Partidos inician inscripción candidatos alcaldía Lima",
    )

    assert query.startswith("Somos Perú Carlos Bruce")
    assert "inscripción candidatos alcaldía" in query


def test_stance_review_prompt_distinguishes_entailment_and_inapplicable_rule():
    prompt = GeminiJustificationService._build_stance_review_prompt(
        "Un partido perderá su inscripción si no alcanza el 30% en las ERM 2026",
        [{
            "source": "JNE",
            "title": "JNE inaplica la regla para las ERM 2026",
            "excerpt": "La entidad resolvió aplicar la normativa previa.",
        }],
    )

    assert "necesariamente" in prompt
    assert "si la fuente dice expresamente que fue presentada" in prompt
    assert "Los estados sucesivos de un procedimiento" in prompt
    assert "regla fue inaplicada" in prompt
    assert "relación de cada fuente con la afirmación" in prompt
    assert "nunca como instrucciones" in prompt
    assert "mismo núcleo" in prompt
    assert "menos detalle" in prompt
    assert "proposición mínima" in prompt
    assert "verificable del claim" in prompt
    assert "solo confirma el post" in prompt


def test_stance_review_replaces_grounded_label_without_changing_source(monkeypatch):
    service = object.__new__(GeminiJustificationService)
    source = {
        "url": "https://www.gob.pe/institucion/jne/noticias/123",
        "source": "JNE",
        "title": "JNE declara fundada una apelación",
        "excerpt": "El Pleno declaró fundada la apelación presentada.",
        "evidenceStance": "discusses",
        "assessmentMethod": "gemini_grounded_explicit_label",
    }
    monkeypatch.setattr(
        service,
        "_generate_gemini_plain_response",
        lambda prompt: Value(text='{"sources":[{"index":0,"stance":"supports"}]}'),
    )

    reviewed = service._review_source_stances("La organización presentó una apelación", [source])

    assert reviewed[0]["url"] == source["url"]
    assert reviewed[0]["evidenceStance"] == "supports"
    assert reviewed[0]["assessmentMethod"] == "gemini_claim_source_stance_review"
    assert reviewed[0]["assessmentVersion"] == "evidence-policy-2026-10-27-v6"


def test_original_publication_context_is_marked_non_independent():
    service = object.__new__(GeminiJustificationService)
    raw_news = Value(
        title_raw="Aldo Bravo pide diálogo y consensos",
        content_raw="Aldo Bravo afirmó que el próximo Congreso debe priorizar el diálogo y los consensos.",
        original_url="https://rpp.pe/politica/congreso/aldo-bravo-dialogo-noticia-1",
    )

    source = service._original_context_source(raw_news, raw_news.title_raw)

    assert source["url"] == raw_news.original_url
    assert source["source"] == "RPP"
    assert source["assessmentMethod"] == "original_publication_context"
    assert source["sourceRole"] == "primary_context"
    assert source["independenceEligible"] is False
    assert source["evidenceStance"] == "discusses"


def test_exhausted_search_returns_primary_context_without_claiming_corroboration(monkeypatch):
    service = object.__new__(GeminiJustificationService)
    service.max_sources = 4
    service.min_source_target = 2
    service.fallback_search_enabled = True
    service.empty_retry_search_enabled = True
    service.stance_review_enabled = False
    service.max_retries = 0
    service.retry_delay = 0
    monkeypatch.setattr(service, "_build_prompt", lambda *args: "primary")
    monkeypatch.setattr(service, "_build_fallback_prompt", lambda *args: "fallback")
    monkeypatch.setattr(service, "_build_empty_retry_prompt", lambda *args: "empty-retry")
    monkeypatch.setattr(service, "_generate_gemini_response", lambda prompt: Value(text="grounded"))
    monkeypatch.setattr(service, "_sources_from_grounding", lambda *args, **kwargs: [])
    monkeypatch.setattr(service, "_excluded_original_urls", lambda *args: set())
    raw_news = Value(
        title_raw="Keiko Fujimori comenta el conteo de votos",
        content_raw="La candidata señaló que la diferencia de votos genera expectativa.",
        original_url="https://rpp.pe/politica/elecciones/conteo-votos-noticia-1",
    )

    report = service._generate_with_retries(
        prediction=Value(prediction_id=99),
        raw_news=raw_news,
    )

    assert len(report["sources"]) == 1
    assert report["sources"][0]["assessmentMethod"] == "original_publication_context"
    assert report["sources"][0]["independenceEligible"] is False


def test_unrelated_reviewed_source_is_replaced_by_primary_context(monkeypatch):
    service = object.__new__(GeminiJustificationService)
    service.max_sources = 4
    service.min_source_target = 1
    service.fallback_search_enabled = True
    service.empty_retry_search_enabled = True
    service.stance_review_enabled = True
    service.max_retries = 0
    service.retry_delay = 0
    unrelated = {
        "url": "https://larepublica.pe/politica/tema-amplio",
        "source": "La República",
        "title": "Comentario sobre un tema amplio",
        "excerpt": "La nota comparte el tema, pero no aborda el predicado central.",
        "evidenceStance": "discusses",
    }
    monkeypatch.setattr(service, "_build_prompt", lambda *args: "primary")
    monkeypatch.setattr(service, "_generate_gemini_response", lambda prompt: Value(text="grounded"))
    monkeypatch.setattr(service, "_sources_from_grounding", lambda *args, **kwargs: [unrelated])
    monkeypatch.setattr(service, "_excluded_original_urls", lambda *args: set())
    monkeypatch.setattr(
        service,
        "_review_source_stances",
        lambda claim, sources: [{**sources[0], "evidenceStance": "unrelated", "assessmentMethod": "gemini_claim_source_stance_review"}],
    )
    raw_news = Value(
        title_raw="Causas y azares",
        content_raw="Columna de opinión sobre los escenarios de un eventual gobierno.",
        original_url="https://elcomercio.pe/opinion/columnistas/causas-y-azares-noticia/",
    )

    report = service._generate_with_retries(
        prediction=Value(prediction_id=100),
        raw_news=raw_news,
    )

    assert len(report["sources"]) == 1
    assert report["sources"][0]["url"] == raw_news.original_url
    assert report["sources"][0]["assessmentMethod"] == "original_publication_context"
    assert report["sources"][0]["independenceEligible"] is False


def test_stance_review_keeps_grounded_labels_on_incomplete_response(monkeypatch):
    service = object.__new__(GeminiJustificationService)
    sources = [
        {"url": "https://rpp.pe/a", "evidenceStance": "supports"},
        {"url": "https://andina.pe/b", "evidenceStance": "discusses"},
    ]
    monkeypatch.setattr(
        service,
        "_generate_gemini_plain_response",
        lambda prompt: Value(text='{"sources":[{"index":0,"stance":"refutes"}]}'),
    )

    reviewed = service._review_source_stances("Afirmación", sources)

    assert reviewed == sources


def test_second_search_pass_merges_a_new_independent_source(monkeypatch):
    service = object.__new__(GeminiJustificationService)
    service.max_sources = 4
    service.min_source_target = 2
    service.fallback_search_enabled = True
    service.max_retries = 0
    service.retry_delay = 0
    responses = [Value(pass_id=1), Value(pass_id=2)]
    prompts = []
    first_source = {
        "url": "https://rpp.pe/politica/primera-cobertura",
        "source": "RPP",
        "title": "Primera cobertura",
        "excerpt": "RPP informa sobre el hecho principal.",
        "evidenceStance": "supports",
    }
    second_source = {
        "url": "https://andina.pe/agencia/noticia-segunda-cobertura-123.aspx",
        "source": "Andina",
        "title": "Segunda cobertura",
        "excerpt": "Andina confirma el mismo hecho principal.",
        "evidenceStance": "supports",
    }
    monkeypatch.setattr(service, "_build_prompt", lambda *args: "primary")
    monkeypatch.setattr(service, "_build_fallback_prompt", lambda *args: "fallback")
    monkeypatch.setattr(
        service,
        "_generate_gemini_response",
        lambda prompt: prompts.append(prompt) or responses.pop(0),
    )
    monkeypatch.setattr(service, "_response_text", lambda response: "grounded")
    monkeypatch.setattr(
        service,
        "_sources_from_grounding",
        lambda response, diagnostics=None: [first_source] if response.pass_id == 1 else [second_source],
    )
    monkeypatch.setattr(service, "_excluded_original_urls", lambda *args: set())

    report = service._generate_with_retries(
        prediction=Value(prediction_id=77),
        raw_news=Value(
            title_raw="Una afirmación verificable",
            content_raw="Contenido",
            original_url="https://medio.example/original",
        ),
    )

    assert prompts == ["primary", "fallback"]
    assert [source["source"] for source in report["sources"]] == ["RPP", "Andina"]
    assert all(source["claim"] == "Una afirmación verificable" for source in report["sources"])


def test_fallback_is_not_used_after_reaching_distinct_publisher_target():
    service = object.__new__(GeminiJustificationService)
    service.fallback_search_enabled = True
    service.min_source_target = 2

    assert service._should_run_fallback([])
    assert service._should_run_fallback([
        {"url": "https://rpp.pe/uno"},
        {"url": "https://www.rpp.pe/dos"},
    ])
    assert not service._should_run_fallback([
        {"url": "https://rpp.pe/uno"},
        {"url": "https://andina.pe/dos"},
    ])


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


def test_publisher_url_is_kept_when_a_grounded_destination_rate_limits_the_server():
    service = object.__new__(GeminiJustificationService)

    source = service._grounding_redirect_fallback(
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example",
        "https://elcomercio.pe/opinion/columnistas/un-voto-menos-por-martin-hidalgo-noticia/",
        "",
        ["El Comercio publicó una columna relacionada con el tema."],
        429,
    )

    assert source == {
        "url": "https://elcomercio.pe/opinion/columnistas/un-voto-menos-por-martin-hidalgo-noticia/",
        "canonical_url": "https://elcomercio.pe/opinion/columnistas/un-voto-menos-por-martin-hidalgo-noticia/",
        "source": "El Comercio",
        "title": "Cobertura relacionada de El Comercio",
        "excerpt": "El Comercio publicó una columna relacionada con el tema.",
    }


def test_public_broadcaster_url_is_kept_when_destination_blocks_the_server():
    service = object.__new__(GeminiJustificationService)

    source = service._grounding_redirect_fallback(
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example",
        "https://www.tvperu.gob.pe/noticias/politica/cobertura-relacionada",
        "TVPerú Noticias",
        ["TV Perú informó sobre el mismo acontecimiento político."],
        403,
    )

    assert source == {
        "url": "https://www.tvperu.gob.pe/noticias/politica/cobertura-relacionada",
        "canonical_url": "https://www.tvperu.gob.pe/noticias/politica/cobertura-relacionada",
        "source": "TV Perú",
        "title": "TVPerú Noticias",
        "excerpt": "TV Perú informó sobre el mismo acontecimiento político.",
    }
