

"""
player.py — Pro M3U8 Player + Multi-Source Extractor (Single File)
==================================================================
Extractors:  Videasy · VidLink · PrimeSrc
Player:      HLS.js · Quality selector · PiP · Fullscreen · Speed
Proxy:       Cloudflare Worker — all segments routed through it

Setup:
    pip install fastapi uvicorn requests beautifulsoup4

Run:
    python player.py        # → http://localhost:8000
"""

from __future__ import annotations

import json
import os
import re
import sys
import subprocess
from urllib.parse import urlparse, urljoin, quote, parse_qs

# ─── Auto-install deps ────────────────────────────────────────────────────────
def _ensure(*pkgs):
    missing = []
    for imp, pip_name in pkgs:
        try:
            __import__(imp)
        except ImportError:
            missing.append(pip_name)
    if missing:
        print(f"[setup] Installing: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])

_ensure(
    ("fastapi",       "fastapi"),
    ("uvicorn",       "uvicorn"),
    ("requests",      "requests"),
    ("bs4",           "beautifulsoup4"),
)

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel


# ══════════════════════════════════════════════════════════════════════════════
#  SHARED UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

CF_PROXY_BASE = "https://foxy-doxy.andruilsyestems.workers.dev"
ENC_DEC_API   = "https://enc-dec.app/api"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

class ExtractorError(Exception):
    pass

def _find_streams(obj):
    """Recursively walk JSON and collect .m3u8 / playlist URLs."""
    found, seen = [], set()
    def walk(node):
        if isinstance(node, dict):
            for v in node.values():
                if isinstance(v, str) and v.startswith("http") and v not in seen:
                    if ".m3u8" in v or "/master" in v or "playlist" in v:
                        found.append(v); seen.add(v)
                walk(v)
        elif isinstance(node, list):
            for it in node: walk(it)
    walk(obj)
    return found

def _find_streams_in_text(text: str):
    """Find m3u8 URLs inside raw HTML/JS text."""
    pattern = r'https?://[^\s\'"<>]+\.m3u8[^\s\'"<>]*'
    return list(dict.fromkeys(re.findall(pattern, text)))

def _get(url, headers, timeout=15):
    r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r

def _post(url, payload, headers, timeout=15):
    r = requests.post(url, json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r

def _api_unwrap(data, label):
    if not isinstance(data, dict):
        raise ExtractorError(f"[{label}] invalid response type")
    if data.get("status") != 200:
        raise ExtractorError(
            f"[{label}] status={data.get('status')} err={data.get('error','unknown')}"
        )
    return data["result"]


# ══════════════════════════════════════════════════════════════════════════════
#  1. VIDEASY EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

VIDEASY_SERVERS = [
    ("mb-flix","api"), ("1movies","api"), ("moviebox","api"), ("cdn","api"),
    ("primesrcme","api"), ("primewire","api2"), ("m4uhd","api2"),
    ("hdmovie","api"), ("lamovie","api"), ("superflix","api"),
    ("cuevana","api2"), ("overflix","api2"), ("visioncine","api"), ("meine","api"),
]

def extract_videasy(movie_url: str) -> dict:
    parsed = urlparse(movie_url)
    if parsed.netloc.lower() != "player.videasy.net":
        raise ExtractorError("Only player.videasy.net URLs are supported")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2 or parts[0] != "movie":
        raise ExtractorError("URL must be: https://player.videasy.net/movie/<tmdb_id>")
    tmdb_id = parts[1]

    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "*/*",
        "Origin": "https://player.videasy.net",
        "Referer": "https://player.videasy.net/",
    }
    errors = []
    for server, api_sub in VIDEASY_SERVERS:
        api_url = (
            f"https://{api_sub}.videasy.net/{server}/sources-with-title"
            f"?mediaType=movie&tmdbId={tmdb_id}"
        )
        try:
            r = _get(api_url, headers)
            encrypted = r.text
            if not encrypted or len(encrypted.strip()) < 10:
                errors.append(f"{server}: empty"); continue
            dec = _post(
                f"{ENC_DEC_API}/dec-videasy",
                {"text": encrypted, "id": str(tmdb_id)},
                {"User-Agent": DEFAULT_UA, "Content-Type": "application/json"},
            )
            decrypted = _api_unwrap(dec.json(), f"dec/{server}")
            streams = _find_streams(decrypted)
            if streams:
                return {"tmdb_id": tmdb_id, "server": server, "streams": streams, "source": "videasy"}
        except (requests.RequestException, ExtractorError) as e:
            errors.append(f"{server}: {e}")
        except Exception as e:
            errors.append(f"{server}: {e}")
    raise ExtractorError("All Videasy servers failed.\n" + "\n".join(errors[-6:]))


# ══════════════════════════════════════════════════════════════════════════════
#  2. VIDLINK EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

VIDLINK_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Origin": "https://vidlink.pro",
    "Referer": "https://vidlink.pro/",
    "Accept": "application/json",
}

def _vidlink_validate(data: dict, path: str):
    if data.get("status") != 200:
        raise ExtractorError(
            f"VidLink API error at {path} | status={data.get('status')} | "
            f"error={data.get('error', 'unknown')}"
        )
    return data["result"]

def _vidlink_encrypt_tmdb_id(tmdb_id: str) -> str:
    url = f"{ENC_DEC_API}/enc-vidlink?text={tmdb_id}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return _vidlink_validate(r.json(), url)

def _vidlink_parse_url(page_url: str) -> dict:
    parsed = urlparse(page_url)
    netloc = parsed.netloc.lower()
    if netloc not in {"vidlink.pro", "www.vidlink.pro"}:
        raise ExtractorError("Only vidlink.pro URLs are supported")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if not parts:
        raise ExtractorError("Unsupported VidLink URL format")
    if parts[0] == "movie":
        if len(parts) < 2:
            raise ExtractorError("Missing TMDB ID in VidLink movie URL")
        return {"type": "movie", "tmdb_id": parts[1], "season": None, "episode": None}
    if parts[0] == "tv":
        if len(parts) < 4:
            raise ExtractorError("VidLink TV URL must be: /tv/<id>/<season>/<episode>")
        return {"type": "tv", "tmdb_id": parts[1], "season": parts[2], "episode": parts[3]}
    raise ExtractorError("Unsupported VidLink URL format")

def _vidlink_build_api_url(content_type: str, enc_id: str, season=None, episode=None) -> str:
    if content_type == "movie":
        return f"https://vidlink.pro/api/b/movie/{enc_id}"
    if content_type == "tv":
        if not season or not episode:
            raise ExtractorError("Season and episode required for TV")
        return f"https://vidlink.pro/api/b/tv/{enc_id}/{season}/{episode}"
    raise ExtractorError("Invalid VidLink content type")

