"""
MITM Advanced Full-Capture Toolkit  v2.0
=========================================
Captures EVERYTHING a browser DevTools can see — and more:
  • Every HTTP/HTTPS request + response (headers, body, timing)
  • Cookies (request Cookie header + response Set-Cookie parsed)
  • Auth tokens, Bearer, API keys, session IDs
  • XHR / Fetch / API calls with JSON body parsed
  • JavaScript source files (full body saved)
  • HTML page source (full body saved)
  • CSS files
  • Media: m3u8 playlists parsed → all segment/key URLs extracted
  • WebSocket frames (both directions)
  • Referrer chain & Origin tracking
  • TLS SNI hostname
  • Signed / presigned CDN URLs (AWS S3, GCS, Azure)
  • GraphQL queries/mutations parsed
  • Server-Sent Events (SSE) streams
  • Response Set-Cookie → cookie jar per domain
  • Auto-saves session to timestamped folder on stop

Environment variables (all optional):
  MITM_FILTER        regex on URL            (default: .*)
  MITM_OUTFILE       JSONL output path       (default: mitm_captured.jsonl)
  MITM_SAVE_DIR      folder for auto-saves   (default: ./captures)
  MITM_STRIP_HEADERS comma-separated headers to strip
"""

import base64
import gzip
import hashlib
import json
import os
import re
import time
import zlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse, unquote

from mitmproxy import ctx, http

# ── Config ────────────────────────────────────────────────────────────────────
URL_FILTER    = re.compile(os.getenv("MITM_FILTER", r".*"))
OUTFILE       = Path(os.getenv("MITM_OUTFILE", "mitm_captured.jsonl"))
SAVE_DIR      = Path(os.getenv("MITM_SAVE_DIR", "captures"))
STRIP_HEADERS = [h.strip().lower()
                 for h in os.getenv("MITM_STRIP_HEADERS", "").split(",") if h.strip()]

# ── Resource type map ─────────────────────────────────────────────────────────
_CT_MAP = [
    (re.compile(r"application/(json|graphql|x-www-form-urlencoded|xml|soap|x-ndjson)", re.I), "xhr/api"),
    (re.compile(r"text/javascript|application/(javascript|x-javascript|ecmascript)", re.I), "js"),
    (re.compile(r"text/css", re.I), "css"),
    (re.compile(r"text/html", re.I), "html"),
    (re.compile(r"image/", re.I), "image"),
    (re.compile(r"video/|audio/|application/x-mpegURL|application/vnd\.apple\.mpegurl|application/dash\+xml", re.I), "media"),
    (re.compile(r"font/|application/font|application/x-font|application/vnd\.ms-fontobject", re.I), "font"),
    (re.compile(r"text/event-stream", re.I), "sse"),
    (re.compile(r"application/octet-stream|application/zip|application/wasm", re.I), "binary"),
    (re.compile(r"text/plain", re.I), "text"),
]
_EXT_MAP = {
    ".js":"js",".mjs":"js",".jsx":"js",".ts":"js",".tsx":"js",
    ".css":"css",
    ".html":"html",".htm":"html",".php":"html",".asp":"html",
    ".json":"xhr/api",".xml":"xhr/api",".graphql":"xhr/api",".gql":"xhr/api",
    ".jpg":"image",".jpeg":"image",".png":"image",".gif":"image",
    ".svg":"image",".webp":"image",".ico":"image",".avif":"image",
    ".mp4":"media",".webm":"media",".m3u8":"media",".m3u":"media",
    ".ts":"media",".mp3":"media",".aac":"media",".ogg":"media",".flac":"media",
    ".woff":"font",".woff2":"font",".ttf":"font",".eot":"font",".otf":"font",
    ".wasm":"binary",".zip":"binary",".gz":"binary",
}

def _rtype(url: str, ct: str) -> str:
    if ct:
        for pat, t in _CT_MAP:
            if pat.search(ct):
                return t
    ext = Path(urlparse(url).path).suffix.lower()
    return _EXT_MAP.get(ext, "other")

