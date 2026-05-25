"""
GDFlix / GoFlix Download Automation
=====================================
Traffic Analysis Summary
------------------------
FLOW:
  1. GET  https://new18.gdflix.net/file/<FILE_ID>
       - Requires: PHPSESSID cookie (from Google OAuth login)
       - Returns: HTML with direct CDN link OR buttons to generate links
       - Key: hardcoded static key "8e8f458e173b38801aab32698fc4d3a2b7cc115c"

  2. POST https://new18.gdflix.net/file/<FILE_ID>
       - Headers: x-token: new18.gdflix.net
       - Body (multipart): action=cloud, key=8e8f458e173b38801aab32698fc4d3a2b7cc115c, action_token=<cf_turnstile>
       - Returns JSON: {"url": "..."} or {"visit_url": "..."}

  3. GET  https://new18.gdflix.net/zfile/<TIMESTAMP>/<FILE_ID>
       - Redirect chain → final CDN download URL

  4. Direct CDN URLs observed:
       - https://lest.aws-eu.online/<hex_token>::<hash>/<filename>
       - https://instant.busycdn.xyz/<hex_token>::<hash>
       - https://video-downloads.googleusercontent.com/<token>

  5. GoFlix mirror API (goflix.sbs):
       - GET  https://goflix.sbs/en/mirror/<MULTIUP_HASH>
       - POST https://goflix.sbs/ajax/add-download-for-link
         Body: id=<numeric_id>
         Headers: x-csrftoken, PHPSESSID cookie

ANTI-BOT:
  - Cloudflare Turnstile on /file/<id> POST (action_token required)
  - reCAPTCHA v2 on /login page
  - Google OAuth for session (PHPSESSID set after /verifyauth callback)
  - Cloudflare WAF on new18.gdflix.net

STRATEGY (shortest path):
  - If PHPSESSID is already captured → skip OAuth entirely
  - Direct CDN links in HTML are immediately usable (no POST needed)
  - Turnstile token is only needed for the "Generate" button POST
  - GoFlix mirror API is fully replayable with just PHPSESSID + CSRF token
"""

import re
import sys
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

# ─────────────────────────────────────────────
# CAPTURED SESSION CREDENTIALS (from MITM)
# Replace these when they expire.
# ─────────────────────────────────────────────
GDFLIX_SESSION = {
    # Captured PHPSESSID for new18.gdflix.net
    "PHPSESSID": "cfcc4352e6953ed647109e794a32e659",
}

GOFLIX_SESSION = {
    # Captured cookies for goflix.sbs
    "PHPSESSID": "e4p3qe15boinhc8ki8hdhkc5ut",
    "_locale": "en",
    "welcome_message_1": "true",
    "timezone": "Asia/Dhaka",
    # Captured CSRF token (rotate with each session)
    "x_csrftoken": "6.oBIJEXl_oc3yRklSN0-CnN_v6yEIdDM3SruQz0cNPK0.9ll9cAorw5W0cicZRSrV-bSWjEBpAnIFfdHn-DV7dN_jVmRFKgvFu8IeAA",
}

# Static key embedded in gdflix JS (does not rotate)
GDFLIX_STATIC_KEY = "8e8f458e173b38801aab32698fc4d3a2b7cc115c"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"

BASE_HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
}


# ─────────────────────────────────────────────
# SESSION SETUP
# ─────────────────────────────────────────────

def make_gdflix_session() -> requests.Session:
    """Build a requests session pre-loaded with captured gdflix cookies."""
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    s.cookies.set("PHPSESSID", GDFLIX_SESSION["PHPSESSID"], domain="new18.gdflix.net")
    return s


def make_goflix_session() -> requests.Session:
    """Build a requests session pre-loaded with captured goflix cookies."""
    s = requests.Session()
    s.headers.update(BASE_HEADERS)
    for k, v in GOFLIX_SESSION.items():
        if not k.startswith("x_"):
            s.cookies.set(k, v, domain="goflix.sbs")
    return s


# ─────────────────────────────────────────────
# GDFLIX: EXTRACT DIRECT LINK FROM PAGE HTML
# ─────────────────────────────────────────────

