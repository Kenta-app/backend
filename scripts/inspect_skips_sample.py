import csv
import requests
from bs4 import BeautifulSoup

SKIPS='data/perucheck_analysis_v3/skips.csv'
N=10

with open(SKIPS, encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = [r for r in reader if r['reason']=='missing_rating']

print(f"Total missing_rating: {len(rows)}; showing first {min(N,len(rows))}\n")

for i,r in enumerate(rows[:N]):
    url = r['url']
    details = r.get('details','')
    print(f"{i+1}. {url}\n   Claim: {details[:120]}...")
    try:
        resp = requests.get(url, headers={'User-Agent':'Mozilla/5.0'}, timeout=15)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, 'html.parser')
        h1 = soup.find('h1')
        if h1:
            print('   H1:', h1.get_text(strip=True)[:200])
        # JSON-LD
        scripts = soup.find_all('script', attrs={'type':'application/ld+json'})
        if scripts:
            print('   JSON-LD snippets:')
            for s in scripts[:2]:
                txt = s.string or ''
                print('    ', txt.strip()[:400].replace('\n',' '))
        # look for verdict-like badges
        badges = soup.find_all(lambda t: t.name in ['div','span'] and ('falso' in t.get_text('',True).lower() or 'verdadero' in t.get_text('',True).lower()), limit=3)
        if badges:
            print('   Found badge text:', ' | '.join(b.get_text(' ',strip=True)[:200] for b in badges))
    except Exception as e:
        print('   Failed fetch:', e)
    print('-'*60)
