import requests

from app.application_services.justification_service import GeminiJustificationService


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

    sources = service._sources_from_grounding(response)

    assert sources == [
        {
            "url": FakeResponse.url,
            "source": "Andina",
            "title": "Ministro de Defensa supervisa puente aéreo para evacuar varados por derrumbes en Arequipa",
            "excerpt": "Andina informó sobre el puente aéreo para evacuar a las personas varadas.",
        }
    ]


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
