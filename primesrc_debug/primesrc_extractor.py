import re
import sys
import json
import time
import codecs
import requests
from base64 import b64decode
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse, parse_qs

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

# Quality ranking — higher index = better quality
QUALITY_RANK = ["360p", "480p", "720p", "1080p", "2160p", "4k"]


# ──────────────────────────────────────────────────────────
# SECTION A — PrimeSrc: parse → fetch servers → resolve
# ──────────────────────────────────────────────────────────

def parse_url(url: str) -> dict:
    parsed = urlparse(url)
    qs     = parse_qs(parsed.query)
    path   = parsed.path.lower()

    def first(k):
        return qs.get(k, [None])[0]

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
        print("  [!] No servers returned.")
    return servers


def resolve_key(key: str, retries: int = 2):
    """
    Resolve a primesrc embed key into a real provider URL via the
    enc-dec.app proxy. Returns (link, reason) where link may be None
    and reason is a short diagnostic string on failure.
    """
    embed_api = f"https://primesrc.me/api/v1/l?key={key}"
    solve_url = f"{API}/solve-primesrc?url={quote(embed_api)}"
    last_reason = "unknown"
    for attempt in range(retries + 1):
        try:
            r = requests.get(solve_url, headers=HEADERS, timeout=20)
            try:
                data = r.json()
            except ValueError:
                last_reason = f"http {r.status_code} non-json"
            else:
                if r.status_code == 200 and data.get("status") == 200 and data.get("result"):
                    return data["result"], "ok"
                # propagate upstream error message if present
                err = data.get("error") or data.get("message") or f"status {data.get('status', r.status_code)}"
                last_reason = f"resolver: {err}"
        except requests.Timeout:
            last_reason = "timeout"
        except requests.RequestException as e:
            last_reason = f"net: {e.__class__.__name__}"
        if attempt < retries:
            time.sleep(1.5)
    return None, last_reason


def resolve_all(servers: list) -> list:
    results = []
    total   = len(servers)
    for i, srv in enumerate(servers, 1):
        name    = str(srv.get("name")    or "unknown")
        key     = srv.get("key", "")
        quality = str(srv.get("quality") or "")
        lang    = str(srv.get("lang")    or srv.get("audio_language") or "—")
        # Build the whole status line, then print as a single line.
        # Avoids garbled output on Windows cmd buffering.
        link, reason = resolve_key(key)
        status = "OK" if link else f"FAIL ({reason})"
        print(f"  [{i:>2}/{total}] {name:<18} ... {status}", flush=True)
        results.append({
            "name": name, "quality": quality, "lang": lang,
            "link": link, "reason": reason,
        })
    return results


def print_results(results: list, params: dict):
    sep = "-" * 70
    media = params["type"].upper()
    label = (
        f"TV  S{params.get('season','?')}E{params.get('episode','?')}"
        if media == "TV" else "MOVIE"
    )
    id_str = params.get("imdb_id") or f"tmdb:{params.get('tmdb_id')}"

    print(f"\n{sep}")
    print(f"  Type : {label}   |   ID : {id_str}")
    print(sep)
    print(f"  {'#':<4} {'Host':<20} {'Quality':<10} {'Lang':<6}  Link")
    print(sep)
    for idx, item in enumerate(results, 1):
        link = item["link"] or "FAILED"
        q    = item["quality"] or "—"
        print(f"  {idx:<4} {item['name']:<20} {q:<10} {item['lang']:<6}  {link}")
    print(sep)
    ok   = sum(1 for r in results if r["link"])
    fail = len(results) - ok
    print(f"  Total: {len(results)}   OK: {ok}   FAIL: {fail}")
    print(sep + "\n")


# ──────────────────────────────────────────────────────────
# SECTION B — Pick the best Voe link from results
# ──────────────────────────────────────────────────────────

def quality_score(q: str) -> int:
    """Return a numeric score for a quality string. Higher = better."""
    q = (q or "").lower()
    # Try to extract a numeric resolution first (e.g. "1080p", "2160p")
    m = re.search(r'(\d{3,4})p?', q)
    if m:
        return int(m.group(1))
    # Map named tiers
    for i, label in enumerate(QUALITY_RANK):
        if label in q:
            return (i + 1) * 100
    return 0  # unknown quality — ranked last


def pick_best_voe(results: list) -> str | None:
    """
    From the resolved server list, collect all successful Voe links,
    rank by quality, and return the single best one.
    """
    voe_entries = [
        r for r in results
        if r.get("link") and "voe.sx" in r["link"]
    ]

    if not voe_entries:
        return None

    # Sort descending by quality score; ties keep original order
    voe_entries.sort(key=lambda r: quality_score(r["quality"]), reverse=True)

    best = voe_entries[0]
    print(f"\n  [Voe] {len(voe_entries)} link(s) found — picked best:")
    for e in voe_entries:
        marker = "  >>>" if e is best else "     "
        q = e["quality"] or "unknown quality"
        print(f"  {marker} [{q}]  {e['link']}")

    return best["link"]


