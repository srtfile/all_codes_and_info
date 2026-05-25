#!/usr/bin/env python3
"""
StreamWish / Playnixes Video Extractor & Downloader
Pure requests — no browser automation.

Flow (reverse-engineered from MITM capture):
  streamwish.to/e/{id}  →  playnixes.com/e/{id}  (same operator)
  playnixes.com page    →  contains a Dean-Edwards packed jwplayer block
  decoded block         →  exposes hls2 / hls3 / hls4 master playlist URLs
  CDN                   →  serves HLS playlists & .ts (or .woff2-renamed) segments

Edit PAGE_URL / OUTPUT below or pass them on the command line.
"""

import re
import sys
import subprocess
import requests
from urllib.parse import urljoin, urlparse

# ── Config ────────────────────────────────────────────────────────────────────
PAGE_URL = "https://streamwish.to/e/6kwa9hp2pvok"
OUTPUT   = "output.mp4"        # set to None or "" to only print URLs
QUALITY  = "best"              # "best" | "hls4" | "hls3" | "hls2" — playlist preference
# ─────────────────────────────────────────────────────────────────────────────

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# streamwish.to is just a thin landing page that iframes/redirects to playnixes.com
# We can hit playnixes.com directly with a streamwish referer.
PLAYNIXES_HOST = "https://playnixes.com"


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


# ── Stream URL extraction ────────────────────────────────────────────────────

def get_stream_urls(page_url: str, session: requests.Session) -> dict:
    """
    Fetch the embed page and return a dict of stream variants:
      {"hls2": "...m3u8?...", "hls3": "...master.txt", "hls4": "..."}
    """
    # Resolve the file code (works for streamwish.to, playnixes.com, etc.)
    m = re.search(r'/e/([A-Za-z0-9]+)', page_url)
    if not m:
        raise ValueError("Could not parse file code from URL")
    file_code = m.group(1)

    # Determine origin host for the Referer header
    origin = urlparse(page_url).netloc
    target = f"{PLAYNIXES_HOST}/e/{file_code}"

    resp = session.get(target, headers={
        "User-Agent": UA,
        "Referer":    f"https://{origin}/",
    }, timeout=20)
    resp.raise_for_status()

    # Locate the packed jwplayer script
    packed_match = re.search(
        r"(eval\(function\(p,a,c,k,e,d\)\{.*?\.split\('\|'\)[^)]*\)\))",
        resp.text, re.DOTALL,
    )
    if not packed_match:
        raise ValueError("Packed jwplayer script not found")

    decoded = unpack(packed_match.group(1))

    # The decoded block looks like:
    #   var links={"hls3":"https://...master.txt","hls2":"https://...master.m3u8?..."};
    streams = dict(re.findall(
        r'"(hls[234])"\s*:\s*"([^"]+)"',
        decoded,
    ))

    # Some pages also expose direct sources outside the links object
    extra = re.findall(r'https?://[^\s"\']+\.(?:m3u8|txt|mp4)\??[^\s"\']*', decoded)
    for u in extra:
        if u not in streams.values():
            key = "hls3" if u.endswith(".txt") or ".txt?" in u else "hls2"
            streams.setdefault(key, u)

    if not streams:
        raise ValueError("No stream URLs found in decoded jwplayer config")
    return streams


def pick_stream(streams: dict, quality: str = "best") -> tuple[str, str]:
    """Pick a stream URL by preference. Returns (label, url)."""
    if quality != "best" and quality in streams:
        return quality, streams[quality]
    # "best" — prefer hls4 > hls3 > hls2 (matches what the player chooses)
    for key in ("hls4", "hls3", "hls2"):
        if key in streams:
            return key, streams[key]
    label, url = next(iter(streams.items()))
    return label, url


# ── Built-in HLS downloader ───────────────────────────────────────────────────

def download_hls(session: requests.Session, m3u8_url: str, output: str, referer: str) -> None:
    """
    Fetch master → variant → segments and write a raw .ts container.
    Note: segments may be served as `.woff2` for obfuscation; the bytes are still TS.
    """
    headers = {"User-Agent": UA, "Referer": referer, "Origin": referer.rstrip("/"), "Accept": "*/*"}

    def fetch_text(url: str) -> str:
        r = session.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.text

    def base_of(url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}{p.path.rsplit('/', 1)[0]}/"

    master = fetch_text(m3u8_url)
    base   = base_of(m3u8_url)

    # If master playlist, descend into the first variant
    if "#EXT-X-STREAM-INF" in master:
        variant = next(l for l in master.splitlines() if l and not l.startswith("#"))
        variant_url = variant if variant.startswith("http") else urljoin(base, variant)
        master = fetch_text(variant_url)
        base   = base_of(variant_url)

    segments = [l.strip() for l in master.splitlines() if l.strip() and not l.startswith("#")]
    print(f"[*] {len(segments)} segments")

    with open(output, "wb") as f:
        for i, seg in enumerate(segments, 1):
            seg_url = seg if seg.startswith("http") else urljoin(base, seg)
            print(f"\r[*] segment {i}/{len(segments)}", end="", flush=True)
            r = session.get(seg_url, headers=headers, timeout=60)
            r.raise_for_status()
            f.write(r.content)

    print(f"\n[+] Saved → {output}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    page_url = sys.argv[1] if len(sys.argv) > 1 else PAGE_URL
    output   = sys.argv[2] if len(sys.argv) > 2 else OUTPUT

    print(f"[*] Page  : {page_url}")
    print(f"[*] Output: {output or '(print URLs only)'}\n")

    session = requests.Session()
    streams = get_stream_urls(page_url, session)

    print("[+] Stream URLs:")
    for label, url in streams.items():
        print(f"    {label:5} → {url}")

    label, m3u8 = pick_stream(streams, QUALITY)
    print(f"\n[+] Selected: {label}")

    if not output:
        print("\nDownload manually:")
        print(f'  yt-dlp --referer "{PLAYNIXES_HOST}/" "{m3u8}"')
        print(f'  ffmpeg -referer "{PLAYNIXES_HOST}/" -i "{m3u8}" -c copy out.mp4')
        return

    # Try ffmpeg first (handles AES-128 + remuxes properly)
    try:
        print(f"\n[*] Downloading with ffmpeg → {output}")
        subprocess.run([
            "ffmpeg", "-y",
            "-referer", f"{PLAYNIXES_HOST}/",
            "-user_agent", UA,
            "-i", m3u8,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            output,
        ], check=True)
        print(f"[+] Done → {output}")
        return
    except FileNotFoundError:
        print("[!] ffmpeg not found — falling back to built-in downloader")
    except subprocess.CalledProcessError as e:
        print(f"[!] ffmpeg failed (exit {e.returncode}) — falling back to built-in downloader")

    # Fallback: pure-Python segment fetcher (writes raw .ts stream)
    download_hls(session, m3u8, output, f"{PLAYNIXES_HOST}/")


if __name__ == "__main__":
    main()
