"""
cinemaos_api.py  —  CinemaOS Direct Stream API Client
======================================================
Fully reverse-engineered. No browser needed.

INSTALL:
    pip install requests pycryptodome

USAGE:
    python cinemaos_api.py
    python cinemaos_api.py --tmdb 1318447 --imdb tt16431404 --title "Apex" --year 2026
    python cinemaos_api.py --tmdb 94997   --imdb tt21209876 --title "House of Dragon" --year 2022 --type tv --season 1 --episode 1
    python cinemaos_api.py --tmdb 1318447 --imdb tt16431404 --title "Apex" --year 2026 --best
    python cinemaos_api.py --tmdb 1318447 --imdb tt16431404 --title "Apex" --year 2026 --json
    python cinemaos_api.py --subs 1318447
"""

import re, json, hashlib, hmac, argparse, sys
import requests
from Crypto.Cipher import AES

# ── Reverse-engineered constants ─────────────────────────────────────────────
_PRIMARY   = "a7f3b9c2e8d4f1a6b5c9e2d7f4a8b3c6e1d9f7a4b2c8e5d3f9a6b4c1e7d2f8a5"
_SECONDARY = "d3f8a5b2c9e6d1f7a4b8c5e2d9f3a6b1c7e4d8f2a9b5c3e7d4f1a8b6c2e9d5f3"
_RK        = "2549b22d9bf0d91847a2811baac98d0079e02dba592aea94"
_ENC_KEY   = "a1b2c3d4e4f6477658455678901477567890abcdef1234567890abcdef123456"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Referer":    "https://cinemaos.tech/",
    "Origin":     "https://cinemaos.tech",
    "Accept":     "application/json, */*",
}

# ─────────────────────────────────────────────────────────────────────────────
# Core functions
# ─────────────────────────────────────────────────────────────────────────────

def generate_secret(tmdb_id: str, imdb_id: str,
                    season_id=None, episode_id=None) -> str:
    """
    Generate the 'secret' parameter for the provider API.
    Algorithm: double HMAC-SHA256 with hardcoded keys.
    """
    parts = [f"tmdbId:{tmdb_id}", f"imdbId:{imdb_id}"]
    if season_id  and str(season_id)  != "": parts.append(f"seasonId:{season_id}")
    if episode_id and str(episode_id) != "": parts.append(f"episodeId:{episode_id}")
    payload = "|".join(parts)
    inner   = hmac.new(_PRIMARY.encode(),   payload.encode(), hashlib.sha256).hexdigest()
    secret  = hmac.new(_SECONDARY.encode(), inner.encode(),   hashlib.sha256).hexdigest()
    return secret


def _decrypt(data: dict) -> str:
    """AES-256-GCM decrypt the provider API response."""
    enc  = bytes.fromhex(data["encrypted"])
    iv   = bytes.fromhex(data["cin"])
    tag  = bytes.fromhex(data["mao"])
    salt = bytes.fromhex(data.get("salt", ""))
    ver  = data.get("version", 0)

    if ver >= 1 and salt:
        key = hashlib.pbkdf2_hmac("sha256", _ENC_KEY.encode(), salt, 100000, 32)
    else:
        key = bytes.fromhex(_ENC_KEY)

    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
    return cipher.decrypt_and_verify(enc, tag).decode("utf-8")


def get_meta_from_page(tmdb_id: str) -> tuple:
    """
    Fetch imdb_id, title, year from the cinemaos player page.
    The page embeds full TMDB metadata in its Next.js SSR HTML.
    Returns (imdb_id, title, year) — all strings, or None if not found.
    """
    r = requests.get(
        f"https://cinemaos.tech/player/{tmdb_id}",
        headers=_HEADERS, timeout=10
    )
    html = r.text
    # Data is in escaped JSON inside __next_f.push() calls
    imdb  = (re.search(r'imdb_id\\":\\"(tt\d+)\\"', html) or
             re.search(r'"imdb_id"\s*:\s*"(tt\d+)"', html))
    title = (re.search(r'\\"title\\":\\"([^\\"]+)\\"', html) or
             re.search(r'"title"\s*:\s*"([^"\\]+)"', html))
    year  = (re.search(r'release_date\\":\\"(\d{4})', html) or
             re.search(r'"release_date"\s*:\s*"(\d{4})', html))
    return (
        imdb.group(1)  if imdb  else None,
        title.group(1) if title else None,
        year.group(1)  if year  else None,
    )


