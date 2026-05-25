"""
fojik_downloader.py  v2  —  Pure Python downloader for fojik.com
=================================================================
Fixed based on live run analysis. The chain is:

  fojik.com
    └─► POST search.technews24.site/blog.php   (FU=b64)
          └─► GET  sharelink-1.shop/dld.php?i=b64
                └─► POST freethemesy.com/dld.php  (FU2=b64)
                      └─► freethemesy.com/new/l/api/m  (XHR, sss+v in JS)
                            └─► sharelink-3.shop/blog/  (returned URL)
                                  └─► sharelink-3.shop/l/api/m  (XHR, sss+v in JS)
                                        └─► boabd.com/file/<b64>
                                              └─► POST clouddownload → R2 signed URL

Key findings from live capture:
  - freethemesy/dld.php has NO <form>. The download button is JS-rendered.
    But the sss token + vurl ARE in the static HTML as plain JS vars.
  - vurl on freethemesy = atob('L25ldy9sL2FwaS9t') = /new/l/api/m
  - v on freethemesy = '6a123e0214313'  (from obfuscated array)
  - The /new/l/api/m response is the sharelink-3.shop/blog/ URL
  - sharelink-3.shop/blog/ has its own sss + vurl = /l/api/m
  - That returns the boabd.com URL

Requirements:
  pip install cloudscraper requests beautifulsoup4

Usage:
  python fojik_downloader.py
  python fojik_downloader.py <url>
  python fojik_downloader.py --replay   (use hardcoded tokens from last capture)
"""

import re, sys, time, json, base64, urllib.parse
from pathlib import Path
import subprocess

def ensure(pkg, import_as=None):
    mod = import_as or pkg.replace("-","_").split("[")[0]
    try: __import__(mod)
    except ImportError:
        print(f"  pip install {pkg} ...")
        subprocess.check_call([sys.executable,"-m","pip","install",
                               pkg,"-q","--disable-pip-version-check"])

ensure("cloudscraper")
ensure("requests")
ensure("bs4", "bs4")

import cloudscraper
from bs4 import BeautifulSoup

# ── CONFIG ────────────────────────────────────────────────────────────────────
TARGET = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--")
          else "https://fojik.site/movie/drishyam-3-2026/")

OUT = Path("downloader_output")
OUT.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ── HELPERS ───────────────────────────────────────────────────────────────────

def log(msg, tag=""):
    icons = {"ok":"✅","err":"❌","req":"→","res":"←",
             "find":"🔍","warn":"⚠","info":"ℹ","step":"━"}
    print(f"  {icons.get(tag,' ')} {msg}")

def sep(title=""):
    print(f"\n{'═'*60}")
    if title: print(f"  {title}\n{'═'*60}")

def b64d(v):
    try: return base64.b64decode(str(v).strip()+"==").decode("utf-8")
    except: return v

def save(name, content):
    (OUT/name).write_text(str(content)[:3_000_000], encoding="utf-8", errors="replace")

def find_finals(text):
    found = {}
    pats = {
        "r2":     re.compile(r'https://[a-z0-9.]+\.r2\.cloudflarestorage\.com/[^\s"\'<>\\]+', re.I),
        "s3":     re.compile(r'https://s3\.[a-z0-9-]+\.amazonaws\.com/[^\s"\'<>\\]+', re.I),
        "gdrive": re.compile(r'https://drive\.google\.com/[^\s"\'<>\\]+', re.I),
        "mega":   re.compile(r'https://mega\.nz/[^\s"\'<>\\]+', re.I),
        "mkv":    re.compile(r'https://[^\s"\'<>\\]+\.mkv[^\s"\'<>\\]*', re.I),
        "mp4":    re.compile(r'https://[^\s"\'<>\\]+\.mp4[^\s"\'<>\\]*', re.I),
        "boabd":  re.compile(r'https://boabd\.com/file/[A-Za-z0-9+/=]+', re.I),
    }
    for name, pat in pats.items():
        hits = [m.group(0).rstrip(".,;)\"'") for m in pat.finditer(text)]
        if hits: found[name] = list(dict.fromkeys(hits))
    return found

