import re
import sys
import json
import time
import random
import codecs
import logging
import warnings
from base64 import b64decode
from urllib.parse import quote, urlparse, parse_qs, urljoin

import requests
from bs4 import BeautifulSoup

# Optional Cloudflare-bypass libraries (strongly recommended for Doodstream)
try:
    from curl_cffi.requests import Session as CffiSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

try:
    import niquests
    HAS_NIQUESTS = True
except ImportError:
    HAS_NIQUESTS = False

warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════
#  SET YOUR URL HERE
# ══════════════════════════════════════════════════════════

TARGET_URL = "https://primesrc.me/embed/movie?tmdb=280"

# Examples:
#   Movie  by TMDB : https://primesrc.me/embed/movie?tmdb=296
#   Movie  by IMDB : https://primesrc.me/embed/movie?imdb=tt0468569
#   TV     by IMDB : https://primesrc.me/embed/tv?imdb=tt0944947&season=1&episode=1
#   TV     by TMDB : https://primesrc.me/embed/tv?tmdb=1399&season=1&episode=1

# ══════════════════════════════════════════════════════════

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/137.0.0.0 Safari/537.36"
    )
}

API              = "https://enc-dec.app/api"
QUALITY_RANK     = ["360p", "480p", "750p", "1080p", "2160p", "4k"]
IMPERSONATE      = "chrome124"
RANDOM_CHARS     = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
PASS_MD5_PATTERN = r"\$\.get\('([^']*\/pass_md5\/[^']*)'"
TOKEN_PATTERN    = r"token=([a-zA-Z0-9]+)"


# ──────────────────────────────────────────────────────────
# SECTION A — PrimeSrc helpers
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
            sys.exit(1)
        api_url = (
            f"https://primesrc.me/api/v1/s?{id_param}"
            f"&season={season}&episode={episode}&type=tv"
        )

    print(f"  Querying : {api_url}")
    resp    = requests.get(api_url, headers=HEADERS, timeout=50).json()
    servers = resp.get("servers", [])

    if not servers:
        print("  [!] No servers returned.")
    return servers


def resolve_key(key: str):
    embed_api = f"https://primesrc.me/api/v1/l?key={key}"
    solve_url = f"{API}/solve-primesrc?url={quote(embed_api)}"
    try:
        data = requests.get(solve_url, headers=HEADERS, timeout=15).json()
        if data.get("status") != 500:
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
        quality = str(srv.get("quality") or "")
        lang    = str(srv.get("lang")    or "—")
        print(f"  [{i:>2}/{total}] {name:<18} ... ", end="", flush=True)
        link = resolve_key(key)
        print("OK" if link else "FAIL")
        results.append({"name": name, "quality": quality, "lang": lang, "link": link})
    return results


def print_results(results: list, params: dict):
    sep   = "-" * 70
    media = params["type"].upper()
    label = (
        f"TV  S{params.get('season','?')}E{params.get('episode','?')}"
        if media == "TV" else "MOVIE"
    )
    id_str = params.get("imdb_id") or f"tmdb:{params.get('tmdb_id')}"

    print(f"\n{sep}")
    print(f"  Type : {label}   |   ID : {id_str}")
    print(sep)
    print(f"  {'#':<4} {'Host':<50} {'Quality':<10} {'Lang':<6}  Link")
    print(sep)
    for idx, item in enumerate(results, 1):
        link = item["link"] or "FAILED"
        q    = item["quality"] or "—"
        print(f"  {idx:<4} {item['name']:<50} {q:<10} {item['lang']:<6}  {link}")
    print(sep)
    ok   = sum(1 for r in results if r["link"])
    fail = len(results) - ok
    print(f"  Total: {len(results)}   OK: {ok}   FAIL: {fail}")
    print(sep + "\n")


# ──────────────────────────────────────────────────────────
# SECTION B — Voe helpers (unchanged from original)
# ──────────────────────────────────────────────────────────

def quality_score(q: str) -> int:
    q = (q or "").lower()
    m = re.search(r'(\d{3,4})p?', q)
    if m:
        return int(m.group(1))
    for i, label in enumerate(QUALITY_RANK):
        if label in q:
            return (i + 1) * 100
    return 0


def pick_best_voe(results: list):
    voe_entries = [r for r in results if r.get("link") and "voe.sx" in r["link"]]
    if not voe_entries:
        return None
    voe_entries.sort(key=lambda r: quality_score(r["quality"]), reverse=True)
    best = voe_entries[0]
    print(f"\n  [Voe] {len(voe_entries)} link(s) found — picked best:")
    for e in voe_entries:
        marker = "  >>>" if e is best else "     "
        print(f"  {marker} [{e['quality'] or 'unknown quality'}]  {e['link']}")
    return best["link"]