def get_sources(tmdb_id: str, imdb_id: str = None, title: str = None, year: str = None,
                content_type: str = "movie",
                season=None, episode=None) -> dict:
    """
    Fetch and decrypt all stream sources for a movie or TV episode.
    If imdb_id/title/year are not provided, they are auto-fetched
    from the cinemaos player page using only the tmdb_id.
    """
    # Auto-fetch metadata if not provided
    if not all([imdb_id, title, year]):
        imdb_id, title, year = get_meta_from_page(tmdb_id)
        if not all([imdb_id, title, year]):
            raise ValueError(f"Could not extract metadata for TMDB ID {tmdb_id}")

    secret = generate_secret(tmdb_id, imdb_id, season, episode)

    params = {
        "type":    content_type,
        "tmdbId":  tmdb_id,
        "imdbId":  imdb_id,
        "t":       title,
        "ry":      year,
        "secret":  secret,
        "_rk":     _RK,
    }
    if season:  params["season"]  = str(season)
    if episode: params["episode"] = str(episode)

    r = requests.get(
        "https://cinemaos.tech/api/providerv4",
        params=params, headers=_HEADERS, timeout=15
    )
    r.raise_for_status()
    resp = r.json()

    if "error" in resp:
        raise ValueError(f"API error: {resp['error']}")

    plaintext = _decrypt(resp["data"])
    data      = json.loads(plaintext)
    data["secret"] = secret
    return data


def get_subtitles(tmdb_id: str, content_type: str = "movie",
                  season=None, episode=None) -> list:
    """
    Fetch subtitle tracks. No auth needed.
    Returns list of {"label": "English", "file": "https://...vtt"}
    """
    if content_type == "movie":
        url = f"https://sub.vdrk.site/v1/movie/{tmdb_id}"
    else:
        url = f"https://sub.vdrk.site/v1/tv/{tmdb_id}/{season}/{episode}"
    r = requests.get(url, headers=_HEADERS, timeout=10)
    return r.json() if r.status_code == 200 else []


def best_source(sources: dict) -> tuple:
    """
    Pick the best stream source by priority:
    4K > FHD > Auto > SD > LD
    Returns (server_name, source_dict)
    """
    priority = {"4k": 0, "fhd": 1, "auto": 2, "sd": 3, "ld": 4, "": 5}
    ranked = sorted(
        sources.items(),
        key=lambda x: priority.get(
            str(x[1].get("bitrate", "")).lower(), 5
        )
    )
    return ranked[0] if ranked else (None, None)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _print_sources(data: dict, show_headers=False):
    sources = data.get("sources", {})
    print(f"\n  Found {len(sources)} stream source(s):\n")
    print(f"  {'#':<3} {'Server':<18} {'Type':<5} {'Quality':<8} {'Language':<12} URL")
    print(f"  {'-'*3} {'-'*18} {'-'*5} {'-'*8} {'-'*12} {'-'*50}")
    for i, (name, src) in enumerate(sources.items(), 1):
        url      = src.get("url", "")
        stype    = src.get("type", "hls")
        bitrate  = src.get("bitrate", "Auto")
        lang     = src.get("language", "")
        print(f"  {i:<3} {name:<18} {stype:<5} {bitrate:<8} {lang:<12} {url[:80]}")
        if show_headers and src.get("headers"):
            for k, v in src["headers"].items():
                print(f"       {'':18}   Header: {k}: {v}")
    print()