def extract_sss_v_vurl(html, page_url):
    """
    Extract sss token, v value, and vurl from any page that has
    the generateDownloadLink / jQuery ajax pattern.
    Returns (sss, v, api_url) or (None, None, None).
    """
    sss = None
    v   = None
    vurl_b64 = None

    # sss token — always: var sss = 'BASE64STRING';
    m = re.search(r"var\s+sss\s*=\s*['\"]([A-Za-z0-9+/=]{20,})['\"]", html)
    if m:
        sss = m.group(1)
        log(f"sss = {sss[:50]}...", "find")

    # vurl — try literal atob() first (sharelink-3 style: var vurl = atob('...'))
    vurl = None
    m = re.search(r"var\s+vurl\s*=\s*atob\(['\"]([A-Za-z0-9+/=]+)['\"]\)", html)
    if m:
        vurl = b64d(m.group(1))
        log(f"vurl = {vurl}", "find")

    # If not found (freethemesy uses obfuscated atob), detect by domain
    if not vurl:
        parsed_host = urllib.parse.urlparse(page_url).netloc
        if "freethemesy" in parsed_host:
            vurl = "/new/l/api/m"   # known from analysis: atob('L25ldy9sL2FwaS9t')
            log(f"vurl = {vurl} (freethemesy known endpoint)", "find")
        else:
            vurl = "/l/api/m"       # sharelink-3 default
            log(f"vurl = {vurl} (default)", "find")

    # v — the version/session ID
    # Pattern 1: explicit in vdata object  {'s': sss, 'v': '6a123...'}
    m = re.search(r"['\"]v['\"]\s*:\s*['\"]([a-f0-9]{8,})['\"]", html)
    if m:
        v = m.group(1)
        log(f"v = {v}", "find")

    # Pattern 2: as CSS class on button: class="butt btn 6a1238880b783"
    if not v:
        m = re.search(r'class=["\']butt btn ([a-f0-9]{10,})["\']', html)
        if m:
            v = m.group(1)
            log(f"v (from button class) = {v}", "find")

    # Pattern 3: in obfuscated string array — find 13-char hex string
    # that appears in the SAME script block as sss
    if not v and sss:
        # Find the script block containing sss
        sss_pos = html.find(sss[:30])
        if sss_pos > 0:
            # Look in a window around sss for a 13-char hex string
            window = html[max(0, sss_pos-500):sss_pos+2000]
            candidates = re.findall(r"['\"]([a-f0-9]{13})['\"]", window)
            if candidates:
                v = candidates[0]
                log(f"v (from script window) = {v}", "find")

    if not sss:
        return None, None, None

    # Build full API URL
    parsed = urllib.parse.urlparse(page_url)
    api_url = f"{parsed.scheme}://{parsed.netloc}{vurl}"
    log(f"API endpoint: {api_url}", "ok")

    return sss, v or "", api_url

def call_api_m(session, api_url, sss, v, referer):
    """POST to /l/api/m or /new/l/api/m and return the URL from response."""
    log(f"POST {api_url}", "req")
    log(f"  s={sss[:50]}...  v={v}", "info")

    headers = {
        "Content-Type":     "application/json",
        "Accept":           "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Referer":          referer,
        "Origin":           urllib.parse.urlparse(referer).scheme+"://"+
                            urllib.parse.urlparse(referer).netloc,
    }
    r = session.post(api_url, json={"s": sss, "v": v},
                     headers=headers, timeout=30)
    log(f"{r.status_code} ← {r.text[:150]}", "res")
    save(f"api_m_{urllib.parse.urlparse(api_url).netloc.replace('.','_')}.txt", r.text)

    body = r.text.strip().strip('"').strip("'")
    if body.startswith("http"):
        return body
    try:
        jd = json.loads(r.text)
        for k in ["url","link","redirect","file","download","data"]:
            if isinstance(jd, dict) and k in jd:
                val = jd[k]
                if isinstance(val, str) and val.startswith("http"):
                    return val
        if isinstance(jd, str) and jd.startswith("http"):
            return jd
    except Exception:
        pass
    urls = re.findall(r'https?://[^\s"\'<>\\]+', r.text)
    return urls[0] if urls else None