# ── Auth header patterns ──────────────────────────────────────────────────────
_AUTH_RE = re.compile(
    r"^(authorization|x-api-key|x-auth-token|x-access-token|api[_-]key|bearer|"
    r"access[_-]token|x-amz-security-token|x-goog-api-key|x-stripe-client|"
    r"x-shopify-access-token|x-hasura-admin-secret|x-forwarded-authorization|"
    r"x-session-token|x-csrf-token|x-xsrf-token|x-request-id|"
    r"proxy-authorization|cookie|x-client-id|x-user-id|x-tenant-id)$",
    re.IGNORECASE,
)

# ── Signed URL patterns ───────────────────────────────────────────────────────
_SIGNED = [
    re.compile(r"X-Amz-Signature="),
    re.compile(r"[?&]sig=", re.I),
    re.compile(r"[?&]token=", re.I),
    re.compile(r"Expires=\d+&Signature="),
    re.compile(r"[?&]X-Goog-Signature=", re.I),
    re.compile(r"sv=\d+&se=.*&sig=", re.I),
]

# ── m3u8 / HLS parser ────────────────────────────────────────────────────────
_M3U8_KEY_RE = re.compile(r'URI="([^"]+)"')

def _parse_m3u8(body: str, base_url: str) -> dict:
    """Extract all segment URLs, key URLs, and sub-playlist URLs from m3u8."""
    base = base_url.rsplit("/", 1)[0] + "/"
    segments, keys, playlists, bandwidth_map = [], [], [], []
    current_bandwidth = None
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-KEY"):
            m = _M3U8_KEY_RE.search(line)
            if m:
                u = m.group(1)
                keys.append(u if u.startswith("http") else base + u)
        elif line.startswith("#EXT-X-STREAM-INF"):
            bw = re.search(r'BANDWIDTH=(\d+)', line)
            current_bandwidth = int(bw.group(1)) if bw else None
        elif line.startswith("#"):
            continue
        else:
            u = line if line.startswith("http") else base + line
            if ".m3u8" in u.lower() or ".m3u" in u.lower():
                playlists.append({"url": u, "bandwidth": current_bandwidth})
                current_bandwidth = None
            else:
                segments.append(u)
    return {"segments": segments, "keys": keys,
            "sub_playlists": playlists, "segment_count": len(segments)}

# ── DASH/MPD parser ───────────────────────────────────────────────────────────
def _parse_mpd(body: str, base_url: str) -> dict:
    """Extract stream URLs from MPEG-DASH MPD manifest."""
    base = base_url.rsplit("/", 1)[0] + "/"
    urls, init_segs = [], []
    # BaseURL tags
    for m in re.finditer(r'<BaseURL[^>]*>([^<]+)</BaseURL>', body, re.I):
        u = m.group(1).strip()
        urls.append(u if u.startswith("http") else base + u)
    # SegmentTemplate
    for m in re.finditer(r'media="([^"]+)"', body):
        urls.append(m.group(1))
    for m in re.finditer(r'initialization="([^"]+)"', body):
        init_segs.append(m.group(1))
    return {"streams": urls, "init_segments": init_segs}

# ── Crypto / encryption detector ─────────────────────────────────────────────
_CRYPTO_PATTERNS = [
    (re.compile(r'\bCryptoJS\b'),                          "CryptoJS"),
    (re.compile(r'\bCryptoJS\.AES\b'),                     "CryptoJS.AES"),
    (re.compile(r'\bCryptoJS\.HmacSHA\d+\b'),              "CryptoJS.HMAC"),
    (re.compile(r'\bwindow\.crypto\b'),                    "window.crypto"),
    (re.compile(r'\bcrypto\.subtle\b'),                    "SubtleCrypto"),
    (re.compile(r'\bAES\.encrypt\b|\bAES\.decrypt\b'),     "AES encrypt/decrypt"),
    (re.compile(r'\bRSA\b|\bRSAKey\b|\bJSEncrypt\b'),      "RSA"),
    (re.compile(r'\bbtoa\s*\(|\batob\s*\('),               "base64 btoa/atob"),
    (re.compile(r'\bCryptoJS\.enc\.Base64\b'),             "CryptoJS.Base64"),
    (re.compile(r'\bsha256\b|\bsha512\b|\bsha1\b', re.I), "SHA hash"),
    (re.compile(r'\bhmac\b', re.I),                        "HMAC"),
    (re.compile(r'\bencrypt\s*\(|\bdecrypt\s*\(', re.I),  "encrypt/decrypt call"),
    (re.compile(r'\bpkcs\b|\bpbkdf2\b', re.I),            "PKCS/PBKDF2"),
    (re.compile(r'\biv\s*=|\bsalt\s*=', re.I),            "IV/Salt"),
    (re.compile(r'["\']([A-Za-z0-9+/]{40,}={0,2})["\']'), "base64 blob"),
    (re.compile(r'U2FsdGVkX1[A-Za-z0-9+/]+'),             "CryptoJS ciphertext"),
    (re.compile(r'[0-9a-fA-F]{64,}'),                     "hex string (64+ chars)"),
]

