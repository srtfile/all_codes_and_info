"""
Advanced M3U8 / HLS Stream Capture Tool
========================================
Priority: Capture m3u8 URLs first, then full analysis.

Flow:
  1. Open target URL in Firefox (headless)
  2. Inject JS interceptor to hook XHR / Fetch / WebSocket
  3. Enable Firefox DevTools network log via CDP
  4. Wait for page + iframes to load and fire requests
  5. Collect ALL network requests, filter m3u8 hits
  6. Parse each m3u8 (master → variants → segments)
  7. Print full report

Usage:
  pip install selenium m3u8 requests
  python network_analyzer_demo.py
  python network_analyzer_demo.py --url "https://vaplayer.ru/embed/movie/tt2948356  " --wait 8
"""

import re
import sys
import json
import time
import argparse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

# ── selenium ──────────────────────────────────────────────────────────────────
try:
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import WebDriverException
    SELENIUM_OK = True
except ImportError:
    SELENIUM_OK = False
    print("[!] pip install selenium")

# ── m3u8 parser ───────────────────────────────────────────────────────────────
try:
    import m3u8 as m3u8lib
    M3U8_OK = True
except ImportError:
    M3U8_OK = False
    print("[!] pip install m3u8")

# ── requests ──────────────────────────────────────────────────────────────────
try:
    import requests as req_lib
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False
    print("[!] pip install requests")


