import re
import sys
import json
import requests

DEFAULT_URL = "https://bigshare.io/watch/e/83370"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"

HEADERS = {
    "user-agent": UA,
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "accept-encoding": "gzip, deflate, br",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "dnt": "1",
}

URL_RE = re.compile(r"url:\s*['\"](https?://[^'\"]+\.(?:mp4|mkv|m3u8|mpd|webm)[^'\"]*)['\"]", re.I)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
CSRF_RE = re.compile(r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', re.I)


def fetch_html(url: str) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30, allow_redirects=True)
        if r.status_code == 200 and "artplayer" in r.text.lower():
            return r.text
    except Exception:
        pass

    try:
        import cloudscraper
        s = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
        r = s.get(url, headers=HEADERS, timeout=45)
        r.raise_for_status()
        return r.text
    except ImportError:
        pass
    except Exception:
        pass

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(f"--user-agent={UA}")
    drv = webdriver.Chrome(options=opts)
    try:
        drv.get(url)
        WebDriverWait(drv, 30).until(lambda d: "artplayer" in d.page_source.lower())
        return drv.page_source
    finally:
        drv.quit()


def extract(url: str = DEFAULT_URL) -> dict:
    html = fetch_html(url)
    matches = list(dict.fromkeys(URL_RE.findall(html)))
    title = TITLE_RE.search(html)
    csrf = CSRF_RE.search(html)
    return {
        "page_url": url,
        "title": title.group(1).strip() if title else None,
        "csrf": csrf.group(1) if csrf else None,
        "stream_urls": matches,
        "primary": matches[0] if matches else None,
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    result = extract(target)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result["primary"]:
        sys.exit(1)
