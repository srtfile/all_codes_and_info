"""
PrimeSrc server lister (hard-coded URL).

Edit EMBED_URL below to point at any /embed/movie or /embed/tv URL on
primesrc.me. Run with no arguments:

    python primesrc_list.py

Generates:
  - servers_<tmdb>.json   structured data (name, key, file_name, etc.)
  - servers_<tmdb>.html   clickable browser page; each row has a "Resolve"
                          button that opens /api/v1/l?key=... in a new tab
                          (your real browser handles Cloudflare).

Why no auto-resolve here:
  /api/v1/l is gated by a Cloudflare Turnstile widget that only succeeds
  on user-gesture-driven calls. Selenium, Playwright, cloudscraper and
  even Tampermonkey scripts that trigger the call programmatically all
  get HTTP 403. So the resolve step has to happen in your real browser,
  which is exactly what the HTML page is for - one click per server.
"""

from __future__ import annotations

import html
import json
import os
import sys
import urllib.parse
import webbrowser
from typing import Any

# --------------------------------------------------------------------------- #
# CONFIG  --  change this URL to point at any movie / tv embed page           #
# --------------------------------------------------------------------------- #
EMBED_URL = "https://primesrc.me/embed/movie?tmdb=45050"
OPEN_HTML_AFTER = True       # auto-open the generated HTML page
OUT_DIR = "."                # where to write the json + html files
# --------------------------------------------------------------------------- #

BASE = "https://primesrc.me"

DEFAULT_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) "
        "Gecko/20100101 Firefox/131.0"
    ),
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "dnt": "1",
}


def _build_session():
    try:
        import cloudscraper  # type: ignore

        s = cloudscraper.create_scraper(
            browser={"browser": "firefox", "platform": "windows", "mobile": False}
        )
    except ImportError:
        import requests

        s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    return s


