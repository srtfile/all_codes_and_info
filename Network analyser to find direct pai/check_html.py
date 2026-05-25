import requests, re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
           "Referer": "https://cinemaos.tech/"}

r = requests.get("https://cinemaos.tech/player/550", headers=HEADERS, timeout=15)
html = r.text

# Find all imdb_id occurrences
for m in re.finditer(r'.{0,30}imdb.{0,60}', html, re.I):
    print(repr(m.group(0)))
    print()
