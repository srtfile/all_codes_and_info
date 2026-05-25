"""
network_analyser_to-find_api.py
================================
Advanced network intelligence tool.
Goal: Given ANY URL, collect everything needed to later build a
      direct pure-Python API client — without a browser.

What it collects:
  - All HTTP request/response headers (Referer, Origin, Cookies, User-Agent)
  - All XHR / Fetch / WebSocket calls intercepted via JS hooks
  - All external JS files + scans them for API endpoints
  - All iframe URLs (recursive)
  - All API endpoints found in HTML + JS source
  - All m3u8 / stream URLs
  - All JSON responses from API calls
  - All cookies set by the server
  - Full page source

Everything is saved to a timestamped .txt report for offline analysis.

Usage:
  pip install selenium requests
  python network_analyser_to-find_api.py --url "https://example.com"
  python network_analyser_to-find_api.py --url "https://vaplayer.ru/embed/movie/tt2948356" --wait 12
  python network_analyser_to-find_api.py --url "https://example.com" --show-browser --wait 15
"""

import re
import os
import sys
import json
import time
import argparse
import urllib.parse
import urllib.request
from datetime import datetime
from dataclasses import dataclass, field

try:
    import requests as req_lib
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False
    print("[!] pip install requests")
    sys.exit(1)

try:
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import WebDriverException
    SELENIUM_OK = True
except ImportError:
    SELENIUM_OK = False
    print("[!] pip install selenium  (browser capture disabled)")


# ─────────────────────────────────────────────────────────────────────────────
# JS injected into every frame — captures ALL outgoing network activity
# ─────────────────────────────────────────────────────────────────────────────
INTERCEPT_JS = """
(function(){
    if(window.__naIntercepted__) return;
    window.__naIntercepted__ = true;
    window.__naRequests__ = window.__naRequests__ || [];

    function rec(obj){ window.__naRequests__.push(obj); }

    // ── fetch() ──────────────────────────────────────────────────────────────
    const _fetch = window.fetch;
    window.fetch = function(...args){
        try{
            const url = typeof args[0]==='string' ? args[0]
                      : (args[0]&&args[0].url) ? args[0].url : String(args[0]);
            const opts = args[1]||{};
            let hdrs={};
            try{
                if(opts.headers instanceof Headers)
                    opts.headers.forEach((v,k)=>hdrs[k]=v);
                else hdrs=Object.assign({},opts.headers||{});
            }catch(e){}
            rec({type:'fetch', url, method:opts.method||'GET',
                 headers:hdrs, origin:location.origin, referer:location.href,
                 cookies:document.cookie});
        }catch(e){}
        return _fetch.apply(this,args);
    };

    // ── XHR ──────────────────────────────────────────────────────────────────
    const _open = XMLHttpRequest.prototype.open;
    const _setH = XMLHttpRequest.prototype.setRequestHeader;
    const _send = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method,url){
        this.__na__ = {method:String(method), url:String(url), headers:{},
                       origin:location.origin, referer:location.href,
                       cookies:document.cookie};
        rec(Object.assign({type:'xhr'},this.__na__));
        return _open.apply(this,arguments);
    };
    XMLHttpRequest.prototype.setRequestHeader = function(k,v){
        if(this.__na__) this.__na__.headers[k]=v;
        return _setH.apply(this,arguments);
    };
    XMLHttpRequest.prototype.send = function(body){
        if(this.__na__ && body) this.__na__.body = String(body).slice(0,500);
        // capture response
        this.addEventListener('load', function(){
            try{
                var ct = this.getResponseHeader('Content-Type')||'';
                if(ct.includes('json')||ct.includes('text')){
                    window.__naResponses__ = window.__naResponses__||[];
                    window.__naResponses__.push({
                        url: this.__na__ ? this.__na__.url : '',
                        status: this.status,
                        body: this.responseText.slice(0,2000),
                        ct: ct,
                    });
                }
            }catch(e){}
        });
        return _send.apply(this,arguments);
    };

    // ── WebSocket ─────────────────────────────────────────────────────────────
    const _WS = window.WebSocket;
    window.WebSocket = function(url,proto){
        rec({type:'websocket', url:String(url), method:'WS',
             origin:location.origin, referer:location.href, headers:{},
             cookies:document.cookie});
        return proto ? new _WS(url,proto) : new _WS(url);
    };
    Object.assign(window.WebSocket,_WS);

    // ── dynamic src / href attributes ─────────────────────────────────────────
    const _setAttr = Element.prototype.setAttribute;
    Element.prototype.setAttribute = function(name,value){
        try{
            if((name==='src'||name==='href') && typeof value==='string'){
                const tag=(this.tagName||'').toLowerCase();
                if(['script','source','video','audio','iframe','link'].includes(tag))
                    rec({type:'attr-'+tag, url:value, method:'GET',
                         origin:location.origin, referer:location.href,
                         headers:{}, cookies:document.cookie});
            }
        }catch(e){}
        return _setAttr.apply(this,arguments);
    };

    // ── player globals poll ───────────────────────────────────────────────────
    function pollPlayers(){
        try{
            if(window.Hls&&window.Hls.instances)
                window.Hls.instances.forEach(h=>{
                    if(h.url) rec({type:'hlsjs',url:h.url,method:'GET',
                        origin:location.origin,referer:location.href,headers:{},cookies:document.cookie});
                });
            if(window.jwplayer){
                try{
                    var jw=window.jwplayer(),item=jw&&jw.getPlaylistItem&&jw.getPlaylistItem();
                    if(item&&item.file) rec({type:'jwplayer',url:item.file,method:'GET',
                        origin:location.origin,referer:location.href,headers:{},cookies:document.cookie});
                }catch(e){}
            }
            if(window.videojs&&window.videojs.players)
                Object.values(window.videojs.players).forEach(p=>{
                    try{var s=p.currentSrc&&p.currentSrc();
                        if(s) rec({type:'videojs',url:s,method:'GET',
                            origin:location.origin,referer:location.href,headers:{},cookies:document.cookie});
                    }catch(e){}
                });
            // scan all <video> and <source> tags
            document.querySelectorAll('video,source').forEach(el=>{
                var s=el.src||el.currentSrc||'';
                if(s&&s.startsWith('http')) rec({type:'video-tag',url:s,method:'GET',
                    origin:location.origin,referer:location.href,headers:{},cookies:document.cookie});
            });
        }catch(e){}
    }
    setInterval(pollPlayers,500);

    // ── postMessage interception ──────────────────────────────────────────────
    window.__naMessages__ = window.__naMessages__ || [];
    var _origAddEL = window.addEventListener;
    window.addEventListener('message', function(e){
        try{
            window.__naMessages__.push({
                origin: e.origin,
                data: JSON.stringify(e.data).slice(0,500),
            });
        }catch(ex){}
    });

    // ── localStorage / sessionStorage snapshot ────────────────────────────────
    window.__naStorage__ = window.__naStorage__ || {local:{}, session:{}};
    function snapStorage(){
        try{
            for(var i=0;i<localStorage.length;i++){
                var k=localStorage.key(i);
                window.__naStorage__.local[k]=localStorage.getItem(k);
            }
        }catch(e){}
        try{
            for(var i=0;i<sessionStorage.length;i++){
                var k=sessionStorage.key(i);
                window.__naStorage__.session[k]=sessionStorage.getItem(k);
            }
        }catch(e){}
    }
    setInterval(snapStorage, 1000);

})();
"""


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class NetRequest:
    url:     str
    method:  str  = "GET"
    rtype:   str  = ""
    origin:  str  = ""
    referer: str  = ""
    headers: dict = field(default_factory=dict)
    cookies: str  = ""
    body:    str  = ""
    is_api:  bool = False
    is_m3u8: bool = False
    is_js:   bool = False