def fetch_servers(
    tmdb: str | int,
    media_type: str = "movie",
    season: int | None = None,
    episode: int | None = None,
) -> dict[str, Any]:
    """Call /api/v1/s and return the parsed JSON {servers: [...], info: {...}}."""
    session = _build_session()
    # warm cf_clearance
    try:
        session.get(f"{BASE}/embed/movie", timeout=30)
    except Exception:
        pass

    params: dict[str, Any] = {"tmdb": str(tmdb), "type": media_type}
    if media_type == "tv":
        if season is None or episode is None:
            raise ValueError("season and episode are required for tv")
        params["season"] = str(season)
        params["episode"] = str(episode)

    headers = {"referer": f"{BASE}/embed/{media_type}?tmdb={tmdb}"}
    r = session.get(f"{BASE}/api/v1/s", params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PrimeSrc servers - __TITLE__</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: system-ui, -apple-system, sans-serif;
    max-width: 1100px;
    margin: 24px auto;
    padding: 0 16px;
  }
  header { display: flex; gap: 16px; align-items: flex-start; }
  header img { width: 120px; border-radius: 8px; }
  header h1 { margin: 0 0 4px 0; font-size: 22px; }
  header p { margin: 4px 0; color: #666; font-size: 14px; }
  .toolbar {
    margin: 18px 0;
    display: flex; gap: 12px; align-items: center;
  }
  .toolbar button, .resolve-btn, .play-btn {
    background: #0b8a3e; color: #fff; border: none; padding: 8px 12px;
    border-radius: 6px; cursor: pointer; font-size: 14px;
  }
  .toolbar button:disabled { opacity: 0.5; cursor: default; }
  .play-btn { background: #1565c0; }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td {
    text-align: left; padding: 8px 10px;
    border-bottom: 1px solid rgba(127,127,127,0.25);
    vertical-align: top;
  }
  th { background: rgba(127,127,127,0.1); font-weight: 600; }
  td.name { font-weight: 600; white-space: nowrap; }
  td.key  { font-family: monospace; color: #888; }
  td.file { word-break: break-all; }
  td.actions { white-space: nowrap; }
  .embed-cell input {
    width: 100%; box-sizing: border-box;
    font-family: monospace; font-size: 12px;
    padding: 4px 6px;
  }
  .status-ok  { color: #0b8a3e; font-weight: 600; }
  .status-err { color: #c62828; font-weight: 600; }
  footer { margin-top: 24px; color: #888; font-size: 12px; }
  .hint {
    background: #fff3cd; color: #663c00;
    border-left: 4px solid #f0ad4e;
    padding: 10px 14px; border-radius: 4px;
    margin: 16px 0; font-size: 14px;
  }
  @media (prefers-color-scheme: dark) {
    body { background: #121212; color: #e0e0e0; }
    header p { color: #aaa; }
    .hint { background: #3a2f00; color: #ffe9a8; }
  }
</style>
</head>
<body>

<header>
  <img src="__IMG__" alt="">
  <div>
    <h1>__TITLE__ <span style="color:#888;font-weight:400">(__YEAR__)</span></h1>
    <p>TMDB id: <code>__TMDB__</code> &middot; type: <code>__TYPE__</code> __SUFFIX__</p>
    <p>__DESC__</p>
  </div>
</header>

<div class="hint">
  <strong>How to resolve:</strong>
  Click <em>Resolve</em> on a row. A new tab opens at
  <code>primesrc.me/api/v1/l?key=...</code>. Your real Firefox handles
  Cloudflare; the JSON response (with the real embed URL) appears in that tab.
  Copy the <code>link</code> field, paste it back into the input next to the
  row, and click <em>Save</em>. The page also offers a <em>Play</em> button
  that just opens the PrimeSrc embed UI on that server.
</div>

<div class="toolbar">
  <button id="copy-keys">Copy all keys</button>
  <button id="export">Export filled rows as JSON</button>
  <span id="status" style="margin-left:auto;color:#888"></span>
</div>

<table>
<thead>
<tr>
  <th>#</th>
  <th>Server</th>
  <th>Key</th>
  <th>File</th>
  <th>Size</th>
  <th>Embed URL (paste here)</th>
  <th>Actions</th>
</tr>
</thead>
<tbody>
__ROWS__
</tbody>
</table>

<footer>
  Generated by primesrc_list.py from the captured /api/v1/s response.
</footer>

<script>
const STATUS = document.getElementById('status');
function setStatus(msg, ok) {
  STATUS.textContent = msg;
  STATUS.className = ok ? 'status-ok' : 'status-err';
  setTimeout(() => STATUS.textContent = '', 4000);
}

// "Resolve" -> open the API URL in a new tab. The user's real Firefox
// passes the Cloudflare check and the JSON shows up directly.
document.querySelectorAll('.resolve-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.key;
    // first tickle /spiderman?l= so the site doesn't flag the request
    fetch('https://primesrc.me/spiderman?l=' + encodeURIComponent(key),
          {mode: 'no-cors', credentials: 'include'}).catch(()=>{});
    setTimeout(() => {
      window.open('https://primesrc.me/api/v1/l?key=' +
        encodeURIComponent(key), '_blank');
    }, 250);
  });
});

document.querySelectorAll('.play-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const key = btn.dataset.key;
    // primesrc UI accepts ?server=<key> on /embed/<type>?tmdb=...
    const tmdb = btn.dataset.tmdb;
    const type = btn.dataset.type;
    const season = btn.dataset.season;
    const episode = btn.dataset.episode;
    let u = 'https://primesrc.me/embed/' + type + '?tmdb=' + tmdb +
      '&server=' + encodeURIComponent(key);
    if (type === 'tv' && season && episode) {
      u += '&season=' + season + '&episode=' + episode;
    }
    window.open(u, '_blank');
  });
});

document.getElementById('copy-keys').addEventListener('click', () => {
  const keys = Array.from(document.querySelectorAll('td.key'))
    .map(td => td.textContent.trim()).join('\\n');
  navigator.clipboard.writeText(keys)
    .then(() => setStatus('keys copied (' + keys.split('\\n').length + ')', true))
    .catch(e => setStatus('clipboard failed: ' + e, false));
});

document.getElementById('export').addEventListener('click', () => {
  const rows = Array.from(document.querySelectorAll('tr[data-key]')).map(tr => {
    const key  = tr.dataset.key;
    const name = tr.querySelector('td.name').textContent.trim();
    const file = tr.querySelector('td.file').textContent.trim();
    const size = tr.querySelector('td.size').textContent.trim();
    const link = tr.querySelector('input.embed-input').value.trim();
    return {name, key, file_name: file, file_size: size || null,
            link: link || null};
  });
  const filled = rows.filter(r => r.link);
  const blob = new Blob([JSON.stringify(filled, null, 2)],
                        {type: 'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'primesrc_resolved.json';
  a.click();
  setStatus('exported ' + filled.length + ' filled row(s)', true);
});

// persist embed URLs in localStorage so they survive refresh
const STORE_KEY = 'primesrc-embed-' + location.pathname;
function loadCache() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); }
  catch { return {}; }
}
function saveCache(c) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(c)); } catch {}
}

