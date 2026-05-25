"""
devtools_networkinterceptor.py  v5.0
=====================================
Universal Streaming Site DevTools Interceptor, API Cracker & Stream Extractor

NEW IN v5:
  - Cross-origin iframe drilling: switches into iframes and captures their
    network traffic separately (catches VidSrc, 2embed, Filemoon, etc.)
  - AES-256-GCM response decryption using keys extracted from JS chunks
  - generateContentHash reverse-engineering: extracts and executes the
    site's own hash function via Node.js to generate valid 'secret' params
  - Cloudflare bypass: realistic browser fingerprint, TLS fingerprinting
    via requests + cloudscraper fallback
  - Signed token replay: captures the _rk / secret / token from live
    browser session and replays them in direct Python API calls
  - Known embed provider handlers: VidSrc, 2embed, Filemoon, StreamTape,
    DoodStream, MixDrop, Upstream, GoFile, Febbox, SuperEmbed, AutoEmbed
  - HLS segment URL reconstruction from partial/proxy URLs
  - Blob URL interception: captures blob: URLs created by MediaSource API
  - Service Worker interception: captures SW fetch events
  - Shadow DOM piercing: finds video elements inside shadow roots
  - Multi-tab capture: opens embed URLs in new tabs and captures those too
  - yt-dlp integration: tries yt-dlp as fallback extractor
  - Automatic stream validation: HEAD request to verify URL is live
  - Proxy URL unwrapping: decodes cinemaos/madplay/xelvonwave proxy URLs

CAPTURES EVERYTHING:
  XHR, Fetch, WebSocket, PerformanceObserver resources, console,
  cookies (JSON + Netscape), localStorage/sessionStorage, all headers
  (User-Agent, Referer, Origin, Authorization, Bearer, API keys, JWTs),
  iframes (live + cross-origin), video elements, blob URLs, SW events,
  page source, scripts, lazy chunks, navigation log, tokens, stream URLs
"""

import os, sys, time, json, re, platform, subprocess, threading
import hashlib, shutil, tempfile, zipfile, base64, hmac, struct
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urljoin, urlencode, quote, unquote

# ── auto-install ──────────────────────────────────────────────────────────────
def ensure(pkg, import_as=None):
    name = import_as or pkg.replace("-", "_")
    try:
        __import__(name)
    except ImportError:
        print(f"[SETUP] Installing {pkg} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg,
                               "-q", "--disable-pip-version-check"])

ensure("selenium")
ensure("webdriver_manager")
ensure("jsbeautifier")
ensure("requests")
ensure("cloudscraper")

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.firefox import GeckoDriverManager
import jsbeautifier, requests, cloudscraper

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
TARGET_URL         = "https://vidrock.ru/embed/movie/1318447"
STREAM_WAIT_SEC    = 60
AUTO_SAVE_INTERVAL = 12
FETCH_CHUNKS       = True
DRILL_IFRAMES      = True   # switch into iframes and capture their network
OPEN_EMBED_TABS    = True   # open discovered embed URLs in new tabs
TRY_YTDLP          = True   # try yt-dlp as fallback
VALIDATE_STREAMS   = True   # HEAD-check discovered stream URLs

SCRIPT_DIR = Path(__file__).parent
TIMESTAMP  = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR    = SCRIPT_DIR / f"capture_{TIMESTAMP}"
ERROR_LOG  = SCRIPT_DIR / "facingerro_failed.txt"
TEMP_DIR   = None

for d in [OUT_DIR, OUT_DIR/"scripts", OUT_DIR/"chunks", OUT_DIR/"iframes",
          OUT_DIR/"embed_tabs", OUT_DIR/"api_responses"]:
    d.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def log_error(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[ERROR] {msg}")
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception: pass

def save_json(data, filename):
    path = OUT_DIR / filename
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[SAVED] {path.name}")
    except Exception as e:
        log_error(f"save_json({filename}): {e}")

def save_text(text, filename):
    path = OUT_DIR / filename
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(text))
        print(f"[SAVED] {path.name}")
    except Exception as e:
        log_error(f"save_text({filename}): {e}")

def beautify_js(code):
    try:
        opts = jsbeautifier.default_options()
        opts.indent_size = 2
        opts.max_preserve_newlines = 2
        return jsbeautifier.beautify(code, opts)
    except Exception:
        return code

def short_hash(s):
    return hashlib.md5(s.encode()).hexdigest()[:8]

def safe_exec(driver, script, default=None):
    try:
        return driver.execute_script(script)
    except Exception as e:
        log_error(f"safe_exec: {e}")
        return default

def node_available():
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# DETECTION PATTERNS
# ═══════════════════════════════════════════════════════════════════════════════
STREAM_RE = [
    r'https?://[^\s\'"<>\]\\,\)\}]+\.m3u8(?:[^\s\'"<>\]\\,\)\}]*)?',
    r'https?://[^\s\'"<>\]\\,\)\}]+\.mpd(?:[^\s\'"<>\]\\,\)\}]*)?',
    r'https?://[^\s\'"<>\]\\,\)\}]+\.mp4(?:[^\s\'"<>\]\\,\)\}]*)?',
    r'https?://[^\s\'"<>\]\\,\)\}]+\.mkv(?:[^\s\'"<>\]\\,\)\}]*)?',
    r'https?://[^\s\'"<>\]\\,\)\}]+/manifest(?:\.m3u8)?(?:[^\s\'"<>\]\\,\)\}]*)?',
    r'https?://[^\s\'"<>\]\\,\)\}]+/index\.m3u8(?:[^\s\'"<>\]\\,\)\}]*)?',
    r'https?://[^\s\'"<>\]\\,\)\}]+/master\.m3u8(?:[^\s\'"<>\]\\,\)\}]*)?',
    r'https?://[^\s\'"<>\]\\,\)\}]+/playlist(?:\.m3u8)?(?:[^\s\'"<>\]\\,\)\}]*)?',
    r'https?://[^\s\'"<>\]\\,\)\}]+/hls/[^\s\'"<>\]\\,\)\}]+',
    r'https?://[^\s\'"<>\]\\,\)\}]+/dash/[^\s\'"<>\]\\,\)\}]+',
    r'https?://[^\s\'"<>\]\\,\)\}]+/stream/[^\s\'"<>\]\\,\)\}]+',
]
API_RE = [
    r'https?://[^\s\'"<>\]\\]+/api/[^\s\'"<>\]\\]{3,}',
    r'https?://[^\s\'"<>\]\\]+/v\d+/[^\s\'"<>\]\\]{3,}',
    r'/api/[a-zA-Z0-9/_\-\.%]{3,}',
    r'https?://[^\s\'"<>\]\\]+/stream[^\s\'"<>\]\\]*',
    r'https?://[^\s\'"<>\]\\]+/source[^\s\'"<>\]\\]*',
    r'https?://[^\s\'"<>\]\\]+/embed[^\s\'"<>\]\\]*',
    r'fetch\s*\(\s*[\'"`]([^\'"` \n]{5,})[\'"`]',
    r'axios\.\w+\s*\(\s*[\'"`]([^\'"` \n]{5,})[\'"`]',
    r'url\s*:\s*[\'"`]([^\'"` \n]{8,})[\'"`]',
    r'src\s*:\s*[\'"`](https?://[^\'"` \n]{8,})[\'"`]',
]
AUTH_RE = [
    r'[Aa]uthorization[\'"\s:]+[Bb]earer\s+([A-Za-z0-9\-_\.]{20,})',
    r'[Aa]pi[_-]?[Kk]ey[\'"\s:=]+([A-Za-z0-9\-_\.]{10,})',
    r'[Tt]oken[\'"\s:=]+([A-Za-z0-9\-_\.]{10,})',
    r'[Xx]-[Aa]uth[\'"\s:=]+([A-Za-z0-9\-_\.]{10,})',
    r'[Xx]-[Aa]pi-[Kk]ey[\'"\s:=]+([A-Za-z0-9\-_\.]{10,})',
    r'eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+',
    r'_rk[\'"\s:=,]+([A-Za-z0-9]{20,})',
    r'secret[\'"\s:=,]+([A-Za-z0-9]{20,})',
    r'ENCRYPTION_KEY[\'"\s:=|]+([A-Za-z0-9]{40,})',
]
PLAYER_SIGS = {
    "Video.js":     ["video.js","videojs","vjs-","VideoJS"],
    "JW Player":    ["jwplayer","jw-player","jwplatform"],
    "Plyr":         ["plyr","plyr.js","plyr.css"],
    "hls.js":       ["hls.js","Hls.js","HlsJs","new Hls("],
    "Shaka Player": ["shaka-player","shaka.js","shakaplayer"],
    "DPlayer":      ["dplayer","DPlayer"],
    "Clappr":       ["clappr","Clappr"],
    "Dash.js":      ["dash.js","dashjs","dash.mediaplayer"],
    "Flowplayer":   ["flowplayer","flow.js"],
    "MediaElement": ["mediaelement","mejs-"],
}
# Known embed providers — their domains indicate cross-origin iframe players
EMBED_PROVIDERS = [
    "vidsrc.to","vidsrc.me","vidsrc.xyz","vidsrc.in","vidsrc.net",
    "2embed.cc","2embed.to","2embed.org",
    "superembed.stream","smashystream.com","autoembed.cc",
    "multiembed.mov","embedgram.com",
    "filemoon.sx","filemoon.to","filemoon.in",
    "streamtape.com","streamtape.to",
    "doodstream.com","dood.watch","dood.to",
    "mixdrop.co","mixdrop.to",
    "upstream.to","upstreamcdn.co",
    "febbox.com","febbox.net",
    "vidplay.online","vidplay.site",
    "megacloud.tv","megacloud.store",
    "rapid-cloud.co","rapid-cloud.ru",
    "gofile.io",
    "streamlare.com",
    "vidmoly.to","vidmoly.me",
    "emturbovid.com","turbovid.me",
    "playm4u.xyz","m4ufree.tv",
    "moviesapi.club","moviesapi.net",
    "aniwave.to","9anime.to","9anime.pl",
    "gogoanime.tel","gogoanime.by",
    "zoro.to","aniwatch.to",
    "kickassanime.am",
    "animesuge.to","animepahe.ru",
]

