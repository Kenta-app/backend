#!/usr/bin/env python3
"""
Script de prueba para el scraper de Andina
"""

import sys
sys.path.insert(0, '/path/to/backend')

from app.scrapers.scrapers import AndinaScraper
from datetime import datetime
from zoneinfo import ZoneInfo

def test_andina_scraper():
    scraper = AndinaScraper()
    print(f"Iniciando scraper de {scraper.source_name}...")
    print(f"URL base: {scraper.base_url}")

    try:
        articles = scraper.scrape()
        print(f"\nTotal de artículos encontrados: {len(articles)}")

        if articles:
            for i, article in enumerate(articles[:3], 1):  # Mostrar primeros 3
                print(f"\n--- Artículo {i} ---")
                print(f"Título: {article['title'][:80]}")
                print(f"Fuente: {article['source']}")
                print(f"Fecha publicación: {article['published_date']}")
                print(f"Fecha scraping: {article['scraped_date']}")
                print(f"URL: {article['url']}")
                print(f"Contenido (primeros 100 chars): {article['content'][:100]}...")
        else:
            print("No se encontraron artículos.")

    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_andina_scraper()