const cache = loadCache();
document.querySelectorAll('input.embed-input').forEach(inp => {
  const key = inp.dataset.key;
  if (cache[key]) inp.value = cache[key];
  inp.addEventListener('input', () => {
    cache[key] = inp.value.trim();
    saveCache(cache);
  });
});
</script>

</body>
</html>
"""


def _row(idx: int, s: dict[str, Any], tmdb: str, media_type: str,
         season: int | None, episode: int | None) -> str:
    name = html.escape(s.get("name") or "")
    key = html.escape(s.get("key") or "")
    file_name = html.escape(s.get("file_name") or "")
    file_size = html.escape(s.get("file_size") or "")
    season_attr = f' data-season="{season}"' if season is not None else ""
    episode_attr = f' data-episode="{episode}"' if episode is not None else ""
    return f"""<tr data-key="{key}">
  <td>{idx}</td>
  <td class="name">{name}</td>
  <td class="key">{key}</td>
  <td class="file">{file_name}</td>
  <td class="size">{file_size}</td>
  <td class="embed-cell">
    <input class="embed-input" data-key="{key}" type="text"
           placeholder="paste link from /api/v1/l response">
  </td>
  <td class="actions">
    <button class="resolve-btn" data-key="{key}">Resolve</button>
    <button class="play-btn" data-key="{key}"
            data-tmdb="{html.escape(str(tmdb))}"
            data-type="{html.escape(media_type)}"{season_attr}{episode_attr}>
      Play
    </button>
  </td>
