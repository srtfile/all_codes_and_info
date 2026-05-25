import re
import json
import time
from urllib.parse import unquote
from playwright.sync_api import sync_playwright

# ── Config — edit these ───────────────────────────────────────────────────────
TYPE    = "movie"    # "tv" or "movie"
ID      = 45050      # TMDB ID
SEASON  = 1          # TV only (ignored for movies)
EPISODE = 1          # TV only (ignored for movies)

# Examples:
#   Movie    → TYPE="movie", ID=76341
#   TV show  → TYPE="tv",    ID=13916, SEASON=1, EPISODE=1

# ── Constants ─────────────────────────────────────────────────────────────────
BASE_API = "https://rivestream.ru/api/backendfetch"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")

REQ_HEADERS = {
    "User-Agent": UA,
    "Referer":    "https://rivestream.ru/",
    "Origin":     "https://rivestream.ru",
}

ALL_SERVICES = [
    "flowcast", "asiacloud", "primevids", "hindicast", "guru", "ophim",
    "drivedownload", "vidsrc", "vidsrcpro", "superembed",
    "embedsoap", "autoembed", "2embed", "moviesapi", "smashystream",
]

# Matches .m3u8, .mpd, .ts URLs anywhere in a response body
STREAM_RE = re.compile(
    r'https?://[^\s\'"<>\[\]{}]+(?:\.m3u8|\.mpd|\.ts)(?:[?#][^\s\'"<>\[\]{}]*)?',
    re.IGNORECASE
)

# Also catch ValhallaStream proxy URLs
VALHALLA_RE = re.compile(
    r'https?://proxy\.valhallastream\.[a-zA-Z0-9\-\.]+/proxy\?'
    r'url=[^\s\'"<>]+(?:&headers=[^\s\'"<>]+)?'
)

# ─────────────────────────────────────────────────────────────────────────────

def find_streams(text):
    return set(STREAM_RE.findall(text))

def find_valhalla(text):
    return set(VALHALLA_RE.findall(text))

def build_page_url():
    if TYPE == "movie":
        return f"https://rivestream.ru/watch?type=movie&id={ID}"
    return f"https://rivestream.ru/watch?type=tv&id={ID}&season={SEASON}&episode={EPISODE}"

def build_api_params(service, secret_key):
    if TYPE == "movie":
        return {
            "requestID": "movieVideoProvider",
            "id":        ID,
            "service":   service,
            "secretKey": secret_key,
            "proxyMode": "undefined",
        }
    return {
        "requestID": "tvVideoProvider",
        "id":        ID,
        "season":    SEASON,
        "episode":   EPISODE,
        "service":   service,
        "secretKey": secret_key,
        "proxyMode": "undefined",
    }

# ─────────────────────────────────────────────────────────────────────────────

def main():
    t_start   = time.time()
    found     = {}   # service -> set of URLs
    page_url  = build_page_url()

    print(f"[+] Mode    : DOXAR")
    print(f"[+] Type    : {TYPE.upper()}")
    print(f"[+] ID      : {ID}")
    if TYPE == "tv":
        print(f"[+] Season  : {SEASON}  Episode: {EPISODE}")
    print(f"[+] Page    : {page_url}\n")

    sniffed_key = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={"Referer": REQ_HEADERS["Referer"],
                                "Origin":  REQ_HEADERS["Origin"]},
        )
        page = context.new_page()

        # Sniff the secret key from the page's own outgoing requests
        def on_request(request):
            nonlocal sniffed_key
            if "backendfetch" in request.url and sniffed_key is None:
                m = re.search(r'secretKey=([^&]+)', request.url)
                if m and m.group(1) != "rive":
                    sniffed_key = m.group(1)

        page.on("request", on_request)

        # Load page to get Cloudflare cookies + secret key
        print("[+] Loading page to get session cookies and secret key...")
        page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)
        print(f"[+] Page loaded ({time.time()-t_start:.1f}s)")
        print(f"[+] Sniffed secret key: {sniffed_key}")

        if not sniffed_key:
            print("[!] Could not sniff secret key. Aborting.")
            browser.close()
            return

        # Get service list
        svc_resp = context.request.get(
            BASE_API,
            params={"requestID": "VideoProviderServices",
                    "secretKey": "rive", "proxyMode": "undefined"},
            headers=REQ_HEADERS,
        )
        try:
            api_services = json.loads(svc_resp.text()).get("data", []) or []
        except Exception:
            api_services = []

        all_services = list(dict.fromkeys(api_services + ALL_SERVICES))
        print(f"[+] Querying {len(all_services)} services: {all_services}\n")

        # Query every service directly via context.request (shares CF cookies)
        responses = []
        for svc in all_services:
            r = context.request.get(
                BASE_API,
                params=build_api_params(svc, sniffed_key),
                headers=REQ_HEADERS,
            )
            responses.append((svc, r.text()))

        browser.close()

    # Parse all responses
    for svc, body in responses:
        stream_hits   = find_streams(body)
        valhalla_hits = find_valhalla(body)
        all_svc_hits  = stream_hits | valhalla_hits

        if all_svc_hits:
            found[svc] = all_svc_hits
            for u in all_svc_hits:
                tag = "STREAM" if u in stream_hits else "VALHALLA"
                print(f"  [{tag} via {svc}] {u}")
        else:
            snippet = body[:100].replace("\n", " ").strip()
            print(f"  [{svc}] {snippet}")

    # Results
    all_urls = {u for hits in found.values() for u in hits}

    print("\n" + "=" * 60)
    print("  DOXAR — EXTRACTED STREAM URLs")
    print("=" * 60)

    if not all_urls:
        print("[!] No stream URLs found.")
    else:
        for i, url in enumerate(sorted(all_urls), 1):
            print(f"\n[{i}] {url}")
            # Decode ValhallaStream proxy URLs
            if "valhallastream" in url:
                try:
                    inner   = re.search(r'url=([^&\s]+)', url)
                    headers = re.search(r'headers=([^\s]+)', url)
                    if inner:
                        print(f"    Video URL : {unquote(inner.group(1))}")
                    if headers:
                        h = json.loads(unquote(headers.group(1)))
                        print(f"    Headers   : {json.dumps(h)}")
                except Exception:
                    pass

    elapsed = time.time() - t_start
    print(f"\n[+] Total found : {len(all_urls)}")
    print(f"[+] Time taken  : {elapsed:.1f}s")

    with open("doxar_urls.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(all_urls)))
    print("[+] Saved to    : doxar_urls.txt")


if __name__ == "__main__":
    main()
