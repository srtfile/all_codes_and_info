import re
import json
import time
from urllib.parse import unquote
from playwright.sync_api import sync_playwright

# ═══════════════════════════════════════════════════════════════════════════════
#  MODE — choose one:
#    "VALHALLA" → extracts ValhallaStream proxy URLs  (from /download page)
#    "DOXAR"    → extracts m3u8 / mpd / stream URLs  (from /watch page)
# ═══════════════════════════════════════════════════════════════════════════════
MODE    = "DOXAR"

# ── Content config ─────────────────────────────────────────────────────────────
TYPE    = "movie"    # "tv" or "movie"
ID      = 76341      # TMDB ID
SEASON  = 1          # TV only
EPISODE = 1          # TV only

# Examples:
#   TV show  → TYPE="tv",    ID=13916, SEASON=1, EPISODE=1
#   Movie    → TYPE="movie", ID=76341

# ── Constants ──────────────────────────────────────────────────────────────────
BASE_API = "https://rivestream.ru/api/backendfetch"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36")

EXTRA_HEADERS = {
    "Referer": "https://rivestream.ru/",
    "Origin":  "https://rivestream.ru",
}

# ── VALHALLA constants ─────────────────────────────────────────────────────────
VALHALLA_RE = re.compile(
    r'https?://proxy\.valhallastream\.[a-zA-Z0-9\-\.]+/proxy\?'
    r'url=[^\s\'"<>]+(?:&headers=[^\s\'"<>]+)?'
)

ALL_SERVICES = [
    "flowcast", "asiacloud", "primevids", "hindicast", "guru", "ophim",
    "drivedownload", "vidsrc", "vidsrcpro", "superembed",
    "embedsoap", "autoembed", "2embed", "moviesapi", "smashystream",
]

# ── DOXAR constants ────────────────────────────────────────────────────────────
STREAM_RE = re.compile(
    r'https?://[^\s\'"<>\[\]{}]+(?:\.m3u8|\.mpd|\.ts)(?:[?#][^\s\'"<>\[\]{}]*)?',
    re.IGNORECASE
)

# ─────────────────────────────────────────────────────────────────────────────

def find_valhalla(text):
    return set(VALHALLA_RE.findall(text))

def find_streams(text):
    return set(STREAM_RE.findall(text))

def build_url(mode):
    if mode == "DOXAR":
        if TYPE == "movie":
            return f"https://rivestream.ru/watch?type=movie&id={ID}"
        return f"https://rivestream.ru/watch?type=tv&id={ID}&season={SEASON}&episode={EPISODE}"
    else:
        if TYPE == "movie":
            return f"https://rivestream.ru/download?type=movie&id={ID}"
        return f"https://rivestream.ru/download?type=tv&id={ID}&season={SEASON}&episode={EPISODE}"


# ══════════════════════════════════════════════════════════════════════════════
#  VALHALLA MODE
# ══════════════════════════════════════════════════════════════════════════════

def run_valhalla():
    t_start     = time.time()
    all_hits    = set()
    page_url    = build_url("VALHALLA")
    provider_id = "movieVideoProvider" if TYPE == "movie" else "tvVideoProvider"

    print(f"[+] Mode    : VALHALLA")
    print(f"[+] Type    : {TYPE.upper()}")
    print(f"[+] ID      : {ID}")
    if TYPE == "tv":
        print(f"[+] Season  : {SEASON}  Episode: {EPISODE}")
    print(f"[+] Page    : {page_url}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1920, "height": 1080},
            extra_http_headers=EXTRA_HEADERS,
        )
        page = context.new_page()

        def handle_backendfetch(route, request):
            url = request.url
            if "VideoProviderServices" in url:
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({"data": ALL_SERVICES}),
                )
                return
            if provider_id in url:
                try:
                    response = route.fetch()
                    body = response.text()
                    hits = find_valhalla(body)
                    if hits:
                        svc = re.search(r'service=([^&]+)', url)
                        svc = svc.group(1) if svc else "unknown"
                        all_hits.update(hits)
                        for u in hits:
                            print(f"  [FOUND via {svc}] {u}")
                    route.fulfill(response=response)
                except Exception as e:
                    print(f"  [route.fetch error] {e}")
                    route.continue_()
                return
            route.continue_()

        page.route("**/api/backendfetch**", handle_backendfetch)

        print("[+] Loading page...")
        page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
        print(f"[+] Page loaded ({time.time()-t_start:.1f}s). Waiting for service responses...")
        page.wait_for_timeout(20000)
        browser.close()

    _print_results("VALHALLASTREAM PROXY URLs", all_hits, t_start, "valhallastream_urls.txt",
                   decode=True)