def _detect_crypto(body: str) -> list:
    """Scan JS/body for crypto patterns. Returns list of findings."""
    if not body:
        return []
    findings = []
    seen = set()
    for pat, label in _CRYPTO_PATTERNS:
        matches = pat.findall(body)
        if matches and label not in seen:
            seen.add(label)
            # grab context snippet
            m = pat.search(body)
            start = max(0, m.start() - 60)
            end   = min(len(body), m.end() + 60)
            snippet = body[start:end].replace("\n", " ").strip()
            findings.append({"pattern": label, "count": len(matches),
                             "snippet": snippet[:200]})
    return findings

# ── Encrypted payload detector ────────────────────────────────────────────────
_ENC_PAYLOAD_RE = [
    (re.compile(r'U2FsdGVkX1[A-Za-z0-9+/=]+'),           "CryptoJS AES ciphertext"),
    (re.compile(r'"[A-Za-z0-9+/]{100,}={0,2}"'),          "large base64 blob"),
    (re.compile(r'[0-9a-fA-F]{128,}'),                    "large hex string"),
    (re.compile(r'eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+'), "JWT token"),
    (re.compile(r'"encrypted"\s*:\s*"[^"]+"'),             "encrypted field"),
    (re.compile(r'"cipher(text|data)"\s*:\s*"[^"]+"', re.I), "ciphertext field"),
    (re.compile(r'"data"\s*:\s*"[A-Za-z0-9+/]{40,}={0,2}"'), "base64 data field"),
]

def _detect_encrypted_payload(body: str) -> list:
    if not body or len(body) < 20:
        return []
    findings = []
    for pat, label in _ENC_PAYLOAD_RE:
        m = pat.search(body)
        if m:
            findings.append({"type": label, "sample": m.group(0)[:120]})
    return findings

# ── Cookie parser ─────────────────────────────────────────────────────────────
def _parse_set_cookie(header_val: str) -> dict:
    parts = [p.strip() for p in header_val.split(";")]
    if not parts:
        return {}
    name_val = parts[0].split("=", 1)
    cookie = {
        "name":     name_val[0].strip(),
        "value":    name_val[1].strip() if len(name_val) > 1 else "",
        "httponly": False, "secure": False,
        "samesite": None, "path": None, "domain": None, "expires": None,
    }
    for attr in parts[1:]:
        al = attr.lower()
        if al == "httponly":   cookie["httponly"] = True
        elif al == "secure":   cookie["secure"]   = True
        elif al.startswith("samesite="):  cookie["samesite"] = attr.split("=",1)[1]
        elif al.startswith("path="):      cookie["path"]     = attr.split("=",1)[1]
        elif al.startswith("domain="):    cookie["domain"]   = attr.split("=",1)[1]
        elif al.startswith("expires="):   cookie["expires"]  = attr.split("=",1)[1]
    return cookie

def _parse_cookie_header(header_val: str) -> dict:
    result = {}
    for part in header_val.split(";"):
        kv = part.strip().split("=", 1)
        if len(kv) == 2:
            result[kv[0].strip()] = kv[1].strip()
    return result

