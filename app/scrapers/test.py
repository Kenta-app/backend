from app.scrapers.scrapers import BBCNewsScraper, ElComercioScraper

scraper=ElComercioScraper()
articles=scraper.scrape()
print(len(articles))
print(articles[2])

#from zoneinfo import ZoneInfo
#from datetime import datetime
#print(datetime.now(ZoneInfo("America/Lima")).date())