# ─────────────────────────────────────────────────────────────────────────────
# JS injected into every frame to intercept ALL outgoing requests
# ─────────────────────────────────────────────────────────────────────────────
INTERCEPT_JS = """
(function() {
    if (window.__kiroIntercepted__) return;
    window.__kiroIntercepted__ = true;
    window.__kiroRequests__    = window.__kiroRequests__ || [];

    function record(obj) {
        window.__kiroRequests__.push(obj);
    }

    // ── Fetch API ────────────────────────────────────────────────────────────
    const _fetch = window.fetch;
    window.fetch = function(...args) {
        try {
            const url = (typeof args[0] === 'string') ? args[0]
                      : (args[0] && args[0].url) ? args[0].url : String(args[0]);
            const opts = args[1] || {};
            const hdrs = opts.headers || {};
            // flatten Headers object or plain object
            let hdrObj = {};
            try {
                if (hdrs instanceof Headers) {
                    hdrs.forEach(function(v,k){ hdrObj[k]=v; });
                } else {
                    hdrObj = Object.assign({}, hdrs);
                }
            } catch(e) {}
            record({
                type:    'fetch',
                url:     url,
                method:  opts.method || 'GET',
                headers: hdrObj,
                origin:  window.location.origin,
                referer: window.location.href,
            });
        } catch(e) {}
        return _fetch.apply(this, args);
    };

    // ── XMLHttpRequest ───────────────────────────────────────────────────────
    const _xhrOpen  = XMLHttpRequest.prototype.open;
    const _xhrSend  = XMLHttpRequest.prototype.send;
    const _xhrSetHdr = XMLHttpRequest.prototype.setRequestHeader;

    XMLHttpRequest.prototype.open = function(method, url) {
        try {
            this.__kiroMeta__ = { method: String(method), url: String(url), headers: {} };
            record({
                type:    'xhr',
                url:     String(url),
                method:  String(method),
                origin:  window.location.origin,
                referer: window.location.href,
                headers: {},
            });
        } catch(e) {}
        return _xhrOpen.apply(this, arguments);
    };

    XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        try {
            if (this.__kiroMeta__) this.__kiroMeta__.headers[name] = value;
        } catch(e) {}
        return _xhrSetHdr.apply(this, arguments);
    };

    // ── WebSocket ────────────────────────────────────────────────────────────
    const _WS = window.WebSocket;
    window.WebSocket = function(url, proto) {
        try {
            record({
                type:    'websocket',
                url:     String(url),
                method:  'WS',
                origin:  window.location.origin,
                referer: window.location.href,
                headers: {},
            });
        } catch(e) {}
        return proto ? new _WS(url, proto) : new _WS(url);
    };
    Object.assign(window.WebSocket, _WS);

    // ── Dynamic <script src> / <source src> / <video src> ────────────────────
    const _setAttribute = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function(name, value) {
        try {
            if ((name === 'src' || name === 'href') && typeof value === 'string') {
                const tag = this.tagName ? this.tagName.toLowerCase() : '';
                if (['script','source','video','audio','iframe'].includes(tag)) {
                    record({ type: 'attr-' + tag, url: value, method: 'GET' });
                }
            }
        } catch(e) {}
        return _setAttribute.apply(this, arguments);
    };

    // ── HLS.js / Video.js / JWPlayer source hooks ────────────────────────────
    // Poll for common player globals and grab their source
    function pollPlayers() {
        try {
            // HLS.js
            if (window.Hls && window.Hls.instances) {
                window.Hls.instances.forEach(function(h) {
                    if (h.url) record({ type: 'hlsjs', url: h.url, method: 'GET',
                        origin: window.location.origin, referer: window.location.href, headers: {} });
                });
            }
            // JWPlayer
            if (window.jwplayer) {
                try {
                    var jw = window.jwplayer();
                    if (jw && jw.getPlaylistItem) {
                        var item = jw.getPlaylistItem();
                        if (item && item.file) record({ type: 'jwplayer', url: item.file, method: 'GET',
                            origin: window.location.origin, referer: window.location.href, headers: {} });
                    }
                } catch(e) {}
            }
            // Video.js
            if (window.videojs && window.videojs.players) {
                Object.values(window.videojs.players).forEach(function(p) {
                    try {
                        var src = p.currentSrc ? p.currentSrc() : null;
                        if (src) record({ type: 'videojs', url: src, method: 'GET',
                            origin: window.location.origin, referer: window.location.href, headers: {} });
                    } catch(e) {}
                });
            }
            // Clappr
            if (window.Clappr && window.Clappr.Player) {
                try {
                    var cp = window.Clappr.Player._players;
                    if (cp) cp.forEach(function(p){
                        var src = p.options && p.options.source;
                        if (src) record({ type: 'clappr', url: src, method: 'GET',
                            origin: window.location.origin, referer: window.location.href, headers: {} });
                    });
                } catch(e) {}
            }
            // Plyr
            if (window.Plyr) {
                try {
                    document.querySelectorAll('video').forEach(function(v){
                        if (v.src && v.src.includes('.m3u8'))
                            record({ type: 'plyr-video', url: v.src, method: 'GET',
                                origin: window.location.origin, referer: window.location.href, headers: {} });
                    });
                } catch(e) {}
            }
            // MediaSource — catches appendBuffer calls (DASH/HLS segment URLs)
            if (window.__kiroMSE__) {
                window.__kiroMSE__.forEach(function(u){
                    record({ type: 'mse-segment', url: u, method: 'GET',
                        origin: window.location.origin, referer: window.location.href, headers: {} });
                });
                window.__kiroMSE__ = [];
            }
        } catch(e) {}
    }
    setInterval(pollPlayers, 500);

    // ── MediaSource URL hook ─────────────────────────────────────────────────
    window.__kiroMSE__ = [];
    const _createObjectURL = URL.createObjectURL;
    URL.createObjectURL = function(obj) {
        try {
            if (obj instanceof MediaSource) {
                // watch for source open to grab segment URLs via SourceBuffer
                obj.addEventListener('sourceopen', function() {
                    const _addSB = obj.addSourceBuffer.bind(obj);
                    obj.addSourceBuffer = function(mime) {
                        var sb = _addSB(mime);
                        var _ab = sb.appendBuffer.bind(sb);
                        sb.appendBuffer = function(data) {
                            // data is ArrayBuffer — we can't get URL here,
                            // but we can note the mime type
                            window.__kiroMSE__.push('mse://' + mime);
                            return _ab(data);
                        };
                        return sb;
                    };
                });
            }
        } catch(e) {}
        return _createObjectURL.apply(this, arguments);
    };

})();
"""


# ─────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class CapturedRequest:
    url: str
    method: str = "GET"
    req_type: str = ""
    is_m3u8: bool = False
    is_api: bool = False
    origin: str = ""
    referer: str = ""
    headers: dict = field(default_factory=dict)