# ══════════════════════════════════════════════════════════════════════════════
#  DOXAR MODE
#  Loads the /watch page to sniff the secret key + get CF cookies, then
#  directly queries every service via context.request — same working pattern
#  as VALHALLA but scans for m3u8 / mpd / stream URLs instead.
# ══════════════════════════════════════════════════════════════════════════════

def run_doxar():
    t_start  = time.time()
    found    = {}
    page_url = build_url("DOXAR")

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
            extra_http_headers=EXTRA_HEADERS,
        )
        page = context.new_page()

        def on_request(request):
            nonlocal sniffed_key
            if "backendfetch" in request.url and sniffed_key is None:
                m = re.search(r'secretKey=([^&]+)', request.url)
                if m and m.group(1) != "rive":
                    sniffed_key = m.group(1)

        page.on("request", on_request)

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
            headers={"User-Agent": UA, "Referer": EXTRA_HEADERS["Referer"],
                     "Origin": EXTRA_HEADERS["Origin"]},
        )
        try:
            api_services = json.loads(svc_resp.text()).get("data", []) or []
        except Exception:
            api_services = []

        all_services = list(dict.fromkeys(api_services + ALL_SERVICES))
        print(f"[+] Querying {len(all_services)} services: {all_services}\n")

        provider_id = "movieVideoProvider" if TYPE == "movie" else "tvVideoProvider"

        def make_params(svc):
            if TYPE == "movie":
                return {"requestID": provider_id, "id": ID,
                        "service": svc, "secretKey": sniffed_key, "proxyMode": "undefined"}
            return {"requestID": provider_id, "id": ID, "season": SEASON, "episode": EPISODE,
                    "service": svc, "secretKey": sniffed_key, "proxyMode": "undefined"}

        h = {"User-Agent": UA, "Referer": EXTRA_HEADERS["Referer"],
             "Origin": EXTRA_HEADERS["Origin"]}

        responses = []
        for svc in all_services:
            r = context.request.get(BASE_API, params=make_params(svc), headers=h)
            responses.append((svc, r.text()))

        browser.close()

    for svc, body in responses:
        stream_hits   = find_streams(body)
        valhalla_hits = find_valhalla(body)
        hits = stream_hits | valhalla_hits
        if hits:
            found[svc] = hits
            for u in hits:
                tag = "STREAM" if u in stream_hits else "VALHALLA"
                print(f"  [{tag} via {svc}] {u}")
        else:
            print(f"  [{svc}] {body[:100].replace(chr(10), ' ').strip()}")

    all_urls = {u for hits in found.values() for u in hits}
    _print_results("DOXAR STREAM URLs", all_urls, t_start, "doxar_urls.txt", decode=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Shared result printer
# ══════════════════════════════════════════════════════════════════════════════

def _print_results(title, urls, t_start, filename, decode=False):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

    if not urls:
        print("[!] No URLs found.")
    else:
        for i, url in enumerate(sorted(urls), 1):
            print(f"\n[{i}] {url}")
            if decode:
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
    print(f"\n[+] Total found : {len(urls)}")
    print(f"[+] Time taken  : {elapsed:.1f}s")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(urls)))
    print(f"[+] Saved to    : {filename}")


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if MODE == "DOXAR":
        run_doxar()
    elif MODE == "VALHALLA":
        run_valhalla()
    else:
        print(f"[!] Unknown MODE: {MODE}. Use 'VALHALLA' or 'DOXAR'.")