def _print_best(data: dict):
    sources = data.get("sources", {})
    name, src = best_source(sources)
    if not src:
        print("  No sources found.")
        return
    print(f"\n  Best source: {name}")
    print(f"  URL:         {src.get('url', '')}")
    print(f"  Type:        {src.get('type', 'hls')}")
    print(f"  Quality:     {src.get('bitrate', 'Auto')}")
    print(f"  Language:    {src.get('language', '')}")
    if src.get("headers"):
        print(f"  Headers:")
        for k, v in src["headers"].items():
            print(f"    {k}: {v}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="CinemaOS Direct Stream API — get stream URLs for any movie/show",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:

  # Get all sources for a movie
  python cinemaos_api.py --tmdb 1318447 --imdb tt16431404 --title "Apex" --year 2026

  # Get only the best source
  python cinemaos_api.py --tmdb 1318447 --imdb tt16431404 --title "Apex" --year 2026 --best

  # Get raw JSON output (pipe to jq, save to file, etc.)
  python cinemaos_api.py --tmdb 1318447 --imdb tt16431404 --title "Apex" --year 2026 --json

  # TV show — season 1 episode 1
  python cinemaos_api.py --tmdb 94997 --imdb tt21209876 --title "House of the Dragon" --year 2022 --type tv --season 1 --episode 1

  # Get subtitles only (no auth needed)
  python cinemaos_api.py --subs 1318447

  # Get subtitles for a TV episode
  python cinemaos_api.py --subs 94997 --type tv --season 1 --episode 1

  # Show request headers for sources that need them
  python cinemaos_api.py --tmdb 1318447 --imdb tt16431404 --title "Apex" --year 2026 --headers

HOW TO FIND TMDB ID / IMDB ID:
  Go to https://www.themoviedb.org/ → search your movie/show
  The URL will be: themoviedb.org/movie/1318447-apex
  TMDB ID = 1318447
  IMDB ID = find it on the movie page under "External IDs"
        """
    )

    parser.add_argument("--tmdb",    help="TMDB ID  (e.g. 1318447)  — the number in the player URL")
    parser.add_argument("--imdb",    help="IMDB ID  (e.g. tt16431404) — optional, auto-fetched if omitted")
    parser.add_argument("--title",   help='Title    (e.g. "Apex")     — optional, auto-fetched if omitted')
    parser.add_argument("--year",    help="Year     (e.g. 2026)       — optional, auto-fetched if omitted")
    parser.add_argument("--type",    default="movie", choices=["movie","tv"],
                        help="Content type: movie or tv  (default: movie)")
    parser.add_argument("--season",  type=int, help="Season number  (TV only)")
    parser.add_argument("--episode", type=int, help="Episode number (TV only)")
    parser.add_argument("--best",    action="store_true",
                        help="Show only the best quality source")
    parser.add_argument("--json",    action="store_true",
                        help="Output raw JSON (all sources + captions)")
    parser.add_argument("--headers", action="store_true",
                        help="Show request headers for each source")
    parser.add_argument("--subs",    metavar="TMDB_ID",
                        help="Fetch subtitles only for this TMDB ID")
    parser.add_argument("--save",    metavar="FILE",
                        help="Save full JSON output to a file")

    args = parser.parse_args()

    # ── Subtitles only ────────────────────────────────────────────────────────
    if args.subs:
        print(f"\nFetching subtitles for TMDB:{args.subs} ...")
        subs = get_subtitles(args.subs, args.type, args.season, args.episode)
        if not subs:
            print("  No subtitles found.")
        else:
            print(f"  {len(subs)} subtitle track(s):\n")
            for s in subs:
                print(f"  [{s.get('label','?')}]  {s.get('file','')}")
        return

    # ── Validate required args ────────────────────────────────────────────────
    if not args.tmdb:
        parser.print_help()
        print("\n  ERROR: --tmdb is required.\n")
        sys.exit(1)

    if args.type == "tv" and not (args.season and args.episode):
        print("\n  ERROR: --season and --episode are required for --type tv\n")
        sys.exit(1)

    # ── Fetch sources ─────────────────────────────────────────────────────────
    print(f"\nFetching streams for: {args.title} ({args.year})")
    print(f"  TMDB: {args.tmdb}  IMDB: {args.imdb}  Type: {args.type}", end="")
    if args.type == "tv":
        print(f"  S{args.season:02d}E{args.episode:02d}", end="")
    print()

    try:
        data = get_sources(
            args.tmdb, args.imdb, args.title, args.year,
            args.type, args.season, args.episode
        )
    except Exception as e:
        print(f"\n  ERROR: {e}")
        sys.exit(1)

    # ── Output ────────────────────────────────────────────────────────────────
    if args.json:
        out = json.dumps(data, indent=2)
        print(out)
        if args.save:
            with open(args.save, "w") as f:
                f.write(out)
            print(f"\n  Saved → {args.save}")
        return

    if args.best:
        _print_best(data)
    else:
        _print_sources(data, show_headers=args.headers)

    # Always show captions if present
    captions = data.get("captions", [])
    if captions:
        print(f"  Subtitles ({len(captions)}):")
        for c in captions:
            print(f"    [{c.get('label','?')}]  {c.get('file','')}")
        print()

    if args.save:
        with open(args.save, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  Saved → {args.save}")


# ─────────────────────────────────────────────────────────────────────────────
# Quick demo when run without arguments
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No args — run demo
        print("=" * 70)
        print("  CinemaOS Direct API — Demo")
        print("=" * 70)
        print("\n  Testing with: Apex (2026)  TMDB:1318447\n")
        try:
            data = get_sources("45050", "tt16431404", "Apex", "2026")
            _print_sources(data)
            name, src = best_source(data.get("sources", {}))
            if src:
                print(f"  Best source: {name}")
                print(f"  URL: {src['url']}")
            print("\n  Run with --help to see all options.")
        except Exception as e:
            print(f"  Error: {e}")
    else:
        main()
