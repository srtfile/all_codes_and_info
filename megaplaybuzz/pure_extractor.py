"""
GogoAnime M3U8 Pure Extractor
==============================
No Selenium. No browser. Just requests.

Flow:
  1. GET gogoanime page  → extract iframe src (megaplay stream URL)
  2. Parse stream ID from megaplay URL
  3. GET megaplay/domains  → get active CDN domain
  4. GET megaplay/stream/getSources?id=X  → get m3u8 URL directly

Usage:
    python pure_extractor.py
    python pure_extractor.py --url "https://gogoanime.me.uk/newplayer.php?id=21?ep=1"
    python pure_extractor.py --url "..." --output results.json
"""

import re
import json
import argparse
import requests
from bs4 import BeautifulSoup
import urllib3
urllib3.disable_warnings()

DEFAULT_URL = "https://gogoanime.me.uk/newplayer.php?id=21?ep=10"

HEADERS_GOGO = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

HEADERS_API = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


def step1_get_iframe(page_url: str) -> str:
    """Fetch gogoanime player page and extract the megaplay iframe src."""
    print(f"[1] Fetching player page: {page_url}")
    r = requests.get(page_url, headers=HEADERS_GOGO, timeout=15, verify=False)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    iframe = soup.find("iframe", src=True)
    if not iframe:
        raise ValueError("No iframe found on page")
    src = iframe["src"]
    print(f"    → iframe src: {src}")
    return src


def step2_parse_stream_id(megaplay_url: str) -> tuple[str, str]:
    """
    Extract the numeric stream ID from the megaplay URL.
    e.g. https://megaplay.buzz/stream/s-2/1/sub?autostart=true → base=megaplay.buzz, id via getSources
    We need to call /domains first to get the file ID.
    """
    # Extract base domain
    from urllib.parse import urlparse
    parsed = urlparse(megaplay_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    print(f"    → megaplay base: {base}")
    return base, megaplay_url


def step3_get_file_id(base: str, stream_url: str) -> str:
    """
    Fetch the megaplay stream page and extract the file ID from the <title> tag.
    e.g. <title>File 42175 - MegaPlay</title>  →  42175
    Strip ?autostart=true so we get the real page, not a redirect.
    """
    # Remove query string — the clean URL returns the full HTML with the title
    clean_url = stream_url.split("?")[0]
    print(f"[2] Fetching megaplay stream page: {clean_url}")

    r = requests.get(
        clean_url,
        headers={**HEADERS_GOGO, "Referer": "https://gogoanime.me.uk/"},
        timeout=15,
        verify=False
    )

    # Extract from <title>File XXXXX - MegaPlay</title>
    match = re.search(r'<title>File\s+(\d+)', r.text, re.IGNORECASE)
    if match:
        file_id = match.group(1)
        print(f"    → file ID: {file_id}")
        return file_id

    # Fallback: getSources?id=XXXXX in JS
    match = re.search(r'getSources\?id=(\d+)', r.text)
    if match:
        file_id = match.group(1)
        print(f"    → file ID (js fallback): {file_id}")
        return file_id

    raise ValueError(f"Could not find file ID in stream page (status {r.status_code})")


def step4_get_sources(base: str, file_id: str, stream_url: str) -> dict:
    """Call the getSources API directly with the correct headers."""
    api_url = f"{base}/stream/getSources?id={file_id}&id={file_id}"
    print(f"[3] Calling getSources API: {api_url}")

    headers = {
        **HEADERS_API,
        "Referer": stream_url,
        "Origin": base,
    }

    r = requests.get(api_url, headers=headers, timeout=15, verify=False)
    r.raise_for_status()

    try:
        data = r.json()
        return data
    except Exception:
        raise ValueError(f"getSources returned non-JSON (status {r.status_code}): {r.text[:200]}")


def extract(page_url: str) -> dict:
    print(f"\n{'='*60}")
    print(f"  URL: {page_url}")
    print(f"{'='*60}\n")

    # Step 1: get iframe URL
    stream_url = step1_get_iframe(page_url)

    # Step 2: parse base domain
    base, stream_url = step2_parse_stream_id(stream_url)

    # Step 3: get file ID from stream page
    file_id = step3_get_file_id(base, stream_url)

    # Step 4: call getSources API
    data = step4_get_sources(base, file_id, stream_url)

    # Parse result
    m3u8_urls = []
    sources = data.get("sources", {})
    if isinstance(sources, dict):
        f = sources.get("file", "")
        if f and ".m3u8" in f:
            m3u8_urls.append(f)
    elif isinstance(sources, list):
        for s in sources:
            f = s.get("file", "")
            if f and ".m3u8" in f:
                m3u8_urls.append(f)

    # Also check top-level file key
    if "file" in data and ".m3u8" in str(data["file"]):
        m3u8_urls.append(data["file"])

    result = {
        "url": page_url,
        "stream_url": stream_url,
        "file_id": file_id,
        "m3u8_urls": list(set(m3u8_urls)),
        "raw_response": data,
    }

    print(f"\n{'='*60}")
    print("  RESULT")
    print(f"{'='*60}")
    if m3u8_urls:
        print(f"\n  ✅  {len(m3u8_urls)} m3u8 URL(s) found:\n")
        for u in m3u8_urls:
            print(f"      {u}")
    else:
        print("\n  ⚠️  No m3u8 found in getSources response.")
        print(f"  Raw response: {json.dumps(data, indent=2)[:500]}")
    print()

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract m3u8 from gogoanime without Selenium")
    parser.add_argument("--url",    default=DEFAULT_URL, help="Player page URL")
    parser.add_argument("--output", default="results.json", help="JSON output file")
    args = parser.parse_args()

    result = extract(args.url)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  💾 Saved to: {args.output}\n")