# ── SESSION ───────────────────────────────────────────────────────────────────

def make_session():
    s = cloudscraper.create_scraper(
        browser={"browser":"chrome","platform":"windows","desktop":True},
        delay=5,
    )
    s.headers.update(HEADERS)
    return s

# ── STEP 1: fojik.com ─────────────────────────────────────────────────────────

def step1_fojik(session):
    sep("STEP 1 — fojik.com")
    log(f"GET {TARGET[:70]}", "req")
    r = session.get(TARGET, timeout=30)
    log(f"{r.status_code} {r.url[:70]}", "res")
    save("step1_fojik.html", r.text)

    html = r.text
    s = BeautifulSoup(html, "html.parser")

    # Find form with FU field (any form, any id)
    for form in s.find_all("form"):
        fu = form.find("input", attrs={"name": "FU"})
        fn = form.find("input", attrs={"name": "FN"})
        if fu:
            action = form.get("action","")
            fields = {i.get("name"): i.get("value","")
                      for i in form.find_all("input") if i.get("name")}
            log(f"Form → POST {action[:70]}", "find")
            log(f"  FU = {fields.get('FU','')[:50]}...", "info")
            log(f"  FN = {fields.get('FN','')[:60]}", "info")
            return action, fields

    # Fallback: regex
    fu_m = re.search(r'name=["\']FU["\'][^>]+value=["\']([^"\']+)["\']', html)
    fn_m = re.search(r'name=["\']FN["\'][^>]+value=["\']([^"\']+)["\']', html)
    act_m = re.search(r'action=["\']([^"\']*technews[^"\']*)["\']', html)
    if fu_m and act_m:
        fields = {"FU": fu_m.group(1)}
        if fn_m: fields["FN"] = fn_m.group(1)
        log(f"Form (regex) → {act_m.group(1)[:70]}", "find")
        return act_m.group(1), fields

    log("No FU form found on fojik.com", "err")
    return None, None

# ── STEP 2: POST technews24/blog.php ─────────────────────────────────────────

def step2_technews24(session, action, fields):
    sep("STEP 2 — POST technews24/blog.php")
    log(f"POST {action[:70]}", "req")
    r = session.post(action, data=fields, timeout=30, allow_redirects=True)
    log(f"{r.status_code} {r.url[:80]}", "res")
    save("step2_technews24.html", r.text)

    # Response contains a form that auto-submits to sharelink-1
    # OR a meta-refresh / JS redirect
    html = r.text

    # Look for form action pointing to sharelink-1
    s = BeautifulSoup(html, "html.parser")
    for form in s.find_all("form"):
        act = form.get("action","")
        if "sharelink" in act or "dld.php" in act:
            ffields = {i.get("name"): i.get("value","")
                       for i in form.find_all("input") if i.get("name")}
            log(f"Found form → {act[:70]}", "find")
            return act, ffields, html

    # Meta-refresh
    m = re.search(r'content=["\'][^;]+;\s*url=([^"\']+)["\']', html, re.I)
    if m:
        url = m.group(1).strip()
        log(f"Meta-refresh → {url[:70]}", "find")
        return url, None, html

    # JS redirect
    m = re.search(r'(?:window\.location|location\.href)\s*=\s*["\']([^"\']+)["\']', html)
    if m:
        log(f"JS redirect → {m.group(1)[:70]}", "find")
        return m.group(1), None, html

    # Already redirected to sharelink-1
    if "sharelink" in r.url or "dld.php" in r.url:
        log(f"Already at: {r.url[:70]}", "ok")
        return r.url, None, html

    # Scan for any sharelink URL
    urls = re.findall(r'https?://[^\s"\'<>]+(?:sharelink|dld\.php)[^\s"\'<>]*', html)
    if urls:
        log(f"Found URL: {urls[0][:70]}", "find")
        return urls[0], None, html

    log("Could not find next URL from technews24", "warn")
    return None, None, html

