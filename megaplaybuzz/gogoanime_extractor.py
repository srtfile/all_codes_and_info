"""
GogoAnime M3U8 Extractor
========================
Uses seleniumwire as a transparent proxy so ALL network requests
(including cross-origin iframes like megaplay.buzz) are captured.

Flow:
  gogoanime.me.uk/newplayer.php?id=21?ep=1
      └─ iframe: megaplay.buzz/stream/s-2/1/sub?autostart=true
              └─ XHR/fetch → *.json  (contains the m3u8 URL)
              └─ HLS request → *.m3u8

Usage:
    python gogoanime_extractor.py
    python gogoanime_extractor.py --url "https://gogoanime.me.uk/newplayer.php?id=21?ep=1"
    python gogoanime_extractor.py --visible        # show browser window
    python gogoanime_extractor.py --wait 40        # wait longer for slow streams
    python gogoanime_extractor.py --debug          # print ALL captured URLs

Requirements:
    pip install selenium-wire
    Google Chrome must be installed.
"""

import re
import json
import time
import argparse

from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_URL  = "https://gogoanime.me.uk/newplayer.php?id=21?ep=1"
DEFAULT_WAIT = 25   # seconds to wait after page load

M3U8_RE = re.compile(r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*', re.IGNORECASE)

# ── Chrome builder ────────────────────────────────────────────────────────────

def build_driver(headless: bool = True) -> webdriver.Chrome:
    opts = Options()

    if headless:
        opts.add_argument("--headless=new")

    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,800")
    opts.add_argument("--autoplay-policy=no-user-gesture-required")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    # seleniumwire options — intercept everything, ignore cert errors
    sw_options = {
        "verify_ssl": False,
        "suppress_connection_errors": True,
    }

    driver = webdriver.Chrome(
        options=opts,
        seleniumwire_options=sw_options,
    )

    # Remove navigator.webdriver fingerprint
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"}
    )

    return driver

# ── Request harvester ─────────────────────────────────────────────────────────

def is_real_m3u8_url(url: str) -> bool:
    """
    Return True only if the URL itself is an m3u8 stream request,
    not a tracker/analytics URL that merely references m3u8 in a query param.
    """
    from urllib.parse import urlparse, parse_qs
    parsed = urlparse(url)
    # The path must end with .m3u8 (real stream request)
    if parsed.path.lower().endswith(".m3u8"):
        return True
    # Reject analytics pings (jwpltx, jwpsrv, ping.gif, etc.)
    skip_hosts = ("jwpltx.com", "jwpsrv.com", "prd.jwpltx", "statlytic", "plausible.io")
    if any(s in parsed.netloc for s in skip_hosts):
        return False
    return False


def harvest_requests(driver: webdriver.Chrome, debug: bool = False) -> tuple[list[str], list[str]]:
    """
    Walk all proxied requests and return:
      (m3u8_urls, all_urls)
    """
    m3u8_urls = []
    all_urls   = []

    for req in driver.requests:
        url = req.url
        if not url or url.startswith("data:"):
            continue
        all_urls.append(url)

        if ".m3u8" in url.lower() and is_real_m3u8_url(url):
            m3u8_urls.append(url)
            continue

        # Also check response body for embedded m3u8 references
        # (e.g. a .json response that contains the stream URL)
        if req.response and req.response.body:
            try:
                body = req.response.body.decode("utf-8", errors="ignore")
                for m in M3U8_RE.finditer(body):
                    found = m.group(0)
                    if found.startswith("http") and is_real_m3u8_url(found) and found not in m3u8_urls:
                        m3u8_urls.append(found)
                        print(f"    ✓ Found m3u8 inside response of: {url}")
            except Exception:
                pass

    return list(set(m3u8_urls)), all_urls

# ── JS deep scan (fallback) ───────────────────────────────────────────────────