def find_streams(text):
    found = set()
    for p in STREAM_RE:
        for m in re.findall(p, text, re.IGNORECASE):
            u = m.strip().rstrip('\\"\'`)},;')
            if len(u) > 12 and u.startswith("http"):
                found.add(u)
    # Decode base64 m3u8 data URLs
    for m in re.findall(r'data:application/vnd\.apple\.mpegurl;base64,([A-Za-z0-9+/=]+)', text):
        try:
            decoded = base64.b64decode(m + "==").decode("utf-8", errors="ignore")
            if "#EXTM3U" in decoded:
                found.add(f"[BASE64_M3U8_DECODED]\n{decoded[:2000]}")
        except Exception: pass
    # Unwrap proxy URLs
    for m in re.findall(r'(?:super-proxy|m3u8-proxy|cors-proxy|encoded-proxy)\?url=([^&\s\'"]+)', text, re.IGNORECASE):
        try:
            real = unquote(m)
            if real.startswith("http"):
                found.add(real)
        except Exception: pass
    return sorted(found)

def find_apis(text):
    found = set()
    for p in API_RE:
        for m in re.findall(p, text, re.IGNORECASE):
            u = (m[0] if isinstance(m, tuple) else m).strip()
            if len(u) > 4: found.add(u)
    return sorted(found)

def find_players(text):
    return [n for n, sigs in PLAYER_SIGS.items()
            if any(s.lower() in text.lower() for s in sigs)]

def find_auth_tokens(text):
    found = []
    for p in AUTH_RE:
        for m in re.findall(p, text, re.IGNORECASE):
            t = m if isinstance(m, str) else (m[0] if m else "")
            if len(t) > 8: found.append(t)
    return list(set(found))

def find_embed_urls(text):
    """Find URLs that point to known embed providers."""
    found = set()
    for provider in EMBED_PROVIDERS:
        pattern = r'https?://(?:[a-zA-Z0-9\-]+\.)?' + re.escape(provider) + r'[^\s\'"<>\]\\,\)\}]*'
        for m in re.findall(pattern, text, re.IGNORECASE):
            u = m.strip().rstrip('\\"\'`)},;')
            if len(u) > 10: found.add(u)
    return sorted(found)

def extract_headers_from_requests(reqs):
    all_rq, all_rs, tokens = {}, {}, set()
    for r in reqs:
        rqh = r.get("reqHeaders") or {}
        if isinstance(rqh, dict):
            for k, v in rqh.items():
                all_rq[k] = v
                tokens.update(find_auth_tokens(f"{k}: {v}"))
        rsh = r.get("resHeaders") or {}
        if isinstance(rsh, dict):
            for k, v in rsh.items():
                all_rs[k] = v
        elif isinstance(rsh, str):
            for line in rsh.split("\r\n"):
                if ":" in line:
                    k, _, v = line.partition(":")
                    all_rs[k.strip()] = v.strip()
        tokens.update(find_auth_tokens(r.get("resBody", "")))
    return all_rq, all_rs, sorted(tokens)

# ═══════════════════════════════════════════════════════════════════════════════
# JAVASCRIPT INJECTION  v5
# All regex uses RegExp() constructor — avoids SyntaxError on hostile pages
# ═══════════════════════════════════════════════════════════════════════════════
CONTENT_SCRIPT_JS = r"""
(function() {
    'use strict';
    if (window.__kiro_v5) return;
    window.__kiro_v5 = true;

    window.__kiro_xhr     = [];
    window.__kiro_fetch   = [];
    window.__kiro_console = [];
    window.__kiro_ws      = [];
    window.__kiro_streams = [];
    window.__kiro_perf    = [];
    window.__kiro_nav     = [];
    window.__kiro_tokens  = [];
    window.__kiro_iframes = [];
    window.__kiro_blobs   = [];
    window.__kiro_sw      = [];

    // ── Stream + token sniffer ────────────────────────────────────────────────
    var _sp = [
        new RegExp('https?:\\/\\/[^\\s\'"<>\\]\\\\,\\)\\}]+\\.m3u8[^\\s\'"<>\\]\\\\,\\)\\}]*', 'gi'),
        new RegExp('https?:\\/\\/[^\\s\'"<>\\]\\\\,\\)\\}]+\\.mpd[^\\s\'"<>\\]\\\\,\\)\\}]*', 'gi'),
        new RegExp('https?:\\/\\/[^\\s\'"<>\\]\\\\,\\)\\}]+\\.mp4[^\\s\'"<>\\]\\\\,\\)\\}]*', 'gi'),
        new RegExp('https?:\\/\\/[^\\s\'"<>\\]\\\\,\\)\\}]+\\/manifest(?:\\.m3u8)?[^\\s\'"<>\\]\\\\,\\)\\}]*', 'gi'),
        new RegExp('https?:\\/\\/[^\\s\'"<>\\]\\\\,\\)\\}]+\\/index\\.m3u8[^\\s\'"<>\\]\\\\,\\)\\}]*', 'gi'),
        new RegExp('https?:\\/\\/[^\\s\'"<>\\]\\\\,\\)\\}]+\\/master\\.m3u8[^\\s\'"<>\\]\\\\,\\)\\}]*', 'gi'),
        new RegExp('https?:\\/\\/[^\\s\'"<>\\]\\\\,\\)\\}]+\\/hls\\/[^\\s\'"<>\\]\\\\,\\)\\}]+', 'gi'),
        new RegExp('https?:\\/\\/[^\\s\'"<>\\]\\\\,\\)\\}]+\\/stream\\/[^\\s\'"<>\\]\\\\,\\)\\}]+', 'gi'),
    ];
    var _tp = [
        new RegExp('Bearer\\s+([A-Za-z0-9\\-_\\.]{20,})', 'gi'),
        new RegExp('eyJ[A-Za-z0-9\\-_]+\\.[A-Za-z0-9\\-_]+\\.[A-Za-z0-9\\-_]+', 'g'),
        new RegExp('_rk[\'\"\\s:=,]+([A-Za-z0-9]{20,})', 'gi'),
        new RegExp('secret[\'\"\\s:=,]+([A-Za-z0-9]{20,})', 'gi'),
        new RegExp('ENCRYPTION_KEY[\'\"\\s:=|]+([A-Za-z0-9]{40,})', 'gi'),
        new RegExp('[Xx]-[Aa]pi-[Kk]ey[\'\"\\s:=]+([A-Za-z0-9\\-_\\.]{10,})', 'gi'),
    ];

    function sniff(text) {
        if (!text || typeof text !== 'string' || text.length < 5) return;
        _sp.forEach(function(p) {
            p.lastIndex = 0;
            var m;
            while ((m = p.exec(text)) !== null) {
                var u = m[0].replace(/['"\\`\)\},;\s]+$/, '');
                if (u.length > 12 && window.__kiro_streams.indexOf(u) === -1) {
                    window.__kiro_streams.push(u);
                    try { console.info('[KIRO_STREAM] ' + u); } catch(e) {}
                }
            }
        });
        _tp.forEach(function(p) {
            p.lastIndex = 0;
            var m;
            while ((m = p.exec(text)) !== null) {
                var t = m[1] || m[0];
                if (t && t.length > 8 && window.__kiro_tokens.indexOf(t) === -1)
                    window.__kiro_tokens.push(t);
            }
        });
    }

    // ── Anti-devtools bypass ──────────────────────────────────────────────────
    var _F = Function;
    window.Function = function() {
        var a = Array.prototype.slice.call(arguments);
        var b = a[a.length - 1] || '';
        if (typeof b === 'string' && b.indexOf('debugger') !== -1)
            a[a.length - 1] = b.replace(new RegExp('debugger', 'g'), '/*d*/');
        return _F.apply(this, a);
    };
    window.Function.prototype = _F.prototype;
    var _si = window.setInterval, _st = window.setTimeout;
    window.setInterval = function(fn, d) {
        if (typeof fn === 'function') {
            var s = fn.toString();
            if (s.indexOf('debugger') !== -1 || s.indexOf('devtool') !== -1)
                return _si(function() {}, d);
        }
        return _si.apply(this, arguments);
    };
    window.setTimeout = function(fn, d) {
        if (typeof fn === 'function' && fn.toString().indexOf('debugger') !== -1)
            return _st(function() {}, d);
        return _st.apply(this, arguments);
    };
    try {
        Object.defineProperty(window, 'outerWidth',  {get: function() { return window.innerWidth;  }, configurable: true});
        Object.defineProperty(window, 'outerHeight', {get: function() { return window.innerHeight; }, configurable: true});
        Object.defineProperty(navigator, 'webdriver', {get: function() { return false; }, configurable: true});
        Object.defineProperty(navigator, 'plugins',   {get: function() { return [1,2,3,4,5]; }, configurable: true});
        Object.defineProperty(navigator, 'languages', {get: function() { return ['en-US','en']; }, configurable: true});
    } catch(e) {}
    console.clear = function() {};
    try { Object.defineProperty(console, 'firebug', {get: function() { return false; }}); } catch(e) {}
    var _dw = document.write.bind(document);
    document.write = function(h) {
        if (typeof h === 'string' && (h.indexOf('devtools') !== -1 || h.indexOf('debugger') !== -1)) return;
        return _dw(h);
    };

    // ── Console capture ───────────────────────────────────────────────────────
    ['log','warn','error','info','debug','trace'].forEach(function(m) {
        var orig = console[m];
        console[m] = function() {
            var args = Array.prototype.slice.call(arguments);
            var msg = args.map(function(a) {
                try { return typeof a === 'object' ? JSON.stringify(a) : String(a); }
                catch(e) { return String(a); }
            }).join(' ');
            window.__kiro_console.push({type: m, ts: new Date().toISOString(), msg: msg});
            sniff(msg);
            if (orig) orig.apply(console, arguments);
        };
    });

    // ── XHR capture ───────────────────────────────────────────────────────────
    var _XHR = window.XMLHttpRequest;
    function KiroXHR() {
        var xhr = new _XHR(), method = '', url = '', rqH = {}, rqB = null;
        xhr.open = function(m, u) { method = m; url = u; return _XHR.prototype.open.apply(xhr, arguments); };
        xhr.setRequestHeader = function(k, v) { rqH[k] = v; return _XHR.prototype.setRequestHeader.apply(xhr, arguments); };
        xhr.send = function(body) {
            rqB = body;
            xhr.addEventListener('load', function() {
                var rb = xhr.responseText || '';
                sniff(rb); sniff(url);
                var rh = {};
                (xhr.getAllResponseHeaders() || '').split('\r\n').forEach(function(l) {
                    var i = l.indexOf(':');
                    if (i > 0) rh[l.substring(0, i).trim()] = l.substring(i + 1).trim();
                });
                window.__kiro_xhr.push({
                    ts: new Date().toISOString(), method: method, url: url,
                    status: xhr.status, statusText: xhr.statusText,
                    reqHeaders: rqH, reqBody: rqB ? String(rqB).substring(0, 5000) : null,
                    resHeaders: rh, resBody: rb.substring(0, 200000),
                    contentType: xhr.getResponseHeader('content-type') || ''
                });
            });
            xhr.addEventListener('error', function() {
                window.__kiro_xhr.push({ts: new Date().toISOString(), method: method, url: url, status: 'ERROR'});
            });
            return _XHR.prototype.send.apply(xhr, arguments);
        };
        return xhr;
    }
    KiroXHR.prototype = _XHR.prototype;
    window.XMLHttpRequest = KiroXHR;

    // ── Fetch capture ─────────────────────────────────────────────────────────
    var _fetch = window.fetch;
    window.fetch = function(input, init) {
        var url = typeof input === 'string' ? input : (input && input.url) || String(input);
        var method = (init && init.method) || 'GET';
        var rqH = {};
        try {
            var h = (init && init.headers) || {};
            if (h && typeof h.forEach === 'function') h.forEach(function(v, k) { rqH[k] = v; });
            else if (typeof h === 'object') Object.keys(h).forEach(function(k) { rqH[k] = h[k]; });
        } catch(e) {}
        var entry = {ts: new Date().toISOString(), method: method, url: url,
                     reqHeaders: rqH, reqBody: (init && init.body) ? String(init.body).substring(0, 5000) : null};
        sniff(url);
        return _fetch.apply(window, arguments).then(function(resp) {
            entry.status = resp.status; entry.statusText = resp.statusText;
            var rsh = {};
            try { resp.headers.forEach(function(v, k) { rsh[k] = v; }); } catch(e) {}
            entry.resHeaders = rsh;
            entry.contentType = rsh['content-type'] || '';
            resp.clone().text().then(function(text) {
                sniff(text);
                entry.resBody = text.substring(0, 200000);
                window.__kiro_fetch.push(entry);
            }).catch(function() { window.__kiro_fetch.push(entry); });
            return resp;
        }).catch(function(err) {
            entry.error = String(err);
            window.__kiro_fetch.push(entry);
            throw err;
        });
    };

    // ── WebSocket capture ─────────────────────────────────────────────────────
    var _WS = window.WebSocket;
    window.WebSocket = function(url, protocols) {
        var ws = protocols ? new _WS(url, protocols) : new _WS(url);
        var entry = {url: url, opened: null, closed: null, messages: []};
        ws.addEventListener('open',    function() { entry.opened = new Date().toISOString(); });
        ws.addEventListener('close',   function() { entry.closed = new Date().toISOString(); window.__kiro_ws.push(entry); });
        ws.addEventListener('message', function(e) {
            var d = String(e.data).substring(0, 20000);
            sniff(d);
            entry.messages.push({dir: 'IN', ts: new Date().toISOString(), data: d});
        });
        var _s = ws.send.bind(ws);
        ws.send = function(data) {
            var d = String(data).substring(0, 20000);
            sniff(d);
            entry.messages.push({dir: 'OUT', ts: new Date().toISOString(), data: d});
            return _s(data);
        };
        return ws;
    };
    window.WebSocket.prototype = _WS.prototype;

    // ── Blob URL interception (MediaSource API) ───────────────────────────────
    var _origCreateObjectURL = URL.createObjectURL;
    URL.createObjectURL = function(obj) {
        var url = _origCreateObjectURL.apply(URL, arguments);
        window.__kiro_blobs.push({url: url, type: obj && obj.type || 'unknown', ts: new Date().toISOString()});
        try { console.info('[KIRO_BLOB] ' + url); } catch(e) {}
        return url;
    };

    // ── PerformanceObserver — ALL resource loads ──────────────────────────────
    try {
        var po = new PerformanceObserver(function(list) {
            list.getEntries().forEach(function(e) {
                sniff(e.name);
                window.__kiro_perf.push({
                    name: e.name, type: e.initiatorType,
                    duration: Math.round(e.duration),
                    transferSize: e.transferSize || 0,
                    ts: new Date().toISOString()
                });
            });
        });
        po.observe({entryTypes: ['resource', 'navigation']});
    } catch(e) {}

    // ── Navigation tracker ────────────────────────────────────────────────────
    var _ps = history.pushState, _rs = history.replaceState;
    history.pushState = function() {
        window.__kiro_nav.push({type: 'push', url: arguments[2], ts: new Date().toISOString()});
        return _ps.apply(history, arguments);
    };
    history.replaceState = function() {
        window.__kiro_nav.push({type: 'replace', url: arguments[2], ts: new Date().toISOString()});
        return _rs.apply(history, arguments);
    };

    // ── Video + iframe watcher ────────────────────────────────────────────────
    function checkVideos() {
        document.querySelectorAll('video').forEach(function(v) {
            var cs = v.currentSrc || v.src || '';
            if (cs && cs.length > 5 && cs !== 'about:blank') {
                sniff(cs);
                if (window.__kiro_streams.indexOf(cs) === -1) window.__kiro_streams.push(cs);
            }
        });
        // Shadow DOM piercing
        document.querySelectorAll('*').forEach(function(el) {
            if (el.shadowRoot) {
                el.shadowRoot.querySelectorAll('video').forEach(function(v) {
                    var cs = v.currentSrc || v.src || '';
                    if (cs && cs.length > 5 && window.__kiro_streams.indexOf(cs) === -1)
                        window.__kiro_streams.push(cs);
                });
            }
        });
    }
    function checkIframes() {
        document.querySelectorAll('iframe, frame, embed, object').forEach(function(el, i) {
            var src = el.src || el.data || '';
            if (src && src.length > 5) {
                var exists = window.__kiro_iframes.some(function(x) { return x.src === src; });
                if (!exists) window.__kiro_iframes.push({index: i, tag: el.tagName, src: src, id: el.id || null});
            }
        });
    }
    var _mo = new MutationObserver(function() { checkVideos(); checkIframes(); });
    _mo.observe(document.documentElement, {childList: true, subtree: true, attributes: true});
    setInterval(checkVideos, 2000);
    setInterval(checkIframes, 3000);

    console.info('[KIRO v5] All captures active.');
})();
"""