def _clean_symbols(s: str) -> str:
    for p in ["@$", "^^", "~@", "%?", "*~", "!!", "#&"]:
        s = re.sub(re.escape(p), "_", s)
    return s


def _shift_back(s: str, n: int) -> str:
    return ''.join(chr(ord(c) - n) for c in s)


def decrypt_voe(voe_embed_url: str):
    domain  = '{uri.scheme}://{uri.netloc}/'.format(uri=urlparse(voe_embed_url))
    session = requests.Session()
    session.headers.update({
        "Referer":                   domain,
        "User-Agent":                HEADERS["User-Agent"],
        "Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language":           "en-US,en;q=0.5",
        "Accept-Encoding":           "gzip, deflate, br",
        "Connection":                "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    try:
        html = session.get(voe_embed_url, timeout=50).text
        if 'Redirecting...' in html:
            redirect_url = re.search(r"href\s*=\s*'(.*?)';", html).group(1)
            html = session.get(redirect_url, timeout=50).text

        soup       = BeautifulSoup(html, 'html.parser')
        script_tag = soup.find('script', attrs={'type': 'application/json'})
        if not script_tag:
            print("  [Voe] Could not find JSON script tag.")
            return None

        obfuscated = script_tag.string
        encoded    = re.search(r'\["(.*?)"\]', obfuscated).group(1)
        decoded    = codecs.decode(encoded, 'rot_13')
        decoded    = _clean_symbols(decoded).replace("_", "")
        decoded    = b64decode(decoded).decode()
        decoded    = _shift_back(decoded, 3)[::-1]
        decoded    = b64decode(decoded).decode()
        data       = json.loads(decoded)
        return data.get('source')

    except Exception as e:
        print(f"  [Voe] Decryption error: {e}")
        return None


# ──────────────────────────────────────────────────────────
# SECTION C — Doodstream extractor (from 2nd script)
# ──────────────────────────────────────────────────────────

def _get_base_url(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _make_headers(referer, base_url, xhr=False):
    h = {
        "User-Agent":      HEADERS["User-Agent"],
        "Referer":         referer,
        "Origin":          base_url,
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "DNT":             "1",
    }
    if xhr:
        h["Accept"]           = "*/*"
        h["X-Requested-With"] = "XMLHttpRequest"
        h["Sec-Fetch-Dest"]   = "empty"
        h["Sec-Fetch-Mode"]   = "cors"
        h["Sec-Fetch-Site"]   = "same-origin"
    else:
        h["Accept"]                    = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        h["Upgrade-Insecure-Requests"] = "1"
        h["Sec-Fetch-Dest"]            = "document"
        h["Sec-Fetch-Mode"]            = "navigate"
        h["Sec-Fetch-Site"]            = "same-origin"
    return h


def _extract_regex(pattern, content, name, url):
    match = re.search(pattern, content)
    if not match:
        raise ValueError(f"{name} not found in {url}")
    return match.group(1)


def _random_string(length=10):
    return "".join(random.choices(RANDOM_CHARS, k=length))


def _create_dood_session():
    if HAS_CURL_CFFI:
        print("  [Dood] Using curl_cffi (Cloudflare bypass enabled)")
        return CffiSession(impersonate=IMPERSONATE, verify=False), True
    elif HAS_NIQUESTS:
        print("  [Dood] Using niquests (no Cloudflare bypass)")
        s = niquests.Session()
        s.verify = False
        return s, False
    else:
        raise ImportError(
            "Install curl_cffi for Doodstream extraction:\n"
            "  pip install curl_cffi"
        )


def _dood_get(session, url, headers, **kwargs):
    return session.get(url, headers=headers, allow_redirects=True, **kwargs)


def extract_doodstream(embed_url: str):
    """
    Given a Doodstream embed URL (dood.watch/e/... or any mirror),
    return (direct_link, referer_base) or (None, None) on failure.
    """
    print(f"  [Dood] Extracting from : {embed_url}")

    try:
        session, _ = _create_dood_session()

        # Step 1 — resolve redirects
        resp           = _dood_get(session, embed_url, headers={"User-Agent": HEADERS["User-Agent"]})
        final_url      = str(resp.url)
        final_base     = _get_base_url(final_url)

        # Step 2 — homepage warm-up
        try:
            _dood_get(session, f"{final_base}/",
                      headers=_make_headers(f"{final_base}/", final_base))
        except Exception:
            pass

        # Step 3 — fetch embed page
        embed_resp = _dood_get(session, final_url,
                               headers=_make_headers(f"{final_base}/", final_base))
        embed_resp.raise_for_status()
        html = embed_resp.text

        # Step 4 — extract pass_md5 path and token
        pass_md5_path = _extract_regex(PASS_MD5_PATTERN, html, "pass_md5 URL", final_url)
        pass_md5_url  = (pass_md5_path if pass_md5_path.startswith("http")
                         else urljoin(final_base, pass_md5_path))
        token         = _extract_regex(TOKEN_PATTERN, html, "token", final_url)

        print(f"  [Dood] pass_md5 : {pass_md5_url}")
        print(f"  [Dood] token    : {token}")

        # Step 5 — XHR request to pass_md5 endpoint
        md5_resp = _dood_get(session, pass_md5_url,
                             headers=_make_headers(final_url, final_base, xhr=True))
        md5_resp.raise_for_status()
        video_base = md5_resp.text.strip()

        if not video_base:
            print("  [Dood] Empty video base URL — extraction failed.")
            return None, None

        # Step 6 — build final direct link
        expiry       = int(time.time() * 1000)
        direct_link  = f"{video_base}{_random_string(10)}?token={token}&expiry={expiry}"

        return direct_link, final_base

    except Exception as e:
        print(f"  [Dood] Error: {e}")
        return None, None


# ──────────────────────────────────────────────────────────
# SECTION D — Pick Dood links from PrimeSrc results
# ──────────────────────────────────────────────────────────

DOOD_DOMAINS = ("dood.watch", "dood.to", "dood.la", "dood.pm", "dood.sh",
                "dood.wf", "dood.yt", "doods.pro", "doodstream.com",
                "playmogo.com", "dooood.com")


def is_dood_link(url: str) -> bool:
    return any(d in url for d in DOOD_DOMAINS)


def pick_dood_links(results: list) -> list:
    """Return all successfully-resolved Doodstream entries."""
    return [r for r in results if r.get("link") and is_dood_link(r["link"])]


# ──────────────────────────────────────────────────────────
# Main pipeline
# ──────────────────────────────────────────────────────────

def run(url: str):
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  PrimeSrc + Voe + Doodstream Extractor")
    print(f"{sep}")
    print(f"  URL  : {url}\n")

    params  = parse_url(url)
    print(f"  Type : {params['type'].upper()}\n")

    # ── Step 1: get all servers ───────────────────────────
    servers = fetch_servers(params)
    if not servers:
        return

    print(f"\n  Found: {len(servers)} server(s)\n")

    # ── Step 2: resolve embed links ───────────────────────
    results = resolve_all(servers)
    print_results(results, params)

    extracted_links = []   # collect all final direct links

    # ── Step 3a: Voe ──────────────────────────────────────
    best_voe = pick_best_voe(results)
    if best_voe:
        print(f"\n  Decrypting Voe embed ...")
        m3u8 = decrypt_voe(best_voe)
        if m3u8:
            extracted_links.append({"host": "Voe", "link": m3u8, "referer": None})
        else:
            print("  [!] Voe decryption failed.")
    else:
        print("  [i] No Voe links in results — skipping Voe step.")

    # ── Step 3b: Doodstream ───────────────────────────────
    dood_entries = pick_dood_links(results)
    if dood_entries:
        print(f"\n  [Dood] {len(dood_entries)} Doodstream link(s) found — extracting ...\n")
        for entry in dood_entries:
            q    = entry["quality"] or "unknown quality"
            link = entry["link"]
            print(f"  Processing [{q}] : {link}")
            direct, referer_base = extract_doodstream(link)
            if direct:
                extracted_links.append({
                    "host":    "Doodstream",
                    "quality": q,
                    "link":    direct,
                    "referer": referer_base,
                })
                print(f"  [Dood] OK\n")
            else:
                print(f"  [Dood] FAILED\n")
    else:
        print("  [i] No Doodstream links in results — skipping Dood step.")

    # ── Final output ──────────────────────────────────────
    print("\n" + "#" * 70)
    print("  FINAL EXTRACTED LINKS")
    print("#" * 70)

    if not extracted_links:
        print("  [!] No direct links could be extracted.")
    else:
        for i, item in enumerate(extracted_links, 1):
            host = item["host"]
            link = item["link"]
            ref  = item.get("referer")
            q    = item.get("quality", "")

            print(f"\n  [{i}] Host    : {host}" + (f"  [{q}]" if q else ""))
            print(f"       Direct  : \033[92m{link}\033[0m")
            if ref:
                print(f"       Referer : {ref}/")
                print(f"       MPV cmd : mpv --http-header-fields='Referer: {ref}/' '{link}'")

    print("\n" + "#" * 70 + "\n")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else TARGET_URL
    run(url)