# ── STEP 3: sharelink-1.shop/dld.php ─────────────────────────────────────────

def step3_sharelink1(session, url_or_action, fields=None):
    sep("STEP 3 — sharelink-1.shop/dld.php")

    if fields:
        # POST form
        log(f"POST {url_or_action[:70]}", "req")
        r = session.post(url_or_action, data=fields, timeout=30, allow_redirects=True)
    else:
        log(f"GET {url_or_action[:70]}", "req")
        r = session.get(url_or_action, timeout=30, allow_redirects=True)

    log(f"{r.status_code} {r.url[:80]}", "res")
    save("step3_sharelink1.html", r.text)
    html = r.text

    # Find form posting to freethemesy
    s = BeautifulSoup(html, "html.parser")
    for form in s.find_all("form"):
        act = form.get("action","")
        ffields = {i.get("name"): i.get("value","")
                   for i in form.find_all("input") if i.get("name")}
        if act:
            log(f"Form → POST {act[:70]}", "find")
            for k,v in list(ffields.items())[:3]:
                print(f"       {k} = {str(v)[:60]}")
            return act, ffields, html

    log("No form on sharelink-1 page", "warn")
    return r.url, {}, html

# ── STEP 4: freethemesy.com/dld.php ──────────────────────────────────────────

def step4_freethemesy(session, action, fields):
    sep("STEP 4 — freethemesy.com/dld.php")
    log(f"POST {action[:70]}", "req")
    r = session.post(action, data=fields, timeout=30, allow_redirects=True)
    log(f"{r.status_code} {r.url[:80]}", "res")
    save("step4_freethemesy.html", r.text)
    return r.url, r.text

# ── STEP 5: freethemesy /new/l/api/m ─────────────────────────────────────────

def step5_freethemesy_api(session, page_url, html):
    sep("STEP 5 — freethemesy /new/l/api/m")

    sss, v, api_url = extract_sss_v_vurl(html, page_url)
    if not sss:
        log("No sss token on freethemesy page", "err")
        log(f"Page snippet: {html[2000:2500]}", "info")
        return None

    result = call_api_m(session, api_url, sss, v, page_url)
    if result:
        log(f"Got: {result[:80]}", "ok")
    else:
        log("No URL from freethemesy /new/l/api/m", "err")
    return result

# ── STEP 6: sharelink-3.shop/blog/ ───────────────────────────────────────────

def step6_sharelink3_blog(session, url):
    sep("STEP 6 — sharelink-3.shop/blog/")

    # May need to GET the blog page first (if url is /dld.php, submit form)
    log(f"GET {url[:70]}", "req")
    r = session.get(url, timeout=30, allow_redirects=True)
    log(f"{r.status_code} {r.url[:80]}", "res")
    save("step6_sharelink3.html", r.text)
    html = r.text
    page_url = r.url

    # If we landed on /dld.php, submit its form(s) until we reach /blog/
    for _ in range(3):  # max 3 form submits to reach /blog/
        if "/blog" in page_url:
            break
        s = BeautifulSoup(html, "html.parser")
        submitted = False
        for form in s.find_all("form"):
            act = form.get("action","")
            ffields = {i.get("name"): i.get("value","")
                       for i in form.find_all("input") if i.get("name")}
            if act and ffields:
                log(f"Submitting form → {act[:70]}", "req")
                r2 = session.post(act, data=ffields, timeout=30, allow_redirects=True)
                log(f"{r2.status_code} {r2.url[:80]}", "res")
                save(f"step6b_sharelink3_{len(ffields)}.html", r2.text)
                html = r2.text
                page_url = r2.url
                submitted = True
                time.sleep(1)
                break
        if not submitted:
            break

    return page_url, html

