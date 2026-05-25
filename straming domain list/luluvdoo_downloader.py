#!/usr/bin/env python3
"""
Luluvdoo Video Extractor & Downloader
Pure requests — no browser automation.

Change PAGE_URL or OUTPUT_FILE at the top to target a different video.
"""

import re
import sys
import subprocess
import requests
from urllib.parse import urljoin, urlparse

# ── Config ────────────────────────────────────────────────────────────────────
PAGE_URL    = "https://luluvdoo.com/e/7d22wlk04ucd"
OUTPUT_FILE = "output.mp4"   # set to None to only print the m3u8 URL
# ─────────────────────────────────────────────────────────────────────────────

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ── P,A,C,K,E,D decoder ──────────────────────────────────────────────────────

def _to_base(n: int, base: int) -> str:
    if n == 0:
        return "0"
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = []
    while n:
        out.append(chars[n % base])
        n //= base
    return "".join(reversed(out))


def unpack(packed: str) -> str:
    """Decode Dean Edwards p,a,c,k,e,d packed JavaScript."""
    m = re.search(
        r"}\s*\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:[^'\\]|\\.)*)'\s*\.split\(",
        packed, re.DOTALL,
    )
    if not m:
        raise ValueError("Could not parse packed script")
    payload = m.group(1).replace("\\'", "'")
    base    = int(m.group(2))
    keys    = m.group(4).split("|")
    lookup  = {_to_base(i, base): w for i, w in enumerate(keys) if w}
    return re.sub(r'\b\w+\b', lambda mo: lookup.get(mo.group(0), mo.group(0)), payload)


# ── m3u8 extraction ───────────────────────────────────────────────────────────

def get_m3u8(session: requests.Session, page_url: str) -> str:
    """Fetch the embed page and return the signed master m3u8 URL."""
    resp = session.get(page_url, timeout=20)
    resp.raise_for_status()

    packed_match = re.search(
        r"(eval\(function\(p,a,c,k,e,d\)\{.*?\.split\('\|'\)[^)]*\)\))",
        resp.text, re.DOTALL,
    )
    if not packed_match:
        raise ValueError("Packed jwplayer script not found in page")

    decoded = unpack(packed_match.group(1))

    m3u8_match = re.search(r'https?://[^\s"\']+\.m3u8[^\s"\']*', decoded)
    if not m3u8_match:
        raise ValueError("m3u8 URL not found in decoded script")

    return m3u8_match.group(0)


# ── Built-in HLS downloader ───────────────────────────────────────────────────

def download_hls(session: requests.Session, m3u8_url: str, output: str) -> None:
    """Download HLS stream segment-by-segment using the same session."""
    parsed   = urlparse(m3u8_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rsplit('/', 1)[0]}/"

    r = session.get(m3u8_url, timeout=20)
    r.raise_for_status()
    master = r.text

    # Follow variant stream if this is a master playlist
    if "#EXT-X-STREAM-INF" in master:
        variant = next(l for l in master.splitlines() if l and not l.startswith("#"))
        variant_url = variant if variant.startswith("http") else urljoin(base_url, variant)
        r = session.get(variant_url, timeout=20)
        r.raise_for_status()
        parsed   = urlparse(variant_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rsplit('/', 1)[0]}/"
        playlist = r.text
    else:
        playlist = master

    segments = [l.strip() for l in playlist.splitlines() if l.strip() and not l.startswith("#")]
    total = len(segments)
    print(f"[*] {total} segments to download")

    with open(output, "wb") as f:
        for i, seg in enumerate(segments, 1):
            seg_url = seg if seg.startswith("http") else urljoin(base_url, seg)
            print(f"\r[*] Segment {i}/{total}", end="", flush=True)
            seg_r = session.get(seg_url, timeout=30)
            seg_r.raise_for_status()
            f.write(seg_r.content)

    print(f"\n[+] Saved → {output}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    page_url = sys.argv[1] if len(sys.argv) > 1 else PAGE_URL
    output   = sys.argv[2] if len(sys.argv) > 2 else OUTPUT_FILE

    print(f"[*] Page  : {page_url}")
    print(f"[*] Output: {output or '(print URL only)'}\n")

    # Single session so cookies + IP are consistent for both page and CDN
    session = requests.Session()
    session.headers.update({
        "User-Agent":      UA,
        "Origin":          "https://luluvdoo.com",
        "Referer":         "https://luluvdoo.com/",
        "Accept":          "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    })

    m3u8 = get_m3u8(session, page_url)
    print(f"[+] m3u8 URL:\n    {m3u8}\n")

    if not output:
        print("To download manually:")
        print(f'  yt-dlp --add-header "Origin:https://luluvdoo.com" --add-header "Referer:https://luluvdoo.com/" "{m3u8}"')
        return

    # Try yt-dlp on the original page URL (it will find the stream itself)
    try:
        print(f"[*] Trying yt-dlp → {output}")
        subprocess.run([
            "yt-dlp",
            "--referer", "https://luluvdoo.com/",
            "--add-header", "Origin:https://luluvdoo.com",
            "-o", output,
            page_url,
        ], check=True)
        print(f"[+] Done → {output}")
        return
    except FileNotFoundError:
        print("[!] yt-dlp not found")
    except subprocess.CalledProcessError:
        print("[!] yt-dlp failed")

    # Fallback: built-in segment downloader (same session = same IP as token)
    print(f"[*] Using built-in downloader → {output}")
    download_hls(session, m3u8, output)


if __name__ == "__main__":
    main()