def extract_vidlink(movie_url: str) -> dict:
    info = _vidlink_parse_url(movie_url)
    tmdb_id = info["tmdb_id"]
    try:
        encrypted_id = _vidlink_encrypt_tmdb_id(tmdb_id)
    except Exception as e:
        raise ExtractorError(f"VidLink encrypt step failed: {e}")
    api_url = _vidlink_build_api_url(
        info["type"], encrypted_id, info["season"], info["episode"]
    )
    try:
        r = requests.get(api_url, headers=VIDLINK_HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise ExtractorError(f"VidLink API request failed: {e}")
    try:
        playlist = data["stream"]["playlist"]
    except (KeyError, TypeError) as e:
        raise ExtractorError(f"VidLink: could not find stream.playlist in response: {e}")
    if not playlist:
        raise ExtractorError("VidLink: empty playlist URL returned")
    return {
        "tmdb_id": tmdb_id,
        "server": "vidlink.pro",
        "streams": [playlist],
        "source": "vidlink",
    }


# ══════════════════════════════════════════════════════════════════════════════
#  3. PRIMESRC EXTRACTOR
# ══════════════════════════════════════════════════════════════════════════════

PRIMESRC_HEADERS = {
    "User-Agent": DEFAULT_UA,
    "Accept": "*/*",
    "Origin": "https://primesrc.me",
    "Referer": "https://primesrc.me/",
}

def _primesrc_parse_url(url: str) -> dict:
    """
    Accepts:
      https://primesrc.me/embed/movie?tmdb=<id>
      https://primesrc.me/embed/movie?imdb=<id>
      https://primesrc.me/embed/tv?tmdb=<id>&season=1&episode=1
      https://primesrc.me/embed/tv?imdb=<id>&season=1&episode=1
    Also plain TMDB IDs passed directly as the 'url' field.
    """
    # If it looks like a plain numeric ID, treat as movie tmdb
    if url.strip().isdigit():
        return {"type": "movie", "imdb_id": None, "tmdb_id": url.strip(), "season": None, "episode": None}

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)

    def first(k):
        return qs.get(k, [None])[0]

    path = parsed.path.lower()
    if "/movie" in path:
        media_type = "movie"
    elif "/tv" in path or "/series" in path or "/anime" in path:
        media_type = "tv"
    else:
        media_type = first("type") or "movie"

    return {
        "type":    media_type,
        "imdb_id": first("imdb"),
        "tmdb_id": first("tmdb"),
        "season":  first("season"),
        "episode": first("episode"),
    }


def _primesrc_fetch_servers(params: dict) -> list:
    imdb_id = params.get("imdb_id")
    tmdb_id = params.get("tmdb_id")
    media   = params["type"]
    season  = params.get("season")
    episode = params.get("episode")

    if imdb_id:
        id_param = f"imdb={imdb_id}"
    elif tmdb_id:
        id_param = f"tmdb={tmdb_id}"
    else:
        raise ExtractorError("PrimeSrc: no IMDB or TMDB id found in URL")

    if media == "movie":
        api_url = f"https://primesrc.me/api/v1/s?{id_param}&type=movie"
    else:
        if not season or not episode:
            raise ExtractorError("PrimeSrc: TV URL needs season and episode parameters")
        api_url = (
            f"https://primesrc.me/api/v1/s?{id_param}"
            f"&season={season}&episode={episode}&type=tv"
        )

    try:
        resp = requests.get(api_url, headers=PRIMESRC_HEADERS, timeout=20).json()
    except Exception as e:
        raise ExtractorError(f"PrimeSrc: server list request failed: {e}")

    servers = resp.get("servers", [])
    if not servers:
        raise ExtractorError("PrimeSrc: no servers returned from API")
    return servers


def _primesrc_resolve_key(key: str) -> str | None:
    embed_api = f"https://primesrc.me/api/v1/l?key={key}"
    solve_url = f"{ENC_DEC_API}/solve-primesrc?url={quote(embed_api)}"
    try:
        data = requests.get(solve_url, headers=PRIMESRC_HEADERS, timeout=15).json()
        if data.get("status") != 200:
            return None
        return data["result"]
    except Exception:
        return None


def extract_primesrc(movie_url: str) -> dict:
    """
    Accepts:
      https://primesrc.me/embed/movie?tmdb=<tmdb_id>
      https://primesrc.me/embed/movie?imdb=<imdb_id>
      https://primesrc.me/embed/tv?tmdb=<id>&season=1&episode=1
      https://primesrc.me/embed/tv?imdb=<id>&season=1&episode=1
    """
    params  = _primesrc_parse_url(movie_url)
    servers = _primesrc_fetch_servers(params)

    tmdb_id = params.get("tmdb_id") or params.get("imdb_id") or "unknown"
    streams  = []
    server_name = "primesrc.me"

    for srv in servers:
        key  = srv.get("key", "")
        name = str(srv.get("name") or "unknown")
        if not key:
            continue
        link = _primesrc_resolve_key(key)
        if link and link.startswith("http"):
            # Only collect m3u8 / HLS links directly; skip Dood/Voe embeds
            if ".m3u8" in link or "/master" in link:
                if link not in streams:
                    streams.append(link)
                    server_name = name
            # Also try to resolve voe.sx embeds inline
            elif "voe.sx" in link:
                m3u8 = _voe_decrypt(link)
                if m3u8 and m3u8 not in streams:
                    streams.append(m3u8)
                    server_name = name

    if not streams:
        raise ExtractorError(
            "PrimeSrc: no HLS streams could be extracted from any server. "
            "Doodstream/other non-HLS hosts are not supported via this player."
        )

    return {
        "tmdb_id": tmdb_id,
        "server":  server_name,
        "streams": streams,
        "source":  "primesrc",
    }


# ── Inline Voe decryptor (used by PrimeSrc pipeline) ─────────────────────────
import codecs
from base64 import b64decode as _b64dec

def _voe_decrypt(voe_embed_url: str) -> str | None:
    try:
        domain  = '{uri.scheme}://{uri.netloc}/'.format(uri=urlparse(voe_embed_url))
        session = requests.Session()
        session.headers.update({
            "Referer":    domain,
            "User-Agent": DEFAULT_UA,
        })
        html = session.get(voe_embed_url, timeout=20).text
        if 'Redirecting...' in html:
            redirect_url = re.search(r"href\s*=\s*'(.*?)';", html).group(1)
            html = session.get(redirect_url, timeout=20).text

        soup       = BeautifulSoup(html, 'html.parser')
        script_tag = soup.find('script', attrs={'type': 'application/json'})
        if not script_tag:
            return None

        obfuscated = script_tag.string
        encoded    = re.search(r'\["(.*?)"\]', obfuscated).group(1)
        decoded    = codecs.decode(encoded, 'rot_13')

        for p in ["@$", "^^", "~@", "%?", "*~", "!!", "#&"]:
            decoded = re.sub(re.escape(p), "_", decoded)
        decoded = decoded.replace("_", "")
        decoded = _b64dec(decoded).decode()
        decoded = ''.join(chr(ord(c) - 3) for c in decoded)[::-1]
        decoded = _b64dec(decoded).decode()
        data    = json.loads(decoded)
        return data.get('source')
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  EXTRACTOR REGISTRY
# ══════════════════════════════════════════════════════════════════════════════