# ── STEP 7: sharelink-3 /l/api/m ─────────────────────────────────────────────

def step7_sharelink3_api(session, page_url, html):
    sep("STEP 7 — sharelink-3.shop /l/api/m")

    sss, v, api_url = extract_sss_v_vurl(html, page_url)
    if not sss:
        log("No sss token on sharelink-3 page", "err")
        return None

    result = call_api_m(session, api_url, sss, v, page_url)
    if result:
        log(f"Got boabd URL: {result[:80]}", "ok")
    else:
        log("No URL from sharelink-3 /l/api/m", "err")
    return result

# ── STEP 8: boabd.com/file/<b64> ─────────────────────────────────────────────

def step8_boabd(session, boabd_url):
    sep("STEP 8 — boabd.com/file/")
    log(f"GET {boabd_url[:80]}", "req")
    r = session.get(boabd_url, timeout=30, allow_redirects=True)
    log(f"{r.status_code} {r.url[:80]}", "res")
    save("step8_boabd.html", r.text)

    # Show file info
    s = BeautifulSoup(r.text, "html.parser")
    title = s.find("title")
    if title: log(f"File: {title.get_text(strip=True)}", "info")

    # Try buttons in order: R2 first (fastest), then submit, then clouddownload
    for btn_name, label in [("clouddownload","R2 Direct Download"),
                             ("submit","Resume Supported Direct Link"),
                             ("submit","Download File")]:
        log(f"Trying: {label}", "req")
        r2 = session.post(boabd_url,
                          data={btn_name: ""},
                          headers={"Referer": boabd_url},
                          timeout=30, allow_redirects=True)
        log(f"{r2.status_code} {r2.url[:80]}", "res")
        save(f"step8_boabd_{btn_name}.html", r2.text)

        # Check redirect URL
        if r2.url != boabd_url:
            finals = find_finals(r2.url)
            if finals:
                for ftype, urls in finals.items():
                    if ftype != "boabd":
                        log(f"[{ftype}] {urls[0][:100]}", "ok")
                        return urls[0], ftype

        # Check response body
        finals = find_finals(r2.text)
        for ftype, urls in finals.items():
            if ftype != "boabd":
                log(f"[{ftype}] {urls[0][:100]}", "ok")
                return urls[0], ftype

        # Check redirect history
        for resp in r2.history:
            loc = resp.headers.get("Location","")
            if loc and loc != boabd_url:
                finals = find_finals(loc)
                for ftype, urls in finals.items():
                    log(f"[{ftype}] redirect: {urls[0][:100]}", "ok")
                    return urls[0], ftype
                if loc.startswith("http"):
                    return loc, "redirect"

        time.sleep(1)

    log("Could not get final URL from boabd", "warn")
    return None, None


# ── DOWNLOAD HELPER ───────────────────────────────────────────────────────────

def print_download_info(url, ftype):
    sep("DOWNLOAD INFO")
    print(f"\n  Type : {ftype}")
    print(f"  URL  : {url}\n")

    if ftype in ("r2","s3","mkv","mp4","redirect"):
        print("  Direct link — resume supported.")
        print(f'\n  aria2c:')
        print(f'    aria2c -x16 -s16 "{url}"\n')
        print(f'  Python stream:')
        print(f'    import requests, tqdm')
        print(f'    r = requests.get("{url[:60]}...", stream=True)')
        print(f'    with open("movie.mkv","wb") as f:')
        print(f'        for chunk in r.iter_content(1<<20): f.write(chunk)')
    elif ftype == "gdrive":
        fid = re.search(r'/d/([A-Za-z0-9_-]+)', url)
        fid = fid.group(1) if fid else "?"
        print(f"  Google Drive file ID: {fid}")
        print(f'\n  gdown:')
        print(f'    pip install gdown')
        print(f'    gdown https://drive.google.com/uc?id={fid}')
        print(f'\n  Direct (small files):')
        print(f'    https://drive.google.com/uc?export=download&id={fid}')
    else:
        print(f'  aria2c "{url}"')