@dataclass
class Report:
    target_url: str
    page_title: str = ""
    iframes: list = field(default_factory=list)
    scripts: list = field(default_factory=list)
    api_endpoints: list = field(default_factory=list)
    m3u8_urls: list = field(default_factory=list)          # ← PRIMARY OUTPUT
    m3u8_headers: dict = field(default_factory=dict)       # url → {Origin, Referer, …}
    all_requests: list = field(default_factory=list)
    js_globals: dict = field(default_factory=dict)
    m3u8_parsed: list = field(default_factory=list)
    errors: list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 – HTTP pre-scan (fast, no browser)
# ─────────────────────────────────────────────────────────────────────────────
def http_prescan(url: str, report: Report):
    if not REQUESTS_OK:
        return
    print(f"  [http] GET {url}")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        r = req_lib.get(url, headers=headers, timeout=15, allow_redirects=True)
        body = r.text

        # m3u8 anywhere in HTML/JS
        for m in re.findall(r'https?://[^\s\'"<>\\]+\.m3u8[^\s\'"<>\\]*', body):
            _add_m3u8(m, report)

        # relative m3u8
        for m in re.findall(r'["\']([^"\']+\.m3u8[^"\']*)["\']', body):
            if m.startswith("/"):
                from urllib.parse import urljoin
                m = urljoin(url, m)
            if m.startswith("http"):
                _add_m3u8(m, report)

        # API endpoints
        for m in re.findall(r'https?://[^\s\'"<>]+/api/[^\s\'"<>]*', body):
            if m not in report.api_endpoints:
                report.api_endpoints.append(m)

        # script srcs
        for m in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', body, re.I):
            if m not in report.scripts:
                report.scripts.append(m)

        # iframe srcs
        for m in re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', body, re.I):
            entry = {"src": m}
            if entry not in report.iframes:
                report.iframes.append(entry)

    except Exception as e:
        report.errors.append(f"http_prescan: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 – Browser capture
# ─────────────────────────────────────────────────────────────────────────────
def build_driver(headless: bool = True) -> "webdriver.Firefox":
    opts = FirefoxOptions()
    if headless:
        opts.add_argument("--headless")
    opts.set_preference("media.autoplay.default", 0)          # allow autoplay
    opts.set_preference("media.autoplay.blocking_policy", 0)
    opts.set_preference("privacy.trackingprotection.enabled", False)
    driver = webdriver.Firefox(options=opts)
    driver.set_page_load_timeout(30)
    return driver


def inject(driver, context="main"):
    """Inject interceptor into current frame."""
    try:
        driver.execute_script(INTERCEPT_JS)
    except Exception as e:
        pass  # frame may have navigated away


def inject_all_frames(driver):
    """Inject into main page + every iframe."""
    inject(driver, "main")
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for i, frame in enumerate(iframes):
        try:
            driver.switch_to.frame(frame)
            inject(driver, f"iframe[{i}]")
            driver.switch_to.default_content()
        except Exception:
            driver.switch_to.default_content()


def collect_requests(driver) -> list[CapturedRequest]:
    """Pull __kiroRequests__ from main page + all iframes."""
    results = []

    def pull(label="main"):
        try:
            raw = driver.execute_script("return window.__kiroRequests__ || []")
            for r in raw:
                url = r.get("url", "")
                if not url or url == "undefined":
                    continue
                cr = CapturedRequest(
                    url=url,
                    method=r.get("method", "GET"),
                    req_type=r.get("type", ""),
                    is_m3u8=".m3u8" in url.lower(),
                    is_api=bool(re.search(r'/api/|\.json(\?|$)', url)),
                    origin=r.get("origin", ""),
                    referer=r.get("referer", ""),
                    headers=r.get("headers", {}),
                )
                results.append(cr)
        except Exception:
            pass

    pull("main")
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for i, frame in enumerate(iframes):
        try:
            driver.switch_to.frame(frame)
            pull(f"iframe[{i}]")
            driver.switch_to.default_content()
        except Exception:
            driver.switch_to.default_content()

    return results


def extract_dom(driver, report: Report):
    """Scrape DOM for iframes, scripts, JS globals, inline m3u8."""
    try:
        report.page_title = driver.title
    except Exception:
        pass

    # iframes
    for el in driver.find_elements(By.TAG_NAME, "iframe"):
        src = el.get_attribute("src") or ""
        fid = el.get_attribute("id") or ""
        entry = {"id": fid, "src": src}
        if entry not in report.iframes:
            report.iframes.append(entry)

    # scripts
    for el in driver.find_elements(By.TAG_NAME, "script"):
        src = el.get_attribute("src") or ""
        if src and src not in report.scripts:
            report.scripts.append(src)

    # inline m3u8 in page source
    try:
        src = driver.page_source
        page_origin = driver.execute_script("return window.location.origin") or ""
        page_href   = driver.execute_script("return window.location.href")   or ""
        for m in re.findall(r'https?://[^\s\'"<>\\]+\.m3u8[^\s\'"<>\\]*', src):
            _add_m3u8(m, report, origin=page_origin, referer=page_href)
    except Exception:
        pass

    # JS globals
    globals_to_check = [
        "__PLAYER_CONFIG__", "__STREAM__", "__NEXT_DATA__", "__NUXT__",
        "playerConfig", "videoConfig", "streamConfig", "playerSettings",
        "jwplayer", "Hls", "videojs", "flowplayer",
    ]
    try:
        page_origin = driver.execute_script("return window.location.origin") or ""
        page_href   = driver.execute_script("return window.location.href")   or ""
    except Exception:
        page_origin = ""
        page_href   = ""
    for var in globals_to_check:
        try:
            val = driver.execute_script(
                f"try {{ return JSON.stringify(window['{var}']) || null }} catch(e) {{ return null }}"
            )
            if val and val != "null":
                parsed = json.loads(val)
                report.js_globals[var] = parsed
                # look for m3u8 inside the object
                text = json.dumps(parsed)
                for m in re.findall(r'https?://[^\s\'"<>\\]+\.m3u8[^\s\'"<>\\]*', text):
                    _add_m3u8(m, report, origin=page_origin, referer=page_href)
        except Exception:
            pass

    # <video> / <source> tags
    for tag in ["video", "source"]:
        for el in driver.find_elements(By.TAG_NAME, tag):
            src = el.get_attribute("src") or ""
            if ".m3u8" in src.lower():
                _add_m3u8(src, report)


def browser_capture(url: str, report: Report, headless: bool, wait_sec: int):
    if not SELENIUM_OK:
        print("  [skip] selenium not available")
        return

    print(f"  [browser] launching Firefox (headless={headless}) …")
    driver = None
    try:
        driver = build_driver(headless)

        # ── Load main page ────────────────────────────────────────────────────
        print(f"  [browser] loading {url} …")
        driver.get(url)
        time.sleep(1)
        inject_all_frames(driver)

        # ── Wait for dynamic content ──────────────────────────────────────────
        print(f"  [browser] waiting {wait_sec}s for streams to load …")
        deadline = time.time() + wait_sec
        while time.time() < deadline:
            time.sleep(1)
            inject_all_frames(driver)   # re-inject in case of lazy iframes
            # Early exit if we already found m3u8
            reqs = collect_requests(driver)
            found = [r for r in reqs if r.is_m3u8]
            if found:
                print(f"  [browser] ✓ m3u8 detected early — stopping wait")
                break

        # ── Final collection ──────────────────────────────────────────────────
        reqs = collect_requests(driver)
        report.all_requests.extend(reqs)
        for cr in reqs:
            if cr.is_m3u8:
                _add_m3u8(cr.url, report, cr.origin, cr.referer, cr.headers)
            if cr.is_api and cr.url not in report.api_endpoints:
                report.api_endpoints.append(cr.url)

        extract_dom(driver, report)

        # ── Visit each iframe URL directly ────────────────────────────────────
        iframe_srcs = [
            fr["src"] for fr in report.iframes
            if fr.get("src", "").startswith("http")
        ]
        for isrc in iframe_srcs:
            print(f"  [browser] visiting iframe: {isrc}")
            try:
                driver.get(isrc)
                time.sleep(1)
                inject_all_frames(driver)
                time.sleep(min(wait_sec, 5))
                inject_all_frames(driver)

                reqs2 = collect_requests(driver)
                for cr in reqs2:
                    if cr.is_m3u8:
                        _add_m3u8(cr.url, report, cr.origin, cr.referer, cr.headers)
                    if cr.is_api and cr.url not in report.api_endpoints:
                        report.api_endpoints.append(cr.url)
                extract_dom(driver, report)
            except Exception as e:
                report.errors.append(f"iframe visit {isrc}: {e}")

    except WebDriverException as e:
        report.errors.append(f"WebDriver: {e}")
        print(f"  [error] {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Step 3 – Parse every m3u8 found
# ─────────────────────────────────────────────────────────────────────────────
def parse_m3u8(url: str, extra_headers: dict = None) -> dict:
    result = {
        "url": url,
        "is_master": False,
        "variants": [],
        "segments": [],
        "duration_sec": 0.0,
        "error": None,
    }
    try:
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
        }
        if extra_headers:
            hdrs.update(extra_headers)
        r = urllib.request.Request(url, headers=hdrs)
        with urllib.request.urlopen(r, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        if M3U8_OK:
            pl = m3u8lib.loads(raw)
            if pl.is_variant:
                result["is_master"] = True
                for p in pl.playlists:
                    si = p.stream_info
                    result["variants"].append({
                        "uri":        p.uri,
                        "bandwidth":  si.bandwidth if si else None,
                        "resolution": str(si.resolution) if si and si.resolution else "?",
                        "codecs":     si.codecs if si else None,
                    })
            else:
                for seg in pl.segments:
                    result["segments"].append(seg.uri)
                    result["duration_sec"] += seg.duration or 0
        else:
            # fallback regex
            result["variants"] = re.findall(r'[^\s]+\.m3u8', raw)
            result["segments"] = re.findall(r'[^\s]+\.ts', raw)

    except Exception as e:
        result["error"] = str(e)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _add_m3u8(url: str, report: Report, origin: str = "", referer: str = "", headers: dict = None):
    url = url.strip().rstrip("\\\"'")
    if url and url not in report.m3u8_urls:
        report.m3u8_urls.append(url)
        # build the headers needed to replay this request
        hdrs = dict(headers) if headers else {}
        if origin:
            hdrs.setdefault("Origin", origin)
        if referer:
            hdrs.setdefault("Referer", referer)
        if hdrs:
            report.m3u8_headers[url] = hdrs
        print(f"  [★ m3u8] {url}")
        if origin:
            print(f"           Origin  : {origin}")
        if referer:
            print(f"           Referer : {referer}")
        if hdrs:
            for k, v in hdrs.items():
                if k not in ("Origin", "Referer"):
                    print(f"           {k}: {v}")


# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────
def print_report(report: Report):
    W = 65
    print("\n" + "═" * W)
    print("  CAPTURE REPORT")
    print("═" * W)
    print(f"  URL   : {report.target_url}")
    print(f"  Title : {report.page_title}")
    print("─" * W)

    # ── M3U8 — top of report ──────────────────────────────────────────────────
    print(f"\n{'★'*W}")
    print(f"  M3U8 / HLS STREAMS FOUND : {len(report.m3u8_urls)}")
    print(f"{'★'*W}")
    if report.m3u8_urls:
        for i, u in enumerate(report.m3u8_urls, 1):
            print(f"  [{i}] {u}")
            hdrs = report.m3u8_headers.get(u, {})
            if hdrs:
                for k, v in hdrs.items():
                    print(f"       {k}: {v}")
    else:
        print("  (none found)")

    # ── Parsed playlists ──────────────────────────────────────────────────────
    if report.m3u8_parsed:
        print(f"\n{'─'*W}")
        print("  PLAYLIST DETAILS")
        print(f"{'─'*W}")
        for p in report.m3u8_parsed:
            print(f"\n  URL : {p['url']}")
            if p.get("error"):
                print(f"  Error: {p['error']}")
                continue
            if p["is_master"]:
                print(f"  Type: MASTER  ({len(p['variants'])} quality levels)")
                for v in p["variants"]:
                    print(f"    • {v['resolution']:>10}  {str(v['bandwidth']):>10} bps  → {v['uri']}")
            else:
                print(f"  Type    : MEDIA")
                print(f"  Segments: {len(p['segments'])}")
                print(f"  Duration: {p['duration_sec']:.1f}s")
                if p["segments"]:
                    print(f"  First   : {p['segments'][0]}")

    # ── iframes ───────────────────────────────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  IFRAMES ({len(report.iframes)})")
    for fr in report.iframes:
        print(f"  • [{fr.get('id','')}] {fr.get('src','')}")

    # ── API endpoints ─────────────────────────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  API ENDPOINTS ({len(report.api_endpoints)})")
    for ep in report.api_endpoints:
        print(f"  • {ep}")

    # ── JS globals ────────────────────────────────────────────────────────────
    if report.js_globals:
        print(f"\n{'─'*W}")
        print("  JS GLOBALS")
        for k, v in report.js_globals.items():
            print(f"  {k}: {json.dumps(v, indent=4)}")

    # ── All network requests ──────────────────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  ALL INTERCEPTED REQUESTS ({len(report.all_requests)})")
    for cr in report.all_requests:
        tag = "[m3u8]" if cr.is_m3u8 else "[api] " if cr.is_api else "[    ]"
        print(f"  {tag} {cr.req_type:<14} {cr.method:<6} {cr.url}")
        if cr.origin:
            print(f"         Origin  : {cr.origin}")
        if cr.referer:
            print(f"         Referer : {cr.referer}")
        for k, v in (cr.headers or {}).items():
            print(f"         {k}: {v}")

    # ── Scripts ───────────────────────────────────────────────────────────────
    print(f"\n{'─'*W}")
    print(f"  SCRIPTS ({len(report.scripts)})")
    for s in report.scripts[:20]:
        print(f"  • {s}")
    if len(report.scripts) > 20:
        print(f"  … +{len(report.scripts)-20} more")

    # ── Errors ────────────────────────────────────────────────────────────────
    if report.errors:
        print(f"\n{'─'*W}")
        print("  ERRORS")
        for e in report.errors:
            print(f"  ⚠ {e}")

    print("\n" + "═" * W)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def run(target_url: str, headless: bool = True, wait_sec: int = 8):
    report = Report(target_url=target_url)

    print(f"\n{'='*65}")
    print(f"  TARGET: {target_url}")
    print(f"{'='*65}\n")

    # ── Phase 1: HTTP pre-scan ────────────────────────────────────────────────
    print("[Phase 1] HTTP pre-scan (no browser) …")
    http_prescan(target_url, report)
    print(f"  → m3u8 so far: {len(report.m3u8_urls)}")

    # ── Phase 2: Browser capture ──────────────────────────────────────────────
    print("\n[Phase 2] Browser capture …")
    browser_capture(target_url, report, headless=headless, wait_sec=wait_sec)
    print(f"  → m3u8 so far: {len(report.m3u8_urls)}")

    # ── Phase 3: Parse each m3u8 ─────────────────────────────────────────────
    if report.m3u8_urls:
        print(f"\n[Phase 3] Parsing {len(report.m3u8_urls)} m3u8 playlist(s) …")
        for url in report.m3u8_urls:
            print(f"  parsing: {url}")
            extra = report.m3u8_headers.get(url)
            parsed = parse_m3u8(url, extra_headers=extra)
            report.m3u8_parsed.append(parsed)
    else:
        print("\n[Phase 3] No m3u8 URLs found — skipping parse.")

    # ── Final report ──────────────────────────────────────────────────────────
    print_report(report)
    return report


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="M3U8 / HLS stream capture tool")
    parser.add_argument(
        "--url", default="https://vaplayer.ru/embed/movie/tt2948356",
        help="Target URL to analyze"
    )
    parser.add_argument(
        "--wait", type=int, default=8,
        help="Seconds to wait for dynamic content (default: 8)"
    )
    parser.add_argument(
        "--show-browser", action="store_true",
        help="Show Firefox window (non-headless)"
    )
    args = parser.parse_args()

    run(
        target_url=args.url,
        headless=not args.show_browser,
        wait_sec=args.wait,
    )