# ── Collect JS ────────────────────────────────────────────────────────────────
COLLECT_JS = """
(function() {
    if (!window.__kiro_streams) window.__kiro_streams = [];
    if (!window.__kiro_iframes) window.__kiro_iframes = [];
    if (!window.__kiro_blobs)   window.__kiro_blobs   = [];

    // Final video scan including shadow DOM
    document.querySelectorAll('video').forEach(function(v) {
        var cs = v.currentSrc || v.src || '';
        if (cs && cs.length > 5 && cs !== 'about:blank' && window.__kiro_streams.indexOf(cs) === -1)
            window.__kiro_streams.push(cs);
        v.querySelectorAll('source').forEach(function(s) {
            if (s.src && window.__kiro_streams.indexOf(s.src) === -1) window.__kiro_streams.push(s.src);
        });
    });
    document.querySelectorAll('*').forEach(function(el) {
        if (el.shadowRoot) {
            el.shadowRoot.querySelectorAll('video').forEach(function(v) {
                var cs = v.currentSrc || v.src || '';
                if (cs && cs.length > 5 && window.__kiro_streams.indexOf(cs) === -1) window.__kiro_streams.push(cs);
            });
        }
    });

    // Scan inline scripts
    var _re = new RegExp('https?:\\/\\/[^\\s\'"<>\\]\\\\,\\)\\}]+\\.m3u8[^\\s\'"<>\\]\\\\,\\)\\}]*', 'gi');
    document.querySelectorAll('script').forEach(function(s) {
        var t = s.textContent || '';
        var m = t.match(_re);
        if (m) m.forEach(function(u) { if (window.__kiro_streams.indexOf(u) === -1) window.__kiro_streams.push(u); });
    });

    // Final iframe scan
    document.querySelectorAll('iframe, frame, embed, object').forEach(function(el, i) {
        var src = el.src || el.data || '';
        if (src && src.length > 5) {
            var exists = window.__kiro_iframes.some(function(x) { return x.src === src; });
            if (!exists) window.__kiro_iframes.push({index: i, tag: el.tagName, src: src, id: el.id || null});
        }
    });

    // Video element details
    var videos = [];
    document.querySelectorAll('video').forEach(function(v, i) {
        var srcs = [];
        v.querySelectorAll('source').forEach(function(s) { srcs.push({src: s.src, type: s.type}); });
        videos.push({index: i, src: v.src || null, currentSrc: v.currentSrc || null,
                     poster: v.poster || null, readyState: v.readyState,
                     networkState: v.networkState, duration: v.duration || null,
                     paused: v.paused, muted: v.muted, sources: srcs,
                     videoWidth: v.videoWidth, videoHeight: v.videoHeight});
    });

    return {
        xhr:      window.__kiro_xhr     || [],
        fetch:    window.__kiro_fetch   || [],
        console:  window.__kiro_console || [],
        ws:       window.__kiro_ws      || [],
        streams:  window.__kiro_streams || [],
        perf:     window.__kiro_perf    || [],
        nav:      window.__kiro_nav     || [],
        tokens:   window.__kiro_tokens  || [],
        iframes:  window.__kiro_iframes || [],
        blobs:    window.__kiro_blobs   || [],
        videos:   videos,
        url:      window.location.href,
        injected: !!window.__kiro_v5
    };
})();
"""

POLL_JS = """
(function() {
    var urls = (window.__kiro_streams || []).slice();
    document.querySelectorAll('video').forEach(function(v) {
        var cs = v.currentSrc || v.src || '';
        if (cs && cs.length > 5 && cs !== 'about:blank' && urls.indexOf(cs) === -1) urls.push(cs);
    });
    return {found: urls.length > 0, urls: urls, injected: !!window.__kiro_v5};
})();
"""

