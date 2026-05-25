"""
direct_testing.py
==================
Pure-Python M3U8 extractor for vaplayer.ru — NO browser, NO selenium.

Discovered API:  https://streamdata.vaplayer.ru/api.php
  Params:  imdb=<imdb_id>  &  type=movie|tv  [&season=N&episode=N]
  Returns: JSON with stream_urls[] containing the m3u8 playlist URL

Usage:
  python direct_testing.py
  python direct_testing.py --imdb tt2948356 --type movie
  python direct_testing.py --imdb tt0944947 --type tv --season 1 --episode 1
"""

import re
import sys
import json
import argparse
import urllib.parse

try:
    import requests
except ImportError:
    print("[!] pip install requests")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
API_URL  = "https://streamdata.vaplayer.ru/api.php"
BASE_REF = "https://brightpathsignals.com/embed/movie/"

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer":         BASE_REF,
    "Origin":          "https://brightpathsignals.com",
}


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — call the API
# ─────────────────────────────────────────────────────────────────────────────
def call_api(imdb_id: str, media_type: str, season: int = None, episode: int = None) -> dict:
    params = {"imdb": imdb_id, "type": media_type}
    if season:
        params["season"]  = season
    if episode:
        params["episode"] = episode

    url = API_URL + "?" + urllib.parse.urlencode(params)
    print(f"[API] GET {url}")

    r = requests.get(url, headers=HEADERS, timeout=15)
    print(f"[API] status: {r.status_code}")

    try:
        return r.json()
    except Exception:
        print(f"[!] Non-JSON response: {r.text[:300]}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — parse m3u8 playlist (pure stdlib, no external lib)
# ─────────────────────────────────────────────────────────────────────────────
def parse_m3u8(url: str) -> dict:
    result = {
        "url":          url,
        "is_master":    False,
        "variants":     [],
        "segments":     [],
        "duration_sec": 0.0,
        "error":        None,
    }
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        raw = r.text
        lines = raw.splitlines()

        is_master = any("#EXT-X-STREAM-INF" in l for l in lines)
        result["is_master"] = is_master

        if is_master:
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if line.startswith("#EXT-X-STREAM-INF"):
                    bw  = re.search(r'BANDWIDTH=(\d+)',     line)
                    res = re.search(r'RESOLUTION=([\dx]+)', line)
                    cod = re.search(r'CODECS="([^"]+)"',    line)
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    uri = lines[j].strip() if j < len(lines) else ""
                    if uri and not uri.startswith("#"):
                        if not uri.startswith("http"):
                            uri = urllib.parse.urljoin(url, uri)
                        result["variants"].append({
                            "uri":        uri,
                            "bandwidth":  int(bw.group(1))  if bw  else 0,
                            "resolution": res.group(1)       if res else "?",
                            "codecs":     cod.group(1)       if cod else "",
                        })
                i += 1
        else:
            dur = 0.0
            for line in lines:
                line = line.strip()
                if line.startswith("#EXTINF"):
                    m = re.search(r'#EXTINF:([\d.]+)', line)
                    if m:
                        dur = float(m.group(1))
                elif line and not line.startswith("#"):
                    seg = line if line.startswith("http") else urllib.parse.urljoin(url, line)
                    result["segments"].append(seg)
                    result["duration_sec"] += dur
                    dur = 0.0

    except Exception as e:
        result["error"] = str(e)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 — print report
# ─────────────────────────────────────────────────────────────────────────────
def print_report(api_data: dict, playlists: list):
    W = 65
    print("\n" + "═" * W)
    print("  DIRECT API REPORT")
    print("═" * W)

    # media info
    d = api_data.get("data", {})
    print(f"  Title    : {d.get('title', '?')}")
    print(f"  IMDB     : {d.get('imdb_id', '?')}")
    print(f"  File     : {d.get('file_name', '?')}")
    print(f"  Backdrop : {d.get('backdrop', '?')}")

    # raw stream URLs from API
    stream_urls = d.get("stream_urls", [])
    print(f"\n{'★' * W}")
    print(f"  M3U8 STREAM URLS FROM API : {len(stream_urls)}")
    print(f"{'★' * W}")
    for i, u in enumerate(stream_urls, 1):
        print(f"  [{i}] {u}")

    # headers needed to use these URLs
    print(f"\n  Required headers to replay:")
    print(f"    Referer : {BASE_REF}")
    print(f"    Origin  : https://brightpathsignals.com")

    # parsed playlist details
    if playlists:
        print(f"\n{'─' * W}")
        print("  PLAYLIST DETAILS")
        print(f"{'─' * W}")
        for p in playlists:
            print(f"\n  URL : {p['url']}")
            if p.get("error"):
                print(f"  Error: {p['error']}")
                continue
            if p["is_master"]:
                print(f"  Type    : MASTER  ({len(p['variants'])} quality levels)")
                # sort by bandwidth descending
                for v in sorted(p["variants"], key=lambda x: x["bandwidth"], reverse=True):
                    bw = f"{v['bandwidth']:,}" if v["bandwidth"] else "?"
                    print(f"    • {v['resolution']:>10}  {bw:>12} bps")
                    print(f"      {v['uri']}")
            else:
                print(f"  Type     : MEDIA")
                print(f"  Segments : {len(p['segments'])}")
                print(f"  Duration : {p['duration_sec']:.1f}s  ({p['duration_sec']/60:.1f} min)")
                if p["segments"]:
                    print(f"  First    : {p['segments'][0]}")
                    print(f"  Last     : {p['segments'][-1]}")

    print("\n" + "═" * W)

    # ffmpeg / vlc copy-paste commands
    if stream_urls:
        print("\n  ── PLAY WITH VLC ──")
        print(f'  vlc --http-referrer="{BASE_REF}" "{stream_urls[0]}"')
        print("\n  ── DOWNLOAD WITH FFMPEG ──")
        print(f'  ffmpeg -headers "Referer: {BASE_REF}" -i "{stream_urls[0]}" -c copy output.mp4')
        print()


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def run(imdb_id: str, media_type: str, season: int = None, episode: int = None):
    print(f"\n{'=' * 65}")
    print(f"  IMDB   : {imdb_id}")
    print(f"  TYPE   : {media_type}")
    if season:
        print(f"  SEASON : {season}  EPISODE : {episode}")
    print(f"  METHOD : direct API call (no browser)")
    print(f"{'=' * 65}\n")

    # Phase 1 — API call
    print("[Phase 1] Calling stream API …")
    api_data = call_api(imdb_id, media_type, season, episode)

    if not api_data or api_data.get("status_code") not in ("200", 200):
        print(f"[!] API error: {api_data}")
        return

    stream_urls = api_data.get("data", {}).get("stream_urls", [])
    print(f"  → {len(stream_urls)} stream URL(s) returned")

    # Phase 2 — parse each playlist
    playlists = []
    if stream_urls:
        print(f"\n[Phase 2] Parsing {len(stream_urls)} playlist(s) …")
        for url in stream_urls:
            print(f"  parsing: {url[:80]}…")
            p = parse_m3u8(url)
            playlists.append(p)
            # if master, also parse each variant to get segment count
            if p["is_master"]:
                for v in p["variants"]:
                    vp = parse_m3u8(v["uri"])
                    v["segments"]     = len(vp["segments"])
                    v["duration_sec"] = vp["duration_sec"]

    # Phase 3 — report
    print_report(api_data, playlists)


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Direct API m3u8 extractor for vaplayer.ru")
    parser.add_argument("--imdb",    default="tt2948356",  help="IMDB ID  (default: tt2948356 = Zootopia)")
    parser.add_argument("--type",    default="movie",      choices=["movie", "tv"], help="Media type")
    parser.add_argument("--season",  type=int, default=None, help="Season number (TV only)")
    parser.add_argument("--episode", type=int, default=None, help="Episode number (TV only)")
    args = parser.parse_args()

    run(args.imdb, args.type, args.season, args.episode)