@dataclass
class Intelligence:
    target_url:    str
    timestamp:     str = ""
    page_title:    str = ""
    # raw HTTP layer
    response_headers: dict = field(default_factory=dict)
    server_cookies:   list = field(default_factory=list)
    redirect_chain:   list = field(default_factory=list)
    # page sources
    http_page_sources:    dict = field(default_factory=dict)
    browser_page_sources: dict = field(default_factory=dict)
    # content
    iframes:       list = field(default_factory=list)
    js_files:      list = field(default_factory=list)
    js_inline:     list = field(default_factory=list)
    # intercepted
    all_requests:  list = field(default_factory=list)
    api_endpoints: list = field(default_factory=list)
    m3u8_urls:     list = field(default_factory=list)
    websockets:    list = field(default_factory=list)
    # NEW — XHR/fetch response bodies
    api_responses: list = field(default_factory=list)   # [{url, status, body}]
    # NEW — tokens / keys found in JS
    tokens_found:  list = field(default_factory=list)   # [{type, value, source}]
    # NEW — GraphQL
    graphql_endpoints: list = field(default_factory=list)
    graphql_queries:   list = field(default_factory=list)
    # NEW — postMessage events
    post_messages: list = field(default_factory=list)   # [{origin, data}]
    # NEW — localStorage / sessionStorage
    local_storage:   dict = field(default_factory=dict)
    session_storage: dict = field(default_factory=dict)
    # NEW — meta tags
    meta_tags:     list = field(default_factory=list)   # [{name, content}]
    # NEW — form actions / POST endpoints
    form_actions:  list = field(default_factory=list)
    # JS analysis
    js_api_hits:   list = field(default_factory=list)
    js_globals:    dict = field(default_factory=dict)
    # cookies / auth
    all_cookies:   dict = field(default_factory=dict)
    user_agent:    str  = ""
    # errors
    errors:        list = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Patterns for API endpoint detection
# ─────────────────────────────────────────────────────────────────────────────
API_PATTERNS = [
    r'https?://[^\s\'"<>]+/api/[^\s\'"<>]*',
    r'https?://[^\s\'"<>]+/v\d+/[^\s\'"<>]*',
    r'["\'](/(?:api|v\d|graphql|rest|stream|source|media|hls|playlist|token|auth|user|search|data)[^\s\'"<>]{2,150})["\']',
    r'fetch\s*\(\s*["\']([^"\']{5,200})["\']',
    r'axios\s*\.\s*(?:get|post|put|delete)\s*\(\s*["\']([^"\']{5,200})["\']',
    r'\$\s*\.\s*(?:get|post|ajax)\s*\(\s*["\']([^"\']{5,200})["\']',
    r'XMLHttpRequest[^;]{0,100}open\s*\(\s*["\'][A-Z]+["\'],\s*["\']([^"\']{5,200})["\']',
    r'(?:url|endpoint|apiUrl|baseUrl|API_URL|BASE_URL)\s*[:=]\s*["\']([^"\']{5,200})["\']',
]

