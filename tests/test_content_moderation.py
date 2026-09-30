from app.raw.models import RawNews
from app.serving.content_normalization import build_display_content, detect_content_warning


def _raw(platform: str, text: str, account: str = "cuenta") -> RawNews:
    return RawNews(
        platform=platform,
        source_account=account,
        original_url="https://x.com/cuenta/status/1" if platform == "twitter" else "https://example.com/1",
        title_raw="Título de prueba",
        content_raw=text,
    )


def test_strong_language_variants_in_social_post():
    for expression in ("carajo", "c0jud0", "m1erda", "p.u.t.a", "conchesumadre", "¡CSM!"):
        display = build_display_content(_raw("twitter", f"Mensaje: {expression}"))
        assert display.content_warning == "strong_language", expression
        assert expression in display.display_text


def test_account_and_url_do_not_trigger_warning():
    display = build_display_content(
        _raw("twitter", "Consulta https://example.com/cojudo ahora", account="cojudo")
    )
    assert display.content_warning is None
    assert detect_content_warning("RT @cojudo: mensaje informativo") is None


def test_news_article_is_not_subject_to_social_language_warning():
    display = build_display_content(_raw("web", "El artículo cita la palabra mierda."))
    assert display.content_warning is None
    assert "mierda" in display.display_text

