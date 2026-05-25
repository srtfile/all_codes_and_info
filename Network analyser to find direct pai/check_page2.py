import re, requests, json
H = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
     "Referer":"https://cinemaos.tech/"}

r = requests.get("https://cinemaos.tech/player/218", headers=H, timeout=10)
html = r.text

# Extract all __next_f.push content
pushes = re.findall(r'__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S)
print(f"Found {len(pushes)} __next_f.push blocks")

# Decode unicode escapes and search for imdb/title
combined = ""
for p in pushes:
    try:
        decoded = p.encode().decode('unicode_escape')
        combined += decoded
    except:
        combined += p

# Search for imdb_id
imdb = re.search(r'"imdb_id"\s*:\s*"(tt\d+)"', combined)
title = re.search(r'"title"\s*:\s*"([^"\\]+)"', combined)
year = re.search(r'"release_date"\s*:\s*"(\d{4})', combined)
tmdb = re.search(r'"id"\s*:\s*(\d+)', combined)

print(f"imdb_id: {imdb.group(1) if imdb else 'NOT FOUND'}")
print(f"title:   {title.group(1) if title else 'NOT FOUND'}")
print(f"year:    {year.group(1) if year else 'NOT FOUND'}")
print(f"tmdb:    {tmdb.group(1) if tmdb else 'NOT FOUND'}")

# Also try raw search in html
print("\n--- Raw search in full HTML ---")
imdb2 = re.search(r'tt\d{7,8}', html)
print(f"Any tt-id: {imdb2.group(0) if imdb2 else 'none'}")

# Show a snippet around imdb
idx = html.find('"imdb_id"')
if idx != -1:
    print(f"imdb_id context: {html[idx:idx+100]}")
else:
    print("'imdb_id' not found in raw HTML")
    # Check if it's in escaped form
    idx2 = html.find('imdb_id')
    if idx2 != -1:
        print(f"'imdb_id' (unquoted) at {idx2}: {html[idx2:idx2+100]}")