# Patterns to find tokens, keys, secrets in JS/HTML
TOKEN_PATTERNS = [
    (r'Bearer\s+([A-Za-z0-9\-_\.]{20,})',           "Bearer token"),
    (r'["\']Authorization["\']\s*:\s*["\']([^"\']+)["\']', "Authorization header"),
    (r'api[_\-]?key\s*[:=]\s*["\']([A-Za-z0-9\-_]{10,})["\']', "API key"),
    (r'token\s*[:=]\s*["\']([A-Za-z0-9\-_\.]{20,})["\']',       "token"),
    (r'secret\s*[:=]\s*["\']([A-Za-z0-9\-_\.]{10,})["\']',      "secret"),
    (r'eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+',  "JWT"),
    (r'["\']x-api-key["\']\s*:\s*["\']([^"\']{8,})["\']',       "x-api-key header"),
    (r'["\']x-auth-token["\']\s*:\s*["\']([^"\']{8,})["\']',    "x-auth-token header"),
]

# GraphQL patterns
GRAPHQL_PATTERNS = [
    r'https?://[^\s\'"<>]+/graphql[^\s\'"<>]*',
    r'["\'](/graphql[^\s\'"<>]{0,50})["\']',
    r'query\s*\{[^}]{10,200}\}',
    r'mutation\s*\{[^}]{10,200}\}',
]

M3U8_PATTERN = r'https?://[A-Za-z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+?\.m3u8(?:[^\s\'"<>\\]*)'

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"