# ═══════════════════════════════════════════════════════════════════════════════
# FIREFOX EXTENSION + PROFILE + LAUNCH
# ═══════════════════════════════════════════════════════════════════════════════
def build_extension(tmp_dir):
    ext_dir = tmp_dir / "kiro_ext"
    ext_dir.mkdir(exist_ok=True)
    manifest = {
        "manifest_version": 2, "name": "Kiro Capture v5", "version": "5.0",
        "permissions": ["<all_urls>"],
        "content_scripts": [{"matches": ["<all_urls>"], "js": ["capture.js"],
                              "run_at": "document_start", "all_frames": True}],
        "browser_specific_settings": {"gecko": {"id": "kiro-v5@local"}}
    }
    (ext_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (ext_dir / "capture.js").write_text(CONTENT_SCRIPT_JS, encoding="utf-8")
    xpi = tmp_dir / "kiro_v5.xpi"
    with zipfile.ZipFile(xpi, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ext_dir / "manifest.json", "manifest.json")
        zf.write(ext_dir / "capture.js",    "capture.js")
    print(f"[EXT] Built: {xpi}")
    return xpi

def get_real_profile():
    if platform.system() == "Windows":
        base = os.path.join(os.environ["APPDATA"], "Mozilla", "Firefox")
    elif platform.system() == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/Firefox")
    else:
        base = os.path.expanduser("~/.mozilla/firefox")
    ini = os.path.join(base, "profiles.ini")
    if not os.path.exists(ini):
        raise FileNotFoundError(f"profiles.ini not found: {ini}")
    profile_rel = None
    with open(ini, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("Default="):
                val = line.strip().split("=", 1)[1]
                if val not in ("0", "1"):
                    profile_rel = val
                    break
    if not profile_rel:
        raise Exception("No default Firefox profile found.")
    path = os.path.normpath(os.path.join(base, profile_rel.replace("/", os.sep)))
    if not os.path.isdir(path):
        raise FileNotFoundError(f"Profile dir missing: {path}")
    return path

def copy_profile(real_path, tmp_dir):
    dest = str(tmp_dir / "ff_profile")
    print(f"[PROFILE] Copying → {dest}")
    skip = {"cache2","cache","startupCache","thumbnails","storage","minidumps","crashes"}
    os.makedirs(dest, exist_ok=True)
    for item in os.listdir(real_path):
        if item in skip: continue
        s = os.path.join(real_path, item)
        d = os.path.join(dest, item)
        try:
            if os.path.isdir(s): shutil.copytree(s, d, dirs_exist_ok=True)
            else: shutil.copy2(s, d)
        except Exception: pass
    for lock in ["lock", ".parentlock", "parent.lock"]:
        lp = os.path.join(dest, lock)
        if os.path.exists(lp):
            try: os.remove(lp)
            except Exception: pass
    print("[PROFILE] Ready.")
    return dest

def kill_firefox():
    print("[SETUP] Killing Firefox...")
    if platform.system() == "Windows":
        os.system("taskkill /F /IM firefox.exe /T >nul 2>&1")
    else:
        os.system("pkill -9 -f firefox 2>/dev/null")
    time.sleep(3)

def launch_firefox(profile_path, xpi_path):
    print("[SETUP] Getting GeckoDriver...")
    gecko = GeckoDriverManager().install()
    fp = FirefoxProfile(profile_path)
    fp.set_preference("dom.webdriver.enabled",                   False)
    fp.set_preference("useAutomationExtension",                  False)
    fp.set_preference("media.autoplay.default",                  0)
    fp.set_preference("media.autoplay.blocking_policy",          0)
    fp.set_preference("devtools.console.stdout.content",         True)
    fp.set_preference("browser.safebrowsing.enabled",            False)
    fp.set_preference("browser.safebrowsing.malware.enabled",    False)
    fp.set_preference("extensions.allowPrivateBrowsingByDefault",True)
    # Allow cross-origin iframe access for drilling
    fp.set_preference("security.fileuri.strict_origin_policy",   False)
    fp.update_preferences()
    options = Options()
    options.profile = fp
    options.page_load_strategy = "none"
    service = FirefoxService(executable_path=gecko, log_output=subprocess.DEVNULL)
    driver  = webdriver.Firefox(service=service, options=options)
    try:
        driver.install_addon(str(xpi_path), temporary=True)
        print("[EXT] Extension installed.")
    except Exception as e:
        log_error(f"install_addon: {e}")
    driver.maximize_window()
    return driver

# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-ORIGIN IFRAME DRILLING
# Switches into each iframe, injects capture hooks, collects data
# ═══════════════════════════════════════════════════════════════════════════════
def drill_iframes(driver) -> list:
    """Switch into every iframe, inject capture hooks, collect streams."""
    print("[IFRAME] Drilling into iframes...")
    found_streams = []
    iframe_data   = []

    try:
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        iframes += driver.find_elements(By.TAG_NAME, "frame")
    except Exception as e:
        log_error(f"drill_iframes find: {e}")
        return []

    for i, iframe in enumerate(iframes):
        try:
            src = iframe.get_attribute("src") or ""
            print(f"[IFRAME] [{i}] {src[:80]}")
            driver.switch_to.frame(iframe)

            # Inject capture hooks into this iframe context
            safe_exec(driver, CONTENT_SCRIPT_JS)
            time.sleep(2)

            # Collect from iframe
            data = safe_exec(driver, COLLECT_JS, default={}) or {}
            streams = data.get("streams", [])
            found_streams.extend(streams)

            # Get iframe page source
            try:
                iframe_src = driver.page_source
                iframe_dir = OUT_DIR / "iframes"
                (iframe_dir / f"iframe_{i:02d}_source.html").write_text(
                    iframe_src, encoding="utf-8", errors="ignore")
            except Exception: pass

            iframe_entry = {
                "index": i, "src": src,
                "streams": streams,
                "xhr":     len(data.get("xhr",   [])),
                "fetch":   len(data.get("fetch", [])),
                "videos":  data.get("videos", []),
                "iframes": data.get("iframes", []),
            }
            iframe_data.append(iframe_entry)

            if streams:
                print(f"[IFRAME] ✓ Found streams in iframe {i}: {streams}")

            # Save iframe network data
            if data.get("xhr") or data.get("fetch"):
                save_json(data.get("xhr",   []), f"iframes/iframe_{i:02d}_xhr.json")
                save_json(data.get("fetch", []), f"iframes/iframe_{i:02d}_fetch.json")

            driver.switch_to.default_content()

        except Exception as e:
            log_error(f"drill_iframes [{i}]: {e}")
            try: driver.switch_to.default_content()
            except Exception: pass

    save_json(iframe_data, "iframes_drilled.json")
    print(f"[IFRAME] Drilled {len(iframes)} iframes. Streams found: {len(found_streams)}")
    return found_streams

# ═══════════════════════════════════════════════════════════════════════════════
# EMBED TAB OPENER
# Opens discovered embed URLs in new tabs and captures their network traffic
# ═══════════════════════════════════════════════════════════════════════════════
def open_embed_tabs(driver, embed_urls: list) -> list:
    """Open each embed URL in a new tab, inject hooks, collect streams."""
    if not embed_urls:
        return []
    print(f"[TABS] Opening {len(embed_urls)} embed URLs in new tabs...")
    found_streams = []
    original_handle = driver.current_window_handle

    for i, url in enumerate(embed_urls[:8]):  # cap at 8 tabs
        try:
            print(f"[TABS] [{i}] {url[:80]}")
            driver.execute_script(f"window.open('{url}', '_blank');")
            time.sleep(1)

            # Switch to new tab
            handles = driver.window_handles
            new_handle = [h for h in handles if h != original_handle]
            if not new_handle:
                continue
            driver.switch_to.window(new_handle[-1])

            # Inject hooks immediately
            safe_exec(driver, CONTENT_SCRIPT_JS)
            time.sleep(8)  # wait for embed to load

            # Collect
            data = safe_exec(driver, COLLECT_JS, default={}) or {}
            streams = data.get("streams", [])
            found_streams.extend(streams)

            # Save tab data
            tab_dir = OUT_DIR / "embed_tabs"
            try:
                src = driver.page_source
                (tab_dir / f"tab_{i:02d}_source.html").write_text(src, encoding="utf-8", errors="ignore")
            except Exception: pass

            save_json(data.get("xhr",   []), f"embed_tabs/tab_{i:02d}_xhr.json")
            save_json(data.get("fetch", []), f"embed_tabs/tab_{i:02d}_fetch.json")
            save_json({"url": url, "streams": streams, "videos": data.get("videos", [])},
                      f"embed_tabs/tab_{i:02d}_summary.json")

            if streams:
                print(f"[TABS] ✓ Streams from tab {i}: {streams}")

            # Close tab
            driver.close()
            driver.switch_to.window(original_handle)

        except Exception as e:
            log_error(f"open_embed_tabs [{i}] [{url}]: {e}")
            try:
                driver.switch_to.window(original_handle)
            except Exception: pass

    print(f"[TABS] Done. Total streams from embed tabs: {len(found_streams)}")
    return found_streams

# ═══════════════════════════════════════════════════════════════════════════════
# KNOWN EMBED PROVIDER HANDLERS
# Direct Python extractors for common embed sites
# ═══════════════════════════════════════════════════════════════════════════════
def make_scraper_session(cookies=None):
    """Build a cloudscraper session (bypasses Cloudflare JS challenges)."""
    try:
        sc = cloudscraper.create_scraper(
            browser={"browser": "firefox", "platform": "windows", "mobile": False}
        )
        sc.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
            "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        })
        if cookies:
            for c in cookies:
                sc.cookies.set(c["name"], c["value"], domain=c.get("domain",""))
        return sc
    except Exception:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"})
        return s

def extract_vidsrc(tmdb_id, content_type="movie", session=None) -> list:
    """VidSrc.to / VidSrc.me direct extractor."""
    streams = []
    s = session or make_scraper_session()
    urls_to_try = [
        f"https://vidsrc.to/embed/{content_type}/{tmdb_id}",
        f"https://vidsrc.me/embed/{content_type}?tmdb={tmdb_id}",
        f"https://vidsrc.xyz/embed/{content_type}/{tmdb_id}",
        f"https://vidsrc.in/embed/{content_type}/{tmdb_id}",
    ]
    for url in urls_to_try:
        try:
            r = s.get(url, timeout=20)
            if r.status_code == 200:
                found = find_streams(r.text)
                streams.extend(found)
                # Look for src_id / data-hash patterns
                for m in re.findall(r'src_id\s*=\s*[\'"]([^\'"]+)[\'"]', r.text):
                    streams.append(f"[VIDSRC_SRC_ID] {m}")
                if found:
                    print(f"[VIDSRC] ✓ {url} → {found}")
        except Exception as e:
            log_error(f"extract_vidsrc [{url}]: {e}")
    return streams

def extract_2embed(tmdb_id, content_type="movie", session=None) -> list:
    """2embed.cc direct extractor."""
    streams = []
    s = session or make_scraper_session()
    urls_to_try = [
        f"https://www.2embed.cc/embed/{tmdb_id}",
        f"https://2embed.to/embed/tmdb/{content_type}?id={tmdb_id}",
        f"https://www.2embed.org/embed/{content_type}/{tmdb_id}",
    ]
    for url in urls_to_try:
        try:
            r = s.get(url, timeout=20, headers={"Referer": "https://www.google.com/"})
            if r.status_code == 200:
                found = find_streams(r.text)
                streams.extend(found)
                embeds = find_embed_urls(r.text)
                streams.extend([f"[EMBED_URL] {e}" for e in embeds])
                if found: print(f"[2EMBED] ✓ {url} → {found}")
        except Exception as e:
            log_error(f"extract_2embed [{url}]: {e}")
    return streams

def extract_superembed(tmdb_id, content_type="movie", session=None) -> list:
    """SuperEmbed / SmashyStream extractor."""
    streams = []
    s = session or make_scraper_session()
    urls_to_try = [
        f"https://multiembed.mov/?video_id={tmdb_id}&tmdb=1",
        f"https://superembed.stream/embed/{content_type}/{tmdb_id}",
        f"https://smashystream.com/playere.php?id={tmdb_id}",
        f"https://autoembed.cc/embed/{content_type}/{tmdb_id}",
    ]
    for url in urls_to_try:
        try:
            r = s.get(url, timeout=20)
            if r.status_code == 200:
                found = find_streams(r.text)
                streams.extend(found)
                if found: print(f"[SUPEREMBED] ✓ {url} → {found}")
        except Exception as e:
            log_error(f"extract_superembed [{url}]: {e}")
    return streams

def try_all_embed_providers(tmdb_id, content_type="movie", driver_cookies=None) -> list:
    """Try all known embed providers for a given tmdb_id."""
    print(f"[PROVIDERS] Trying all embed providers for tmdbId={tmdb_id}...")
    session = make_scraper_session(driver_cookies)
    all_streams = []
    all_streams.extend(extract_vidsrc(tmdb_id, content_type, session))
    all_streams.extend(extract_2embed(tmdb_id, content_type, session))
    all_streams.extend(extract_superembed(tmdb_id, content_type, session))
    all_streams = sorted(set(s for s in all_streams if s.startswith("http")))
    save_json({"tmdb_id": tmdb_id, "content_type": content_type,
               "streams": all_streams}, "embed_providers_results.json")
    print(f"[PROVIDERS] Total streams from embed providers: {len(all_streams)}")
    return all_streams

# ═══════════════════════════════════════════════════════════════════════════════
# AES-256-GCM DECRYPTION + CONTENT HASH GENERATION
# Extracted from cinemaos chunk analysis
# ═══════════════════════════════════════════════════════════════════════════════
def aes_gcm_decrypt(encrypted_hex: str, cin_hex: str, mao_hex: str,
                    key_hex: str, salt_hex: str = None) -> dict:
    """
    Decrypt cinemaos AES-256-GCM encrypted API responses.
    Fields: encrypted=ciphertext, cin=IV/nonce, mao=auth_tag
    Key from chunk: a1b2c3d4e4f6477658455678901477567890abcdef1234567890abcdef123456
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        key        = bytes.fromhex(key_hex)
        nonce      = bytes.fromhex(cin_hex)
        ciphertext = bytes.fromhex(encrypted_hex)
        auth_tag   = bytes.fromhex(mao_hex)
        # In AES-GCM, auth tag is appended to ciphertext
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext + auth_tag, None)
        return json.loads(plaintext.decode("utf-8"))
    except ImportError:
        log_error("cryptography package not installed — run: pip install cryptography")
        return {}
    except Exception as e:
        log_error(f"aes_gcm_decrypt: {e}")
        return {}

def generate_content_hash_python(tmdb_id: str, imdb_id: str = None,
                                  season_id: str = None, episode_id: str = None) -> str:
    """
    Reverse-engineered generateContentHash from cinemaos chunk 1386.
    The function builds a canonical string from the media identifiers
    and hashes it. Based on the chunk code pattern, it uses SHA-256
    of a JSON-serialized sorted object.
    """
    data = {"tmdbId": tmdb_id}
    if imdb_id:   data["imdbId"]   = imdb_id
    if season_id: data["seasonId"] = season_id
    if episode_id:data["episodeId"]= episode_id
    # Canonical JSON (sorted keys, no spaces) — matches JS JSON.stringify behavior
    canonical = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()

def generate_content_hash_node(tmdb_id: str, chunk_path: str,
                                imdb_id: str = None) -> str:
    """
    Execute the actual generateContentHash function from the downloaded chunk
    using Node.js — 100% accurate, no reverse-engineering needed.
    """
    if not node_available():
        return generate_content_hash_python(tmdb_id, imdb_id)
    try:
        # Extract the generateContentHash function from the chunk
        chunk_text = Path(chunk_path).read_text(encoding="utf-8", errors="ignore")
        # Find the function definition
        match = re.search(
            r'generateContentHash\s*[=:]\s*(?:function\s*)?\(([^)]*)\)\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}',
            chunk_text, re.DOTALL)
        if not match:
            return generate_content_hash_python(tmdb_id, imdb_id)

        func_body = match.group(2)
        node_script = f"""
const crypto = require('crypto');
function generateContentHash(data) {{
    {func_body}
}}
const result = generateContentHash({{
    tmdbId: "{tmdb_id}",
    {f'imdbId: "{imdb_id}",' if imdb_id else ''}
}});
console.log(result);
"""
        tmp_js = Path(tempfile.mktemp(suffix=".js"))
        tmp_js.write_text(node_script, encoding="utf-8")
        r = subprocess.run(["node", str(tmp_js)], capture_output=True, text=True, timeout=10)
        tmp_js.unlink(missing_ok=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception as e:
        log_error(f"generate_content_hash_node: {e}")
    return generate_content_hash_python(tmdb_id, imdb_id)

# ═══════════════════════════════════════════════════════════════════════════════
# STREAM VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════
def validate_stream_url(url: str, session=None) -> dict:
    """HEAD request to verify a stream URL is actually live and accessible."""
    if not url.startswith("http"):
        return {"url": url, "valid": False, "reason": "not http"}
    s = session or requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"})
    try:
        r = s.head(url, timeout=10, allow_redirects=True)
        ct = r.headers.get("content-type", "")
        valid = r.status_code in (200, 206) or "m3u8" in ct or "mpegurl" in ct or "video" in ct
        return {"url": url, "valid": valid, "status": r.status_code,
                "content_type": ct, "content_length": r.headers.get("content-length")}
    except Exception as e:
        return {"url": url, "valid": False, "reason": str(e)}

# ═══════════════════════════════════════════════════════════════════════════════
# YT-DLP FALLBACK
# ═══════════════════════════════════════════════════════════════════════════════
def try_ytdlp(url: str, cookies_file: str = None) -> list:
    """Use yt-dlp to extract stream URLs as a fallback."""
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, timeout=5)
    except Exception:
        print("[YTDLP] yt-dlp not found — skipping.")
        return []

    print(f"[YTDLP] Trying yt-dlp on: {url}")
    cmd = ["yt-dlp", "--get-url", "--no-warnings", "-q", url]
    if cookies_file and Path(cookies_file).exists():
        cmd += ["--cookies", cookies_file]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            urls = [u.strip() for u in r.stdout.strip().split("\n") if u.strip().startswith("http")]
            print(f"[YTDLP] ✓ Found {len(urls)} URL(s)")
            save_json({"source_url": url, "extracted": urls}, "ytdlp_results.json")
            return urls
        else:
            log_error(f"yt-dlp: {r.stderr[:500]}")
    except Exception as e:
        log_error(f"try_ytdlp: {e}")
    return []

# ═══════════════════════════════════════════════════════════════════════════════
# DIRECT API CRACKER  v5
# ═══════════════════════════════════════════════════════════════════════════════
def build_session(driver) -> requests.Session:
    parsed = urlparse(TARGET_URL)
    base   = f"{parsed.scheme}://{parsed.netloc}"
    try:
        sc = cloudscraper.create_scraper(
            browser={"browser": "firefox", "platform": "windows", "mobile": False})
    except Exception:
        sc = requests.Session()
    sc.headers.update({
        "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
        "Accept":          "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer":         TARGET_URL,
        "Origin":          base,
        "DNT":             "1",
        "Sec-Fetch-Dest":  "empty",
        "Sec-Fetch-Mode":  "cors",
        "Sec-Fetch-Site":  "same-origin",
    })
    try:
        for c in driver.get_cookies():
            sc.cookies.set(c["name"], c["value"],
                           domain=c.get("domain",""), path=c.get("path","/"))
    except Exception as e:
        log_error(f"build_session cookies: {e}")
    return sc

def crack_stream_api(driver, chunks_index: list, live_tokens: list) -> dict:
    """
    Multi-strategy stream API cracker:
    1. Replay captured tokens + _rk key in direct API calls
    2. Generate content hash and call /api/providerv4 with correct params
    3. Decrypt AES-256-GCM responses
    4. Try all discovered API endpoints
    5. Try known embed providers
    """
    print("[API] Starting stream API crack...")
    parsed = urlparse(TARGET_URL)
    base   = f"{parsed.scheme}://{parsed.netloc}"
    session = build_session(driver)

    # Extract tmdb_id from URL
    tmdb_match = re.search(r'/(?:player|movie|watch|embed)/(\d+)', TARGET_URL)
    tmdb_id    = tmdb_match.group(1) if tmdb_match else "1318447"

    # Known encryption key from chunk analysis
    ENCRYPTION_KEY = "a1b2c3d4e4f6477658455678901477567890abcdef1234567890abcdef123456"
    # Known _rk from chunk analysis
    RK_KEY = "2549b22d9bf0d91847a2811baac98d0079e02dba592aea94"

    results = {
        "target": TARGET_URL, "base": base, "tmdb_id": tmdb_id,
        "endpoints_tried": [], "stream_urls": [], "decrypted_responses": []
    }

    # ── Strategy 1: cinemaos providerv4 with correct secret + _rk ────────────
    print(f"[API] Strategy 1: providerv4 with generated secret + _rk...")

    # Find the hash chunk
    hash_chunk_path = None
    for chunk in chunks_index:
        if "1386" in chunk.get("saved_as", "") or "1386" in chunk.get("url", ""):
            hash_chunk_path = str(OUT_DIR / "chunks" / chunk["saved_as"])
            break

    secret = generate_content_hash_node(tmdb_id, hash_chunk_path or "") if hash_chunk_path \
             else generate_content_hash_python(tmdb_id)
    print(f"[API] Generated secret: {secret[:20]}...")

    for content_type in ["movie", "tv"]:
        try:
            params = {
                "tmdbId": tmdb_id,
                "type": content_type,
                "secret": secret,
                "_rk": RK_KEY,
            }
            url = f"{base}/api/providerv4"
            r = session.get(url, params=params, timeout=30)
            results["endpoints_tried"].append({"url": url, "params": params, "status": r.status_code})
            print(f"[API] providerv4?type={content_type} → HTTP {r.status_code}")

            if r.status_code == 200 and r.text.strip():
                try:
                    data = r.json()
                    save_json(data, f"api_responses/providerv4_{content_type}.json")
                    # Check if encrypted
                    if data.get("encrypted") and data.get("data"):
                        print("[API] Response is encrypted — attempting AES-256-GCM decrypt...")
                        enc_data = data["data"]
                        if isinstance(enc_data, dict):
                            decrypted = aes_gcm_decrypt(
                                enc_data.get("encrypted",""),
                                enc_data.get("cin",""),
                                enc_data.get("mao",""),
                                ENCRYPTION_KEY,
                                enc_data.get("salt","")
                            )
                            if decrypted:
                                save_json(decrypted, f"api_responses/providerv4_{content_type}_decrypted.json")
                                results["decrypted_responses"].append(decrypted)
                                streams = find_streams(json.dumps(decrypted))
                                results["stream_urls"].extend(streams)
                                if streams: print(f"[API] ✓ Decrypted streams: {streams}")
                    else:
                        streams = find_streams(json.dumps(data))
                        results["stream_urls"].extend(streams)
                        if streams: print(f"[API] ✓ Direct streams: {streams}")
                except Exception as e:
                    log_error(f"providerv4 parse: {e}")
                    streams = find_streams(r.text)
                    results["stream_urls"].extend(streams)
        except Exception as e:
            log_error(f"providerv4 [{content_type}]: {e}")

    # ── Strategy 2: providerv4/scrape with each scraper ───────────────────────
    print("[API] Strategy 2: providerv4/scrape with all scrapers...")
    scrapers = ["alpha","delta","Pkaystream","nexus4k","cinemaos","primary","backup","hd","stream","main"]
    for scraper in scrapers:
        try:
            params = {"scraper": scraper, "tmdbId": tmdb_id,
                      "contentType": "movie", "secret": secret, "_rk": RK_KEY}
            r = session.get(f"{base}/api/providerv4/scrape", params=params, timeout=25)
            results["endpoints_tried"].append({"url": f"{base}/api/providerv4/scrape",
                                               "scraper": scraper, "status": r.status_code})
            if r.status_code == 200 and r.text.strip():
                try:
                    data = r.json()
                    streams = find_streams(json.dumps(data))
                    if streams:
                        save_json(data, f"api_responses/scrape_{scraper}.json")
                        results["stream_urls"].extend(streams)
                        print(f"[API] ✓ Scraper '{scraper}': {streams}")
                except Exception:
                    streams = find_streams(r.text)
                    results["stream_urls"].extend(streams)
        except Exception as e:
            log_error(f"scrape[{scraper}]: {e}")

    # ── Strategy 3: replay live captured tokens ───────────────────────────────
    if live_tokens:
        print(f"[API] Strategy 3: replaying {len(live_tokens)} captured tokens...")
        for token in live_tokens[:5]:
            try:
                session.headers["Authorization"] = f"Bearer {token}"
                r = session.get(f"{base}/api/providerv4",
                                params={"tmdbId": tmdb_id, "contentType": "movie"},
                                timeout=20)
                if r.status_code == 200:
                    streams = find_streams(r.text)
                    results["stream_urls"].extend(streams)
                    if streams: print(f"[API] ✓ Token replay streams: {streams}")
            except Exception as e:
                log_error(f"token_replay: {e}")
        del session.headers["Authorization"]

    # ── Strategy 4: all discovered API endpoints ──────────────────────────────
    print("[API] Strategy 4: all discovered endpoints from chunks...")
    all_apis = set()
    for chunk in chunks_index:
        for api in chunk.get("apis", []):
            if api.startswith("/"):
                all_apis.add(base + api)
            elif api.startswith("http"):
                all_apis.add(api)

    for url in sorted(all_apis):
        if any(x in url.lower() for x in ["google","gtag","analytics","font","css",
                                            "favicon","icon","png","jpg","socket.io/docs"]):
            continue
        try:
            r = session.get(url, timeout=15)
            results["endpoints_tried"].append({"url": url, "status": r.status_code})
            if r.status_code == 200 and r.text.strip():
                streams = find_streams(r.text)
                if streams:
                    results["stream_urls"].extend(streams)
                    save_json({"url": url, "streams": streams},
                              f"api_responses/endpoint_{short_hash(url)}.json")
                    print(f"[API] ✓ {url} → {streams}")
        except Exception as e:
            log_error(f"endpoint [{url}]: {e}")

    results["stream_urls"] = sorted(set(results["stream_urls"]))
    save_json(results, "api_direct_results.json")
    print(f"[API] Done. Tried:{len(results['endpoints_tried'])} Streams:{len(results['stream_urls'])}")
    return results

# ═══════════════════════════════════════════════════════════════════════════════
# CAPTURE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════
def wait_for_stream(driver, timeout=STREAM_WAIT_SEC) -> list:
    print(f"[STREAM] Polling for stream URLs (up to {timeout}s)...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = driver.execute_script(POLL_JS)
            if r:
                if not r.get("injected"):
                    safe_exec(driver, CONTENT_SCRIPT_JS)
                if r.get("found") and r.get("urls"):
                    urls = r["urls"]
                    print(f"[STREAM] ✓ {len(urls)} stream URL(s):")
                    for u in urls: print(f"         → {u}")
                    return urls
        except Exception as e:
            log_error(f"wait_for_stream: {e}")
        time.sleep(2)
    print(f"[STREAM] None found after {timeout}s.")
    return []

def collect_all(driver) -> dict:
    data = safe_exec(driver, COLLECT_JS, default={}) or {}
    if not data: return {}
    xhr     = data.get("xhr",     [])
    fetch   = data.get("fetch",   [])
    console = data.get("console", [])
    ws      = data.get("ws",      [])
    streams = data.get("streams", [])
    perf    = data.get("perf",    [])
    nav     = data.get("nav",     [])
    tokens  = data.get("tokens",  [])
    iframes = data.get("iframes", [])
    blobs   = data.get("blobs",   [])
    videos  = data.get("videos",  [])

    save_json(xhr,     "network_xhr.json")
    save_json(fetch,   "network_fetch.json")
    save_json(console, "console_log.json")
    save_json(ws,      "websocket_log.json")
    save_json(perf,    "network_resources.json")
    save_json(nav,     "navigation_log.json")
    save_json(videos,  "video_elements.json")
    save_json(iframes, "iframes_live.json")
    save_json(blobs,   "blob_urls.json")

    combined = []
    for r in xhr:   r["_type"]="XHR";      combined.append(r)
    for r in fetch: r["_type"]="Fetch";    combined.append(r)
    for r in perf:  r["_type"]="Resource"; combined.append(r)
    combined.sort(key=lambda x: x.get("ts",""))
    save_json(combined, "network_all_requests.json")

    all_rq, all_rs, found_tokens = extract_headers_from_requests(xhr + fetch)
    all_tokens = sorted(set(tokens + found_tokens))
    save_json({
        "captured_at":      datetime.now().isoformat(),
        "request_headers":  all_rq,
        "response_headers": all_rs,
        "tokens_found":     all_tokens,
        "auth_headers":     {k:v for k,v in all_rq.items()
                             if any(x in k.lower() for x in ["auth","token","key","bearer","secret","api"])},
        "user_agents":      list(set(v for k,v in all_rq.items() if k.lower()=="user-agent")),
        "referers":         list(set(v for k,v in all_rq.items() if k.lower()=="referer")),
        "origins":          list(set(v for k,v in all_rq.items() if k.lower()=="origin")),
        "cookies_sent":     [v for k,v in all_rq.items() if k.lower()=="cookie"],
    }, "headers_and_auth.json")

    print(f"[LOGS] XHR:{len(xhr)} Fetch:{len(fetch)} Resources:{len(perf)} "
          f"Console:{len(console)} WS:{len(ws)} Streams:{len(streams)} "
          f"Tokens:{len(all_tokens)} Iframes:{len(iframes)} Blobs:{len(blobs)}")
    return data

def save_page_source(driver) -> str:
    try:
        src = driver.page_source
        save_text(src, "page_source.html")
        return src
    except Exception as e:
        log_error(f"save_page_source: {e}")
        return ""

def extract_meta(driver, url):
    meta = safe_exec(driver, """
        var m={};
        document.querySelectorAll('meta').forEach(function(el){
            var k=el.name||el.property||el.httpEquiv||'?'; m[k]=el.content;
        });
        return {title:document.title, url:window.location.href,
                charset:document.characterSet, metas:m,
                links:Array.from(document.querySelectorAll('a[href]'))
                    .map(function(a){return a.href;})
                    .filter(function(h){return h.startsWith('http');}).slice(0,300)};
    """, default={}) or {}
    try: meta["cookies"] = driver.get_cookies()
    except Exception: pass
    meta["captured_at"] = datetime.now().isoformat()
    meta["target_url"]  = url
    save_json(meta, "page_meta.json")

def extract_storage(driver):
    s = safe_exec(driver, """
        var ls={},ss={};
        try{for(var k in localStorage){if(localStorage.hasOwnProperty(k))ls[k]=localStorage.getItem(k);}}catch(e){}
        try{for(var k in sessionStorage){if(sessionStorage.hasOwnProperty(k))ss[k]=sessionStorage.getItem(k);}}catch(e){}
        return {localStorage:ls,sessionStorage:ss};
    """, default={})
    if s: save_json(s, "browser_storage.json")

def extract_cookies_detailed(driver):
    try:
        cookies = driver.get_cookies()
        save_json(cookies, "cookies_full.json")
        lines = ["# Netscape HTTP Cookie File", "# Generated by Kiro v5", ""]
        for c in cookies:
            domain = c.get("domain","")
            flag   = "TRUE" if domain.startswith(".") else "FALSE"
            lines.append(f"{domain}\t{flag}\t{c.get('path','/')}\t"
                         f"{'TRUE' if c.get('secure') else 'FALSE'}\t"
                         f"{int(c.get('expiry',0))}\t{c.get('name','')}\t{c.get('value','')}")
        save_text("\n".join(lines), "cookies_netscape.txt")
        print(f"[COOKIES] {len(cookies)} cookies saved.")
    except Exception as e:
        log_error(f"extract_cookies_detailed: {e}")

def extract_scripts(driver, base_url) -> list:
    raw = safe_exec(driver, """
        var r=[];
        document.querySelectorAll('script').forEach(function(s,i){
            r.push({index:i,src:s.src||null,type:s.type||'text/javascript',
                    inline:s.src?null:s.textContent});
        });
        return r;
    """, default=[]) or []
    data = []
    seen = set()
    for sc in raw:
        idx=sc.get("index",0); src=sc.get("src"); inline=sc.get("inline") or ""
        entry={"index":idx,"src":src,"type":sc.get("type"),
               "players":[],"streams":[],"apis":[],"tokens":[],"embeds":[]}
        if src and src not in seen:
            seen.add(src)
            try:
                resp = requests.get(src, timeout=15,
                    headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
                             "Referer":base_url})
                code = resp.text
                entry.update({"status":resp.status_code,"players":find_players(code),
                               "streams":find_streams(code),"apis":find_apis(code)[:30],
                               "tokens":find_auth_tokens(code),"embeds":find_embed_urls(code)})
                fname=f"script_{idx:03d}_external.js"
                save_text(beautify_js(code), f"scripts/{fname}")
                entry["saved_as"]=fname
            except Exception as e:
                log_error(f"fetch script [{src}]: {e}")
        elif inline.strip():
            entry.update({"players":find_players(inline),"streams":find_streams(inline),
                           "apis":find_apis(inline)[:30],"tokens":find_auth_tokens(inline),
                           "embeds":find_embed_urls(inline)})
            fname=f"script_{idx:03d}_inline.js"
            save_text(beautify_js(inline), f"scripts/{fname}")
            entry["saved_as"]=fname
        data.append(entry)
    save_json(data, "scripts_index.json")
    print(f"[SCRIPTS] {len(data)} scripts extracted.")
    return data

def fetch_chunks(base_url) -> list:
    print("[CHUNKS] Fetching lazy JS chunks...")
    ps_path = OUT_DIR / "page_source.html"
    if not ps_path.exists(): return []
    html = ps_path.read_text(encoding="utf-8", errors="ignore")
    parsed = urlparse(base_url)
    root   = f"{parsed.scheme}://{parsed.netloc}"
    paths  = set()
    paths.update(re.findall(r'["\']?(static/chunks/[a-zA-Z0-9/_\-\.\[\]%]+\.js)["\']?', html))
    paths.update(re.findall(r'["\']?(static/chunks/app/[a-zA-Z0-9/_\-\.\[\]%]+\.js)["\']?', html))
    paths.update(re.findall(r'["\']?(_next/static/[a-zA-Z0-9/_\-\.\[\]%]+\.js)["\']?', html))
    found_streams=[]; index=[]
    for path in sorted(paths):
        url = f"{root}/_next/{path}" if not path.startswith("_next") else f"{root}/{path}"
        fname = "chunk_"+short_hash(url)+"_"+Path(path).name
        out   = OUT_DIR/"chunks"/fname
        if out.exists(): continue
        try:
            resp = requests.get(url, timeout=20,
                headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
                         "Referer":base_url})
            if resp.status_code==200:
                code=resp.text
                streams=find_streams(code); apis=find_apis(code)
                players=find_players(code); tokens=find_auth_tokens(code)
                embeds=find_embed_urls(code)
                found_streams.extend(streams)
                out.write_text(beautify_js(code), encoding="utf-8")
                entry={"url":url,"saved_as":fname,"size":len(code),
                       "streams":streams,"apis":apis[:30],"players":players,
                       "tokens":tokens,"embeds":embeds}
                index.append(entry)
                if streams or players or tokens or embeds:
                    print(f"[CHUNK] {Path(path).name} → streams:{len(streams)} players:{players} tokens:{len(tokens)} embeds:{len(embeds)}")
        except Exception as e:
            log_error(f"fetch_chunk [{url}]: {e}")
    save_json(index, "chunks_index.json")
    print(f"[CHUNKS] {len(index)} chunks fetched.")
    return found_streams


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY BUILDER
# ═══════════════════════════════════════════════════════════════════════════════
def build_summary(all_streams, scripts, page_src, log_data, api_results, url):
    # Aggregate streams from every source
    stream_set = set(all_streams)
    for sc in scripts:
        stream_set.update(sc.get("streams", []))
    for r in log_data.get("fetch", []) + log_data.get("xhr", []):
        stream_set.update(find_streams(r.get("resBody", "")))
        u = r.get("url", "")
        if any(x in u.lower() for x in [".m3u8",".mpd",".mp4","/hls/","/dash/","/manifest"]):
            stream_set.add(u)
    stream_set.update(log_data.get("streams", []))
    for v in log_data.get("videos", []):
        for k in ["currentSrc","src"]:
            if v.get(k) and len(v[k]) > 5: stream_set.add(v[k])
    for r in log_data.get("perf", []):
        n = r.get("name","")
        if any(x in n.lower() for x in [".m3u8",".mpd",".mp4","/hls/","/manifest",".ts"]):
            stream_set.add(n)
    stream_set.update(api_results.get("stream_urls", []))
    # Filter to real http URLs only
    stream_list = sorted(u for u in stream_set
                         if u and len(u) > 10 and u.startswith("http"))

    # Validate streams if enabled
    validated = []
    if VALIDATE_STREAMS and stream_list:
        print(f"[VALIDATE] Checking {len(stream_list)} stream URL(s)...")
        vsession = requests.Session()
        vsession.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0"
        for u in stream_list:
            result = validate_stream_url(u, vsession)
            validated.append(result)
            status = "✓ LIVE" if result["valid"] else "✗ dead"
            print(f"[VALIDATE] {status} {u[:80]}")
        save_json(validated, "stream_validation.json")

    # Aggregate APIs
    api_set = set()
    for sc in scripts: api_set.update(sc.get("apis", []))
    for r in log_data.get("fetch",[]) + log_data.get("xhr",[]): api_set.add(r.get("url",""))
    api_set.update(find_apis(page_src))
    api_list = sorted(u for u in api_set if u and len(u) > 4)

    # Aggregate tokens
    token_set = set(log_data.get("tokens", []))
    for sc in scripts: token_set.update(sc.get("tokens", []))
    token_list = sorted(token_set)

    # Aggregate embed URLs
    embed_set = set()
    for sc in scripts: embed_set.update(sc.get("embeds", []))
    embed_set.update(find_embed_urls(page_src))
    embed_list = sorted(embed_set)

    players = find_players(page_src)
    for sc in scripts: players = list(set(players + sc.get("players",[])))

    iframes = log_data.get("iframes", [])
    blobs   = log_data.get("blobs",   [])

    summary = {
        "target_url":          url,
        "captured_at":         datetime.now().isoformat(),
        "injection_active":    log_data.get("injected", False),
        "detected_players":    players,
        "stream_urls":         stream_list,
        "total_streams":       len(stream_list),
        "live_streams":        [v["url"] for v in validated if v.get("valid")],
        "api_endpoints":       api_list,
        "total_apis":          len(api_list),
        "tokens_found":        token_list,
        "embed_urls":          embed_list,
        "iframes":             iframes,
        "blob_urls":           [b.get("url","") for b in blobs],
        "scripts":             len(scripts),
        "xhr":                 len(log_data.get("xhr",     [])),
        "fetch":               len(log_data.get("fetch",   [])),
        "resources":           len(log_data.get("perf",    [])),
        "console":             len(log_data.get("console", [])),
        "ws":                  len(log_data.get("ws",      [])),
        "videos":              len(log_data.get("videos",  [])),
        "api_endpoints_tried": len(api_results.get("endpoints_tried", [])),
        "decrypted_responses": len(api_results.get("decrypted_responses", [])),
    }
    save_json(summary, "SUMMARY.json")

    # stream_urls.json — clean ready-to-use
    if stream_list:
        m3u8  = [u for u in stream_list if ".m3u8" in u.lower()]
        mpd   = [u for u in stream_list if ".mpd"  in u.lower()]
        mp4   = [u for u in stream_list if ".mp4"  in u.lower()]
        other = [u for u in stream_list if u not in m3u8+mpd+mp4]
        live  = [v["url"] for v in validated if v.get("valid")] if validated else stream_list
        best  = (live or m3u8 or mpd or mp4 or other or [""])[0]
        save_json({
            "best":       best,
            "hls_m3u8":   m3u8,
            "dash_mpd":   mpd,
            "mp4_direct": mp4,
            "other":      other,
            "all":        stream_list,
            "live_only":  live,
            "python_code": (
                f'stream_url = "{best}"\n\n'
                '# Play with mpv:\nimport subprocess\n'
                'subprocess.run(["mpv", stream_url])\n\n'
                '# Download with yt-dlp:\n'
                'subprocess.run(["yt-dlp", stream_url, "-o", "output.%(ext)s"])\n\n'
                '# Download with ffmpeg:\n'
                'subprocess.run(["ffmpeg", "-i", stream_url, "-c", "copy", "output.mp4"])\n'
            )
        }, "stream_urls.json")

    # SUMMARY.txt
    sep = "=" * 72
    lines = [sep, "  DEVTOOLS CAPTURE SUMMARY  v5.0", sep,
             f"  URL          : {url}",
             f"  Captured     : {summary['captured_at']}",
             f"  Injection    : {'✓ ACTIVE' if summary['injection_active'] else '✗ NOT ACTIVE'}",
             f"  Players      : {', '.join(players) if players else 'None'}",
             f"  Scripts      : {summary['scripts']}",
             f"  XHR          : {summary['xhr']}",
             f"  Fetch        : {summary['fetch']}",
             f"  Resources    : {summary['resources']}",
             f"  Console      : {summary['console']}",
             f"  WebSocket    : {summary['ws']}",
             f"  Videos       : {summary['videos']}",
             f"  Iframes      : {len(iframes)}",
             f"  Blob URLs    : {len(blobs)}",
             f"  Tokens       : {len(token_list)}",
             f"  Embed URLs   : {len(embed_list)}",
             f"  Stream URLs  : {len(stream_list)}",
             f"  Live Streams : {len(summary['live_streams'])}",
             f"  API Endpts   : {len(api_list)}",
             f"  API Tried    : {summary['api_endpoints_tried']}",
             f"  Decrypted    : {summary['decrypted_responses']}", ""]

    if stream_list:
        lines += ["── STREAM URLS ──────────────────────────────────────────────────"]
        for u in stream_list:
            live_tag = " [LIVE]" if u in summary["live_streams"] else ""
            lines.append(f"  {u}{live_tag}")
        lines.append("")
    if token_list:
        lines += ["── TOKENS / AUTH ────────────────────────────────────────────────"]
        for t in token_list[:20]: lines.append(f"  {t}")
        lines.append("")
    if embed_list:
        lines += ["── EMBED PROVIDER URLS ──────────────────────────────────────────"]
        for e in embed_list[:20]: lines.append(f"  {e}")
        lines.append("")
    if iframes:
        lines += ["── IFRAMES ──────────────────────────────────────────────────────"]
        for f in iframes: lines.append(f"  [{f.get('tag','')}] {f.get('src','')}")
        lines.append("")
    if api_list:
        lines += ["── API ENDPOINTS ────────────────────────────────────────────────"]
        for ep in api_list[:60]: lines.append(f"  {ep}")
        if len(api_list) > 60: lines.append(f"  ... +{len(api_list)-60} more in SUMMARY.json")
        lines.append("")
    lines.append(sep)
    save_text("\n".join(lines), "SUMMARY.txt")
    print(f"[SUMMARY] Streams:{len(stream_list)} Live:{len(summary['live_streams'])} "
          f"APIs:{len(api_list)} Tokens:{len(token_list)} "
          f"Embeds:{len(embed_list)} Players:{players} "
          f"Injection:{summary['injection_active']}")
    return stream_list


# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND SAVER
# ═══════════════════════════════════════════════════════════════════════════════
_stop    = threading.Event()
_lock    = threading.Lock()
_streams = []

def background_saver(driver, url):
    cycle = 0
    while not _stop.is_set():
        time.sleep(AUTO_SAVE_INTERVAL)
        if _stop.is_set(): break
        cycle += 1
        print(f"\n[AUTO-SAVE #{cycle}]")
        try:
            log_data = collect_all(driver)
            extract_storage(driver)
            src = save_page_source(driver)
            new = log_data.get("streams", [])
            for v in log_data.get("videos", []):
                for k in ["currentSrc","src"]:
                    if v.get(k) and len(v[k]) > 5: new.append(v[k])
            with _lock:
                for s in new:
                    if s not in _streams:
                        _streams.append(s)
                        print(f"[AUTO-SAVE] New stream: {s}")
            scripts = []
            p = OUT_DIR / "scripts_index.json"
            if p.exists():
                try:
                    with open(p, encoding="utf-8") as f: scripts = json.load(f)
                except Exception: pass
            with _lock:
                build_summary(_streams[:], scripts, src, log_data,
                              {"stream_urls":[],"endpoints_tried":[],"decrypted_responses":[]}, url)
        except Exception as e:
            log_error(f"background_saver #{cycle}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def main():
    global TEMP_DIR
    print("\n" + "="*72)
    print("  ADVANCED DEVTOOLS NETWORK INTERCEPTOR  v5.0")
    print("="*72)
    print(f"  Target  : {TARGET_URL}")
    print(f"  Output  : {OUT_DIR}")
    print(f"  Errors  : {ERROR_LOG}")
    print("="*72 + "\n")

    TEMP_DIR = Path(tempfile.mkdtemp(prefix="kiro_v5_"))
    print(f"[SETUP] Temp dir: {TEMP_DIR}")

    # ── Profile ───────────────────────────────────────────────────────────────
    try:
        real_profile = get_real_profile()
        print(f"[SETUP] Real profile: {real_profile}")
    except Exception as e:
        log_error(f"get_real_profile: {e}")
        print("[FATAL] Cannot find Firefox profile.")
        return

    kill_firefox()

    try:
        profile_copy = copy_profile(real_profile, TEMP_DIR)
    except Exception as e:
        log_error(f"copy_profile: {e}")
        profile_copy = real_profile

    # ── Extension ─────────────────────────────────────────────────────────────
    try:
        xpi_path = build_extension(TEMP_DIR)
    except Exception as e:
        log_error(f"build_extension: {e}")
        print("[FATAL] Could not build extension.")
        return

    # ── Launch Firefox ────────────────────────────────────────────────────────
    try:
        driver = launch_firefox(profile_copy, xpi_path)
        print("[SETUP] Firefox launched.\n")
    except Exception as e:
        log_error(f"launch_firefox: {e}")
        print("[FATAL] Firefox failed to launch.")
        return

    # ── Navigate ──────────────────────────────────────────────────────────────
    print(f"[NAV] Opening: {TARGET_URL}")
    try:
        driver.get(TARGET_URL)
    except Exception as e:
        if "timeout" not in str(e).lower():
            log_error(f"driver.get: {e}")

    # Verify injection
    time.sleep(3)
    injected = safe_exec(driver, "return !!window.__kiro_v5;", default=False)
    if injected:
        print("[INJECT] ✓ Extension content_script confirmed active.")
    else:
        print("[INJECT] Injecting manually as fallback...")
        safe_exec(driver, CONTENT_SCRIPT_JS)
        time.sleep(1)

    # ── Wait for player to load ───────────────────────────────────────────────
    print("[WAIT] Waiting 18s for player + React hydration...")
    time.sleep(18)

    # ── Poll for stream URLs ──────────────────────────────────────────────────
    stream_urls = wait_for_stream(driver, timeout=STREAM_WAIT_SEC)
    with _lock:
        _streams.extend(stream_urls)

    # ── Full capture ──────────────────────────────────────────────────────────
    print("\n[CAPTURE] Running full capture...")
    log_data = collect_all(driver)
    page_src = save_page_source(driver)
    extract_meta(driver, TARGET_URL)
    extract_storage(driver)
    extract_cookies_detailed(driver)
    scripts  = extract_scripts(driver, TARGET_URL)

    # ── Fetch lazy chunks ─────────────────────────────────────────────────────
    chunk_streams = []
    if FETCH_CHUNKS:
        chunk_streams = fetch_chunks(TARGET_URL)
        with _lock:
            for s in chunk_streams:
                if s not in _streams: _streams.append(s)

    # Load chunks index
    ci = []
    cp = OUT_DIR / "chunks_index.json"
    if cp.exists():
        try:
            with open(cp, encoding="utf-8") as f: ci = json.load(f)
        except Exception: pass

    # ── Collect all embed URLs from every source ──────────────────────────────
    all_embed_urls = set()
    for sc in scripts: all_embed_urls.update(sc.get("embeds", []))
    for chunk in ci:   all_embed_urls.update(chunk.get("embeds", []))
    all_embed_urls.update(find_embed_urls(page_src))
    for iframe in log_data.get("iframes", []):
        src = iframe.get("src","")
        if src: all_embed_urls.add(src)
    all_embed_urls = sorted(all_embed_urls)
    print(f"[EMBEDS] Found {len(all_embed_urls)} embed provider URL(s).")

    # ── Drill iframes ─────────────────────────────────────────────────────────
    iframe_streams = []
    if DRILL_IFRAMES:
        iframe_streams = drill_iframes(driver)
        with _lock:
            for s in iframe_streams:
                if s not in _streams: _streams.append(s)

    # ── Open embed tabs ───────────────────────────────────────────────────────
    tab_streams = []
    if OPEN_EMBED_TABS and all_embed_urls:
        tab_streams = open_embed_tabs(driver, list(all_embed_urls))
        with _lock:
            for s in tab_streams:
                if s not in _streams: _streams.append(s)

    # ── Direct API crack ──────────────────────────────────────────────────────
    live_tokens = list(set(log_data.get("tokens", [])))
    api_results = crack_stream_api(driver, ci, live_tokens)
    with _lock:
        for s in api_results.get("stream_urls", []):
            if s not in _streams: _streams.append(s)

    # ── Try known embed providers ─────────────────────────────────────────────
    tmdb_match = re.search(r'/(?:player|movie|watch|embed)/(\d+)', TARGET_URL)
    tmdb_id    = tmdb_match.group(1) if tmdb_match else None
    if tmdb_id:
        try:
            driver_cookies = driver.get_cookies()
        except Exception:
            driver_cookies = []
        provider_streams = try_all_embed_providers(tmdb_id, "movie", driver_cookies)
        with _lock:
            for s in provider_streams:
                if s not in _streams: _streams.append(s)

    # ── yt-dlp fallback ───────────────────────────────────────────────────────
    if TRY_YTDLP:
        cookies_file = str(OUT_DIR / "cookies_netscape.txt")
        ytdlp_streams = try_ytdlp(TARGET_URL, cookies_file)
        with _lock:
            for s in ytdlp_streams:
                if s not in _streams: _streams.append(s)

    # ── Build summary ─────────────────────────────────────────────────────────
    with _lock:
        build_summary(_streams[:], scripts, page_src, log_data, api_results, TARGET_URL)

    # ── Start background saver ────────────────────────────────────────────────
    t = threading.Thread(target=background_saver, args=(driver, TARGET_URL), daemon=True)
    t.start()

    print("\n" + "="*72)
    print("  CAPTURE ACTIVE — close Firefox manually when done")
    print(f"  Output: {OUT_DIR}")
    print("="*72 + "\n")

    # ── Keep alive ────────────────────────────────────────────────────────────
    try:
        while True:
            time.sleep(3)
            try:
                _ = driver.window_handles
            except Exception:
                print("\n[DETECT] Browser closed.")
                break
    except KeyboardInterrupt:
        print("\n[INTERRUPT] Ctrl+C.")

    # ── Final save ────────────────────────────────────────────────────────────
    _stop.set()
    print("\n[FINAL] Final save...")
    try:
        log_data = collect_all(driver)
        extract_storage(driver)
        extract_cookies_detailed(driver)
        src = save_page_source(driver)
        for s in log_data.get("streams", []):
            with _lock:
                if s not in _streams: _streams.append(s)
        scripts = []
        p = OUT_DIR / "scripts_index.json"
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f: scripts = json.load(f)
            except Exception: pass
        with _lock:
            build_summary(_streams[:], scripts, src, log_data,
                          {"stream_urls":[],"endpoints_tried":[],"decrypted_responses":[]},
                          TARGET_URL)
    except Exception as e:
        log_error(f"final_save: {e}")

    try: driver.quit()
    except Exception: pass
    try: shutil.rmtree(str(TEMP_DIR), ignore_errors=True)
    except Exception: pass

    print(f"\n[DONE] Output: {OUT_DIR}")
    with _lock:
        live = [s for s in _streams if s.startswith("http")]
        if live:
            print(f"[DONE] Stream URLs found ({len(live)}):")
            for u in live: print(f"       {u}")
        else:
            print("[DONE] No stream URLs captured.")
            print("       Check: api_direct_results.json, embed_providers_results.json,")
            print("              chunks_index.json, network_fetch.json")


if __name__ == "__main__":
    main()
