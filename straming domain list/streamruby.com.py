import re
import sys
import argparse

from curl_cffi import requests

DEFAULT_URL = "https://streamruby.com/embed-2lsz9uozaoaa.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://streamruby.com/",
}


def unpack_p_a_c_k(packed_js):
    m = re.search(
        r"eval\(function\(p,a,c,k,e,d\)\{[^}]+\}\('(.*?)',(\d+),(\d+),'(.*?)'\.split\('\|'\)\)\)",
        packed_js, re.DOTALL
    )
    if not m:
        return packed_js
    body, base, count, kw_raw = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    keywords = kw_raw.split('|')

    def replacer(match):
        idx = int(match.group(0), base)
        return keywords[idx] if idx < len(keywords) and keywords[idx] else match.group(0)

    return re.sub(r'\b\w+\b', replacer, body)


def get_streams(url=DEFAULT_URL):
    print(f"[*] Fetching: {url}")
    r = requests.get(url, headers=HEADERS, impersonate="chrome120", timeout=30)
    r.raise_for_status()
    html = r.text

    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    packed_js = next((s for s in scripts if 'eval(function(p,a,c,k' in s), None)

    if not packed_js:
        print("[-] No packed JS found in page")
        return []

    unpacked = unpack_p_a_c_k(packed_js)

    m3u8s = re.findall(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', unpacked)
    return list(dict.fromkeys(m3u8s))


def main():
    parser = argparse.ArgumentParser(description="StreamRuby m3u8 extractor")
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    args = parser.parse_args()

    streams = get_streams(args.url)

    if streams:
        print(f"\n[+] Found {len(streams)} stream(s):\n")
        for i, s in enumerate(streams, 1):
            print(f"  [{i}] {s}")
        master = next((s for s in streams if "master.m3u8" in s), streams[0])
        print(f"\n[BEST] {master}")
        return master
    else:
        print("[-] No streams found.")
        return None


if __name__ == "__main__":
    main()
