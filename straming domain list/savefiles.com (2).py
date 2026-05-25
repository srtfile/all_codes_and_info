import re
import sys
import cloudscraper

DEFAULT_URL = "https://savefiles.com/e/p7ydrt7zuo4n"

HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "origin": "https://savefiles.com",
    "referer": "https://savefiles.com/",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "dnt": "1",
}


def extract_file_code(url: str) -> str:
    match = re.search(r"/e/([a-z0-9]+)", url)
    if not match:
        raise ValueError(f"Cannot extract file_code from URL: {url}")
    return match.group(1)


def get_m3u8(page_url: str = DEFAULT_URL) -> str:
    file_code = extract_file_code(page_url)

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False}
    )

    # Step 1: visit embed page to get cf_clearance + cookies
    scraper.get(page_url, headers=HEADERS)

    # Step 2: POST to /dl — this returns the HTML with JWPlayer sources
    post_headers = {**HEADERS, "content-type": "application/x-www-form-urlencoded",
                    "sec-fetch-dest": "document", "sec-fetch-mode": "navigate",
                    "sec-fetch-site": "same-origin", "referer": page_url}

    resp = scraper.post(
        "https://savefiles.com/dl",
        data=f"op=embed&file_code={file_code}&auto=1&referer=",
        headers=post_headers,
        allow_redirects=True,
    )
    resp.raise_for_status()

    # Step 3: extract m3u8 from JWPlayer sources config
    match = re.search(r'sources:\s*\[\{file:"([^"]+\.m3u8[^"]+)"', resp.text)
    if not match:
        # fallback: any m3u8 URL in the page
        match = re.search(r'(https://[^\s"\']+\.m3u8[^\s"\']*)', resp.text)
    if not match:
        raise RuntimeError("No m3u8 URL found in response. Cloudflare may have blocked the request.")

    return match.group(1)


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print(f"[*] Extracting stream from: {url}")
    m3u8_url = get_m3u8(url)
    print(f"\n[+] Master m3u8:\n{m3u8_url}\n")
    print(f"[i] Play with:\n    mpv \"{m3u8_url}\"\n    vlc \"{m3u8_url}\"")
    return m3u8_url


if __name__ == "__main__":
    main()
