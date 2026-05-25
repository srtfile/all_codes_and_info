import re, requests
H = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
     "Referer":"https://cinemaos.tech/"}

r = requests.get("https://cinemaos.tech/player/218", headers=H, timeout=10)
print(f"HTTP {r.status_code}  {len(r.text)} chars")

# Show all lines containing imdb, title, release
for line in r.text.split('\n'):
    if any(x in line.lower() for x in ['imdb_id', '"title"', 'release_date', 'tt0']):
        print(repr(line[:200]))
