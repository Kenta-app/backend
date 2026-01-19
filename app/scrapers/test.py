from app.scrapers.scrapers import BBCNewsScraper, ElComercioScraper

scraper=ElComercioScraper()
articles=scraper.scrape()
print(len(articles))
print(articles[0])