JS_SCAN = """
(function() {
    var r = [];
    document.querySelectorAll('video,source').forEach(function(el){
        if(el.src && el.src.includes('.m3u8')) r.push(el.src);
        if(el.currentSrc && el.currentSrc.includes('.m3u8')) r.push(el.currentSrc);
    });
    try{ if(window.jwplayer){
        var p=window.jwplayer(), item=p&&p.getPlaylistItem&&p.getPlaylistItem();
        if(item){
            if(item.file&&item.file.includes('.m3u8')) r.push(item.file);
            (item.sources||[]).forEach(function(s){if(s.file&&s.file.includes('.m3u8'))r.push(s.file);});
        }
    }}catch(e){}
    try{ if(window.hls&&window.hls.url) r.push(window.hls.url); }catch(e){}
    try{ Object.keys(window).forEach(function(k){
        try{ var v=window[k]; if(typeof v==='string'&&v.startsWith('http')&&v.includes('.m3u8')) r.push(v); }catch(e){}
    });}catch(e){}
    return [...new Set(r)];
})();
"""

def js_scan_all_frames(driver: webdriver.Chrome) -> list[str]:
    found = set()
    try:
        res = driver.execute_script(JS_SCAN)
        if res: found.update(res)
    except Exception:
        pass
    for i in range(len(driver.find_elements(By.TAG_NAME, "iframe"))):
        try:
            driver.switch_to.frame(i)
            res = driver.execute_script(JS_SCAN)
            if res: found.update(res)
            driver.switch_to.default_content()
        except Exception:
            driver.switch_to.default_content()
    return [u for u in found if u.startswith("http") and ".m3u8" in u.lower()]

# ── Core extractor ────────────────────────────────────────────────────────────

def extract(url: str, headless: bool = True, wait: int = DEFAULT_WAIT, debug: bool = False) -> dict:
    print(f"\n{'='*65}")
    print(f"  Target  : {url}")
    print(f"  Mode    : {'headless' if headless else 'visible'}")
    print(f"  Wait    : {wait}s")
    print(f"{'='*65}\n")

    driver = build_driver(headless=headless)
    result = {"url": url, "m3u8_urls": [], "all_requests": [], "method": None}

    try:
        print("[1] Loading page ...")
        driver.get(url)

        # Poll every second — stop early if we find something
        print(f"[2] Intercepting network traffic for up to {wait}s ...")
        m3u8_urls = []
        for elapsed in range(1, wait + 1):
            time.sleep(1)
            m3u8_urls, all_urls = harvest_requests(driver, debug)
            if m3u8_urls:
                print(f"    ✓ Captured via proxy after {elapsed}s")
                result["method"] = "seleniumwire_proxy"
                break
            if elapsed % 5 == 0:
                print(f"    ... {elapsed}s — requests so far: {len(all_urls)}")

        # Final harvest after full wait
        m3u8_urls, all_urls = harvest_requests(driver, debug)
        result["all_requests"] = all_urls

        if not m3u8_urls:
            print("[3] Proxy empty — trying JS deep scan ...")
            m3u8_urls = js_scan_all_frames(driver)
            if m3u8_urls:
                result["method"] = "js_deep_scan"
                print("    ✓ Found via JS scan")

        result["m3u8_urls"] = list(set(m3u8_urls))

    finally:
        driver.quit()

    return result

# ── Output ────────────────────────────────────────────────────────────────────

def print_result(result: dict, debug: bool = False):
    print(f"\n{'='*65}")
    print("  RESULT")
    print(f"{'='*65}")

    if result["m3u8_urls"]:
        print(f"\n  ✅  {len(result['m3u8_urls'])} m3u8 URL(s) found  [{result['method']}]\n")
        for u in result["m3u8_urls"]:
            print(f"      {u}")
    else:
        print("\n  ⚠️   No m3u8 URLs found.\n")

    if debug:
        print(f"\n  All {len(result['all_requests'])} captured requests:\n")
        for u in result["all_requests"]:
            print(f"      {u}")

    print()

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract m3u8 stream URLs from gogoanime.me.uk player pages"
    )
    parser.add_argument("--url",     default=DEFAULT_URL,  help="Player page URL")
    parser.add_argument("--visible", action="store_true",  help="Show browser window")
    parser.add_argument("--wait",    type=int, default=DEFAULT_WAIT, help="Seconds to wait (default 25)")
    parser.add_argument("--output",  default="results.json", help="JSON output file")
    parser.add_argument("--debug",   action="store_true",  help="Print all captured URLs")
    args = parser.parse_args()

    result = extract(args.url, headless=not args.visible, wait=args.wait, debug=args.debug)
    print_result(result, debug=args.debug)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  💾 Saved to: {args.output}\n")
