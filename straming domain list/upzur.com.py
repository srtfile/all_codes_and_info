import re
import sys
import requests

DEFAULT_URL = "https://upzur.com/embed-im6qf2esvfok.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
}

COOKIES = {"lang": "english", "aff": "4881"}


def extract_from_embed(embed_url: str) -> list[str]:
    """Extract direct MP4 URLs from an upzur.com embed page."""
    session = requests.Session()
    session.headers.update(HEADERS)
    session.cookies.update(COOKIES)

    results = []

    # Step 1: fetch embed page
    r = session.get(embed_url, timeout=15)
    r.raise_for_status()
    html = r.text

    # Step 2: extract video file ID from embed URL
    file_id_match = re.search(r"embed-([a-z0-9]+)\.html", embed_url)
    if not file_id_match:
        raise ValueError(f"Cannot parse file ID from URL: {embed_url}")
    file_id = file_id_match.group(1)

    # Step 3: decode obfuscated JS array -> direct video.mp4 src
    # The embed page contains a reversed hex-encoded array that builds a <source src="..."> tag
    array_match = re.search(r'var\s+\w+\s*=\s*(\[(?:"[^"]*",?\s*)+\])', html)
    if array_match:
        raw = array_match.group(1)
        chars = re.findall(r'"(\\x[0-9a-fA-F]{2}|[^"\\])"', raw)
        decoded = "".join(
            bytes.fromhex(c[2:]).decode() if c.startswith("\\x") else c
            for c in reversed(chars)
        )
        mp4_match = re.search(r'src="(https://[^"]+\.mp4)"', decoded)
        if mp4_match:
            results.append(mp4_match.group(1))

    # Step 4: also try regex directly on raw HTML for peanut.upzur.com mp4 URLs
    direct = re.findall(r'https://peanut\.upzur\.com/d/[^"\'>\s]+\.mp4', html)
    results.extend(u for u in direct if u not in results)

    # Step 5: POST to download page to get the tokenized download link
    page_url = f"https://upzur.com/{file_id}.html"
    session.headers["Referer"] = embed_url
    session.get(page_url, timeout=15)  # load page first to get aff cookie

    post_data = {
        "op": "download2",
        "id": file_id,
        "rand": "",
        "referer": embed_url,
        "method_free": "",
        "method_premium": "",
        "adblock_detected": "1",
    }
    session.headers.update({
        "Origin": "https://upzur.com",
        "Referer": page_url,
        "Content-Type": "application/x-www-form-urlencoded",
    })
    r2 = session.post(page_url, data=post_data, timeout=15)
    r2.raise_for_status()

    # parse download link from response HTML
    dl_links = re.findall(
        r'href="(https://peanut\.upzur\.com/d/[^"]+)"', r2.text
    )
    results.extend(u for u in dl_links if u not in results)

    # also catch any mp4 in the response
    extra = re.findall(r'https://peanut\.upzur\.com/d/[^"\'>\s]+\.mp4', r2.text)
    results.extend(u for u in extra if u not in results)

    return results


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print(f"[*] Extracting from: {url}")
    try:
        links = extract_from_embed(url)
    except Exception as e:
        print(f"[!] Error: {e}")
        sys.exit(1)

    if not links:
        print("[!] No direct media links found.")
        sys.exit(1)

    print(f"[+] Found {len(links)} link(s):\n")
    for i, link in enumerate(links, 1):
        print(f"  [{i}] {link}")


if __name__ == "__main__":
    main()
