import re
import sys
import json
import argparse
import urllib.parse
import requests


PACKER_RE = re.compile(
    r"\}\s*\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:[^'\\]|\\.)*)'\.split\('\|'\)",
    re.S,
)

LINKS_RE = re.compile(
    r'(?:var\s+)?(?:links|sources)\s*=\s*(\{[^{}]*"hls[234]"\s*:[^{}]*\})',
    re.S,
)

KV_RE = re.compile(r'"(hls[234])"\s*:\s*"([^"]+)"')

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _decode_base(word, base):
    n = 0
    for ch in word:
        if ch.isdigit():
            d = int(ch)
        elif ch.islower():
            d = ord(ch) - ord('a') + 10
        elif ch.isupper():
            d = ord(ch) - ord('A') + 36
        else:
            return None
        if d >= base:
            return None
        n = n * base + d
    return n


def unpack(payload):
    m = PACKER_RE.search(payload)
    if not m:
        return payload
    p, a, c, k = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4).split('|')
    p = p.encode().decode('unicode_escape')

    def repl(match):
        word = match.group(0)
        idx = _decode_base(word, a)
        if idx is not None and 0 <= idx < len(k) and k[idx]:
            return k[idx]
        return word

    return re.sub(r"\b\w+\b", repl, p)


def extract_links(html):
    unpacked = unpack(html)
    block = LINKS_RE.search(unpacked)
    if not block:
        return {}
    return dict(KV_RE.findall(block.group(1)))


def resolve_master_txt(url, referer, session):
    r = session.get(url, headers={**DEFAULT_HEADERS, "Referer": referer}, allow_redirects=True, timeout=20)
    final = r.url
    body = (r.text or "").strip()
    if final.endswith(".m3u8") or "m3u8" in final:
        return final
    if body.startswith("http") and ".m3u8" in body.split()[0]:
        return body.split()[0]
    if body.startswith("#EXTM3U"):
        return final
    return None


def resolve(embed_url, session=None):
    session = session or requests.Session()
    parsed = urllib.parse.urlparse(embed_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    r = session.get(embed_url, headers=DEFAULT_HEADERS, timeout=20)
    r.raise_for_status()
    links = extract_links(r.text)
    if not links:
        return {"embed": embed_url, "links": {}, "m3u8": None}

    m3u8 = links.get("hls2")
    if not m3u8:
        for k in ("hls4", "hls3"):
            if k in links:
                resolved = resolve_master_txt(links[k], origin + "/", session)
                if resolved:
                    m3u8 = resolved
                    break

    return {"embed": embed_url, "links": links, "m3u8": m3u8}


def main():
    ap = argparse.ArgumentParser(description="Resolve final m3u8 from VidHide-style embed page")
    ap.add_argument("url", help="Embed URL e.g. https://callistanise.com/v/<code>")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    result = resolve(args.url)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["m3u8"]:
            print(result["m3u8"])
        else:
            print("FAILED to resolve. Found links:", result["links"], file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