EXTRACTORS = {
    "videasy":  extract_videasy,
    "vidlink":  extract_vidlink,
    "primesrc": extract_primesrc,
}

SOURCE_HEADERS = {
    "videasy": {
        "Referer": "https://player.videasy.net/",
        "Origin":  "https://player.videasy.net",
    },
    "vidlink": {
        "Referer": "https://vidlink.pro/",
        "Origin":  "https://vidlink.pro",
    },
    "primesrc": {
        "Referer": "https://primesrc.me/",
        "Origin":  "https://primesrc.me",
    },
}

SOURCE_SAMPLE_MOVIES = [
    ("Terminator 2", "280"),
    ("The Matrix",   "603"),
    ("Inception",    "27205"),
    ("Dark Knight",  "155"),
]


# ══════════════════════════════════════════════════════════════════════════════
#  FRONTEND HTML
# ══════════════════════════════════════════════════════════════════════════════

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>FoxyPlay — Pro M3U8 Player</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;700;800;900&display=swap" rel="stylesheet"/>
<script src="https://cdn.jsdelivr.net/npm/hls.js@1/dist/hls.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#04060d;--s1:#080c16;--s2:#0d1220;--s3:#121828;--s4:#1b2338;
  --border:rgba(255,255,255,.055);--border2:rgba(255,255,255,.11);
  --text:#dde4f2;--muted:#6b7a99;--muted2:#343d54;
  --acc:#4f8eff;--acc2:#2f6bda;
  --gold:#f0c060;--gold2:#c9923a;
  --green:#36d98a;--red:#e0506a;--cyan:#38c5e0;
  --purple:#a06cf0;--orange:#f07040;
  --r:14px;--r2:9px;--r3:6px;
  --c-videasy:#f0c060;
  --c-vidlink:#a06cf0;
  --c-primesrc:#36d98a;
}

html,body{height:100%;background:var(--bg);color:var(--text);
  font-family:'Syne',sans-serif;overflow-x:hidden;font-size:15px}

body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:
    radial-gradient(ellipse at 10% 10%,rgba(79,142,255,.13) 0,transparent 55%),
    radial-gradient(ellipse at 90% 80%,rgba(160,108,240,.09) 0,transparent 50%),
    radial-gradient(ellipse at 50% 50%,rgba(240,192,96,.04) 0,transparent 60%);}
body::after{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:
    linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);
  background-size:40px 40px;}

.shell{position:relative;z-index:1;max-width:1140px;margin:0 auto;
  padding:32px 24px 90px;display:flex;flex-direction:column;gap:20px}

/* ── top bar ── */
.topbar{display:flex;align-items:center;gap:14px;padding-bottom:4px}
.brand{display:flex;align-items:center;gap:13px}
.brand-mark{
  width:44px;height:44px;border-radius:12px;
  background:linear-gradient(135deg,var(--acc),var(--purple));
  display:grid;place-items:center;font-size:20px;
  box-shadow:0 0 28px rgba(79,142,255,.4)}
.brand-name{font-size:1.55rem;font-weight:900;letter-spacing:-.02em;
  background:linear-gradient(90deg,#fff 0%,var(--acc) 60%,var(--purple) 100%);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.brand-sub{font-family:'Space Mono',monospace;font-size:.58rem;color:var(--muted);
  letter-spacing:.14em;text-transform:uppercase;margin-top:2px}
.tb-spacer{flex:1}
.pill{padding:5px 12px;border-radius:20px;border:1px solid var(--border2);
  background:rgba(255,255,255,.04);font-size:.6rem;letter-spacing:.08em;
  text-transform:uppercase;font-family:'Space Mono',monospace;color:var(--muted);
  display:inline-flex;align-items:center;gap:6px}
.pill.live{border-color:rgba(54,217,138,.3);color:var(--green);
  animation:pulse-border 2.5s ease-in-out infinite}
@keyframes pulse-border{0%,100%{border-color:rgba(54,217,138,.3)}50%{border-color:rgba(54,217,138,.7)}}
.pill.btn{cursor:pointer;transition:all .15s}
.pill.btn:hover{color:var(--acc);border-color:rgba(79,142,255,.45);background:rgba(79,142,255,.07)}
.dot{width:6px;height:6px;border-radius:50%;background:currentColor;
  animation:blink 1.6s step-end infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}

/* ── url row ── */
.url-card{background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r);padding:14px;display:flex;gap:10px;flex-wrap:wrap;
  box-shadow:0 4px 20px rgba(0,0,0,.3)}
.url-input{flex:1;min-width:260px;padding:13px 16px;
  background:var(--s3);border:1px solid var(--border);border-radius:var(--r2);
  color:var(--text);font-family:'Space Mono',monospace;font-size:.82rem;
  outline:none;transition:border-color .18s,box-shadow .18s}
.url-input:focus{border-color:var(--acc);box-shadow:0 0 0 3px rgba(79,142,255,.12)}
.url-input::placeholder{color:var(--muted2)}

/* ── buttons ── */
.btn{border:none;cursor:pointer;font-family:'Syne',sans-serif;
  font-weight:700;letter-spacing:.05em;text-transform:uppercase;
  transition:all .16s;display:inline-flex;align-items:center;
  justify-content:center;gap:7px;border-radius:var(--r2);white-space:nowrap}
.btn-primary{
  background:linear-gradient(135deg,var(--acc),var(--acc2));
  color:#fff;padding:13px 22px;font-size:.76rem;
  box-shadow:0 4px 18px rgba(79,142,255,.3)}
.btn-primary:hover{filter:brightness(1.15);transform:translateY(-1px);
  box-shadow:0 6px 24px rgba(79,142,255,.45)}
.btn-ghost{background:rgba(255,255,255,.05);color:var(--text);
  border:1px solid var(--border2);padding:10px 16px;font-size:.7rem}
.btn-ghost:hover{border-color:var(--acc);color:var(--acc);background:rgba(79,142,255,.07)}
.btn-sm{padding:7px 12px;font-size:.62rem}
.btn-red{background:rgba(224,80,106,.1);color:var(--red);
  border:1px solid rgba(224,80,106,.25);padding:9px 14px;font-size:.68rem}
.btn-red:hover{background:rgba(224,80,106,.2)}
.btn:disabled{opacity:.35;cursor:not-allowed;transform:none!important}

/* ── extractor buttons ── */
.ext-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.ext-label{font-family:'Space Mono',monospace;font-size:.58rem;
  text-transform:uppercase;letter-spacing:.1em;color:var(--muted);
  flex-basis:100%;margin-bottom:2px}

