import re
import sys
import json
import requests

DEFAULT_URL = "https://vids.st/e/40263"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")

CDN_TEMPLATE = "https://cdn.vids.st/video{id}/master.m3u8"
POSTER_TEMPLATE = "https://cdn.vids.st/video{id}/thumb{id}.jpg"

ID_RE = re.compile(r"/e/(\d+)")
URL_RE = re.compile(r'const\s+url\s*=\s*"([^"]+\.m3u8[^"]*)"')
TITLE_RE = re.compile(r'<meta\s+property="og:title"\s+content="([^"]+)"', re.I)
POSTER_RE = re.compile(r'const\s+poster\s*=\s*"([^"]+)"')


def _verify(stream_url, referer="https://vids.st/"):
    h = {"User-Agent": UA, "Referer": referer, "Accept": "*/*"}
    r = requests.get(stream_url, headers=h, timeout=15, stream=True)
    ok = r.status_code == 200 and b"#EXTM3U" in r.raw.read(64)
    r.close()
    return ok


def _from_id(vid):
    return {
        "id": vid,
        "stream": CDN_TEMPLATE.format(id=vid),
        "poster": POSTER_TEMPLATE.format(id=vid),
        "title": None,
        "method": "cdn-direct",
    }


def _from_page(url):
    try:
        from curl_cffi import requests as cf
        r = cf.get(url, impersonate="chrome", timeout=20,
                   headers={"Referer": "https://vids.st/"})
    except Exception:
        r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://vids.st/"},
                         timeout=20)
    r.raise_for_status()
    html = r.text.replace("\\/", "/")
    m = URL_RE.search(html)
    if not m:
        return None
    title = TITLE_RE.search(html)
    poster = POSTER_RE.search(html)
    vid_m = ID_RE.search(url)
    return {
        "id": vid_m.group(1) if vid_m else None,
        "stream": m.group(1),
        "poster": poster.group(1) if poster else None,
        "title": title.group(1) if title else None,
        "method": "page-scrape",
    }


def extract(url=DEFAULT_URL):
    m = ID_RE.search(url)
    if m:
        info = _from_id(m.group(1))
        try:
            if _verify(info["stream"]):
                return info
        except Exception:
            pass
    return _from_page(url)


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    data = extract(url)
    if not data or not data.get("stream"):
        print("No stream URL found.")
        sys.exit(1)
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