# ── GraphQL detector ──────────────────────────────────────────────────────────
def _parse_graphql(body_raw: str, ct: str) -> Optional[dict]:
    if not body_raw:
        return None
    try:
        obj = json.loads(body_raw)
        if isinstance(obj, dict) and ("query" in obj or "mutation" in obj or "operationName" in obj):
            return {
                "operation": obj.get("operationName"),
                "type":      "mutation" if "mutation" in obj.get("query","") else "query",
                "variables": obj.get("variables"),
                "query":     obj.get("query","")[:2000],
            }
    except Exception:
        pass
    return None

# ── Body decoder ─────────────────────────────────────────────────────────────
def _decode_body(msg) -> Optional[str]:
    raw = msg.content
    if not raw:
        return None
    try:
        enc = msg.headers.get("content-encoding", "")
        if "gzip" in enc:
            raw = gzip.decompress(raw)
        elif "deflate" in enc:
            raw = zlib.decompress(raw)
        elif "br" in enc:
            try:
                import brotli
                raw = brotli.decompress(raw)
            except Exception:
                pass
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return base64.b64encode(raw).decode()

def _parse_body(body: Optional[str], ct: str) -> object:
    if not body:
        return None
    ctl = ct.lower()
    if "json" in ctl:
        try:
            return json.loads(body)
        except Exception:
            return body
    if "x-www-form-urlencoded" in ctl:
        try:
            return {k: v[0] if len(v)==1 else v for k,v in parse_qs(body).items()}
        except Exception:
            return body
    return body

# ── Helpers ───────────────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _extract_auth(headers: dict) -> dict:
    return {k: v for k, v in headers.items() if _AUTH_RE.match(k)}

def _is_signed(url: str) -> bool:
    return any(p.search(url) for p in _SIGNED)

def _url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:8]

def _write_jsonl(record: dict) -> None:
    try:
        with OUTFILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        ctx.log.error(f"[toolkit] write error: {exc}")

# ── Session stats ─────────────────────────────────────────────────────────────
_stats = defaultdict(int)
_cookie_jar   = defaultdict(dict)   # domain → {name: value}
_auth_vault   = {}                  # header_key → latest value
_m3u8_index   = {}                  # url → parsed m3u8 dict
_flow_pairs   = {}                  # flow_id → request record (for pairing)

# ── Record builders ───────────────────────────────────────────────────────────
def _build_request(flow: http.HTTPFlow) -> dict:
    req     = flow.request
    headers = dict(req.headers)
    auth    = _extract_auth(headers)
    body_raw = _decode_body(req)
    ct       = headers.get("content-type", "")
    parsed   = urlparse(req.pretty_url)

    # Update auth vault
    for k, v in auth.items():
        if k.lower() != "cookie":
            _auth_vault[k.lower()] = v

    # Parse cookies from request
    req_cookies = {}
    if "cookie" in headers:
        req_cookies = _parse_cookie_header(headers["cookie"])

    # GraphQL detection
    gql = _parse_graphql(body_raw, ct)

    # XHR/Fetch detection via request headers
    is_xhr = (headers.get("x-requested-with","").lower() == "xmlhttprequest" or
              "fetch" in headers.get("sec-fetch-mode","").lower() or
              headers.get("sec-fetch-dest","") in ("empty","") and
              headers.get("accept","").startswith("application/"))

    # Encrypted payload detection in request body
    enc_payload = _detect_encrypted_payload(body_raw or "")

    rec = {
        "type":          "request",
        "ts":            _now_iso(),
        "id":            flow.id,
        "method":        req.method,
        "url":           req.pretty_url,
        "scheme":        req.scheme,
        "host":          req.pretty_host,
        "port":          req.port,
        "path":          parsed.path,
        "query":         dict(parse_qs(parsed.query)),
        "query_raw":     parsed.query,
        "fragment":      parsed.fragment,
        "http_version":  req.http_version,
        "headers":       headers,
        "auth_found":    auth,
        "cookies":       req_cookies,
        "signed_url":    _is_signed(req.pretty_url),
        "body_raw":      body_raw,
        "body_parsed":   _parse_body(body_raw, ct),
        "body_size":     len(body_raw) if body_raw else 0,
        "graphql":       gql,
        "is_xhr":        is_xhr,
        "enc_payload":   enc_payload,
        "resource_type": _rtype(req.pretty_url, ct),
        "referrer":      headers.get("referer", headers.get("referrer", "")),
        "origin":        headers.get("origin", ""),
        "user_agent":    headers.get("user-agent", ""),
        "accept":        headers.get("accept", ""),
        "tls":           flow.server_conn.tls_established if flow.server_conn else False,
        "tls_sni":       getattr(flow.server_conn, "tls_extensions_sni", None) if flow.server_conn else None,
        "url_hash":      _url_hash(req.pretty_url),
    }
    return rec


