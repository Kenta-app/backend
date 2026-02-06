from app.scrapers.scrapers import  ElComercioScraper, RPPNoticiasScraper, LaRepublicaScraper, Peru21Scraper

from app.tasks.scheduler import ScrapingScheduler

import time

#scraper=ElComercioScraper()
#scraper2=RPPNoticiasScraper()
#scraper3=LaRepublicaScraper()
#scraper4=Peru21Scraper()
#articles=scraper.scrape()
#articles=scraper2.scrape()
#articles=scraper3.scrape()
#articles4=scraper4.scrape()

#print("-----------------")
#print(len(articles))
#for article in articles:
#    print(article['title'])
#    print(article['summary'])
#    print(article['content'])
#    print(article['url'])
#    print(article['author'])
#    print(article['published_date'])
#    print("-"*20)
#print("--------------")


#from zoneinfo import ZoneInfo
#from datetime import datetime
#print(datetime.now(ZoneInfo("America/Lima")).date())