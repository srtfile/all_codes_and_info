"""
embedmultipage.py
─────────────────
Runs all 50 top-grossing movies through every embed server from embed.py.

Output files:
  allserverlist.txt           — every server URL for every movie
  uniquedomainserverslist.txt — one entry per unique domain
"""

import re
import sys
import time
from urllib.parse import urlparse

# ── Import from embed.py ───────────────────────────────────────────────────────
try:
    sys.path.insert(0, __file__.rsplit("\\", 1)[0])
    from embed import SERVERS, build_embed_url
except ImportError as e:
    print(f"[!] Could not import from embed.py: {e}")
    print("[!] Make sure embed.py is in the same folder.")
    sys.exit(1)

# ── Top 50 grossing movies — TMDB IDs ─────────────────────────────────────────
MOVIE_IDS = [
    19995, 597,   24428, 12445,   122, 38356, 49026,    58, 10193,  1865,
     1893, 12155,   155,   671,   285, 12444,  8587,   675,   767,   121,
      329,   809,   674,   559,  8355, 57800,   672,   120,    12,  1895,
     8373, 27205,   602,   557,    11,   810,   673,   217,   558, 14161,
      591,   601,  1930, 10192,   411,   604, 14160, 18239,  1858, 50619,
]

BASE_URL = "https://rivestream.ru"

# ─────────────────────────────────────────────────────────────────────────────

def domain_of(url):
    """Return bare domain, stripping common subdomains for grouping."""
    try:
        parsed = urlparse(url if url.startswith("http") else "https://rivestream.ru" + url)
        host = parsed.netloc
        host = re.sub(r'^(?:www|player|embed|iframe|api)\.', '', host)
        return host.lower()
    except Exception:
        return url


def main():
    t_start = time.time()

    total_movies  = len(MOVIE_IDS)
    total_servers = len(SERVERS)

    print("=" * 65)
    print("  EMBED MULTI-PAGE EXTRACTOR")
    print("=" * 65)
    print(f"  Movies  : {total_movies}")
    print(f"  Servers : {total_servers}")
    print(f"  Total   : {total_movies * total_servers} URLs to generate")
    print("=" * 65)

    all_entries    = []   # list of (movie_id, server_name, url)
    unique_domains = {}   # domain -> (server_name, example_url)
    errors         = []   # list of (movie_id, server_name, error_msg)

    for idx, tmdb_id in enumerate(MOVIE_IDS, 1):
        print(f"\n[{idx:02d}/{total_movies}] TMDB ID: {tmdb_id}")
        for code, name, base in SERVERS:
            try:
                url = build_embed_url(code, base, tmdb_id, "movie", 1, 1)
                # Make relative URLs absolute
                if url.startswith("/"):
                    url = BASE_URL + url
                all_entries.append((tmdb_id, name, url))
                dom = domain_of(url)
                if dom not in unique_domains:
                    unique_domains[dom] = (name, url)
                print(f"    [{name:20s}] {url}")
            except Exception as e:
                err = f"[!] TMDB {tmdb_id} / {name}: {e}"
                errors.append((tmdb_id, name, str(e)))
                print(err)

    # ── Save allserverlist.txt ─────────────────────────────────────────────────
    all_file = "allserverlist.txt"
    try:
        with open(all_file, "w", encoding="utf-8") as f:
            f.write(f"# All embed server URLs — {total_movies} movies x {total_servers} servers\n")
            f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total entries: {len(all_entries)}\n\n")
            current_movie = None
            for tmdb_id, name, url in all_entries:
                if tmdb_id != current_movie:
                    current_movie = tmdb_id
                    f.write(f"\n── Movie TMDB ID: {tmdb_id} ──\n")
                f.write(f"  {name}: {url}\n")
        print(f"\n[+] Saved {len(all_entries)} entries → {all_file}")
    except Exception as e:
        print(f"[!] Failed to save {all_file}: {e}")

    # ── Save uniquedomainserverslist.txt ───────────────────────────────────────
    unique_file = "uniquedomainserverslist.txt"
    try:
        with open(unique_file, "w", encoding="utf-8") as f:
            f.write(f"# Unique embed server domains — {len(unique_domains)} total\n")
            f.write(f"# Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for dom in sorted(unique_domains.keys()):
                name, url = unique_domains[dom]
                f.write(f"{name:22s}  {dom:38s}  {url}\n")
        print(f"[+] Saved {len(unique_domains)} unique domains → {unique_file}")
    except Exception as e:
        print(f"[!] Failed to save {unique_file}: {e}")

    # ── Report errors ──────────────────────────────────────────────────────────
    if errors:
        print(f"\n[!] {len(errors)} errors encountered:")
        for tmdb_id, name, msg in errors:
            print(f"    TMDB {tmdb_id} / {name}: {msg}")

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    print("\n" + "=" * 65)
    print("  DONE")
    print("=" * 65)
    print(f"  Movies processed      : {total_movies}")
    print(f"  URLs generated        : {len(all_entries)}")
    print(f"  Unique domains        : {len(unique_domains)}")
    print(f"  Errors                : {len(errors)}")
    print(f"  Time taken            : {elapsed:.1f}s")
    print(f"  Saved → {all_file}")
    print(f"  Saved → {unique_file}")

    print(f"\n{'─'*65}")
    print(f"  UNIQUE DOMAINS ({len(unique_domains)})")
    print(f"{'─'*65}")
    for dom in sorted(unique_domains.keys()):
        name, _ = unique_domains[dom]
        print(f"  {name:22s}  {dom}")


if __name__ == "__main__":
    main()