def _build_response(flow: http.HTTPFlow) -> dict:
    resp     = flow.response
    req      = flow.request
    headers  = dict(resp.headers)
    body_raw = _decode_body(resp)
    ct       = headers.get("content-type", "")
    rt       = _rtype(req.pretty_url, ct)

    # Parse Set-Cookie headers
    set_cookies = []
    for hk, hv in resp.headers.items(multi=True):
        if hk.lower() == "set-cookie":
            parsed_ck = _parse_set_cookie(hv)
            set_cookies.append(parsed_ck)
            # Update cookie jar
            domain = parsed_ck.get("domain") or req.pretty_host
            _cookie_jar[domain][parsed_ck["name"]] = parsed_ck["value"]

    # m3u8 parsing
    m3u8_data = None
    if rt == "media" and body_raw and ("m3u8" in req.pretty_url.lower() or
                                        "m3u" in ct.lower() or
                                        body_raw.strip().startswith("#EXTM3U")):
        m3u8_data = _parse_m3u8(body_raw, req.pretty_url)
        _m3u8_index[req.pretty_url] = m3u8_data

    # DASH/MPD parsing
    mpd_data = None
    if body_raw and (".mpd" in req.pretty_url.lower() or "dash+xml" in ct.lower()
                     or (body_raw.strip().startswith("<") and "MPD" in body_raw[:200])):
        mpd_data = _parse_mpd(body_raw, req.pretty_url)

    # Crypto detection in JS source
    crypto_findings = []
    if rt == "js" and body_raw:
        crypto_findings = _detect_crypto(body_raw)
        if crypto_findings:
            _stats["js_crypto_detected"] += 1
            ctx.log.warn(f"[CRYPTO] {len(crypto_findings)} patterns in JS: {req.pretty_url[:60]}")

    # Encrypted payload in response body
    enc_payload = _detect_encrypted_payload(body_raw or "") if rt in ("xhr/api","text","other") else []

    # JS / HTML body — keep full source
    keep_full = rt in ("js", "html", "css", "xhr/api", "sse")

    rec = {
        "type":          "response",
        "ts":            _now_iso(),
        "id":            flow.id,
        "url":           req.pretty_url,
        "host":          req.pretty_host,
        "method":        req.method,
        "status":        resp.status_code,
        "reason":        resp.reason,
        "headers":       headers,
        "set_cookies":   set_cookies,
        "body_raw":      body_raw if keep_full else (body_raw[:512] if body_raw else None),
        "body_full":     keep_full,
        "body_parsed":   _parse_body(body_raw, ct) if rt == "xhr/api" else None,
        "body_size":     len(body_raw) if body_raw else 0,
        "content_type":  ct,
        "resource_type": rt,
        "m3u8":          m3u8_data,
        "mpd":           mpd_data,
        "crypto":        crypto_findings,
        "enc_payload":   enc_payload,
        "timing_ms":     round((resp.timestamp_end - req.timestamp_start) * 1000, 2)
                         if resp.timestamp_end else None,
        "url_hash":      _url_hash(req.pretty_url),
    }
    return rec