</tr>"""


def render_html(
    payload: dict[str, Any],
    tmdb: str,
    media_type: str,
    season: int | None,
    episode: int | None,
) -> str:
    info = payload.get("info") or {}
    servers = payload.get("servers") or []

    title = info.get("title") or info.get("name") or f"TMDB {tmdb}"
    release = info.get("release_date") or info.get("first_air_date") or ""
    year = release[:4] if release else ""
    desc = info.get("description") or info.get("overview") or ""
    img = info.get("tmdb_image") or ""
    if img and img.startswith("/"):
        img = "https://image.tmdb.org/t/p/w200" + img

    suffix = ""
    if media_type == "tv":
        suffix = f"&middot; S{season:02d}E{episode:02d}"

    rows = "\n".join(
        _row(i + 1, s, tmdb, media_type, season, episode)
        for i, s in enumerate(servers)
    )

    return (
        HTML_TEMPLATE
        .replace("__TITLE__", html.escape(title))
        .replace("__YEAR__", html.escape(year))
        .replace("__TMDB__", html.escape(str(tmdb)))
        .replace("__TYPE__", html.escape(media_type))
        .replace("__SUFFIX__", suffix)
        .replace("__DESC__", html.escape(desc))
        .replace("__IMG__", html.escape(img))
        .replace("__ROWS__", rows)
    )


def _parse_embed_url(url: str) -> dict[str, Any]:
    """
    Extract tmdb / type / season / episode from a primesrc.me embed URL.

    Accepts e.g.:
        https://primesrc.me/embed/movie?tmdb=296
        https://primesrc.me/embed/tv?tmdb=1399&season=1&episode=1
        primesrc.me/embed/movie?tmdb=27205           (no scheme)
        /embed/tv?tmdb=1399&season=2&episode=4       (path only)
    """
    if "://" not in url and not url.startswith("/"):
        url = "https://" + url
    p = urllib.parse.urlparse(url)
    path = p.path or url
    if "/embed/movie" in path:
        media_type = "movie"
    elif "/embed/tv" in path:
        media_type = "tv"
    else:
        raise ValueError(
            f"URL must contain /embed/movie or /embed/tv: {url!r}"
        )
    qs = urllib.parse.parse_qs(p.query)
    tmdb = (qs.get("tmdb") or [None])[0]
    if not tmdb:
        raise ValueError(f"missing tmdb= query parameter in {url!r}")
    season = qs.get("season", [None])[0]
    episode = qs.get("episode", [None])[0]
    return {
        "tmdb": tmdb,
        "type": media_type,
        "season": int(season) if season else None,
        "episode": int(episode) if episode else None,
    }


def main() -> int:
    try:
        cfg = _parse_embed_url(EMBED_URL)
    except ValueError as e:
        print(f"[!] bad EMBED_URL: {e}", file=sys.stderr)
        return 2

    if cfg["type"] == "tv" and (cfg["season"] is None or cfg["episode"] is None):
        print(
            "[!] tv URLs need both ?season= and ?episode= "
            f"(got {EMBED_URL!r})",
            file=sys.stderr,
        )
        return 2

    print(
        f"[*] EMBED_URL = {EMBED_URL}\n"
        f"    tmdb={cfg['tmdb']} type={cfg['type']}"
        + (f" season={cfg['season']} episode={cfg['episode']}"
           if cfg["type"] == "tv" else ""),
        file=sys.stderr,
    )

    print(f"[*] fetching /api/v1/s ...", file=sys.stderr)
    data = fetch_servers(cfg["tmdb"], cfg["type"], cfg["season"], cfg["episode"])

    info = data.get("info") or {}
    servers = data.get("servers") or []
    print(
        f"[+] {info.get('title', '?')} ({info.get('release_date', '?')}) "
        f"-> {len(servers)} servers",
        file=sys.stderr,
    )

    suffix = ""
    if cfg["type"] == "tv":
        suffix = f"_s{cfg['season']:02d}e{cfg['episode']:02d}"
    base = os.path.join(OUT_DIR, f"servers_{cfg['tmdb']}{suffix}")

    json_path = base + ".json"
    html_path = base + ".html"

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    print(f"[+] wrote {json_path}", file=sys.stderr)

    page = render_html(data, cfg["tmdb"], cfg["type"], cfg["season"], cfg["episode"])
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"[+] wrote {html_path}", file=sys.stderr)

    print(f"\n{'#':<3} {'NAME':<12} {'KEY':<8} FILE", file=sys.stderr)
    for i, s in enumerate(servers, 1):
        print(
            f"{i:<3} {(s.get('name') or '')[:12]:<12} "
            f"{(s.get('key') or '')[:8]:<8} "
            f"{(s.get('file_name') or '')[:80]}",
            file=sys.stderr,
        )

    if OPEN_HTML_AFTER:
        try:
            webbrowser.open("file:///" + os.path.abspath(html_path).replace("\\", "/"))
        except Exception as e:
            print(f"[!] open failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
