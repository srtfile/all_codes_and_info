import requests, re, json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Referer':    'https://vaplayer.ru/',
    'Origin':     'https://vaplayer.ru',
}

# Step 1 — fetch the real iframe
r = requests.get('https://brightpathsignals.com/embed/movie/tt2948356', headers=HEADERS)
html = r.text

# Save full HTML for inspection
with open('_iframe_html.txt', 'w', encoding='utf-8') as f:
    f.write(html)
print(f"[+] HTML saved ({len(html)} bytes)")

# Step 2 — all external script srcs
scripts = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html, re.I)
print(f"\n[SCRIPTS] {len(scripts)}")
for s in scripts:
    print(f"  {s}")

# Step 3 — all fetch() / $.ajax / axios calls
print("\n[FETCH/AJAX CALLS]")
for m in re.findall(r'''(?:fetch|ajax|axios\.get|axios\.post|\$\.get|\$\.post)\s*\(\s*['"`]([^'"`]+)['"`]''', html):
    print(f"  {m}")

# Step 4 — any URL-like strings containing /api/ or /stream or /source or /media
print("\n[API / STREAM URLS]")
for m in re.findall(r'["\']((https?://|/)[^"\'<>\s]{5,}(?:api|stream|source|media|hls|m3u8|playlist|token|key)[^"\'<>\s]*)["\']', html, re.I):
    print(f"  {m[0]}")

# Step 5 — all inline JS variable assignments that look like config
print("\n[JS CONFIG VARS]")
for m in re.findall(r'(?:var|let|const)\s+(\w+)\s*=\s*(\{[^;]{10,300}\})', html):
    print(f"  {m[0]} = {m[1][:120]}")

# Step 6 — data-* attributes on body/player elements
print("\n[DATA ATTRIBUTES]")
for m in re.findall(r'data-[\w-]+=["\'"][^"\']+["\']', html):
    print(f"  {m}")

# Step 7 — look for the player JS file (usually contains the API endpoint)
print("\n[PLAYER JS FILES]")
for s in scripts:
    if 'player' in s.lower() or 'app' in s.lower() or 'main' in s.lower() or 'embed' in s.lower():
        print(f"  {s}")
        # fetch it and look for API endpoints
        try:
            base = 'https://brightpathsignals.com'
            url = s if s.startswith('http') else base + s
            js = requests.get(url, headers=HEADERS, timeout=10).text
            # find fetch/XHR calls
            for ep in re.findall(r'''(?:fetch|open)\s*\(\s*['"`]([^'"`]{5,200})['"`]''', js):
                print(f"    API call: {ep}")
            # find string URLs
            for ep in re.findall(r'''['"`](/(?:api|stream|source|media|hls|embed)[^'"`\s]{3,150})['"`]''', js, re.I):
                print(f"    URL: {ep}")
        except Exception as e:
            print(f"    fetch error: {e}")