# ── Auto-save session to folder ───────────────────────────────────────────────
def _auto_save_session():
    """On proxy stop, export everything to a timestamped folder."""
    if not OUTFILE.exists() or OUTFILE.stat().st_size == 0:
        return

    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest  = SAVE_DIR / ts
    dest.mkdir(parents=True, exist_ok=True)

    records = []
    with OUTFILE.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    if not records:
        return

    requests  = [r for r in records if r["type"] == "request"]
    responses = [r for r in records if r["type"] == "response"]
    resp_map  = {r["id"]: r for r in responses}

    # 1. Full JSONL copy
    import shutil
    shutil.copy(OUTFILE, dest / "full_capture.jsonl")

    # 2. API endpoints
    apis = {}
    for r in requests:
        p = urlparse(r["url"])
        key = f"{r['method']} {p.scheme}://{r['host']}{p.path}"
        if key not in apis:
            apis[key] = {"method": r["method"], "url": key, "count": 0,
                         "auth": bool(r.get("auth_found")), "signed": r.get("signed_url")}
        apis[key]["count"] += 1
    with (dest / "api_endpoints.json").open("w", encoding="utf-8") as f:
        json.dump(list(apis.values()), f, indent=2, ensure_ascii=False)

    # 3. Auth tokens / headers
    auth_data = {}
    for r in requests:
        for k, v in (r.get("auth_found") or {}).items():
            if k.lower() != "cookie":
                auth_data[k] = v
    with (dest / "auth_tokens.json").open("w", encoding="utf-8") as f:
        json.dump(auth_data, f, indent=2, ensure_ascii=False)

    # 4. Cookie jar
    with (dest / "cookies.json").open("w", encoding="utf-8") as f:
        json.dump({d: dict(v) for d, v in _cookie_jar.items()}, f, indent=2, ensure_ascii=False)

    # 5. m3u8 / media URLs
    media_urls = {"m3u8_playlists": [], "segments": [], "keys": []}
    for r in requests:
        if r.get("resource_type") == "media":
            media_urls["m3u8_playlists"].append(r["url"])
    for url, data in _m3u8_index.items():
        media_urls["segments"].extend(data.get("segments", []))
        media_urls["keys"].extend(data.get("keys", []))
        media_urls["m3u8_playlists"].extend(data.get("sub_playlists", []))
    with (dest / "media_urls.json").open("w", encoding="utf-8") as f:
        json.dump(media_urls, f, indent=2, ensure_ascii=False)

    # 6. JS files
    js_dir = dest / "js_files"
    js_dir.mkdir(exist_ok=True)
    for r in responses:
        if r.get("resource_type") == "js" and r.get("body_raw"):
            fname = _url_hash(r["url"]) + "_" + Path(urlparse(r["url"]).path).name[:40]
            if not fname.endswith(".js"):
                fname += ".js"
            (js_dir / fname).write_text(r["body_raw"], encoding="utf-8", errors="replace")

    # 7. HTML page sources
    html_dir = dest / "html_pages"
    html_dir.mkdir(exist_ok=True)
    for r in responses:
        if r.get("resource_type") == "html" and r.get("body_raw"):
            fname = _url_hash(r["url"]) + "_" + (Path(urlparse(r["url"]).path).name or "index")[:40] + ".html"
            (html_dir / fname).write_text(r["body_raw"], encoding="utf-8", errors="replace")

    # 8. XHR / API responses
    xhr_dir = dest / "xhr_responses"
    xhr_dir.mkdir(exist_ok=True)
    for r in responses:
        if r.get("resource_type") == "xhr/api" and r.get("body_raw"):
            fname = _url_hash(r["url"]) + "_" + Path(urlparse(r["url"]).path).name[:40] + ".json"
            (xhr_dir / fname).write_text(r["body_raw"], encoding="utf-8", errors="replace")

    # 9. WebSocket frames
    ws_frames = [r for r in records if r["type"] == "ws_frame"]
    if ws_frames:
        with (dest / "websocket_frames.json").open("w", encoding="utf-8") as f:
            json.dump(ws_frames, f, indent=2, ensure_ascii=False, default=str)

    # 10. All request headers (full)
    with (dest / "all_request_headers.json").open("w", encoding="utf-8") as f:
        json.dump([{"url": r["url"], "method": r["method"],
                    "headers": r.get("headers", {})} for r in requests],
                  f, indent=2, ensure_ascii=False)

    # 11. Referrer chain
    referrers = [{"url": r["url"], "referrer": r.get("referrer",""),
                  "origin": r.get("origin","")}
                 for r in requests if r.get("referrer") or r.get("origin")]
    with (dest / "referrer_chain.json").open("w", encoding="utf-8") as f:
        json.dump(referrers, f, indent=2, ensure_ascii=False)

    # 12. GraphQL operations
    gql_ops = [{"url": r["url"], "graphql": r["graphql"]}
               for r in requests if r.get("graphql")]
    if gql_ops:
        with (dest / "graphql_operations.json").open("w", encoding="utf-8") as f:
            json.dump(gql_ops, f, indent=2, ensure_ascii=False)

    # 13. Crypto findings from JS
    crypto_hits = []
    for r in responses:
        if r.get("crypto"):
            crypto_hits.append({"url": r["url"], "findings": r["crypto"]})
    if crypto_hits:
        with (dest / "crypto_in_js.json").open("w", encoding="utf-8") as f:
            json.dump(crypto_hits, f, indent=2, ensure_ascii=False)

    # 14. Encrypted payloads in requests/responses
    enc_hits = []
    for r in requests + responses:
        if r.get("enc_payload"):
            enc_hits.append({"url": r.get("url"), "type": r["type"],
                             "findings": r["enc_payload"]})
    if enc_hits:
        with (dest / "encrypted_payloads.json").open("w", encoding="utf-8") as f:
            json.dump(enc_hits, f, indent=2, ensure_ascii=False)

    # 15. DASH/MPD streams
    mpd_hits = [{"url": r["url"], "mpd": r["mpd"]}
                for r in responses if r.get("mpd")]
    if mpd_hits:
        with (dest / "dash_mpd_streams.json").open("w", encoding="utf-8") as f:
            json.dump(mpd_hits, f, indent=2, ensure_ascii=False)

    # 16. XHR/Fetch only requests
    xhr_reqs = [{"url": r["url"], "method": r["method"],
                 "headers": r.get("headers",{}), "body": r.get("body_raw","")}
                for r in requests if r.get("is_xhr") or r.get("resource_type")=="xhr/api"]
    with (dest / "xhr_fetch_requests.json").open("w", encoding="utf-8") as f:
        json.dump(xhr_reqs, f, indent=2, ensure_ascii=False)

    # 17. Summary report
    summary = {
        "session_ts":       ts,
        "total_records":    len(records),
        "requests":         len(requests),
        "responses":        len(responses),
        "ws_frames":        len(ws_frames),
        "unique_hosts":     len({r["host"] for r in requests}),
        "api_endpoints":    len(apis),
        "auth_tokens":      len(auth_data),
        "cookie_domains":   len(_cookie_jar),
        "m3u8_playlists":   len(media_urls["m3u8_playlists"]),
        "media_segments":   len(media_urls["segments"]),
        "js_files":         len(list(js_dir.iterdir())),
        "html_pages":       len(list(html_dir.iterdir())),
        "crypto_js_hits":   len(crypto_hits),
        "encrypted_payloads": len(enc_hits),
        "dash_mpd_streams": len(mpd_hits),
        "xhr_fetch_requests": len(xhr_reqs),
        "graphql_ops":      len(gql_ops),
        "stats":            dict(_stats),
    }
    with (dest / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    ctx.log.info(f"[SAVED] Session exported → {dest.resolve()}")
    ctx.log.info(f"[SAVED] {len(requests)} requests, {len(apis)} endpoints, "
                 f"{len(auth_data)} tokens, {len(ws_frames)} WS frames")

# ── Main Addon ────────────────────────────────────────────────────────────────
class AdvancedToolkit:

    def running(self):
        OUTFILE.parent.mkdir(parents=True, exist_ok=True)
        SAVE_DIR.mkdir(parents=True, exist_ok=True)
        ctx.log.info("=" * 64)
        ctx.log.info("  MITM Advanced Full-Capture Toolkit  v2.0  — ACTIVE")
        ctx.log.info(f"  Filter   : {URL_FILTER.pattern}")
        ctx.log.info(f"  JSONL    : {OUTFILE.resolve()}")
        ctx.log.info(f"  Auto-save: {SAVE_DIR.resolve()}")
        ctx.log.info("=" * 64)

    def done(self):
        _auto_save_session()
        ctx.log.info("=" * 64)
        ctx.log.info("  SESSION STATS")
        for k, v in sorted(_stats.items()):
            ctx.log.info(f"  {k:<22} {v}")
        ctx.log.info("=" * 64)

    def request(self, flow: http.HTTPFlow):
        _stats["total_requests"] += 1
        for h in STRIP_HEADERS:
            flow.request.headers.pop(h, None)
        if not URL_FILTER.search(flow.request.pretty_url):
            return
        _stats["matched_requests"] += 1
        rec = _build_request(flow)
        _flow_pairs[flow.id] = rec

        if rec["auth_found"]:
            _stats["auth_detected"] += 1
            ctx.log.warn(f"[AUTH] {rec['method']} {rec['url'][:80]} → {list(rec['auth_found'].keys())}")
        if rec["signed_url"]:
            _stats["signed_urls"] += 1
        if rec["graphql"]:
            _stats["graphql_ops"] += 1
            ctx.log.info(f"[GQL] {rec['graphql'].get('operation','?')} @ {rec['url'][:60]}")

        _write_jsonl(rec)
        _stats[f"type_{rec['resource_type']}"] += 1
        ctx.log.info(f"[REQ] {rec['method']} {rec['resource_type']:8} {rec['url'][:90]}")

    def response(self, flow: http.HTTPFlow):
        if not URL_FILTER.search(flow.request.pretty_url):
            return
        rec = _build_response(flow)
        _write_jsonl(rec)

        if rec["set_cookies"]:
            _stats["cookies_captured"] += len(rec["set_cookies"])
            ctx.log.info(f"[COOKIE] {len(rec['set_cookies'])} cookies from {rec['host']}")
        if rec["m3u8"]:
            segs = len(rec["m3u8"].get("segments", []))
            _stats["m3u8_segments"] += segs
            ctx.log.warn(f"[M3U8] {rec['url'][:70]} → {segs} segments, "
                         f"{len(rec['m3u8'].get('keys',[]))} keys")
        if rec["resource_type"] == "js":
            _stats["js_files"] += 1
        if rec["resource_type"] == "html":
            _stats["html_pages"] += 1

        ctx.log.info(f"[RES] {rec['status']} {rec['resource_type']:8} "
                     f"{rec['timing_ms']}ms  {rec['url'][:80]}")

    def websocket_start(self, flow: http.HTTPFlow):
        _stats["ws_connections"] += 1
        _write_jsonl({"type":"ws_open","ts":_now_iso(),"id":flow.id,"url":flow.request.pretty_url})
        ctx.log.info(f"[WS-OPEN] {flow.request.pretty_url}")

    def websocket_message(self, flow: http.HTTPFlow):
        _stats["ws_frames"] += 1
        msg = flow.websocket.messages[-1]
        content = msg.content
        if isinstance(content, bytes):
            try:    content = content.decode("utf-8")
            except: content = base64.b64encode(content).decode()
        _write_jsonl({
            "type":      "ws_frame",
            "ts":        _now_iso(),
            "id":        flow.id,
            "url":       flow.request.pretty_url,
            "direction": "client→server" if msg.from_client else "server→client",
            "content":   content,
            "size":      len(msg.content),
        })

    def websocket_end(self, flow: http.HTTPFlow):
        _write_jsonl({"type":"ws_close","ts":_now_iso(),"id":flow.id,"url":flow.request.pretty_url})

    def error(self, flow: http.HTTPFlow):
        _stats["errors"] += 1
        _write_jsonl({
            "type": "error", "ts": _now_iso(), "id": flow.id,
            "url":  flow.request.pretty_url if flow.request else None,
            "msg":  str(flow.error),
        })


addons = [AdvancedToolkit()]