.ext-btn{
  flex:1;min-width:130px;
  border:none;cursor:pointer;font-family:'Syne',sans-serif;
  font-weight:800;font-size:.74rem;letter-spacing:.06em;text-transform:uppercase;
  padding:13px 18px;border-radius:var(--r2);
  display:inline-flex;align-items:center;justify-content:center;gap:8px;
  transition:all .18s;position:relative;overflow:hidden}
.ext-btn::before{
  content:'';position:absolute;inset:0;opacity:0;
  background:linear-gradient(135deg,rgba(255,255,255,.15),rgba(255,255,255,0));
  transition:opacity .18s}
.ext-btn:hover::before{opacity:1}
.ext-btn:hover{transform:translateY(-2px)}
.ext-btn:active{transform:translateY(0)}

.ext-btn.videasy{
  background:linear-gradient(135deg,#f0c060,#c9923a);color:#1a0e00;
  box-shadow:0 4px 18px rgba(240,192,96,.28)}
.ext-btn.vidlink{
  background:linear-gradient(135deg,#a06cf0,#7040c8);color:#fff;
  box-shadow:0 4px 18px rgba(160,108,240,.28)}
.ext-btn.primesrc{
  background:linear-gradient(135deg,#36d98a,#1a9e5c);color:#001a0d;
  box-shadow:0 4px 18px rgba(54,217,138,.28)}

.ext-btn .ext-icon{font-size:1rem}
.ext-btn .ext-spinner{display:none;width:14px;height:14px;
  border:2px solid rgba(255,255,255,.3);border-top-color:currentColor;
  border-radius:50%;animation:spin .7s linear infinite}
.ext-btn.loading .ext-icon{display:none}
.ext-btn.loading .ext-spinner{display:inline-block}
.ext-btn.loading{opacity:.7;cursor:wait;transform:none!important}

@keyframes spin{to{transform:rotate(360deg)}}

/* ── player ── */
.player-card{background:#000;border:1px solid var(--border);
  border-radius:var(--r);overflow:hidden;
  box-shadow:0 24px 70px rgba(0,0,0,.6);position:relative}
.player-wrap{position:relative;width:100%;aspect-ratio:16/9;background:#000;
  display:flex;align-items:center;justify-content:center}
#video{width:100%;height:100%;display:block;background:#000}
.player-overlay{position:absolute;inset:0;display:flex;
  flex-direction:column;align-items:center;justify-content:center;
  gap:16px;color:var(--muted);pointer-events:none;text-align:center;padding:24px;
  background:radial-gradient(circle at center,rgba(13,18,32,.6),rgba(4,6,13,.9))}
.player-overlay svg{opacity:.2;filter:drop-shadow(0 0 20px var(--acc))}
.player-overlay .ov-title{font-size:1.1rem;font-weight:800;color:var(--text);opacity:.5}
.player-overlay p{font-family:'Space Mono',monospace;font-size:.72rem;
  line-height:1.7;color:var(--muted)}
.player-overlay.gone{display:none}

.loader{position:absolute;inset:0;display:none;align-items:center;
  justify-content:center;background:rgba(0,0,0,.6);z-index:5;
  backdrop-filter:blur(4px)}
.loader.vis{display:flex}
.spinner{width:48px;height:48px;border:3px solid rgba(255,255,255,.1);
  border-top-color:var(--acc);border-radius:50%;animation:spin .75s linear infinite}

.ctrl-bar{padding:12px 18px;background:var(--s1);
  border-top:1px solid var(--border);display:flex;align-items:center;
  gap:10px;flex-wrap:wrap}
.ctrl-info{flex:1;min-width:0;display:flex;align-items:center;gap:10px}
.ctrl-title{font-size:.76rem;font-family:'Space Mono',monospace;
  color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.src-badge{padding:2px 8px;border-radius:4px;font-size:.58rem;
  font-family:'Space Mono',monospace;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;flex-shrink:0}
.ctrl-stats{font-family:'Space Mono',monospace;font-size:.62rem;
  color:var(--muted2);white-space:nowrap}
.qsel{background:var(--s3);border:1px solid var(--border2);color:var(--text);
  border-radius:var(--r3);padding:6px 10px;font-family:'Space Mono',monospace;
  font-size:.68rem;cursor:pointer;outline:none;transition:border-color .15s}
.qsel:focus{border-color:var(--acc)}

/* ── status ── */
.status-card{display:none;padding:13px 18px;border-radius:var(--r2);
  font-family:'Space Mono',monospace;font-size:.73rem;line-height:1.6}
.status-card.vis{display:block;animation:fadeUp .3s ease}
.status-card.info{background:rgba(79,142,255,.07);border:1px solid rgba(79,142,255,.22);color:var(--acc)}
.status-card.ok{background:rgba(54,217,138,.06);border:1px solid rgba(54,217,138,.22);color:var(--green)}
.status-card.err{background:rgba(224,80,106,.06);border:1px solid rgba(224,80,106,.22);color:var(--red)}
.status-card pre{white-space:pre-wrap;word-break:break-word;font-size:.65rem;
  margin-top:7px;color:var(--muted);opacity:.8}

/* ── streams list ── */
.streams-card{display:none;background:var(--s1);border:1px solid var(--border);
  border-radius:var(--r);overflow:hidden}
.streams-card.vis{display:block;animation:fadeUp .3s ease}
.streams-hdr{padding:13px 18px;border-bottom:1px solid var(--border);
  background:var(--s2);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.streams-hdr h3{font-size:.76rem;text-transform:uppercase;
  letter-spacing:.1em;flex:1;font-weight:700}
.tag{font-family:'Space Mono',monospace;font-size:.6rem;
  padding:3px 9px;border-radius:4px;font-weight:700}
.tag.green{background:rgba(54,217,138,.1);border:1px solid rgba(54,217,138,.25);color:var(--green)}
.tag.acc{background:rgba(79,142,255,.1);border:1px solid rgba(79,142,255,.25);color:var(--acc)}
.sitem{padding:10px 16px;border-top:1px solid var(--border);
  display:flex;align-items:center;gap:8px;transition:background .12s}
.sitem:first-child{border-top:none}
.sitem:hover{background:var(--s2)}
.sitem .num{font-family:'Space Mono',monospace;font-size:.6rem;
  color:var(--acc);width:20px;flex-shrink:0}
.sitem .surl{flex:1;font-family:'Space Mono',monospace;font-size:.64rem;
  color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sitem .acts{display:flex;gap:5px;flex-shrink:0}

/* ── MODAL ── */
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);
  z-index:50;backdrop-filter:blur(10px);align-items:flex-start;
  justify-content:center;padding:56px 20px 20px;overflow-y:auto}
.modal-bg.vis{display:flex}
.modal{background:var(--s1);border:1px solid var(--border2);
  border-radius:var(--r);width:100%;max-width:580px;
  box-shadow:0 30px 90px rgba(0,0,0,.7);animation:slideUp .22s ease}
@keyframes slideUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.mhdr{padding:16px 22px;border-bottom:1px solid var(--border);
  background:var(--s2);display:flex;align-items:center;gap:11px;border-radius:var(--r) var(--r) 0 0}
.mhdr h3{flex:1;font-size:1.05rem;font-weight:800;color:var(--text)}
.mbody{padding:22px}
.frm-grp{margin-bottom:17px}
.frm-grp:last-child{margin-bottom:0}
.frm-grp label{display:block;font-size:.6rem;text-transform:uppercase;
  letter-spacing:.1em;color:var(--muted);font-family:'Space Mono',monospace;
  margin-bottom:6px;font-weight:700}
.frm-grp input,.frm-grp textarea{width:100%;padding:10px 13px;
  background:var(--s3);border:1px solid var(--border);border-radius:var(--r3);
  color:var(--text);font-family:'Space Mono',monospace;font-size:.78rem;
  outline:none;resize:vertical;transition:border-color .15s}
.frm-grp input:focus,.frm-grp textarea:focus{border-color:var(--acc)}
.frm-grp textarea{min-height:64px;font-size:.68rem;line-height:1.55}
.frm-note{font-size:.58rem;color:var(--muted2);
  font-family:'Space Mono',monospace;margin-top:5px;line-height:1.55}
.frm-note code{background:var(--s3);padding:1px 5px;border-radius:3px;color:var(--muted)}
.mftr{padding:14px 22px;border-top:1px solid var(--border);
  background:var(--s2);display:flex;gap:8px;justify-content:flex-end;
  flex-wrap:wrap;border-radius:0 0 var(--r) var(--r)}

.src-accent-videasy  .mhdr{border-top:3px solid var(--c-videasy)}
.src-accent-vidlink  .mhdr{border-top:3px solid var(--c-vidlink)}
.src-accent-primesrc .mhdr{border-top:3px solid var(--c-primesrc)}

/* ── samples ── */
.samples{display:flex;gap:8px;flex-wrap:wrap}
.sample-chip{padding:4px 12px;border-radius:14px;border:1px solid var(--border2);
  background:var(--s2);font-family:'Space Mono',monospace;font-size:.6rem;
  color:var(--muted);cursor:pointer;transition:all .15s}
.sample-chip:hover{color:var(--gold);border-color:rgba(240,192,96,.4);
  background:rgba(240,192,96,.06)}

/* ── divider ── */
.divider{display:flex;align-items:center;gap:10px}
.divider::before,.divider::after{content:'';flex:1;height:1px;background:var(--border)}
.divider span{font-family:'Space Mono',monospace;font-size:.58rem;
  color:var(--muted2);letter-spacing:.1em;text-transform:uppercase}

.fade{animation:fadeUp .3s ease}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}

@media(max-width:760px){
  .shell{padding:14px 12px 60px;gap:14px}
  .ext-btn{min-width:calc(50% - 5px);flex:none}
  .url-card{padding:10px;gap:8px}
  .btn-primary{flex:1}
}
@media(max-width:480px){
  .ext-btn{min-width:100%}
  .brand-name{font-size:1.2rem}
}
</style>
</head>
<body>
<div class="shell">

  <!-- ── TOP BAR ── -->
  <div class="topbar">
    <div class="brand">
      <div class="brand-mark">▶</div>
      <div>
        <div class="brand-name">FoxyPlay</div>
        <div class="brand-sub">Pro M3U8 Player</div>
      </div>
    </div>
    <div class="tb-spacer"></div>
    <span class="pill live"><span class="dot"></span>CF PROXY</span>
    <span class="pill btn" onclick="openHeaders()">⚙ HEADERS</span>
  </div>

  <!-- ── URL INPUT ── -->
  <div class="url-card">
    <input id="url" class="url-input" type="text"
      placeholder="Paste a direct .m3u8 URL and press PLAY…"
      onkeydown="if(event.key==='Enter') loadFromInput()"/>
    <button class="btn btn-primary" onclick="loadFromInput()">
      <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21"/></svg>
      PLAY
    </button>
  </div>

  <!-- ── PLAYER ── -->
  <div class="player-card">
    <div class="player-wrap">
      <video id="video" controls playsinline></video>
      <div class="player-overlay" id="overlay">
        <svg width="72" height="72" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
          <circle cx="12" cy="12" r="10"/>
          <polygon points="10 8 16 12 10 16 10 8" fill="currentColor" opacity=".5"/>
        </svg>
        <div class="ov-title">FoxyPlay</div>
        <p>Paste an .m3u8 URL above for direct playback<br/>
        or click one of the extractor buttons below<br/>
        to extract a stream from a movie URL.</p>
      </div>
      <div class="loader" id="loader"><div class="spinner"></div></div>
    </div>
    <div class="ctrl-bar">
      <div class="ctrl-info">
        <span id="src-badge" class="src-badge" style="display:none"></span>
        <span class="ctrl-title" id="now-playing">— idle —</span>
      </div>
      <span class="ctrl-stats" id="stats"></span>
      <div id="quality-wrap"></div>
      <button class="btn btn-ghost btn-sm" onclick="copyCurrentURL(this)">COPY URL</button>
      <button class="btn btn-ghost btn-sm" onclick="stopPlayer()">STOP</button>
    </div>
  </div>

  <!-- ── EXTRACTOR BUTTONS ── -->
  <div class="divider"><span>Stream Extractors</span></div>
  <div class="ext-row">
    <button class="ext-btn videasy"  id="btn-videasy"  onclick="openExtractModal('videasy')">
      <span class="ext-icon">★</span>
      <span class="ext-spinner"></span>
      VIDEASY
    </button>
    <button class="ext-btn vidlink"  id="btn-vidlink"  onclick="openExtractModal('vidlink')">
      <span class="ext-icon">◎</span>
      <span class="ext-spinner"></span>
      VIDLINK
    </button>
    <button class="ext-btn primesrc" id="btn-primesrc" onclick="openExtractModal('primesrc')">
      <span class="ext-icon">⬡</span>
      <span class="ext-spinner"></span>
      PRIMESRC
    </button>
  </div>

  <!-- ── STATUS ── -->
  <div class="status-card fade" id="status"></div>

  <!-- ── STREAMS LIST ── -->
  <div class="streams-card" id="streamsc">
    <div class="streams-hdr">
      <h3>Extracted Streams</h3>
      <span class="tag acc" id="strm-source"></span>
      <span class="tag acc" id="strm-server"></span>
      <span class="tag green" id="strm-count"></span>
    </div>
    <div id="streams-list"></div>
  </div>

</div><!-- /shell -->

<!-- ══════════════════════════════════════════════════════════
     HEADERS MODAL
═══════════════════════════════════════════════════════════ -->
<div class="modal-bg" id="hdrModal">
  <div class="modal">
    <div class="mhdr">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--acc)" stroke-width="2">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
      <h3>Proxy Headers</h3>
      <button class="btn btn-ghost btn-sm" onclick="closeModal('hdrModal')">✕</button>
    </div>
    <div class="mbody">
      <div class="frm-grp">
        <label>Referer</label>
        <input id="hf-ref" type="text"/>
        <div class="frm-note">Sent as <code>Referer</code> to the upstream CDN.</div>
      </div>
      <div class="frm-grp">
        <label>Origin</label>
        <input id="hf-org" type="text"/>
        <div class="frm-note">Sent as <code>Origin</code> — usually the host without trailing slash.</div>
      </div>
      <div class="frm-grp">
        <label>User-Agent</label>
        <input id="hf-ua" type="text"/>
      </div>
      <div class="frm-grp">
        <label>Extra JSON Headers (optional)</label>
        <textarea id="hf-extra" placeholder='{"X-Token":"abc"}'></textarea>
        <div class="frm-note">Raw JSON object merged into headers.</div>
      </div>
      <div class="frm-grp">
        <label>Cloudflare Proxy Base URL</label>
        <input id="hf-proxy" type="text"/>
        <div class="frm-note">Endpoint: <code>/proxy?url=B64&headers=B64</code></div>
      </div>
    </div>
    <div class="mftr">
      <button class="btn btn-red" onclick="resetHeaders()">RESET</button>
      <button class="btn btn-ghost btn-sm" onclick="closeModal('hdrModal')">CANCEL</button>
      <button class="btn btn-primary btn-sm" onclick="saveHeaders()">SAVE</button>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════════
     UNIVERSAL EXTRACTOR MODAL
═══════════════════════════════════════════════════════════ -->
<div class="modal-bg" id="extModal">
  <div class="modal" id="extModalInner">
    <div class="mhdr">
      <span id="ext-modal-icon" style="font-size:1.3rem"></span>
      <h3 id="ext-modal-title">Extractor</h3>
      <button class="btn btn-ghost btn-sm" onclick="closeModal('extModal')">✕</button>
    </div>
    <div class="mbody">
      <div class="frm-grp">
        <label id="ext-url-label">Movie URL</label>
        <input id="ext-url" type="text" onkeydown="if(event.key==='Enter') runExtract()"/>
        <div class="frm-note" id="ext-url-note"></div>
      </div>
      <div class="frm-grp">
        <label>Quick Samples (TMDB)</label>
        <div class="samples" id="ext-samples" style="padding:0;margin-top:2px"></div>
      </div>
    </div>
    <div class="mftr">
      <button class="btn btn-ghost btn-sm" onclick="closeModal('extModal')">CANCEL</button>
      <button class="btn btn-primary" id="ext-run-btn" onclick="runExtract()">⚡ EXTRACT</button>
    </div>
  </div>
</div>

<script>
// ═══════════════════════════════════════════════════════
//  CONFIG & CONSTANTS
// ═══════════════════════════════════════════════════════
const CF_PROXY_BASE = "__CF_PROXY__";
const DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36";

const HDR_DEFAULTS = {
  Referer:"https://player.videasy.net/",
  Origin:"https://player.videasy.net",
  UserAgent:DEFAULT_UA,
  ExtraJSON:"",
  ProxyURL:CF_PROXY_BASE
};
const HK = "foxyplay_hdrs_v2";
const QK = "foxyplay_pref_q";

const SOURCES = {
  videasy: {
    label:"Videasy", icon:"★", accent:"var(--c-videasy)",
    urlBase:"https://player.videasy.net/movie/",
    note:'Format: <code>https://player.videasy.net/movie/&lt;tmdb_id&gt;</code>',
    headers:{ Referer:"https://player.videasy.net/", Origin:"https://player.videasy.net" },
    badgeBg:"rgba(240,192,96,.15)", badgeColor:"#f0c060"
  },
  vidlink: {
    label:"VidLink", icon:"◎", accent:"var(--c-vidlink)",
    urlBase:"https://vidlink.pro/movie/",
    note:'Format: <code>https://vidlink.pro/movie/&lt;tmdb_id&gt;</code> or <code>https://vidlink.pro/tv/&lt;tmdb_id&gt;/&lt;season&gt;/&lt;episode&gt;</code>',
    headers:{ Referer:"https://vidlink.pro/", Origin:"https://vidlink.pro" },
    badgeBg:"rgba(160,108,240,.15)", badgeColor:"#a06cf0"
  },
  primesrc: {
    label:"PrimeSrc", icon:"⬡", accent:"var(--c-primesrc)",
    urlBase:"https://primesrc.me/embed/movie?tmdb=",
    note:'Format: <code>https://primesrc.me/embed/movie?tmdb=&lt;id&gt;</code> or <code>https://primesrc.me/embed/tv?tmdb=&lt;id&gt;&amp;season=1&amp;episode=1</code>',
    headers:{ Referer:"https://primesrc.me/", Origin:"https://primesrc.me" },
    badgeBg:"rgba(54,217,138,.15)", badgeColor:"#36d98a"
  }
};

const SAMPLE_MOVIES = [
  ["Terminator 2","280"],["The Matrix","603"],["Inception","27205"],["Dark Knight","155"]
];

let HDR = loadHeaders();
let hlsInst = null, levelsCache = [];
let currentRawURL = null, currentProxyURL = null;
let currentSource = null;
let activeExtractor = null;

const $ = id => document.getElementById(id);
const esc = s => String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');

// ═══════════════════════════════════════════════════════
//  HEADERS
// ═══════════════════════════════════════════════════════
function loadHeaders(){
  try{ const s=localStorage.getItem(HK); if(!s) return{...HDR_DEFAULTS};
    return{...HDR_DEFAULTS,...JSON.parse(s)}; }
  catch{ return{...HDR_DEFAULTS}; }
}
function openHeaders(){
  $('hf-ref').value=HDR.Referer;
  $('hf-org').value=HDR.Origin;
  $('hf-ua').value=HDR.UserAgent;
  $('hf-extra').value=HDR.ExtraJSON;
  $('hf-proxy').value=HDR.ProxyURL;
  $('hdrModal').classList.add('vis');
}
function saveHeaders(){
  const next={
    Referer:$('hf-ref').value.trim()||HDR_DEFAULTS.Referer,
    Origin:$('hf-org').value.trim()||HDR_DEFAULTS.Origin,
    UserAgent:$('hf-ua').value.trim()||HDR_DEFAULTS.UserAgent,
    ExtraJSON:$('hf-extra').value.trim(),
    ProxyURL:($('hf-proxy').value.trim()||HDR_DEFAULTS.ProxyURL).replace(/\/+$/,"")
  };
  if(next.ExtraJSON){ try{ JSON.parse(next.ExtraJSON); }
    catch{ alert("Extra Headers JSON is invalid."); return; } }
  HDR=next; localStorage.setItem(HK,JSON.stringify(HDR)); closeModal('hdrModal');
  if(currentRawURL) playStream(currentRawURL, $('now-playing').textContent, currentSource);
}
function resetHeaders(){ HDR={...HDR_DEFAULTS}; localStorage.removeItem(HK); openHeaders(); }

function buildHeadersDict(sourceKey){
  const h={
    Referer:HDR.Referer, Origin:HDR.Origin, "User-Agent":HDR.UserAgent
  };
  if(sourceKey && SOURCES[sourceKey]){
    Object.assign(h, SOURCES[sourceKey].headers);
  }
  if(HDR.ExtraJSON){ try{ Object.assign(h,JSON.parse(HDR.ExtraJSON)); }catch{} }
  return h;
}
function buildProxyURL(streamURL, sourceKey){
  const hdrs = buildHeadersDict(sourceKey);
  const u = encodeURIComponent(btoa(streamURL));
  const h = encodeURIComponent(btoa(JSON.stringify(hdrs)));
  return `${HDR.ProxyURL.replace(/\/+$/,"")}/proxy?url=${u}&headers=${h}`;
}

// ═══════════════════════════════════════════════════════
//  STATUS
// ═══════════════════════════════════════════════════════
function setStatus(type,html){
  const el=$('status'); el.className=`status-card vis ${type}`; el.innerHTML=html;
}
function clearStatus(){ $('status').classList.remove('vis'); }

// ═══════════════════════════════════════════════════════
//  PLAYER
// ═══════════════════════════════════════════════════════
function getPrefH(){ const s=localStorage.getItem(QK); return s?parseInt(s,10):720; }
function savePref(h){ localStorage.setItem(QK,String(h)); }

function loadFromInput(){
  const u=$('url').value.trim();
  if(!u){ setStatus('err','Paste an .m3u8 URL first.'); return; }
  playStream(u,'Direct URL',null);
}

function playStream(url, label, sourceKey){
  currentRawURL=url; currentSource=sourceKey;
  currentProxyURL=buildProxyURL(url, sourceKey);
  $('overlay').classList.add('gone');
  $('loader').classList.add('vis');
  $('now-playing').textContent=label||url;
  $('stats').textContent='';
  clearStatus();
  $('quality-wrap').innerHTML='';
  const badge=$('src-badge');
  if(sourceKey && SOURCES[sourceKey]){
    const s=SOURCES[sourceKey];
    badge.textContent=s.label;
    badge.style.background=s.badgeBg;
    badge.style.color=s.badgeColor;
    badge.style.border=`1px solid ${s.badgeColor}55`;
    badge.style.display='';
  } else {
    badge.style.display='none';
  }
  mountHLS(currentProxyURL);
}

function stopPlayer(){
  if(hlsInst){ hlsInst.destroy(); hlsInst=null; }
  const v=$('video'); v.removeAttribute('src'); v.load();
  $('overlay').classList.remove('gone');
  $('loader').classList.remove('vis');
  $('now-playing').textContent='— idle —';
  $('stats').textContent='';
  $('quality-wrap').innerHTML='';
  $('src-badge').style.display='none';
  currentRawURL=null; currentProxyURL=null; currentSource=null;
}

function mountHLS(src){
  const v=$('video');
  if(hlsInst){ hlsInst.destroy(); hlsInst=null; }
  if(Hls.isSupported()){
    const hls=new Hls({ startLevel:-1, lowLatencyMode:false });
    hlsInst=hls;
    hls.loadSource(src);
    hls.attachMedia(v);
    hls.on(Hls.Events.MANIFEST_PARSED,(_,data)=>{
      $('loader').classList.remove('vis');
      const levels=data.levels.map((l,i)=>({
        i,h:l.height||0,b:l.bitrate||0,
        lbl:l.height?`${l.height}p`:(l.bitrate?`${Math.round(l.bitrate/1000)}k`:`L${i+1}`)
      }));
      const seen=new Map();
      levels.forEach(l=>{ if(!seen.has(l.lbl)) seen.set(l.lbl,l); });
      const uniq=Array.from(seen.values()).sort((a,b)=>a.h-b.h);
      levelsCache=uniq;
      const pref=getPrefH(); const chosen=pickLevel(uniq,pref);
      hls.currentLevel=chosen;
      renderQualityBar(uniq,chosen,pref);
      setStatus('ok',`✓ Loaded — ${uniq.length} quality level${uniq.length===1?'':'s'}`);
      v.play().catch(()=>{});
      updateStats(hls);
    });
    hls.on(Hls.Events.LEVEL_SWITCHED,()=>updateStats(hls));
    hls.on(Hls.Events.ERROR,(_,d)=>{
      if(d.fatal){
        $('loader').classList.remove('vis');
        setStatus('err',
          `Playback error: <b>${esc(d.type)}</b> — ${esc(d.details||'')}`+
          `<pre>${esc(d.reason||d.error?.message||'unknown')}</pre>`);
      }
    });
  } else if(v.canPlayType('application/vnd.apple.mpegurl')){
    v.src=src;
    v.addEventListener('loadedmetadata',()=>{
      $('loader').classList.remove('vis');
      setStatus('ok','✓ Native HLS (Safari)');
      v.play().catch(()=>{});
    });
    v.addEventListener('error',()=>{
      $('loader').classList.remove('vis');
      setStatus('err','Native HLS playback failed.');
    });
  } else {
    $('loader').classList.remove('vis');
    setStatus('err','HLS not supported in this browser.');
  }
}
function pickLevel(levels,pref){
  for(const t of [pref,720,1080,480,360]){
    const m=levels.find(l=>l.h===t); if(m) return m.i;
  }
  return levels.length?levels[Math.floor(levels.length/2)].i:-1;
}
function renderQualityBar(levels,chosen,pref){
  if(!levels.length){ $('quality-wrap').innerHTML=''; return; }
  const opts=[`<option value="-1">AUTO</option>`].concat(
    levels.map(l=>`<option value="${l.i}"${l.i===chosen?' selected':''}>${l.lbl}${l.h===pref?' ★':''}</option>`)
  ).join('');
  $('quality-wrap').innerHTML=
    `<select class="qsel" onchange="changeQuality(this)">${opts}</select>`;
}
function changeQuality(sel){
  const idx=parseInt(sel.value,10);
  if(hlsInst) hlsInst.currentLevel=idx;
  if(idx>=0){ const lv=levelsCache.find(l=>l.i===idx); if(lv&&lv.h) savePref(lv.h); }
}
function updateStats(hls){
  try{
    const lvl=hls.levels[hls.currentLevel];
    if(lvl){
      const kbps=lvl.bitrate?`${Math.round(lvl.bitrate/1000)}k`:'';
      const res=lvl.height?`${lvl.width||'?'}×${lvl.height}`:'';
      $('stats').textContent=[res,kbps].filter(Boolean).join(' · ');
    }
  }catch{}
}
async function copyCurrentURL(btn){
  const target=currentProxyURL||$('url').value.trim(); if(!target) return;
  try{
    await navigator.clipboard.writeText(target);
    const o=btn.textContent; btn.textContent='✓ COPIED';
    setTimeout(()=>btn.textContent=o,1400);
  }catch{}
}

// ═══════════════════════════════════════════════════════
//  EXTRACTOR MODAL (universal)
// ═══════════════════════════════════════════════════════
function openExtractModal(sourceKey){
  activeExtractor=sourceKey;
  const s=SOURCES[sourceKey];
  $('ext-modal-icon').textContent=s.icon;
  $('ext-modal-title').textContent=s.label+' Extractor';
  $('ext-url-label').textContent=s.label+' Movie URL';
  $('ext-url-note').innerHTML=s.note;
  // For primesrc the default placeholder includes ?tmdb=
  $('ext-url').value=s.urlBase+'280';
  const runBtn=$('ext-run-btn');
  runBtn.className='btn ext-btn '+sourceKey;
  runBtn.innerHTML=`<span>${s.icon}</span> EXTRACT`;
  $('extModalInner').className='modal src-accent-'+sourceKey;
  const samplesEl=$('ext-samples');
  samplesEl.innerHTML=SAMPLE_MOVIES.map(([name,id])=>{
    // For primesrc, the URL base already includes ?tmdb= so we don't add a slash
    const sampleUrl = sourceKey==='primesrc'
      ? `${s.urlBase}${id}`
      : `${s.urlBase}${id}`;
    return `<span class="sample-chip"
      onclick="document.getElementById('ext-url').value='${esc(sampleUrl)}'"
    >${name} (${id})</span>`;
  }).join('');
  $('extModal').classList.add('vis');
  setTimeout(()=>$('ext-url').focus(),80);
}

async function runExtract(){
  if(!activeExtractor) return;
  const url=$('ext-url').value.trim();
  if(!url){ alert('Enter a URL'); return; }
  closeModal('extModal');

  const s=SOURCES[activeExtractor];
  const btn=document.getElementById('btn-'+activeExtractor);
  btn.classList.add('loading');

  setStatus('info',`⏳ Extracting via <b>${s.label}</b> — <code>${esc(url)}</code>`);
  $('streamsc').classList.remove('vis');

  try{
    const r=await fetch('/api/extract',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({source:activeExtractor, url})
    });
    const d=await r.json();
    if(!r.ok){
      setStatus('err',
        `<b>${s.label}</b> extraction failed: ${esc(d.detail?.error||d.error||'unknown')}`+
        (d.detail?.tried?`<pre>${esc(d.detail.tried)}</pre>`:''));
      return;
    }
    if(!d.streams||!d.streams.length){ setStatus('err','No streams found.'); return; }
    setStatus('ok',
      `✓ <b>${s.label}</b> — found ${d.streams.length} stream${d.streams.length===1?'':'s'} `+
      `on server <b>${esc(d.server)}</b> (TMDB ${esc(d.tmdb_id)})`);
    showStreams(d.streams, d.server, d.tmdb_id, activeExtractor);
    playStream(d.streams[0], `${s.label} · ${d.server} · TMDB ${d.tmdb_id}`, activeExtractor);
  } catch(e){
    setStatus('err',`Network error: ${esc(String(e))}`);
  } finally{
    btn.classList.remove('loading');
  }
}

function showStreams(streams, server, tmdb, sourceKey){
  $('streamsc').classList.add('vis');
  const s=SOURCES[sourceKey]||{label:sourceKey};
  $('strm-source').textContent=s.label||sourceKey;
  $('strm-server').textContent=server||'—';
  $('strm-count').textContent=`${streams.length} stream${streams.length===1?'':'s'}`;
  $('streams-list').innerHTML=streams.map((u,i)=>`
    <div class="sitem">
      <span class="num">${String(i+1).padStart(2,'0')}</span>
      <span class="surl" title="${esc(u)}">${esc(u)}</span>
      <div class="acts">
        <button class="btn btn-primary btn-sm"
          onclick="playStream(${JSON.stringify(u)},${JSON.stringify(`${s.label}·${server}·TMDB ${tmdb}`)},${JSON.stringify(sourceKey)})">
          ▶ PLAY
        </button>
        <button class="btn btn-ghost btn-sm" onclick="copyText(${JSON.stringify(u)},this)">COPY</button>
        <button class="btn btn-ghost btn-sm" onclick="copyText(buildProxyURL(${JSON.stringify(u)},${JSON.stringify(sourceKey)}),this)">PROXY</button>
      </div>
    </div>
  `).join('');
}

async function copyText(text,btn){
  try{
    await navigator.clipboard.writeText(text);
    const o=btn.textContent; btn.textContent='✓';
    setTimeout(()=>btn.textContent=o,1200);
  }catch{}
}

// ═══════════════════════════════════════════════════════
//  MODAL HELPERS
// ═══════════════════════════════════════════════════════
function closeModal(id){ $(id).classList.remove('vis'); }
document.querySelectorAll('.modal-bg').forEach(bg=>{
  bg.addEventListener('click',e=>{ if(e.target===bg) bg.classList.remove('vis'); });
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape')
    document.querySelectorAll('.modal-bg.vis').forEach(m=>m.classList.remove('vis'));
});
</script>
</body>
</html>"""

HTML = HTML.replace("__CF_PROXY__", CF_PROXY_BASE)


# ══════════════════════════════════════════════════════════════════════════════
#  FASTAPI APP
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(title="FoxyPlay — Pro M3U8 Player")


class ExtractReq(BaseModel):
    source: str
    url: str


@app.get("/", response_class=HTMLResponse)
def root():
    return HTMLResponse(HTML)


@app.get("/api/healthz")
def healthz():
    return {
        "status": "ok",
        "cf_proxy": CF_PROXY_BASE,
        "extractors": list(EXTRACTORS.keys()),
    }


@app.post("/api/extract")
def api_extract(body: ExtractReq):
    source = body.source.lower().strip()
    fn = EXTRACTORS.get(source)
    if not fn:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Unknown source '{source}'. Valid: {list(EXTRACTORS)}"}
        )
    try:
        result = fn(body.url)
        return result
    except ExtractorError as e:
        msg = str(e)
        head, _, tail = msg.partition("\n")
        raise HTTPException(
            status_code=502,
            detail={"error": head, "tried": tail or ""}
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"error": f"{type(e).__name__}: {e}"}
        )


# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║         FoxyPlay  —  Pro M3U8 Player  (3 Extractors)         ║
╠══════════════════════════════════════════════════════════════╣
║  Open      : http://localhost:{port:<32}║
║  CF Proxy  : {CF_PROXY_BASE:<48}║
║  Extractors: videasy · vidlink · primesrc                      ║
╚══════════════════════════════════════════════════════════════╝
""")
    uvicorn.run(app, host="0.0.0.0", port=port)