from bs4 import BeautifulSoup

from app.scrapers.scrapers import AndinaScraper


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