# ──────────────────────────────────────────────────────────
# SECTION C — Voe decryptor  (extracts the .m3u8 URL)
# ──────────────────────────────────────────────────────────

def _clean_symbols(s: str) -> str:
    for p in ["@$", "^^", "~@", "%?", "*~", "!!", "#&"]:
        s = re.sub(re.escape(p), "_", s)
    return s

def _shift_back(s: str, n: int) -> str:
    return ''.join(chr(ord(c) - n) for c in s)


def decrypt_voe(voe_embed_url: str) -> str | None:
    """
    Given a voe.sx embed URL (e.g. https://voe.sx/e/80z1tpfbsfdkgyc),
    return the direct .m3u8 (HLS) stream URL.
    """
    domain = '{uri.scheme}://{uri.netloc}/'.format(uri=urlparse(voe_embed_url))

    session = requests.Session()
    session.headers.update({
        "Referer":                  domain,
        "User-Agent":               HEADERS["User-Agent"],
        "Accept":                   "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":          "en-US,en;q=0.5",
        "Accept-Encoding":          "gzip, deflate, br",
        "Connection":               "keep-alive",
        "Upgrade-Insecure-Requests":"1",
    })

    try:
        html = session.get(voe_embed_url, timeout=20).text

        # Follow redirect if needed
        if 'Redirecting...' in html:
            redirect_url = re.search(r"href\s*=\s*'(.*?)';", html).group(1)
            html = session.get(redirect_url, timeout=20).text

        soup = BeautifulSoup(html, 'html.parser')
        script_tag = soup.find('script', attrs={'type': 'application/json'})
        if not script_tag:
            print("  [Voe] Could not find JSON script tag.")
            return None

        obfuscated  = script_tag.string
        encoded     = re.search(r'\["(.*?)"\]', obfuscated).group(1)

        # Decode pipeline (matches voe.sx obfuscation)
        decoded = codecs.decode(encoded, 'rot_13')
        decoded = _clean_symbols(decoded)
        decoded = decoded.replace("_", "")
        decoded = b64decode(decoded).decode()
        decoded = _shift_back(decoded, 3)
        decoded = decoded[::-1]
        decoded = b64decode(decoded).decode()
        data    = json.loads(decoded)

        return data.get('source')

    except Exception as e:
        print(f"  [Voe] Decryption error: {e}")
        return None


# ──────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────

def run(url: str):
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  PrimeSrc + Voe Extractor")
    print(f"{sep}")
    print(f"  URL  : {url}")

    params  = parse_url(url)
    print(f"  Type : {params['type'].upper()}\n")

    # Step 1 — get all servers
    servers = fetch_servers(params)
    if not servers:
        return

    print(f"\n  Found: {len(servers)} server(s)\n")

    # Step 2 — resolve all embed links
    results = resolve_all(servers)
    print_results(results, params)

    # Detect upstream resolver outage so the user understands the cause.
    ok_count = sum(1 for r in results if r["link"])
    if ok_count == 0 and results:
        reasons = {r["reason"] for r in results}
        proxy_failed = all("Proxy solve failed" in r["reason"] or
                           "resolver" in r["reason"]
                           for r in results)
        print("  Diagnostic:")
        for reason in sorted(reasons):
            count = sum(1 for r in results if r["reason"] == reason)
            print(f"    - {reason}  ({count}/{len(results)})")
        if proxy_failed:
            print()
            print("  All keys failed at the upstream resolver (enc-dec.app).")
            print("  This is an external service outage, not a bug in this script.")
            print("  The primesrc.me /api/v1/l endpoint is protected by Cloudflare")
            print("  Turnstile, so it cannot be queried directly without a real browser.")
            print("  Try again later, or replace the API constant with a working")
            print("  primesrc-solver endpoint.")
        print()

    # Step 3 — pick best Voe link
    best_voe = pick_best_voe(results)

    if not best_voe:
        print("\n  [!] No Voe links found in results.")
        return

    # Step 4 — decrypt Voe → .m3u8
    print(f"\n  Decrypting Voe embed ...")
    m3u8_url = decrypt_voe(best_voe)

    print("\n" + "#" * 50)
    if m3u8_url:
        print(f"  Captured URL:\n  \033[92m{m3u8_url}\033[0m")
    else:
        print("  [!] Failed to extract stream URL from Voe.")
    print("#" * 50 + "\n")

    print(b64decode(
        "Rm9yIGVtYmVkIGRlY3J5cHRvcnMsIHJlZmVyZW5jZSB0aGUgZm9sbG93aW5nIHJlcG86IGh0dHBz"
        "Oi8vZ2l0aHViLmNvbS95b2dlc2gtaGFja2VyL01lZGlhVmFuY2VkL3RyZWUvbWFpbi9zaXRlcw=="
    ).decode())


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else TARGET_URL
    run(url)