# ── MAIN ──────────────────────────────────────────────────────────────────────

def run():
    sep("FOJIK.COM PURE PYTHON DOWNLOADER  v2")
    log(f"Target : {TARGET}", "info")
    log(f"Output : {OUT.resolve()}", "info")

    session = make_session()
    final_url = final_type = None

    try:
        # Step 1 — fojik.com
        action, fields = step1_fojik(session)
        if not action:
            log("Step 1 failed", "err"); return
        time.sleep(2)

        # Step 2 — technews24/blog.php
        next_url, next_fields, html2 = step2_technews24(session, action, fields)
        if not next_url:
            log("Step 2 failed", "err"); return
        time.sleep(2)

        # Step 3 — sharelink-1.shop/dld.php
        sl1_action, sl1_fields, html3 = step3_sharelink1(session, next_url, next_fields)
        time.sleep(2)

        # Step 4 — freethemesy.com/dld.php
        ft_url, ft_html = step4_freethemesy(session, sl1_action, sl1_fields)
        time.sleep(2)

        # Step 5 — freethemesy /new/l/api/m  → returns technews24/links/ URL
        next_url = step5_freethemesy_api(session, ft_url, ft_html)
        if not next_url:
            log("Step 5 failed — freethemesy /new/l/api/m returned nothing", "err")
            log("Possible: Cloudflare blocked the request or token expired", "warn")
            return
        time.sleep(2)

        # Step 5b — if we got technews24/links/, follow it to get GDS link → sharelink-3
        if "technews24" in next_url and "links" in next_url:
            log(f"Following technews24/links/ → GDS → sharelink-3 ...", "info")
            r_links = session.get(next_url, timeout=30, allow_redirects=True)
            log(f"{r_links.status_code} {r_links.url[:70]}", "res")
            save("step5b_technews24_links.html", r_links.text)
            links_html = r_links.text

            # Find GDS link (go.php)
            gds_url = None
            s_links = BeautifulSoup(links_html, "html.parser")
            for a in s_links.find_all("a", href=True):
                href = a.get("href","")
                text = a.get_text(strip=True)
                if text == "GDS" or "go.php" in href:
                    gds_url = href
                    log(f"GDS link: {gds_url[:70]}", "find")
                    break
            if not gds_url:
                m = re.search(r'href=["\']([^"\']*go\.php[^"\']*)["\']', links_html)
                if m: gds_url = m.group(1)

            if gds_url:
                if not gds_url.startswith("http"):
                    base = urllib.parse.urlparse(next_url)
                    gds_url = f"{base.scheme}://{base.netloc}{gds_url}"
                log(f"GET {gds_url[:70]}", "req")
                r_gds = session.get(gds_url, timeout=30, allow_redirects=True)
                log(f"{r_gds.status_code} {r_gds.url[:70]}", "res")
                save("step5c_go_php.html", r_gds.text)
                next_url = r_gds.url
                time.sleep(2)
            else:
                log("No GDS link found — scanning for sharelink-3 URL", "warn")
                m = re.search(r'https?://[^\s"\'<>]*sharelink-3[^\s"\'<>]*', links_html)
                if m: next_url = m.group(0)

        # Step 6 — sharelink-3.shop/blog/
        sl3_page_url, sl3_html = step6_sharelink3_blog(session, next_url)
        time.sleep(2)

        # Step 7 — sharelink-3 /l/api/m  → returns boabd.com URL
        boabd_url = step7_sharelink3_api(session, sl3_page_url, sl3_html)
        if not boabd_url:
            log("Step 7 failed — sharelink-3 /l/api/m returned nothing", "err")
            return
        time.sleep(2)

        # Step 8 — boabd.com → final R2/GDrive URL
        final_url, final_type = step8_boabd(session, boabd_url)

    except KeyboardInterrupt:
        log("Interrupted", "warn")
    except Exception as e:
        log(f"Error: {e}", "err")
        import traceback; traceback.print_exc()

    sep("RESULT")
    if final_url:
        log("SUCCESS!", "ok")
        save("RESULT.json", json.dumps(
            {"url": final_url, "type": final_type, "target": TARGET}, indent=2))
        print_download_info(final_url, final_type)
    else:
        log("Failed to get final URL", "err")
        log("Check downloader_output/ for partial captures", "info")
        log("If Cloudflare blocked: run site_monitor.py first to get fresh tokens", "info")