BASE_HEADERS = {
    "User-Agent":      UA,
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — HTTP layer analysis (no browser)
# ─────────────────────────────────────────────────────────────────────────────
def http_phase(url: str, intel: Intelligence, referer: str = ""):
    print(f"  [http] GET {url}")
    hdrs = dict(BASE_HEADERS)
    if referer:
        hdrs["Referer"] = referer
        hdrs["Origin"]  = urllib.parse.urlparse(referer).scheme + "://" + urllib.parse.urlparse(referer).netloc

    session = req_lib.Session()
    try:
        r = session.get(url, headers=hdrs, timeout=15, allow_redirects=True)

        # redirect chain
        for resp in r.history:
            intel.redirect_chain.append({"url": resp.url, "status": resp.status_code})

        # response headers
        intel.response_headers[url] = dict(r.headers)

        # server cookies
        for c in session.cookies:
            intel.server_cookies.append({
                "name": c.name, "value": c.value,
                "domain": c.domain, "path": c.path,
                "secure": c.secure,
            })
            intel.all_cookies[c.name] = c.value

        body = r.text

        # ── save raw HTTP page source ─────────────────────────────────────────
        intel.http_page_sources[url] = body

        # ── extract from HTML ─────────────────────────────────────────────────
        _extract_all(body, url, intel)

        # ── fetch each iframe recursively (1 level) ───────────────────────────
        iframes = re.findall(r'<iframe[^>]+src=["\']([^"\']+)["\']', body, re.I)
        for src in iframes:
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = urllib.parse.urljoin(url, src)
            if src.startswith("http") and src not in [f["src"] for f in intel.iframes]:
                intel.iframes.append({"src": src, "from": url})
                print(f"  [iframe] {src}")
                http_phase(src, intel, referer=url)

    except Exception as e:
        intel.errors.append(f"http_phase({url}): {e}")


def _extract_all(body: str, base_url: str, intel: Intelligence):
    """Extract everything useful from a block of HTML/JS text."""

    # m3u8
    for m in re.findall(M3U8_PATTERN, body, re.I):
        m = m.strip().rstrip("\"'\\")
        if m and m not in intel.m3u8_urls:
            intel.m3u8_urls.append(m)
            print(f"  [★ m3u8] {m}")

    # API endpoints
    for pat in API_PATTERNS:
        for m in re.findall(pat, body, re.I):
            ep = m.strip().strip("\"'")
            if ep.startswith("/"):
                ep = urllib.parse.urljoin(base_url, ep)
            if len(ep) > 5 and ep not in intel.api_endpoints:
                intel.api_endpoints.append(ep)

    # GraphQL endpoints + queries
    for pat in GRAPHQL_PATTERNS:
        for m in re.findall(pat, body, re.I):
            ep = m.strip().strip("\"'")
            if ep.startswith("/"):
                ep = urllib.parse.urljoin(base_url, ep)
            if "query" in ep.lower() or "mutation" in ep.lower():
                if ep not in intel.graphql_queries:
                    intel.graphql_queries.append(ep)
            elif ep not in intel.graphql_endpoints:
                intel.graphql_endpoints.append(ep)
                print(f"  [graphql] {ep}")

    # Token / key / secret scanner
    for pattern, label in TOKEN_PATTERNS:
        for m in re.findall(pattern, body, re.I):
            val = m.strip()
            entry = {"type": label, "value": val[:120], "source": base_url}
            if not any(t["value"] == entry["value"] for t in intel.tokens_found):
                intel.tokens_found.append(entry)
                print(f"  [token] {label}: {val[:60]}")

    # meta tags
    for m in re.findall(r'<meta[^>]+>', body, re.I):
        name    = re.search(r'name=["\']([^"\']+)["\']',    m, re.I)
        prop    = re.search(r'property=["\']([^"\']+)["\']', m, re.I)
        content = re.search(r'content=["\']([^"\']+)["\']', m, re.I)
        key = (name or prop)
        if key and content:
            entry = {"name": key.group(1), "content": content.group(1)}
            if entry not in intel.meta_tags:
                intel.meta_tags.append(entry)

    # form actions (POST endpoints)
    for m in re.findall(r'<form[^>]+action=["\']([^"\']+)["\']', body, re.I):
        ep = m.strip()
        if ep.startswith("/"):
            ep = urllib.parse.urljoin(base_url, ep)
        if ep not in intel.form_actions:
            intel.form_actions.append(ep)

    # external JS files
    for src in re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', body, re.I):
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            src = urllib.parse.urljoin(base_url, src)
        if src not in intel.js_files:
            intel.js_files.append(src)

    # inline scripts
    for content in re.findall(r'<script[^>]*>(.*?)</script>', body, re.DOTALL | re.I):
        content = content.strip()
        if len(content) > 20:
            intel.js_inline.append(content[:3000])
            _extract_all(content, base_url, intel)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 — Fetch and scan every external JS file
# ─────────────────────────────────────────────────────────────────────────────
def js_phase(intel: Intelligence):
    print(f"\n[Phase 2] Scanning {len(intel.js_files)} JS file(s) …")
    for js_url in intel.js_files:
        print(f"  [js] {js_url[:90]}")
        try:
            r = req_lib.get(js_url, headers=BASE_HEADERS, timeout=10)
            js_body = r.text

            hits_before = len(intel.api_endpoints)
            _extract_all(js_body, js_url, intel)
            new_hits = intel.api_endpoints[hits_before:]
            if new_hits:
                for h in new_hits:
                    intel.js_api_hits.append({"js_file": js_url, "endpoint": h})
                    print(f"    [api] {h}")

        except Exception as e:
            intel.errors.append(f"js_phase({js_url}): {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — Browser capture (selenium)
# ─────────────────────────────────────────────────────────────────────────────
def browser_phase(url: str, intel: Intelligence, headless: bool, wait_sec: int):
    if not SELENIUM_OK:
        print("  [skip] selenium not installed")
        return

    print(f"\n[Phase 3] Browser capture (headless={headless}) …")
    driver = None
    try:
        opts = FirefoxOptions()
        if headless:
            opts.add_argument("--headless")
        opts.set_preference("media.autoplay.default", 0)
        opts.set_preference("media.autoplay.blocking_policy", 0)
        opts.set_preference("privacy.trackingprotection.enabled", False)
        driver = webdriver.Firefox(options=opts)
        driver.set_page_load_timeout(30)

        intel.user_agent = driver.execute_script("return navigator.userAgent") or UA

        print(f"  [browser] loading {url} …")
        driver.get(url)
        time.sleep(1)
        _inject_all(driver)

        print(f"  [browser] waiting {wait_sec}s …")
        deadline = time.time() + wait_sec
        while time.time() < deadline:
            time.sleep(1)
            _inject_all(driver)
            reqs = _collect(driver)
            if any(r.is_m3u8 for r in reqs):
                print("  [browser] m3u8 detected — stopping wait early")
                break

        # final collect
        reqs = _collect(driver)
        intel.all_requests.extend(reqs)
        for r in reqs:
            if r.is_m3u8 and r.url not in intel.m3u8_urls:
                intel.m3u8_urls.append(r.url)
                print(f"  [★ m3u8] {r.url}")
            if r.rtype == "websocket" and r.url not in intel.websockets:
                intel.websockets.append(r.url)
            if r.is_api and r.url not in intel.api_endpoints:
                intel.api_endpoints.append(r.url)
            # collect cookies from JS
            if r.cookies:
                for part in r.cookies.split(";"):
                    kv = part.strip().split("=", 1)
                    if len(kv) == 2:
                        intel.all_cookies[kv[0].strip()] = kv[1].strip()

        # DOM extraction
        _dom_extract(driver, intel)

        # visit each iframe directly
        for fr in intel.iframes:
            src = fr.get("src", "")
            if not src.startswith("http"):
                continue
            print(f"  [browser] visiting iframe: {src}")
            try:
                driver.get(src)
                time.sleep(1)
                _inject_all(driver)
                time.sleep(min(wait_sec, 5))
                _inject_all(driver)
                reqs2 = _collect(driver)
                intel.all_requests.extend(reqs2)
                for r in reqs2:
                    if r.is_m3u8 and r.url not in intel.m3u8_urls:
                        intel.m3u8_urls.append(r.url)
                        print(f"  [★ m3u8] {r.url}")
                    if r.is_api and r.url not in intel.api_endpoints:
                        intel.api_endpoints.append(r.url)
                _dom_extract(driver, intel)
            except Exception as e:
                intel.errors.append(f"iframe visit {src}: {e}")

    except WebDriverException as e:
        intel.errors.append(f"WebDriver: {e}")
        print(f"  [error] {e}")
    finally:
        if driver:
            try: driver.quit()
            except: pass


def _inject_all(driver):
    try: driver.execute_script(INTERCEPT_JS)
    except: pass
    for frame in driver.find_elements(By.TAG_NAME, "iframe"):
        try:
            driver.switch_to.frame(frame)
            driver.execute_script(INTERCEPT_JS)
            driver.switch_to.default_content()
        except:
            driver.switch_to.default_content()


def _collect(driver) -> list:
    results = []
    def pull():
        try:
            raw = driver.execute_script("return window.__naRequests__ || []")
            for r in raw:
                url = r.get("url","")
                if not url or url == "undefined": continue
                results.append(NetRequest(
                    url=url, method=r.get("method","GET"),
                    rtype=r.get("type",""), origin=r.get("origin",""),
                    referer=r.get("referer",""), headers=r.get("headers",{}),
                    cookies=r.get("cookies",""), body=r.get("body",""),
                    is_api=bool(re.search(r'/api/|/v\d+/|\.json(\?|$)|graphql', url)),
                    is_m3u8=".m3u8" in url.lower(),
                    is_js=url.endswith(".js") or ".js?" in url,
                ))
        except: pass
    pull()
    for frame in driver.find_elements(By.TAG_NAME, "iframe"):
        try:
            driver.switch_to.frame(frame)
            pull()
            driver.switch_to.default_content()
        except:
            driver.switch_to.default_content()
    return results


def _dom_extract(driver, intel: Intelligence):
    try: intel.page_title = intel.page_title or driver.title
    except: pass
    try:
        src = driver.page_source
        current = driver.current_url
        if current not in intel.browser_page_sources:
            intel.browser_page_sources[current] = src
        _extract_all(src, current, intel)
    except: pass

    # XHR response bodies
    try:
        responses = driver.execute_script("return window.__naResponses__ || []")
        for resp in responses:
            entry = {"url": resp.get("url",""), "status": resp.get("status",0),
                     "body": resp.get("body",""), "ct": resp.get("ct","")}
            if entry not in intel.api_responses:
                intel.api_responses.append(entry)
                # scan response body for more endpoints
                if resp.get("body"):
                    _extract_all(resp["body"], resp.get("url",""), intel)
    except: pass

    # postMessage events
    try:
        msgs = driver.execute_script("return window.__naMessages__ || []")
        for m in msgs:
            if m not in intel.post_messages:
                intel.post_messages.append(m)
                # scan message data for URLs / tokens
                if m.get("data"):
                    _extract_all(m["data"], driver.current_url, intel)
    except: pass

    # localStorage / sessionStorage
    try:
        storage = driver.execute_script("return window.__naStorage__ || {local:{},session:{}}")
        intel.local_storage.update(storage.get("local", {}))
        intel.session_storage.update(storage.get("session", {}))
        # scan storage values for tokens / endpoints
        for v in list(storage.get("local",{}).values()) + list(storage.get("session",{}).values()):
            if v and len(v) > 5:
                _extract_all(str(v), driver.current_url, intel)
    except: pass

    # JS globals
    for var in ["__NEXT_DATA__","__NUXT__","__PLAYER_CONFIG__","__STREAM__",
                "playerConfig","videoConfig","streamConfig","jwplayer","Hls",
                "APP_CONFIG","window.__config__","__APP__","__STORE__"]:
        try:
            val = driver.execute_script(
                f"try{{return JSON.stringify(window['{var}'])||null}}catch(e){{return null}}")
            if val and val != "null":
                parsed = json.loads(val)
                intel.js_globals[var] = parsed
                _extract_all(json.dumps(parsed), driver.current_url, intel)
        except: pass


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — Probe discovered API endpoints
# ─────────────────────────────────────────────────────────────────────────────
def probe_apis(intel: Intelligence):
    if not intel.api_endpoints:
        return
    print(f"\n[Phase 4] Probing {len(intel.api_endpoints)} API endpoint(s) …")
    for ep in intel.api_endpoints[:30]:  # cap at 30 to avoid hammering
        if not ep.startswith("http"):
            continue
        print(f"  [probe] {ep[:90]}")
        try:
            r = req_lib.get(ep, headers=BASE_HEADERS, timeout=8)
            ct = r.headers.get("Content-Type","")
            if "json" in ct:
                try:
                    data = r.json()
                    # scan JSON for more endpoints / m3u8
                    text = json.dumps(data)
                    _extract_all(text, ep, intel)
                    print(f"    → JSON {r.status_code}: {text[:120]}")
                except:
                    pass
            elif "javascript" in ct or ep.endswith(".js"):
                _extract_all(r.text, ep, intel)
        except Exception as e:
            pass  # silent — many endpoints need auth


def _gen_client(intel: Intelligence, lines: list):
    """Auto-generate a ready-to-run Python API client from discovered intel."""

    # pick best referer and origin from intercepted requests
    referer = ""
    origin  = ""
    auth_header = ""
    cookies_code = ""

    for r in intel.all_requests:
        if r.referer and not referer:
            referer = r.referer
        if r.origin and not origin:
            origin = r.origin
        for k, v in (r.headers or {}).items():
            if k.lower() == "authorization" and not auth_header:
                auth_header = v

    # pick best API endpoints (prefer JSON-returning ones from responses)
    best_eps = []
    for resp in intel.api_responses:
        if resp["url"] and resp["url"] not in best_eps:
            best_eps.append(resp["url"])
    for ep in intel.api_endpoints:
        if ep not in best_eps:
            best_eps.append(ep)

    # cookies
    if intel.all_cookies:
        cookie_lines = [f'    session.cookies.set("{k}", "{v}")'
                        for k, v in list(intel.all_cookies.items())[:10]]
        cookies_code = "\n".join(cookie_lines)

    # tokens
    token_code = ""
    for t in intel.tokens_found[:3]:
        if "Bearer" in t["type"] or "JWT" in t["type"]:
            token_code = f'    "Authorization": "Bearer {t["value"][:60]}",'
            break
        elif "API key" in t["type"]:
            token_code = f'    "X-Api-Key": "{t["value"][:60]}",'
            break

    lines.append("""
  # ── Copy this file and run it directly ──────────────────────────────────
  # Save as: direct_api_client.py
  # Run:     python direct_api_client.py
""")
    lines.append('  import requests')
    lines.append('  import json')
    lines.append('')
    lines.append(f'  TARGET = "{intel.target_url}"')
    lines.append('')
    lines.append('  session = requests.Session()')
    lines.append('  session.headers.update({')
    lines.append(f'      "User-Agent": "{intel.user_agent or UA}",')
    if referer:
        lines.append(f'      "Referer":    "{referer}",')
    if origin:
        lines.append(f'      "Origin":     "{origin}",')
    if token_code:
        lines.append(f'      {token_code}')
    lines.append('  })')
    if cookies_code:
        lines.append('')
        lines.append('  # Cookies found during analysis:')
        lines.append(cookies_code)
    lines.append('')
    lines.append('  # ── API endpoints discovered ──────────────────────────')
    for ep in best_eps[:8]:
        safe = ep.replace("'", "\\'")
        lines.append(f"  # {safe}")
    lines.append('')
    if best_eps:
        ep = best_eps[0].replace("'", "\\'")
        lines.append(f"  r = session.get('{ep}', timeout=15)")
        lines.append('  print(f"Status: {r.status_code}")')
        lines.append('  try:')
        lines.append('      print(json.dumps(r.json(), indent=2))')
        lines.append('  except:')
        lines.append('      print(r.text[:500])')
    if intel.graphql_endpoints:
        lines.append('')
        lines.append('  # ── GraphQL endpoint found ────────────────────────')
        gql = intel.graphql_endpoints[0]
        lines.append(f"  # gql_r = session.post('{gql}',")
        lines.append('  #     json={"query": "{ __schema { types { name } } }"})')
        lines.append('  # print(gql_r.json())')


# ─────────────────────────────────────────────────────────────────────────────
# Save all page sources to page_source.txt
# ─────────────────────────────────────────────────────────────────────────────
def save_page_sources(intel: Intelligence, out_dir: str) -> str:
    fname = os.path.join(out_dir, "page_source.txt")
    W = 70

    with open(fname, "w", encoding="utf-8") as f:
        f.write("=" * W + "\n")
        f.write("  PAGE SOURCE DUMP\n")
        f.write(f"  Target    : {intel.target_url}\n")
        f.write(f"  Timestamp : {intel.timestamp}\n")
        f.write("=" * W + "\n")

        # ── HTTP raw sources ──────────────────────────────────────────────────
        f.write(f"\n{'─' * W}\n")
        f.write(f"  HTTP RAW SOURCES ({len(intel.http_page_sources)} page(s))\n")
        f.write(f"  (as received from server — before JavaScript runs)\n")
        f.write(f"{'─' * W}\n")
        for url, src in intel.http_page_sources.items():
            f.write(f"\n{'─' * W}\n")
            f.write(f"  URL: {url}\n")
            f.write(f"  SIZE: {len(src):,} bytes\n")
            f.write(f"{'─' * W}\n")
            f.write(src)
            f.write("\n")

        # ── Browser rendered sources ──────────────────────────────────────────
        f.write(f"\n{'═' * W}\n")
        f.write(f"  BROWSER RENDERED SOURCES ({len(intel.browser_page_sources)} page(s))\n")
        f.write(f"  (after JavaScript has executed — full DOM)\n")
        f.write(f"{'═' * W}\n")
        for url, src in intel.browser_page_sources.items():
            f.write(f"\n{'─' * W}\n")
            f.write(f"  URL: {url}\n")
            f.write(f"  SIZE: {len(src):,} bytes\n")
            f.write(f"{'─' * W}\n")
            f.write(src)
            f.write("\n")

        f.write(f"\n{'=' * W}\n")
        f.write("  END OF PAGE SOURCE DUMP\n")
        f.write(f"{'=' * W}\n")

    return fname


# ─────────────────────────────────────────────────────────────────────────────
# Save report to .txt
# ─────────────────────────────────────────────────────────────────────────────
def save_report(intel: Intelligence, out_dir: str) -> str:
    domain = urllib.parse.urlparse(intel.target_url).netloc.replace(".", "_")
    ts     = intel.timestamp.replace(":", "-").replace(" ", "_")
    fname  = os.path.join(out_dir, f"analysis_{domain}_{ts}.txt")

    lines = []
    W = 70

    def h(title):
        lines.append("\n" + "═" * W)
        lines.append(f"  {title}")
        lines.append("═" * W)

    def s(title):
        lines.append(f"\n{'─' * W}")
        lines.append(f"  {title}")
        lines.append(f"{'─' * W}")

    h("NETWORK INTELLIGENCE REPORT")
    lines.append(f"  Target    : {intel.target_url}")
    lines.append(f"  Timestamp : {intel.timestamp}")
    lines.append(f"  Title     : {intel.page_title}")
    lines.append(f"  UserAgent : {intel.user_agent or UA}")

    # ── M3U8 ─────────────────────────────────────────────────────────────────
    s(f"M3U8 / HLS STREAM URLS ({len(intel.m3u8_urls)})")
    for u in intel.m3u8_urls:
        lines.append(f"  {u}")

    # ── API endpoints ─────────────────────────────────────────────────────────
    s(f"API ENDPOINTS ({len(intel.api_endpoints)})")
    for ep in intel.api_endpoints:
        lines.append(f"  {ep}")

    # ── API endpoints found inside JS files ───────────────────────────────────
    s(f"API ENDPOINTS FOUND IN JS FILES ({len(intel.js_api_hits)})")
    for hit in intel.js_api_hits:
        lines.append(f"  JS : {hit['js_file'][:80]}")
        lines.append(f"  EP : {hit['endpoint']}")
        lines.append("")

    # ── WebSockets ────────────────────────────────────────────────────────────
    s(f"WEBSOCKET URLS ({len(intel.websockets)})")
    for w in intel.websockets:
        lines.append(f"  {w}")

    # ── Cookies ───────────────────────────────────────────────────────────────
    s(f"COOKIES ({len(intel.all_cookies)})")
    for k, v in intel.all_cookies.items():
        lines.append(f"  {k} = {v}")

    s(f"SERVER SET-COOKIE DETAILS ({len(intel.server_cookies)})")
    for c in intel.server_cookies:
        lines.append(f"  {c['name']} = {c['value']}")
        lines.append(f"    domain={c['domain']}  path={c['path']}  secure={c['secure']}")

    # ── Iframes ───────────────────────────────────────────────────────────────
    s(f"IFRAMES ({len(intel.iframes)})")
    for fr in intel.iframes:
        lines.append(f"  {fr['src']}")
        lines.append(f"    (found in: {fr.get('from','')})")

    # ── JS files ─────────────────────────────────────────────────────────────
    s(f"EXTERNAL JS FILES ({len(intel.js_files)})")
    for js in intel.js_files:
        lines.append(f"  {js}")

    # ── Response headers ──────────────────────────────────────────────────────
    s(f"RESPONSE HEADERS")
    for url, hdrs in intel.response_headers.items():
        lines.append(f"\n  URL: {url}")
        for k, v in hdrs.items():
            lines.append(f"    {k}: {v}")

    # ── Redirect chain ────────────────────────────────────────────────────────
    s(f"REDIRECT CHAIN ({len(intel.redirect_chain)})")
    for r in intel.redirect_chain:
        lines.append(f"  {r['status']} → {r['url']}")

    # ── All intercepted requests ──────────────────────────────────────────────
    s(f"ALL INTERCEPTED BROWSER REQUESTS ({len(intel.all_requests)})")
    for r in intel.all_requests:
        tag = "[m3u8]" if r.is_m3u8 else "[api] " if r.is_api else "[js]  " if r.is_js else "[    ]"
        lines.append(f"  {tag} {r.rtype:<14} {r.method:<6} {r.url}")
        if r.origin:   lines.append(f"         Origin  : {r.origin}")
        if r.referer:  lines.append(f"         Referer : {r.referer}")
        if r.cookies:  lines.append(f"         Cookies : {r.cookies[:120]}")
        for k, v in (r.headers or {}).items():
            lines.append(f"         {k}: {v}")

    # ── JS globals ────────────────────────────────────────────────────────────
    if intel.js_globals:
        s("JS GLOBALS (window.__X__)")
        for k, v in intel.js_globals.items():
            lines.append(f"\n  {k}:")
            lines.append(f"  {json.dumps(v, indent=2)[:500]}")

    # ── Inline scripts summary ────────────────────────────────────────────────
    s(f"INLINE SCRIPTS ({len(intel.js_inline)}) — first 300 chars each")
    for i, sc in enumerate(intel.js_inline[:10], 1):
        lines.append(f"\n  [{i}] {sc[:300]}")

    # ── Tokens / keys found ───────────────────────────────────────────────────
    s(f"TOKENS / KEYS / SECRETS FOUND ({len(intel.tokens_found)})")
    for t in intel.tokens_found:
        lines.append(f"  [{t['type']}]  {t['value']}")
        lines.append(f"    found in: {t['source'][:80]}")

    # ── GraphQL ───────────────────────────────────────────────────────────────
    s(f"GRAPHQL ENDPOINTS ({len(intel.graphql_endpoints)})")
    for g in intel.graphql_endpoints:
        lines.append(f"  {g}")
    s(f"GRAPHQL QUERIES/MUTATIONS ({len(intel.graphql_queries)})")
    for g in intel.graphql_queries:
        lines.append(f"  {g[:200]}")

    # ── postMessage events ────────────────────────────────────────────────────
    s(f"POSTMESSAGE EVENTS ({len(intel.post_messages)})")
    for m in intel.post_messages:
        lines.append(f"  origin: {m.get('origin','')}")
        lines.append(f"  data  : {m.get('data','')[:200]}")
        lines.append("")

    # ── localStorage / sessionStorage ─────────────────────────────────────────
    s(f"LOCALSTORAGE ({len(intel.local_storage)} keys)")
    for k, v in intel.local_storage.items():
        lines.append(f"  {k} = {str(v)[:120]}")
    s(f"SESSIONSTORAGE ({len(intel.session_storage)} keys)")
    for k, v in intel.session_storage.items():
        lines.append(f"  {k} = {str(v)[:120]}")

    # ── meta tags ─────────────────────────────────────────────────────────────
    s(f"META TAGS ({len(intel.meta_tags)})")
    for m in intel.meta_tags:
        lines.append(f"  {m['name']} = {m['content']}")

    # ── form actions ──────────────────────────────────────────────────────────
    s(f"FORM ACTIONS / POST ENDPOINTS ({len(intel.form_actions)})")
    for f in intel.form_actions:
        lines.append(f"  {f}")

    # ── XHR / fetch response bodies ───────────────────────────────────────────
    s(f"API RESPONSE BODIES ({len(intel.api_responses)})")
    for resp in intel.api_responses:
        lines.append(f"\n  URL    : {resp['url']}")
        lines.append(f"  Status : {resp['status']}  CT: {resp['ct']}")
        lines.append(f"  Body   : {resp['body'][:300]}")

    # ── Errors ────────────────────────────────────────────────────────────────
    if intel.errors:
        s(f"ERRORS ({len(intel.errors)})")
        for e in intel.errors:
            lines.append(f"  ⚠ {e}")

    # ── Auto-generated direct API client ─────────────────────────────────────
    h("AUTO-GENERATED DIRECT API CLIENT")
    _gen_client(intel, lines)

    h("END OF REPORT")

    with open(fname, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return fname


# ─────────────────────────────────────────────────────────────────────────────
# Console report (quick summary)
# ─────────────────────────────────────────────────────────────────────────────
def print_summary(intel: Intelligence, report_file: str, page_src_file: str = ""):
    W = 70
    print("\n" + "═" * W)
    print("  SUMMARY")
    print("═" * W)
    print(f"  Target       : {intel.target_url}")
    print(f"  Title        : {intel.page_title}")
    print(f"  M3U8 URLs    : {len(intel.m3u8_urls)}")
    print(f"  API endpoints: {len(intel.api_endpoints)}")
    print(f"  GraphQL      : {len(intel.graphql_endpoints)}")
    print(f"  JS files     : {len(intel.js_files)}")
    print(f"  Iframes      : {len(intel.iframes)}")
    print(f"  Cookies      : {len(intel.all_cookies)}")
    print(f"  Tokens/keys  : {len(intel.tokens_found)}")
    print(f"  postMessages : {len(intel.post_messages)}")
    print(f"  localStorage : {len(intel.local_storage)} keys")
    print(f"  API responses: {len(intel.api_responses)}")
    print(f"  WS sockets   : {len(intel.websockets)}")
    print(f"  Requests     : {len(intel.all_requests)}")
    print(f"  Page sources : {len(intel.http_page_sources)} HTTP + {len(intel.browser_page_sources)} rendered")
    print(f"  Errors       : {len(intel.errors)}")

    if intel.m3u8_urls:
        print(f"\n  {'★'*W}")
        print("  M3U8 STREAMS:")
        for u in intel.m3u8_urls:
            print(f"    {u}")

    if intel.api_endpoints:
        print(f"\n  TOP API ENDPOINTS:")
        for ep in intel.api_endpoints[:15]:
            print(f"    {ep}")

    if intel.tokens_found:
        print(f"\n  TOKENS FOUND:")
        for t in intel.tokens_found[:5]:
            print(f"    [{t['type']}] {t['value'][:60]}")

    print(f"\n  Full report  → {report_file}")
    if page_src_file:
        print(f"  Page source  → {page_src_file}")
    print("═" * W)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def run(target_url: str, headless: bool, wait_sec: int, out_dir: str):
    intel = Intelligence(
        target_url=target_url,
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    print(f"\n{'=' * 70}")
    print(f"  TARGET : {target_url}")
    print(f"  TIME   : {intel.timestamp}")
    print(f"{'=' * 70}\n")

    # Phase 1 — HTTP + iframe crawl
    print("[Phase 1] HTTP scan + iframe crawl …")
    http_phase(target_url, intel)
    print(f"  → api: {len(intel.api_endpoints)}  m3u8: {len(intel.m3u8_urls)}  js: {len(intel.js_files)}")

    # Phase 2 — JS file analysis
    js_phase(intel)
    print(f"  → api: {len(intel.api_endpoints)}  m3u8: {len(intel.m3u8_urls)}")

    # Phase 3 — Browser capture
    browser_phase(target_url, intel, headless=headless, wait_sec=wait_sec)
    print(f"  → api: {len(intel.api_endpoints)}  m3u8: {len(intel.m3u8_urls)}")

    # Phase 4 — Probe APIs
    probe_apis(intel)
    print(f"  → api: {len(intel.api_endpoints)}  m3u8: {len(intel.m3u8_urls)}")

    # Save report
    os.makedirs(out_dir, exist_ok=True)
    report_file = save_report(intel, out_dir)
    page_src_file = save_page_sources(intel, out_dir)

    # Console summary
    print_summary(intel, report_file, page_src_file)

    return intel, report_file


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Advanced network intelligence tool — finds API endpoints, XHR, JS, cookies, m3u8 for any URL"
    )
    parser.add_argument("--url",          default="https://vaplayer.ru/embed/movie/tt2948356",
                        help="Target URL to analyse")
    parser.add_argument("--wait",         type=int, default=10,
                        help="Seconds to wait for JS to fire (default: 10)")
    parser.add_argument("--show-browser", action="store_true",
                        help="Show Firefox window instead of headless")
    parser.add_argument("--out",          default=".",
                        help="Output directory for .txt report (default: current folder)")
    args = parser.parse_args()

    run(
        target_url=args.url,
        headless=not args.show_browser,
        wait_sec=args.wait,
        out_dir=args.out,
    )
