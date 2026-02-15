from app.scrapers.scrapers import *
'''
scraper1=ElComercioScraper()
scraper2=RPPNoticiasScraper()
scraper3=LaRepublicaScraper()
scraper4=Peru21Scraper()

scrape1=scraper1.scrape()
scrape2=scraper2.scrape()
scrape3=scraper3.scrape()
scrape4=scraper4.scrape()

print("el comercio: ",len(scrape1))
print("RPP: ",len(scrape2))
print("La Republica: ",len(scrape3))
print("Peru21: ",len(scrape4))
for i in range(len(scrape1)):
    print(scrape1[i]['title'])
    print(scrape1[i]['content'])
    print(scrape2[i]['title'])
    print(scrape3[i]['title'])
    print(scrape4[i]['title'])
'''

scraper5=ElPeruanoScraper()
scrape5=scraper5.scrape()
print("El Peruano: ",len(scrape5))
for i in range(len(scrape5)):
    print(scrape5[i]['title'])
    print(scrape5[i]['summary'])
    print(scrape5[i]['content'])
    print(scrape5[i]['author'])
    print("-"*20)