import requests
import sys
from urllib.parse import quote, urlparse, parse_qs
from base64 import b64decode

# ══════════════════════════════════════════════════════════
#  SET YOUR URL HERE  (movie or tv/anime — auto-detected)
# ══════════════════════════════════════════════════════════

TARGET_URL = "https://primesrc.me/embed/movie?tmdb=296"

# Other examples — just swap TARGET_URL:
#   Movie  by TMDB : https://primesrc.me/embed/movie?tmdb=296
#   Movie  by IMDB : https://primesrc.me/embed/movie?imdb=tt0468569
#   TV     by IMDB : https://primesrc.me/embed/tv?imdb=tt0944947&season=1&episode=1
#   TV     by TMDB : https://primesrc.me/embed/tv?tmdb=1399&season=1&episode=1
#   Anime  by TMDB : https://primesrc.me/embed/tv?tmdb=1429&season=1&episode=1

# ══════════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    )
}

API = "https://enc-dec.app/api"


# ──────────────────────────────────────────────────────────
# Step 1 — Parse the URL into params
# ──────────────────────────────────────────────────────────

def parse_url(url: str) -> dict:
    parsed = urlparse(url)
    qs     = parse_qs(parsed.query)
    path   = parsed.path.lower()

    def first(k):
        return qs.get(k, [None])[0]

    # Auto-detect type from URL path segment
    if "/movie" in path:
        media_type = "movie"
    elif "/tv" in path or "/series" in path or "/anime" in path:
        media_type = "tv"
    else:
        media_type = first("type") or "movie"

    return {
        "type":    media_type,
        "imdb_id": first("imdb"),
        "tmdb_id": first("tmdb"),
        "season":  first("season"),
        "episode": first("episode"),
    }


# ──────────────────────────────────────────────────────────
# Step 2 — Fetch server list from primesrc API
# ──────────────────────────────────────────────────────────

def fetch_servers(params: dict) -> list:
    imdb_id = params.get("imdb_id")
    tmdb_id = params.get("tmdb_id")
    media   = params["type"]
    season  = params.get("season")
    episode = params.get("episode")

    if imdb_id:
        id_param = f"imdb={imdb_id}"
    elif tmdb_id:
        id_param = f"tmdb={tmdb_id}"
    else:
        print("  [!] No IMDB or TMDB id found in URL.")
        sys.exit(1)

    if media == "movie":
        api_url = f"https://primesrc.me/api/v1/s?{id_param}&type=movie"
    else:
        if not season or not episode:
            print("  [!] TV/anime URL needs season and episode.")
            print("       Add them to the URL:  &season=1&episode=1")
            sys.exit(1)
        api_url = (
            f"https://primesrc.me/api/v1/s?{id_param}"
            f"&season={season}&episode={episode}&type=tv"
        )

    print(f"  Querying : {api_url}")
    resp    = requests.get(api_url, headers=HEADERS, timeout=20).json()
    servers = resp.get("servers", [])

    if not servers:
        print("  [!] No servers returned. Check your ID / season / episode.")
    return servers


# ──────────────────────────────────────────────────────────
# Step 3 — Resolve each server key -> playable link
# ──────────────────────────────────────────────────────────

def resolve_key(key: str):
    embed_api = f"https://primesrc.me/api/v1/l?key={key}"
    solve_url = f"{API}/solve-primesrc?url={quote(embed_api)}"
    try:
        data = requests.get(solve_url, headers=HEADERS, timeout=15).json()
        if data.get("status") != 200:
            return None
        return data["result"]
    except Exception:
        return None


def resolve_all(servers: list) -> list:
    results = []
    total   = len(servers)
    for i, srv in enumerate(servers, 1):
        name    = str(srv.get("name")    or "unknown")
        key     = srv.get("key", "")
        quality = str(srv.get("quality") or "—")
        lang    = str(srv.get("lang")    or "—")
        print(f"  [{i:>2}/{total}] {name:<18} ... ", end="", flush=True)
        link = resolve_key(key)
        print("OK" if link else "FAIL")
        results.append({"name": name, "quality": quality, "lang": lang, "link": link})
    return results


# ──────────────────────────────────────────────────────────
# Step 4 — Print results table
# ──────────────────────────────────────────────────────────

def print_results(results: list, params: dict):
    sep = "-" * 70
    media = params["type"].upper()
    if media == "TV":
        label = f"TV  S{params.get('season','?')}E{params.get('episode','?')}"
    else:
        label = "MOVIE"

    id_str = params.get("imdb_id") or f"tmdb:{params.get('tmdb_id')}"

    print(f"\n{sep}")
    print(f"  Type : {label}   |   ID : {id_str}")
    print(sep)
    print(f"  {'#':<4} {'Host':<20} {'Quality':<10} {'Lang':<6}  Link")
    print(sep)
    for idx, item in enumerate(results, 1):
        link = item["link"] or "FAILED"
        print(f"  {idx:<4} {item['name']:<20} {item['quality']:<10} {item['lang']:<6}  {link}")
    print(sep)
    ok   = sum(1 for r in results if r["link"])
    fail = len(results) - ok
    print(f"  Total: {len(results)}   OK: {ok}   FAIL: {fail}")
    print(sep + "\n")


# ──────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────

def run(url: str):
    print(f"\n  URL  : {url}")
    params = parse_url(url)
    print(f"  Type : {params['type'].upper()}")

    servers = fetch_servers(params)
    if not servers:
        return

    print(f"  Found: {len(servers)} server(s)\n")
    results = resolve_all(servers)
    print_results(results, params)
    print(b64decode(
        "Rm9yIGVtYmVkIGRlY3J5cHRvcnMsIHJlZmVyZW5jZSB0aGUgZm9sbG93aW5nIHJlcG86IGh0dHBz"
        "Oi8vZ2l0aHViLmNvbS95b2dlc2gtaGFja2VyL01lZGlhVmFuY2VkL3RyZWUvbWFpbi9zaXRlcw=="
    ).decode())


if __name__ == "__main__":
    # Priority: command-line arg > TARGET_URL at top of file
    url = sys.argv[1] if len(sys.argv) > 1 else TARGET_URL
    run(url)