def gdflix_get_direct_links(file_id: str) -> dict:
    """
    GET the gdflix file page and extract any direct download links
    that are already embedded in the HTML (no POST / Turnstile needed).

    Returns:
        {
          "direct_links": [...],   # href links from buttons
          "zfile_url": "...",      # /zfile/ redirect URL if present
          "file_name": "...",
          "file_size": "...",
        }
    """
    url = f"https://new18.gdflix.net/file/{file_id}"
    s = make_gdflix_session()

    resp = s.get(url, headers={"Referer": "https://new18.gdflix.net/"}, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # File name from title / og:description
    file_name = ""
    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        file_name = og_desc.get("content", "").replace("Download ", "").split(" - ")[0].strip()

    # File size
    file_size = ""
    title_tag = soup.find("h5")
    if title_tag:
        m = re.search(r'\[\s*([\d.]+\s*\w+)\s*\]', title_tag.text)
        if m:
            file_size = m.group(1)

    # Direct download links (href on <a> buttons that point to CDN)
    direct_links = []
    cdn_patterns = [
        r"lest\.aws-eu\.online",
        r"instant\.busycdn\.xyz",
        r"video-downloads\.googleusercontent\.com",
        r"pub-.*\.r2\.dev",
    ]
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if any(re.search(p, href) for p in cdn_patterns):
            direct_links.append(href)

    # /zfile/ URL (timestamp-based redirect)
    zfile_url = None
    for a in soup.find_all("a", href=True):
        if "/zfile/" in a["href"]:
            zfile_url = urljoin("https://new18.gdflix.net", a["href"])
            break

    return {
        "direct_links": direct_links,
        "zfile_url": zfile_url,
        "file_name": file_name,
        "file_size": file_size,
        "raw_html": resp.text,
    }


# ─────────────────────────────────────────────
# GDFLIX: FOLLOW ZFILE REDIRECT CHAIN
# ─────────────────────────────────────────────

def gdflix_resolve_zfile(zfile_url: str) -> str | None:
    """
    Follow the /zfile/<timestamp>/<id> redirect chain to get the final CDN URL.
    The server issues 302 redirects; requests.Session follows them automatically.
    Returns the final resolved URL.
    """
    s = make_gdflix_session()
    # Allow redirects, capture the final URL
    resp = s.get(
        zfile_url,
        headers={"Referer": "https://new18.gdflix.net/"},
        timeout=30,
        allow_redirects=True,
    )
    final_url = resp.url
    if final_url != zfile_url:
        return final_url
    # If no redirect, try to parse a meta-refresh or JS redirect
    m = re.search(r'window\.location(?:\.href)?\s*=\s*["\']([^"\']+)["\']', resp.text)
    if m:
        return m.group(1)
    return None


# ─────────────────────────────────────────────
# GDFLIX: POST GENERATE (needs Turnstile token)
# ─────────────────────────────────────────────

def gdflix_generate_link(file_id: str, action_token: str = "", action: str = "cloud") -> dict:
    """
    POST to /file/<id> to generate a cloud/quick link.

    action_token: Cloudflare Turnstile token. Leave empty to attempt without it
                  (may fail with 403 or return error JSON).
    action: "cloud" or "quick"

    Returns parsed JSON response: {"url": "..."} or {"visit_url": "..."} or {"error": True, ...}
    """
    url = f"https://new18.gdflix.net/file/{file_id}"
    s = make_gdflix_session()

    data = {
        "action": action,
        "key": GDFLIX_STATIC_KEY,
        "action_token": action_token,
    }

    resp = s.post(
        url,
        data=data,
        headers={
            "Referer": url,
            "Origin": "https://new18.gdflix.net",
            "x-token": "new18.gdflix.net",
            "Accept": "*/*",
        },
        timeout=30,
    )

    try:
        return resp.json()
    except Exception:
        return {"error": True, "raw": resp.text[:500]}


# ─────────────────────────────────────────────
# GOFLIX: GET MIRROR LIST
# ─────────────────────────────────────────────

def goflix_get_mirrors(multiup_hash: str) -> list[dict]:
    """
    GET https://goflix.sbs/en/mirror/<hash> and extract all mirror entries.

    Returns list of:
        {"host": "...", "link": "...", "validity": "...", "id": "..."}
    """
    url = f"https://goflix.sbs/en/mirror/{multiup_hash}"
    s = make_goflix_session()

    resp = s.get(url, headers={"Referer": "https://goflix.sbs/"}, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    mirrors = []

    for a in soup.find_all("a", attrs={"nameHost": True}):
        mirrors.append({
            "host": a.get("nameHost", ""),
            "link": a.get("link", a.get("href", "")),
            "validity": a.get("validity", ""),
            "id": a.get("id", ""),
        })

    return mirrors


# ─────────────────────────────────────────────
# GOFLIX: ADD DOWNLOAD FOR LINK (debrid)
# ─────────────────────────────────────────────

def goflix_add_download(mirror_id: str) -> dict:
    """
    POST https://goflix.sbs/ajax/add-download-for-link
    Body: id=<mirror_id>

    Returns JSON: {"error": "success"} on success.
    Requires valid PHPSESSID + x-csrftoken.
    """
    s = make_goflix_session()

    resp = s.post(
        "https://goflix.sbs/ajax/add-download-for-link",
        data={"id": mirror_id},
        headers={
            "Origin": "https://goflix.sbs",
            "Referer": "https://goflix.sbs/",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": GOFLIX_SESSION["x_csrftoken"],
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        timeout=30,
    )

    try:
        return resp.json()
    except Exception:
        return {"error": True, "raw": resp.text[:300]}


# ─────────────────────────────────────────────
# VALIDATE MULTIUP HASH (optional check)
# ─────────────────────────────────────────────

def validate_multiup_hash(multiup_hash: str) -> dict:
    """
    GET https://validate.multiup2.workers.dev/<hash>
    Returns JSON with file info / validity.
    """
    resp = requests.get(
        f"https://validate.multiup2.workers.dev/{multiup_hash}",
        headers=BASE_HEADERS,
        timeout=15,
    )
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text[:300]}


# ─────────────────────────────────────────────
# DOWNLOAD FILE (streaming, with resume support)
# ─────────────────────────────────────────────

def download_file(url: str, dest_path: str, chunk_size: int = 1024 * 1024) -> None:
    """
    Stream-download a file from url to dest_path.
    Supports HTTP Range resume if file partially exists.
    """
    import os

    headers = dict(BASE_HEADERS)
    resume_pos = 0

    if os.path.exists(dest_path):
        resume_pos = os.path.getsize(dest_path)
        if resume_pos > 0:
            headers["Range"] = f"bytes={resume_pos}-"
            print(f"  Resuming from byte {resume_pos:,}")

    resp = requests.get(url, headers=headers, stream=True, timeout=60)

    if resp.status_code == 416:
        print("  File already complete.")
        return

    resp.raise_for_status()

    total = int(resp.headers.get("Content-Length", 0)) + resume_pos
    mode = "ab" if resume_pos else "wb"

    downloaded = resume_pos
    with open(dest_path, mode) as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  {downloaded:,} / {total:,} bytes ({pct:.1f}%)", end="", flush=True)

    print(f"\n  Saved → {dest_path}")


# ─────────────────────────────────────────────
# MAIN ORCHESTRATION
# ─────────────────────────────────────────────

def resolve_gdflix(file_id: str, download: bool = False, dest_dir: str = ".") -> str | None:
    """
    Full pipeline for a gdflix file ID.

    Priority order:
      1. Direct CDN link already in page HTML  (no POST, no Turnstile)
      2. /zfile/ redirect chain                (no POST, no Turnstile)
      3. POST generate (requires Turnstile)    (fallback — needs browser)

    Returns the final download URL or None.
    """
    print(f"\n[GDFlix] Fetching file page: /file/{file_id}")
    info = gdflix_get_direct_links(file_id)

    print(f"  File : {info['file_name']}")
    print(f"  Size : {info['file_size']}")

    # ── Path 1: Direct CDN link in HTML ──────────────────────────────
    if info["direct_links"]:
        url = info["direct_links"][0]
        print(f"  [✓] Direct CDN link found:\n      {url[:100]}...")
        if download and info["file_name"]:
            import os
            dest = os.path.join(dest_dir, info["file_name"])
            download_file(url, dest)
        return url

    # ── Path 2: /zfile/ redirect ──────────────────────────────────────
    if info["zfile_url"]:
        print(f"  [→] Following zfile redirect: {info['zfile_url']}")
        final = gdflix_resolve_zfile(info["zfile_url"])
        if final:
            print(f"  [✓] Resolved URL:\n      {final[:100]}...")
            if download and info["file_name"]:
                import os
                dest = os.path.join(dest_dir, info["file_name"])
                download_file(final, dest)
            return final

    # ── Path 3: POST generate (Turnstile required) ────────────────────
    print("  [!] No direct link found. Attempting POST generate (no Turnstile token)...")
    result = gdflix_generate_link(file_id, action_token="", action="cloud")
    print(f"  POST response: {result}")

    url = result.get("url") or result.get("visit_url")
    if url:
        print(f"  [✓] Generated URL: {url[:100]}...")
        if download and info["file_name"]:
            import os
            dest = os.path.join(dest_dir, info["file_name"])
            download_file(url, dest)
        return url

    print("  [✗] Could not resolve download URL. Turnstile token required for POST.")
    print("      Run with Playwright to solve Turnstile automatically.")
    return None


def resolve_goflix_mirror(multiup_hash: str, preferred_host: str = "1fichier") -> str | None:
    """
    Get mirror list from goflix.sbs and return the best download link.

    preferred_host: partial match against host name (case-insensitive).
    Falls back to first valid mirror.
    """
    print(f"\n[GoFlix] Fetching mirrors for hash: {multiup_hash}")
    mirrors = goflix_get_mirrors(multiup_hash)

    if not mirrors:
        print("  [✗] No mirrors found.")
        return None

    print(f"  Found {len(mirrors)} mirror(s):")
    for m in mirrors:
        print(f"    [{m['validity']:5}] {m['host']:20} id={m['id']}")

    # Pick preferred host
    chosen = None
    for m in mirrors:
        if preferred_host.lower() in m["host"].lower() and m["validity"] == "valid":
            chosen = m
            break
    if not chosen:
        # Fall back to first valid
        for m in mirrors:
            if m["validity"] == "valid":
                chosen = m
                break
    if not chosen and mirrors:
        chosen = mirrors[0]

    if not chosen:
        return None

    print(f"  [→] Using mirror: {chosen['host']} (id={chosen['id']})")

    # Trigger debrid
    result = goflix_add_download(chosen["id"])
    print(f"  Debrid response: {result}")

    # The link itself is the direct download URL
    link = chosen["link"]
    if link.startswith("/"):
        link = "https://goflix.sbs" + link
    return link


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="GDFlix / GoFlix download automation (requests-based, no browser)"
    )
    parser.add_argument("--gdflix", metavar="FILE_ID",
                        help="GDFlix file ID, e.g. 0mTELJYc0KIZiGQ")
    parser.add_argument("--goflix", metavar="MULTIUP_HASH",
                        help="GoFlix/MultiUp hash, e.g. 77fb45f079ed10c008b563c3ba1dd82a")
    parser.add_argument("--download", action="store_true",
                        help="Actually download the file after resolving URL")
    parser.add_argument("--dest", default=".", metavar="DIR",
                        help="Destination directory for downloads (default: current dir)")
    parser.add_argument("--host", default="1fichier", metavar="HOST",
                        help="Preferred mirror host for GoFlix (default: 1fichier)")
    args = parser.parse_args()

    if not args.gdflix and not args.goflix:
        # Demo with captured file IDs from the MITM session
        print("No arguments given — running demo with captured session data.\n")
        print("=" * 60)

        # Demo 1: GDFlix direct link
        url = resolve_gdflix("0mTELJYc0KIZiGQ", download=False)
        if url:
            print(f"\n[RESULT] GDFlix download URL:\n  {url}\n")

        print("=" * 60)

        # Demo 2: GoFlix mirror
        url = resolve_goflix_mirror("77fb45f079ed10c008b563c3ba1dd82a", preferred_host="1fichier")
        if url:
            print(f"\n[RESULT] GoFlix mirror URL:\n  {url}\n")

    else:
        if args.gdflix:
            url = resolve_gdflix(args.gdflix, download=args.download, dest_dir=args.dest)
            if url:
                print(f"\n[RESULT] {url}")

        if args.goflix:
            url = resolve_goflix_mirror(args.goflix, preferred_host=args.host)
            if url:
                print(f"\n[RESULT] {url}")