# ── REPLAY MODE ───────────────────────────────────────────────────────────────
# Skip the full chain — use tokens captured by site_monitor.py
# Update SSS_FREETHEMESY and SSS_SHARELINK3 from the latest monitor run

def replay():
    sep("REPLAY MODE — using captured tokens")

    # ── Paste tokens from latest site_monitor.py run here ────────────────────
    # From hop_04_freethemesy.html:
    SSS_FREETHEMESY = "OWlhWVJkQWVKVUFRNWxCRFd3VGQvOEFEU0hITDNhNHdzVEFGc01PVjFpN3pGNmorV3VKSCtyS2hya2VJN0RwYUhRcXRJWi8wOVF5MXdnN0Jvc2hINHc9PQ=="
    V_FREETHEMESY   = "6a123e0214313"
    API_FREETHEMESY = "https://freethemesy.com/new/l/api/m"

    # From hop_05_sharelink3_blog.html (if freethemesy /api/m fails):
    SSS_SHARELINK3  = "bnlCQzJUWHVLUFVZUTlkeTJEOE5ab0FiVmVWS211YkNhd1JlRnJKWHVPcnl3bWtjOVljOXRDd2FNV3dRRzVqbW9tVTNtalZHZ0xZMzhJTFdxSVpYb1E9PQ=="
    V_SHARELINK3    = "6a1238880b77f"
    API_SHARELINK3  = "https://sharelink-3.shop/l/api/m"
    # ─────────────────────────────────────────────────────────────────────────

    session = make_session()

    # Try freethemesy first
    log("Trying freethemesy /new/l/api/m ...", "info")
    sl3_url = call_api_m(session, API_FREETHEMESY, SSS_FREETHEMESY, V_FREETHEMESY,
                         "https://freethemesy.com/dld.php")
    time.sleep(1)

    if sl3_url and "sharelink" in sl3_url:
        log(f"Got sharelink-3 URL: {sl3_url[:80]}", "ok")
        sl3_page_url, sl3_html = step6_sharelink3_blog(session, sl3_url)
        time.sleep(2)
        boabd_url = step7_sharelink3_api(session, sl3_page_url, sl3_html)
    else:
        # Fallback: use sharelink-3 token directly
        log("Freethemesy token expired — trying sharelink-3 token directly", "warn")
        boabd_url = call_api_m(session, API_SHARELINK3, SSS_SHARELINK3, V_SHARELINK3,
                               "https://sharelink-3.shop/blog/")

    if not boabd_url:
        log("Both tokens failed — tokens are expired. Run site_monitor.py for fresh ones.", "err")
        return

    time.sleep(2)
    final_url, final_type = step8_boabd(session, boabd_url)

    sep("RESULT")
    if final_url:
        log("SUCCESS!", "ok")
        print_download_info(final_url, final_type)
    else:
        log("Failed at boabd step", "err")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--replay" in sys.argv:
        replay()
    else:
        run()
