from bs4 import BeautifulSoup

from app.raw.source_catalog import DEFAULT_SOURCES
from app.scrapers.scrapers import AndinaScraper, LaRepublicaScraper, RPPNoticiasScraper


def test_andina_discovers_only_publisher_article_links():
    scraper = AndinaScraper()
    html = """
    <a href="https://www.facebook.com/sharer?u=https://andina.pe/agencia/noticia-falsa-9.aspx">Share</a>
    <a href="noticia-primera-1.aspx">First</a>
    <a href="https://andina.pe/agencia/noticia-segunda-2.aspx">Second</a>
    <a href="https://other.example/noticia-tercera-3.aspx">Other site</a>
    <a href="noticia-primera-1.aspx">Duplicate</a>
    """
    scraper.fetch_page = lambda _: BeautifulSoup(html, "html.parser")

    assert scraper._discover_urls() == [
        "https://andina.pe/agencia/noticia-primera-1.aspx",
        "https://andina.pe/agencia/noticia-segunda-2.aspx",
    ]


def test_larepublica_article_parser_uses_semantic_body_fallback():
    scraper = LaRepublicaScraper()
    paragraphs = "".join(
        f"<p>Párrafo político número {index} con suficiente contexto verificable.</p>"
        for index in range(1, 5)
    )
    html = f"""
    <article>
      <h1>Congreso debate una reforma nacional</h1>
      <h2>La propuesta será discutida esta semana.</h2>
      {paragraphs}
    </article>
    """
    scraper.fetch_page = lambda _: BeautifulSoup(html, "html.parser")

    article = scraper._scrape_article("/politica/reforma-1", "2026-10-02")

    assert article is not None
    assert article["url"] == "https://larepublica.pe/politica/reforma-1"
    assert "Párrafo político" in article["content"]


def test_rpp_rejects_pages_without_a_meaningful_article_body():
    scraper = RPPNoticiasScraper()
    html = '<h1 class="article__title">Titular sin cuerpo</h1><div class="body"><p>Corto.</p></div>'
    scraper.fetch_page = lambda _: BeautifulSoup(html, "html.parser")

    assert scraper._scrape_article("/politica/nota", "2026-10-02") is None


def test_peru21_remains_registered_but_inactive_while_origin_blocks_server():
    peru21 = next(source for source in DEFAULT_SOURCES if source["name"] == "Peru21")

    assert peru21["is_active"] is False
