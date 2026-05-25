"""
enc_dec_gui.py
==============
PyQt6 GUI for enc-dec.app Combined Decryptor.

UI:
  - Pick site from left list
  - Toggle: Movie  |  TV
  - Movie -> TMDB ID only
  - TV    -> TMDB ID + Season + Episode
  - Live colour-coded log on the right

Requirements:
    pip install PyQt6 requests pycryptodome json5
"""

import hashlib
import json
import re
import sys
import time
import base64
import traceback
from urllib.parse import quote, quote_plus
from typing import Callable

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QComboBox, QPushButton, QTextEdit,
        QSplitter, QFrame, QListWidget, QListWidgetItem,
        QStackedWidget, QSizePolicy, QStatusBar,
        QAbstractItemView,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
    from PyQt6.QtGui import QFont, QColor, QPalette, QTextCursor
except ImportError:
    sys.exit("Missing: pip install PyQt6")

try:
    import requests
except ImportError:
    sys.exit("Missing: pip install requests")

# ── palette ────────────────────────────────────────────────────────────────────
BG      = "#0b0d12"
PANEL   = "#11141c"
BORDER  = "#1c2030"
ACCENT  = "#e8b04b"
ACCENT2 = "#4b9fe8"
FG      = "#d4d8e8"
FG_DIM  = "#555a72"
SUCCESS = "#4be88a"
WARNING = "#e8c24b"
ERROR   = "#e8504b"
INP     = "#161924"
SEL     = "#1a1f2e"

API      = "https://enc-dec.app/api"
DATABASE = "https://enc-dec.app/db"
UA       = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/137.0.0.0 Safari/537.36")

# ══════════════════════════════════════════════════════════════════════════════
# Logger (cross-thread signal)
# ══════════════════════════════════════════════════════════════════════════════
class Logger(QObject):
    log = pyqtSignal(str, str)
    def info(self, m):   self.log.emit(str(m), "INFO")
    def warn(self, m):   self.log.emit(str(m), "WARN")
    def error(self, m):  self.log.emit(str(m), "ERROR")
    def result(self, m): self.log.emit(str(m), "RESULT")
    def sep(self):       self.log.emit("─" * 64, "SEP")

# ══════════════════════════════════════════════════════════════════════════════
# Worker thread
# ══════════════════════════════════════════════════════════════════════════════
class Worker(QThread):
    finished = pyqtSignal()
    def __init__(self, fn, logger):
        super().__init__()
        self.fn = fn
        self.logger = logger
    def run(self):
        try:
            self.fn(self.logger)
        except SystemExit as e:
            self.logger.error(f"Aborted: {e}")
        except Exception:
            self.logger.error(traceback.format_exc())
        finally:
            self.finished.emit()

# ══════════════════════════════════════════════════════════════════════════════
# API helper
# ══════════════════════════════════════════════════════════════════════════════
def validate(data, path, log):
    if data.get("status") != 200:
        msg = (f"API error  {path}\n"
               f"  status: {data.get('status')}  error: {data.get('error','unknown')}")
        log.error(msg)
        raise SystemExit(msg)
    return data["result"]

def jdump(v):
    return json.dumps(v, indent=2) if isinstance(v, (dict, list)) else str(v)

# ══════════════════════════════════════════════════════════════════════════════
# Runner functions
# ══════════════════════════════════════════════════════════════════════════════

def run_videasy(tmdb, mtype, season, episode, log, server="cdn"):
    log.info(f"[Videasy] type={mtype}  tmdb={tmdb}  s={season}  e={episode}  server={server}")
    try:
        meta = requests.get(
            f"https://api.themoviedb.org/3/{'movie' if mtype=='movie' else 'tv'}/{tmdb}"
            f"?api_key=a07e22bc18f5cb106bfe4cc1f83ad8ed", timeout=8
        ).json()
        title = meta.get("title") or meta.get("name") or tmdb
        year  = (meta.get("release_date") or meta.get("first_air_date") or "")[:4]
    except Exception:
        title, year = tmdb, ""
    log.info(f"  title={title}  year={year}")
    headers = {
        "Accept": "*/*", "Origin": "https://cineby.sc",
        "Referer": "https://cineby.sc/", "User-Agent": UA,
    }
    enc_t = quote(quote(title, safe=""), safe="")
    url = (f"https://api.videasy.net/{server}/sources-with-title"
           f"?title={enc_t}&mediaType={mtype}&year={year}"
           f"&episodeId={episode}&seasonId={season}"
           f"&tmdbId={tmdb}&imdbId=")
    log.info(f"  GET {url[:90]}...")
    enc = requests.get(url, headers=headers).text
    log.info("  Decrypting...")
    dec = validate(
        requests.post(f"{API}/dec-videasy", json={"text": enc, "id": tmdb}).json(),
        f"{API}/dec-videasy", log
    )
    log.sep()
    log.result(jdump(dec))


def run_vidsync(tmdb, mtype, season, episode, log, server="cinevault"):
    log.info(f"[VidSync] type={mtype}  tmdb={tmdb}  s={season}  e={episode}  server={server}")
    headers = {
        "Accept": "*/*", "Origin": "https://vidsync.xyz",
        "Referer": "https://vidsync.xyz/", "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
    }
    ep = f"{API}/enc-vidsync"
    log.info("  Fetching Turnstile token...")
    tok = validate(requests.get(ep).json(), ep, log)
    headers["X-Cf-Turnstile"] = tok["token"]
    url = (f"https://vidsync.xyz/api/stream/fetch"
           f"?title=&type={mtype}&releaseYear=&mediaId={tmdb}"
           f"&serverName={server}&season={season}&episode={episode}")
    log.info(f"  GET {url}")
    text = requests.get(url, headers=headers).text
    dec = validate(
        requests.post(f"{API}/dec-vidsync", json={"text": text, "id": tmdb}).json(),
        f"{API}/dec-vidsync", log
    )
    log.sep()
    log.result(jdump(dec))


def run_vidlink(tmdb, mtype, season, episode, log):
    log.info(f"[VidLink] type={mtype}  tmdb={tmdb}  s={season}  e={episode}")
    ep = f"{API}/enc-vidlink?text={tmdb}"
    log.info("  Encrypting TMDB ID...")
    enc = validate(requests.get(ep).json(), ep, log)
    headers = {"User-Agent": UA, "Origin": "https://vidlink.pro", "Referer": "https://vidlink.pro/"}
    url = f"https://vidlink.pro/api/b/{mtype}/{enc}/{season}/{episode}"
    log.info(f"  GET {url}")
    data = requests.get(url, headers=headers).json()
    log.sep()
    log.result(jdump(data))


def run_vidfast(tmdb, mtype, season, episode, log, version="1"):
    log.info(f"[VidFast] type={mtype}  tmdb={tmdb}  s={season}  e={episode}  ver={version}")
    headers = {
        "User-Agent": UA, "Referer": "https://vidfast.pro/",
        "X-Requested-With": "XMLHttpRequest",
    }
    base = f"https://vidfast.pro/{mtype}/{tmdb}/{season}/{episode}/"
    log.info(f"  Loading page: {base}")
    resp = requests.get(base).text
    m = re.search(r'\\"en\\":\\"(.*?)\\"', resp)
    if not m:
        log.error("VidFast: encoded text not found.")
        return
    ep = f"{API}/enc-vidfast?text={m.group(1)}&version={version}"
    parts = validate(requests.get(ep).json(), ep, log)
    headers["X-CSRF-Token"] = parts["token"]
    log.info("  Fetching servers...")
    s_enc = requests.post(parts["servers"], headers=headers).text
    s_dec = validate(
        requests.post(f"{API}/dec-vidfast", json={"text": s_enc, "version": version}).json(),
        f"{API}/dec-vidfast", log
    )
    sv = s_dec[0]
    st_url = f"{parts['stream']}/{sv['data']}"
    log.info(f"  Fetching stream: {st_url}")
    st_enc = requests.post(st_url, headers=headers).text
    st_dec = validate(
        requests.post(f"{API}/dec-vidfast", json={"text": st_enc, "version": version}).json(),
        f"{API}/dec-vidfast", log
    )
    log.sep()
    log.result(jdump(st_dec))


def run_hexa(tmdb, mtype, season, episode, log):
    log.info(f"[Hexa] type={mtype}  tmdb={tmdb}  s={season}  e={episode}")
    try:
        from Crypto.Random import get_random_bytes
    except ImportError:
        log.error("Missing: pip install pycryptodome")
        return
    headers = {
        "User-Agent": UA, "Referer": "https://hexa.su/",
        "Accept": "text/plain", "X-Fingerprint-Lite": "e9136c41504646444",
    }
    key = get_random_bytes(32).hex()
    headers["X-Api-Key"] = key
    ep = f"{API}/enc-hexa"
    log.info("  Fetching cap token...")
    token = validate(requests.get(ep).json(), ep, log)["token"]
    headers["X-Cap-Token"] = token
    if mtype == "movie":
        url = f"https://theemoviedb.hexa.su/api/tmdb/movie/{tmdb}/images"
    else:
        url = f"https://theemoviedb.hexa.su/api/tmdb/tv/{tmdb}/season/{season}/episode/{episode}/images"
    log.info(f"  GET {url}")
    enc = requests.get(url, headers=headers).text
    dec = validate(
        requests.post(f"{API}/dec-hexa", json={"text": enc, "key": key}).json(),
        f"{API}/dec-hexa", log
    )
    log.sep()
    log.result(jdump(dec))


def run_lordflix(tmdb, mtype, season, episode, log, server="Berlin"):
    log.info(f"[LordFlix] type={mtype}  tmdb={tmdb}  s={season}  e={episode}  server={server}")
    ltype = "series" if mtype == "tv" else "movie"
    headers = {
        "Accept": "*/*", "Origin": "https://lordflix.org",
        "Referer": "https://lordflix.org/", "User-Agent": UA,
    }
    url = (f"https://network.hasta-la-vista.site/"
           f"?title=&type={ltype}&year=&imdb=&tmdb={tmdb}"
           f"&server={server}&season={season}&episode={episode}")
    ep = f"{API}/enc-lordflix?url={quote(url)}"
    log.info("  Getting signed URL...")
    data = validate(requests.get(ep).json(), ep, log)
    enc  = requests.get(data["url"], headers=headers).text
    dec  = validate(
        requests.post(f"{API}/dec-lordflix", json={"text": enc, "sign": data["sign"]}).json(),
        f"{API}/dec-lordflix", log
    )
    log.sep()
    log.result(jdump(dec))


def run_abyss(content_id, log):
    log.info(f"[Abyss] content_id={content_id}")
    headers = {"User-Agent": UA, "Origin": "https://playhydrax.com", "Referer": "https://playhydrax.com/"}
    url = f"https://playhydrax.com/?v={content_id}"
    log.info(f"  GET {url}")
    resp = requests.get(url, headers=headers).text
    m = re.search(r'const\s+datas\s*=\s*"([^"]*)"', resp)
    if not m:
        log.error("Abyss: datas variable not found.")
        return
    dec = validate(
        requests.post(f"{API}/dec-abyss", json={"text": m.group(1)}).json(),
        f"{API}/dec-abyss", log
    )
    log.sep()
    log.result(jdump(dec))


def run_kisskh(episode_id, log):
    log.info(f"[KissKH] episode_id={episode_id}")
    headers = {"User-Agent": UA, "Accept": "application/json"}
    vp = f"{API}/enc-kisskh?text={episode_id}&type=vid"
    vk = validate(requests.get(vp).json(), vp, log)
    vurl = f"https://kisskh.do/api/DramaList/Episode/{episode_id}.png?err=false&ts=&time=&kkey={vk}"
    log.info(f"  Video: {vurl}")
    vr = requests.get(vurl, headers=headers).json()
    sp = f"{API}/enc-kisskh?text={episode_id}&type=sub"
    sk = validate(requests.get(sp).json(), sp, log)
    surl = f"https://kisskh.do/api/Sub/{episode_id}?kkey={sk}"
    log.info(f"  Sub: {surl}")
    sr = requests.get(surl, headers=headers).json()
    sd = requests.get(f"{API}/dec-kisskh?url={quote(sr[0]['src'])}").text
    log.sep()
    log.result("-- Video --\n" + jdump(vr))
    log.result("-- Subtitles --\n" + jdump(sr))
    log.result("-- Sub decrypt (200 chars) --\n" + sd[:200])


def run_onetouchtv(content_url, log):
    log.info(f"[OneTouchTV] {content_url}")
    enc = requests.get(content_url, headers={"User-Agent": UA}).text
    dec = validate(
        requests.post(f"{API}/dec-onetouchtv", json={"text": enc}).json(),
        f"{API}/dec-onetouchtv", log
    )
    log.sep()
    log.result(jdump(dec))


def run_primesrc(tmdb, mtype, season, episode, log):
    log.info(f"[PrimeSrc] type={mtype}  tmdb={tmdb}  s={season}  e={episode}")
    url = f"https://primesrc.me/api/v1/s?imdb=&season={season}&episode={episode}&type={mtype}&tmdb={tmdb}"
    log.info(f"  GET {url}")
    resp   = requests.get(url, headers={"User-Agent": UA}).json()
    server = resp.get("servers", [{}])[0]
    key    = server.get("key", "")
    embed  = f"https://primesrc.me/api/v1/l?key={key}"
    solve  = f"{API}/solve-primesrc?url={quote(embed)}"
    log.info("  Solving embed...")
    link = validate(requests.get(solve).json(), solve, log)
    log.sep()
    log.result(f"Host : {server.get('name')}\nLink : {link}")


def run_reanime(anilist_id, episode, log):
    log.info(f"[Reanime] anilist_id={anilist_id}  ep={episode}")
    try:
        import json5 as j5
    except ImportError:
        log.error("Missing: pip install json5")
        return
    from urllib.parse import urlparse
    headers = {"User-Agent": UA, "Referer": "https://reanime.to/"}
    resp   = requests.get(f"https://reanime.to/api/flix/{anilist_id}/{episode}", headers=headers).json()
    sv_url = resp["servers"][0]["dataLink"]
    domain = urlparse(sv_url).netloc
    log.info(f"  server domain: {domain}")
    page   = requests.get(sv_url, headers=headers).text
    m      = re.search(r'type:\s*"data",\s*data:\s*(\{.*?\})\s*,\s*uses:', page, re.S)
    if not m:
        log.error("Reanime: data block not found.")
        return
    data = j5.loads(m.group(1))
    subs = data.pop("subtitles", None)
    rp   = f"{API}/dec-reanime?type=resolve"
    log.info("  Resolving...")
    res  = validate(requests.post(rp, json={"data": data}).json(), rp, log)
    ref  = f"https://{domain}/"
    tr   = requests.get(
        f"https://{domain}/api/m3u8/{res['token']}",
        headers={**headers, "Referer": ref}
    ).json()
    dp  = f"{API}/dec-reanime?type=decrypt"
    dec = validate(
        requests.post(dp, json={"data": {"state": res["state"], "token_response": tr}}).json(),
        dp, log
    )
    log.sep()
    log.result(jdump(dec))
    if subs:
        log.info(f"  Subtitles: {subs}")


def _xprime_altcha(log):
    log.info("  XPrime: solving Altcha PoW...")
    ch  = requests.get("https://mznxiwqjdiq00239q.space/altcha/challenge").json()
    alg, c, salt, mx = ch["algorithm"], ch["challenge"], ch["salt"], ch["maxnumber"]
    thr = hex(((1 << 256) - 1) // (mx + 1))[2:].rjust(64, "0")
    t   = time.time()
    n   = -1
    for i in range(mx * 10 + 1):
        if hashlib.sha256(f"{alg}:{c}:{salt}:{i}".encode()).hexdigest() <= thr:
            n = i
            break
    if n < 0:
        log.error("Altcha failed.")
        return None
    log.info(f"  PoW solved  n={n}  ms={int((time.time()-t)*1000)}")
    pl = {
        "algorithm": alg, "challenge": c, "maxnumber": mx,
        "number": n, "salt": salt, "signature": ch["signature"],
        "took": int((time.time() - t) * 1000),
    }
    return base64.b64encode(json.dumps(pl).encode()).decode()


def run_xprime(tmdb, mtype, season, episode, log, server="primebox"):
    log.info(f"[XPrime] type={mtype}  tmdb={tmdb}  s={season}  e={episode}  server={server}")
    altcha = _xprime_altcha(log)
    if not altcha:
        return
    headers = {"User-Agent": UA, "Referer": "https://mznxiwqjdiq00239q.space/"}
    url = (f"https://mznxiwqjdiq00239q.space/{server}"
           f"?name=&year=&id={tmdb}&imdb="
           f"&season={season}&episode={episode}&altcha={altcha}")
    log.info(f"  GET {url[:80]}...")
    enc = requests.get(url, headers=headers).text
    dec = validate(
        requests.post(f"{API}/dec-xprime", json={"text": enc}).json(),
        f"{API}/dec-xprime", log
    )
    log.sep()
    log.result(jdump(dec))


def run_megaup(view_url, log):
    log.info(f"[MegaUp] {view_url[:70]}...")
    headers = {"User-Agent": UA, "Accept": "application/json"}
    enc  = requests.get(view_url, headers=headers).json()["result"]
    dec  = requests.post(f"{API}/dec-kai", json={"text": enc}).json()["result"]
    emb  = dec["url"]
    ref  = emb.split("/e/")[0] + "/"
    headers["Referer"] = ref
    med  = emb.replace("/e/", "/media/")
    log.info(f"  media: {med}")
    enc2 = requests.get(med, headers=headers).json()["result"]
    dec2 = validate(
        requests.post(f"{API}/dec-mega", json={"text": enc2, "agent": UA}).json(),
        f"{API}/dec-mega", log
    )
    log.sep()
    log.result(jdump(dec2))


def run_rapidshare(view_url, log):
    log.info(f"[RapidShare] {view_url[:70]}...")
    headers = {"User-Agent": UA, "Accept": "application/json"}
    enc  = requests.get(view_url, headers=headers).json()["result"]
    dec  = requests.post(f"{API}/dec-movies-flix", json={"text": enc}).json()["result"]
    emb  = dec["url"]
    ref  = emb.split("/e/")[0] + "/"
    headers["Referer"] = ref
    med  = emb.replace("/e/", "/media/")
    log.info(f"  media: {med}")
    enc2 = requests.get(med, headers=headers).json()["result"]
    dec2 = validate(
        requests.post(f"{API}/dec-rapid", json={"text": enc2, "agent": UA}).json(),
        f"{API}/dec-rapid", log
    )
    log.sep()
    log.result(jdump(dec2))


def run_animekai(tmdb, mtype, season, episode, log, sub_type="softsub", server_id="1"):
    log.info(f"[AnimeKai] tmdb={tmdb}  s={season}  e={episode}  sub={sub_type}")
    KAI = "https://animekai.to/ajax"
    headers = {"User-Agent": UA, "Referer": "https://animekai.to/", "Accept": "application/json"}
    search_url = f"https://animekai.to/browser?keyword={tmdb}"
    log.info(f"  Searching: {search_url}")
    html  = requests.get(search_url, headers=headers).text
    cid_m = re.search(r'data-id="([^"]+)"', html)
    if not cid_m:
        log.error("AnimeKai: content ID not found.")
        return
    cid = cid_m.group(1)
    log.info(f"  content_id={cid}")
    enc_id   = requests.get(f"{API}/enc-kai?text={cid}").json()["result"]
    eps_r    = requests.get(f"{KAI}/episodes/list?ani_id={cid}&_={enc_id}", headers=headers).json()
    episodes = requests.post(f"{API}/parse-html", json={"text": eps_r["result"]}).json()["result"]
    token    = episodes[season][episode]["token"]
    enc_tok  = requests.get(f"{API}/enc-kai?text={token}").json()["result"]
    srvs_r   = requests.get(f"{KAI}/links/list?token={token}&_={enc_tok}", headers=headers).json()
    servers  = requests.post(f"{API}/parse-html", json={"text": srvs_r["result"]}).json()["result"]
    lid      = servers[sub_type][server_id]["lid"]
    enc_lid  = requests.get(f"{API}/enc-kai?text={lid}").json()["result"]
    emb_r    = requests.get(f"{KAI}/links/view?id={lid}&_={enc_lid}", headers=headers).json()
    dec      = requests.post(f"{API}/dec-kai", json={"text": emb_r["result"]}).json()["result"]
    log.sep()
    log.result(jdump(dec))


def run_yflix(tmdb, mtype, season, episode, log, server_id="1"):
    log.info(f"[YFlix/1Movies] tmdb={tmdb}  type={mtype}  s={season}  e={episode}")
    headers  = {"User-Agent": UA, "Referer": "https://yflix.to/", "Accept": "application/json"}
    YFLIX    = "https://yflix.to/ajax"
    entries  = requests.get(f"{DATABASE}/flix/find?tmdb_id={tmdb}").json()
    if not entries:
        log.error("YFlix: TMDB ID not found in database.")
        return
    episodes = entries[0]["episodes"]
    eid      = episodes[season][episode]["eid"]
    enc_eid  = requests.get(f"{API}/enc-movies-flix?text={eid}").json()["result"]
    srvs_r   = requests.get(f"{YFLIX}/links/list?eid={eid}&_={enc_eid}", headers=headers).json()
    servers  = requests.post(f"{API}/parse-html", json={"text": srvs_r["result"]}).json()["result"]
    lid      = servers["default"][server_id]["lid"]
    enc_lid  = requests.get(f"{API}/enc-movies-flix?text={lid}").json()["result"]
    emb_r    = requests.get(f"{YFLIX}/links/view?id={lid}&_={enc_lid}", headers=headers).json()
    dec      = requests.post(f"{API}/dec-movies-flix", json={"text": emb_r["result"]}).json()["result"]
    log.sep()
    log.result(jdump(dec))


def run_database_kai(tmdb, mtype, season, episode, log, sub_type="sub", server="server1"):
    log.info(f"[Database-Kai] tmdb={tmdb}  s={season}  e={episode}  sub={sub_type}")
    entries = requests.get(f"{DATABASE}/kai/find?anilist_id={tmdb}").json()
    if not entries:
        log.error("DB-Kai: not found.")
        return
    entry      = entries[0]
    mirrors    = entry["info"]["mirrors"]
    megaup_m   = mirrors["megaup"][0]
    eps        = entry["episodes"]
    media      = eps[season][episode]["sources"][sub_type][server]
    stream_url = f"{megaup_m}{media}"
    log.sep()
    log.result(f"Stream URL:\n{stream_url}")


def run_database_flix(tmdb, mtype, season, episode, log, server_id="1"):
    log.info(f"[Database-Flix] tmdb={tmdb}  type={mtype}  s={season}  e={episode}")
    headers  = {"User-Agent": UA, "Referer": "https://yflix.to/", "Accept": "application/json"}
    YFLIX    = "https://yflix.to/ajax"
    entries  = requests.get(f"{DATABASE}/flix/find?tmdb_id={tmdb}").json()
    if not entries:
        log.error("DB-Flix: not found.")
        return
    episodes = entries[0]["episodes"]
    eid      = episodes[season][episode]["eid"]
    enc_eid  = requests.get(f"{API}/enc-movies-flix?text={eid}").json()["result"]
    srvs_r   = requests.get(f"{YFLIX}/links/list?eid={eid}&_={enc_eid}", headers=headers).json()
    servers  = requests.post(f"{API}/parse-html", json={"text": srvs_r["result"]}).json()["result"]
    lid      = servers["default"][server_id]["lid"]
    enc_lid  = requests.get(f"{API}/enc-movies-flix?text={lid}").json()["result"]
    emb_r    = requests.get(f"{YFLIX}/links/view?id={lid}&_={enc_lid}", headers=headers).json()
    dec      = requests.post(f"{API}/dec-movies-flix", json={"text": emb_r["result"]}).json()["result"]
    log.sep()
    log.result(jdump(dec))


# ══════════════════════════════════════════════════════════════════════════════
# Site registry
#   type:  "media"  -> shows Movie/TV toggle + TMDB + season/ep
#          "id"     -> single ID field  (+ optional episode)
#          "url"    -> single URL field
#
#   builder signatures (called inside build_runner):
#     media : builder(tmdb, mtype, season, episode, *extra_values)
#     id    : builder(id_val)  OR  builder(id_val, episode)
#     url   : builder(url_val)
# ══════════════════════════════════════════════════════════════════════════════
SITES = [
    # ( name,  domain-tag,  input_type,  extra_opts_dict,  builder )
    (
        "Videasy", "cineby.sc", "media",
        {"Server": ["cdn","neon","cypher","breach","killjoy","harbor","chamber","fade","omen","raze","sage","vyse"]},
        lambda tmdb,mt,s,e,srv: (lambda log: run_videasy(tmdb,mt,s,e,log,server=srv)),
    ),
    (
        "VidSync", "vidsync.xyz", "media",
        {"Server": ["cinevault","cinedub","cinebox","cineflix","cinevip","cinecloud","cine4k"]},
        lambda tmdb,mt,s,e,srv: (lambda log: run_vidsync(tmdb,mt,s,e,log,server=srv)),
    ),
    (
        "VidLink", "vidlink.pro", "media", {},
        lambda tmdb,mt,s,e: (lambda log: run_vidlink(tmdb,mt,s,e,log)),
    ),
    (
        "VidFast", "vidfast.pro", "media",
        {"Version": ["1","2"]},
        lambda tmdb,mt,s,e,ver: (lambda log: run_vidfast(tmdb,mt,s,e,log,version=ver)),
    ),
    (
        "Hexa / Flixer", "hexa.su / flixer.su", "media", {},
        lambda tmdb,mt,s,e: (lambda log: run_hexa(tmdb,mt,s,e,log)),
    ),
    (
        "LordFlix", "lordflix.org", "media",
        {"Server": ["Berlin","Tokyo","Bogota","Oslo","Luna","LordFlix","Sakura","Rio","Ativa"]},
        lambda tmdb,mt,s,e,srv: (lambda log: run_lordflix(tmdb,mt,s,e,log,server=srv)),
    ),
    (
        "Abyss", "playhydrax.com", "id",
        {"label": "Content ID  (v=… param)", "default": "K8R6OOjS7", "episode": False},
        lambda cid: (lambda log: run_abyss(cid, log)),
    ),
    (
        "KissKH", "kisskh.do", "id",
        {"label": "Episode ID", "default": "192143", "episode": False},
        lambda eid: (lambda log: run_kisskh(eid, log)),
    ),
    (
        "OneTouchTV", "api3.devcorp.me", "url",
        {"label": "Content URL",
         "default": "https://api3.devcorp.me/web/vod/150294-ghost-train-2024/episode/1"},
        lambda url: (lambda log: run_onetouchtv(url, log)),
    ),
    (
        "PrimeSrc", "primesrc.me", "media", {},
        lambda tmdb,mt,s,e: (lambda log: run_primesrc(tmdb,mt,s,e,log)),
    ),
    (
        "Reanime", "reanime.to", "id",
        {"label": "AniList ID", "default": "120377", "episode": True},
        lambda aid,ep: (lambda log: run_reanime(aid,ep,log)),
    ),
    (
        "XPrime", "mznxiwqjdiq00239q.space", "media",
        {"Server": ["primebox","primenet","finger","king","facile","lighter","fed","eek"]},
        lambda tmdb,mt,s,e,srv: (lambda log: run_xprime(tmdb,mt,s,e,log,server=srv)),
    ),
    (
        "MegaUp", "AnimeKai embed", "url",
        {"label": "View URL",
         "default": "https://animekai.to/ajax/links/view?id=dIG98qei6A&_=xQm9tJfLwGhz_0Eq8S_YAHYkwp-qSvLfm50W5X1nyd2NnAcpzTUWyAgck4I"},
        lambda url: (lambda log: run_megaup(url, log)),
    ),
    (
        "RapidShare", "YFlix embed", "url",
        {"label": "View URL",
         "default": "https://yflix.to/ajax/links/view?id=cYe--KWj5g&_=VU7EzW-r3IptzPzkwFi43K6fMXG1W-twXRnEjr7jYvY2mi6oJTqlmYTf"},
        lambda url: (lambda log: run_rapidshare(url, log)),
    ),
    (
        "AnimeKai", "animekai.to", "media",
        {"Sub": ["softsub","sub","dub"], "Server": ["1","2"]},
        lambda tmdb,mt,s,e,sub,srv: (lambda log: run_animekai(tmdb,mt,s,e,log,sub_type=sub,server_id=srv)),
    ),
    (
        "YFlix / 1Movies", "yflix.to / 1movies.sx", "media",
        {"Server": ["1","2"]},
        lambda tmdb,mt,s,e,srv: (lambda log: run_yflix(tmdb,mt,s,e,log,server_id=srv)),
    ),
    (
        "Database-Kai", "enc-dec.app/db/kai", "media",
        {"Sub": ["sub","softsub","dub"], "Srv": ["server1","server2"]},
        lambda tmdb,mt,s,e,sub,srv: (lambda log: run_database_kai(tmdb,mt,s,e,log,sub_type=sub,server=srv)),
    ),
    (
        "Database-Flix", "enc-dec.app/db/flix", "media",
        {"Server": ["1","2"]},
        lambda tmdb,mt,s,e,srv: (lambda log: run_database_flix(tmdb,mt,s,e,log,server_id=srv)),
    ),
]

# ══════════════════════════════════════════════════════════════════════════════
# Widget helpers
# ══════════════════════════════════════════════════════════════════════════════
MONO = QFont("Consolas", 9)

def mk_input(placeholder="", default=""):
    w = QLineEdit(default)
    w.setPlaceholderText(placeholder)
    w.setFont(MONO)
    w.setFixedHeight(34)
    w.setStyleSheet(f"""
        QLineEdit {{
            background:{INP}; color:{FG};
            border:1px solid {BORDER}; border-radius:5px;
            padding:0 10px;
        }}
        QLineEdit:focus {{ border-color:{ACCENT}; }}
    """)
    return w

def mk_combo(items):
    w = QComboBox()
    w.addItems(items)
    w.setFont(MONO)
    w.setFixedHeight(34)
    w.setStyleSheet(f"""
        QComboBox {{
            background:{INP}; color:{FG};
            border:1px solid {BORDER}; border-radius:5px;
            padding:0 10px;
        }}
        QComboBox::drop-down {{ border:none; width:22px; }}
        QComboBox QAbstractItemView {{
            background:{PANEL}; color:{FG};
            selection-background-color:{ACCENT};
            selection-color:{BG};
        }}
    """)
    return w

def mk_label(txt, color=FG_DIM, size=9):
    lbl = QLabel(txt)
    lbl.setFont(QFont("Consolas", size))
    lbl.setStyleSheet(f"color:{color}; background:transparent;")
    return lbl

def mk_toggle(text, checked=False):
    b = QPushButton(text)
    b.setCheckable(True)
    b.setChecked(checked)
    b.setFixedHeight(38)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
    _refresh_toggle(b)
    b.toggled.connect(lambda: _refresh_toggle(b))
    return b

def _refresh_toggle(b):
    if b.isChecked():
        b.setStyleSheet(f"""
            QPushButton {{
                background:{ACCENT}; color:{BG};
                border:2px solid {ACCENT}; border-radius:6px;
            }}
        """)
    else:
        b.setStyleSheet(f"""
            QPushButton {{
                background:{INP}; color:{FG_DIM};
                border:1px solid {BORDER}; border-radius:6px;
            }}
            QPushButton:hover {{ color:{FG}; border-color:{FG_DIM}; }}
        """)


# ══════════════════════════════════════════════════════════════════════════════
# Parameter panel (one per site, shown in QStackedWidget)
# ══════════════════════════════════════════════════════════════════════════════
class ParamPanel(QWidget):
    def __init__(self, site_entry):
        super().__init__()
        self._name, self._tag, self._stype, self._opts, self._builder = site_entry
        self.setStyleSheet(f"background:{PANEL};")
        self._extra_widgets = {}
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)

        # site name + tag
        name_lbl = mk_label(self._name, ACCENT, 13)
        name_lbl.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        lay.addWidget(name_lbl)
        lay.addWidget(mk_label(self._tag, ACCENT2, 8))

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color:{BORDER}; background:{BORDER}; max-height:1px;")
        lay.addWidget(sep)
        lay.addSpacing(4)

        if self._stype == "media":
            self._build_media(lay)
        else:
            self._build_id_url(lay)

        lay.addStretch()

    # ── media layout (Movie / TV toggle + TMDB + season/ep) ──────────────────
    def _build_media(self, lay):
        # toggle row
        row = QHBoxLayout()
        row.setSpacing(8)
        self._btn_movie = mk_toggle("🎬  Movie", checked=True)
        self._btn_tv    = mk_toggle("📺  TV Series", checked=False)
        self._btn_movie.setFixedWidth(130)
        self._btn_tv.setFixedWidth(130)
        # mutual exclusion
        self._btn_movie.toggled.connect(self._on_movie_toggled)
        self._btn_tv.toggled.connect(self._on_tv_toggled)
        row.addWidget(self._btn_movie)
        row.addWidget(self._btn_tv)
        row.addStretch()
        lay.addLayout(row)
        lay.addSpacing(6)

        # TMDB ID
        lay.addWidget(mk_label("TMDB ID"))
        self._tmdb = mk_input("e.g. 1399  or  105248", "1399")
        lay.addWidget(self._tmdb)

        # Season / Episode (hidden for Movie)
        self._se_widget = QWidget()
        self._se_widget.setStyleSheet("background:transparent;")
        se_lay = QHBoxLayout(self._se_widget)
        se_lay.setContentsMargins(0, 0, 0, 0)
        se_lay.setSpacing(12)

        sc = QVBoxLayout(); sc.setSpacing(4)
        sc.addWidget(mk_label("Season"))
        self._season = mk_input("1", "1")
        self._season.setFixedWidth(90)
        sc.addWidget(self._season)

        ec = QVBoxLayout(); ec.setSpacing(4)
        ec.addWidget(mk_label("Episode"))
        self._episode = mk_input("1", "1")
        self._episode.setFixedWidth(90)
        ec.addWidget(self._episode)

        se_lay.addLayout(sc)
        se_lay.addLayout(ec)
        se_lay.addStretch()
        self._se_widget.setVisible(False)
        lay.addWidget(self._se_widget)

        # extra options (Server, Sub, Version …)
        for lbl_text, choices in self._opts.items():
            lay.addWidget(mk_label(lbl_text))
            w = mk_combo(choices)
            self._extra_widgets[lbl_text] = w
            lay.addWidget(w)

    def _on_movie_toggled(self, checked):
        if checked:
            self._btn_tv.blockSignals(True)
            self._btn_tv.setChecked(False)
            self._btn_tv.blockSignals(False)
            _refresh_toggle(self._btn_tv)
            self._se_widget.setVisible(False)

    def _on_tv_toggled(self, checked):
        if checked:
            self._btn_movie.blockSignals(True)
            self._btn_movie.setChecked(False)
            self._btn_movie.blockSignals(False)
            _refresh_toggle(self._btn_movie)
            self._se_widget.setVisible(True)
        # if unchecking TV while movie not checked → re-check movie
        if not checked and not self._btn_movie.isChecked():
            self._btn_movie.blockSignals(True)
            self._btn_movie.setChecked(True)
            self._btn_movie.blockSignals(False)
            _refresh_toggle(self._btn_movie)
            self._se_widget.setVisible(False)

    # ── id / url layout ───────────────────────────────────────────────────────
    def _build_id_url(self, lay):
        lbl_text = self._opts.get("label", "Value")
        default  = self._opts.get("default", "")
        lay.addWidget(mk_label(lbl_text))
        self._id_input = mk_input(lbl_text, default)
        lay.addWidget(self._id_input)
        if self._opts.get("episode"):
            lay.addWidget(mk_label("Episode"))
            self._ep_input = mk_input("e.g. 1", "1")
            lay.addWidget(self._ep_input)
        else:
            self._ep_input = None

    # ── collect params and return a runner ────────────────────────────────────
    def build_runner(self):
        if self._stype == "media":
            tmdb   = self._tmdb.text().strip()
            is_tv  = self._btn_tv.isChecked()
            mtype  = "tv" if is_tv else "movie"
            season = self._season.text().strip() if is_tv else "1"
            ep     = self._episode.text().strip() if is_tv else "1"
            extras = [w.currentText() for w in self._extra_widgets.values()]
            try:
                return self._builder(tmdb, mtype, season, ep, *extras)
            except TypeError:
                return self._builder(tmdb, mtype, season, ep)
        else:
            val = self._id_input.text().strip()
            if self._ep_input is not None:
                return self._builder(val, self._ep_input.text().strip())
            return self._builder(val)


# ══════════════════════════════════════════════════════════════════════════════
# Main window
# ══════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("enc-dec.app  ·  Stream Decryptor")
        self.setMinimumSize(1020, 660)
        self._worker = None
        self._logger = Logger()
        self._logger.log.connect(self._on_log)
        self._apply_palette()
        self._build_ui()

    def _apply_palette(self):
        self.setStyleSheet(f"""
            * {{ font-family: Consolas, monospace; }}
            QMainWindow, QWidget {{ background:{BG}; color:{FG}; }}
            QSplitter::handle {{ background:{BORDER}; width:1px; }}
            QScrollBar:vertical {{ background:{BG}; width:7px; border:none; }}
            QScrollBar::handle:vertical {{
                background:{BORDER}; border-radius:3px; min-height:20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
            QStatusBar {{
                background:{PANEL}; color:{FG_DIM}; font-size:8pt;
                border-top:1px solid {BORDER};
            }}
        """)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_v = QVBoxLayout(root)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)

        # ── header bar ───────────────────────────────────────────────────────
        hdr = QFrame()
        hdr.setFixedHeight(50)
        hdr.setStyleSheet(f"background:{PANEL}; border-bottom:2px solid {ACCENT};")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(18, 0, 18, 0)

        logo = mk_label("enc-dec.app", ACCENT, 13)
        logo.setFont(QFont("Consolas", 13, QFont.Weight.Bold))
        sub  = mk_label("Stream Decryptor  ·  18 Sites", FG_DIM, 9)
        self._dot     = mk_label("●", FG_DIM, 12)
        self._dot_lbl = mk_label("Idle", FG_DIM, 9)

        hl.addWidget(logo)
        hl.addSpacing(14)
        hl.addWidget(sub)
        hl.addStretch()
        hl.addWidget(self._dot)
        hl.addSpacing(5)
        hl.addWidget(self._dot_lbl)
        root_v.addWidget(hdr)

        # ── three-column layout ───────────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        # COL-1: site list (fixed 196px)
        col1 = QWidget()
        col1.setFixedWidth(196)
        col1.setStyleSheet(f"background:{PANEL}; border-right:1px solid {BORDER};")
        c1l = QVBoxLayout(col1)
        c1l.setContentsMargins(0, 0, 0, 0)
        c1l.setSpacing(0)

        ch1 = QLabel("  SITES")
        ch1.setFixedHeight(32)
        ch1.setStyleSheet(f"background:{BG}; color:{ACCENT2}; font-size:8pt; "
                          f"letter-spacing:2px; border-bottom:1px solid {BORDER};")
        c1l.addWidget(ch1)

        self._site_list = QListWidget()
        self._site_list.setFont(MONO)
        self._site_list.setStyleSheet(f"""
            QListWidget {{
                background:{PANEL}; color:{FG};
                border:none; outline:none;
            }}
            QListWidget::item {{
                padding:9px 14px;
                border-bottom:1px solid {BORDER};
                font-size:9pt;
            }}
            QListWidget::item:selected {{
                background:{SEL}; color:{ACCENT};
                border-left:3px solid {ACCENT};
                padding-left:11px;
            }}
            QListWidget::item:hover:!selected {{
                background:{SEL}; color:{FG};
            }}
        """)
        self._site_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for name, *_ in SITES:
            item = QListWidgetItem(f"  {name}")
            self._site_list.addItem(item)
        self._site_list.currentRowChanged.connect(self._on_site_change)
        c1l.addWidget(self._site_list)

        # COL-2: parameter panel + run button (fixed 310px)
        col2 = QWidget()
        col2.setFixedWidth(310)
        col2.setStyleSheet(f"background:{PANEL}; border-right:1px solid {BORDER};")
        c2l = QVBoxLayout(col2)
        c2l.setContentsMargins(0, 0, 0, 0)
        c2l.setSpacing(0)

        ch2 = QLabel("  PARAMETERS")
        ch2.setFixedHeight(32)
        ch2.setStyleSheet(f"background:{BG}; color:{ACCENT2}; font-size:8pt; "
                          f"letter-spacing:2px; border-bottom:1px solid {BORDER};")
        c2l.addWidget(ch2)

        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"background:{PANEL};")
        self._panels: list[ParamPanel] = []
        for entry in SITES:
            p = ParamPanel(entry)
            self._panels.append(p)
            self._stack.addWidget(p)
        c2l.addWidget(self._stack)

        self._run_btn = QPushButton("▶   EXTRACT / DECRYPT")
        self._run_btn.setFixedHeight(48)
        self._run_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_btn.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self._run_btn.setStyleSheet(f"""
            QPushButton {{
                background:{ACCENT}; color:{BG};
                border:none; border-radius:0;
                letter-spacing:1px;
            }}
            QPushButton:hover   {{ background:#f4c060; }}
            QPushButton:pressed {{ background:#c89030; }}
            QPushButton:disabled {{
                background:{BORDER}; color:{FG_DIM};
            }}
        """)
        self._run_btn.clicked.connect(self._on_run)
        c2l.addWidget(self._run_btn)

        # COL-3: log (stretchy)
        col3 = QWidget()
        col3.setStyleSheet(f"background:{BG};")
        c3l = QVBoxLayout(col3)
        c3l.setContentsMargins(0, 0, 0, 0)
        c3l.setSpacing(0)

        log_hdr = QFrame()
        log_hdr.setFixedHeight(32)
        log_hdr.setStyleSheet(f"background:{BG}; border-bottom:1px solid {BORDER};")
        lhl = QHBoxLayout(log_hdr)
        lhl.setContentsMargins(14, 0, 10, 0)
        lhl.addWidget(mk_label("OUTPUT LOG", ACCENT2, 8))
        lhl.addStretch()
        lhl.addWidget(self._small_btn("⎘  Copy",  self._copy_log))
        lhl.addSpacing(6)
        lhl.addWidget(self._small_btn("✕  Clear", self._clear_log))
        c3l.addWidget(log_hdr)

        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", 9))
        self._log_view.setStyleSheet(f"""
            QTextEdit {{
                background:{BG}; color:{FG};
                border:none; padding:12px;
                selection-background-color:{ACCENT};
                selection-color:{BG};
            }}
        """)
        c3l.addWidget(self._log_view)

        splitter.addWidget(col1)
        splitter.addWidget(col2)
        splitter.addWidget(col3)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        root_v.addWidget(splitter)

        # status bar
        sb = QStatusBar()
        sb.showMessage("Select a site → set parameters → click EXTRACT / DECRYPT")
        self.setStatusBar(sb)
        self._sb = sb

        # default selection
        self._site_list.setCurrentRow(0)

    # ── small action buttons ──────────────────────────────────────────────────
    def _small_btn(self, text, slot):
        b = QPushButton(text)
        b.setFixedHeight(24)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFont(QFont("Consolas", 8))
        b.setStyleSheet(f"""
            QPushButton {{
                background:{BORDER}; color:{FG};
                border:none; border-radius:4px; padding:0 10px;
            }}
            QPushButton:hover {{ background:{SEL}; color:{ACCENT2}; }}
        """)
        b.clicked.connect(slot)
        return b

    # ── slots ─────────────────────────────────────────────────────────────────
    def _on_site_change(self, row):
        if row >= 0:
            self._stack.setCurrentIndex(row)

    def _on_run(self):
        if self._worker and self._worker.isRunning():
            return
        idx    = self._stack.currentIndex()
        panel  = self._panels[idx]
        runner = panel.build_runner()
        name   = SITES[idx][0]
        self._set_busy(True)
        self._append("=" * 64, "SEP")
        self._append(f"  ▶  {name.upper()}", "INFO")
        self._append("=" * 64, "SEP")
        self._worker = Worker(runner, self._logger)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _set_busy(self, busy: bool):
        self._run_btn.setEnabled(not busy)
        if busy:
            self._run_btn.setText("⏳  Running …")
            self._dot.setStyleSheet(f"color:{WARNING}; font-size:12pt;")
            self._dot_lbl.setStyleSheet(f"color:{WARNING}; font-size:9pt;")
            self._dot_lbl.setText("Running")
            self._sb.showMessage("Requesting …")
        else:
            self._run_btn.setText("▶   EXTRACT / DECRYPT")
            self._dot.setStyleSheet(f"color:{SUCCESS}; font-size:12pt;")
            self._dot_lbl.setStyleSheet(f"color:{SUCCESS}; font-size:9pt;")
            self._dot_lbl.setText("Done")
            self._sb.showMessage("Done.")

    def _on_log(self, msg: str, level: str):
        self._append(msg, level)

    def _append(self, msg: str, level: str):
        color = {
            "INFO"  : FG,
            "WARN"  : WARNING,
            "ERROR" : ERROR,
            "RESULT": SUCCESS,
            "SEP"   : BORDER,
        }.get(level, FG)
        prefix = {
            "INFO"  : "[INFO]  ",
            "WARN"  : "[WARN]  ",
            "ERROR" : "[ERR!]  ",
            "RESULT": "",
            "SEP"   : "",
        }.get(level, "")
        cur = self._log_view.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = cur.charFormat()
        fmt.setForeground(QColor(color))
        cur.setCharFormat(fmt)
        cur.insertText(prefix + msg + "\n")
        self._log_view.setTextCursor(cur)
        self._log_view.ensureCursorVisible()

    def _copy_log(self):
        QApplication.clipboard().setText(self._log_view.toPlainText())
        self._sb.showMessage("Copied to clipboard.")

    def _clear_log(self):
        self._log_view.clear()
        self._sb.showMessage("Log cleared.")


# ══════════════════════════════════════════════════════════════════════════════
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(FG))
    pal.setColor(QPalette.ColorRole.Base,            QColor(INP))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(PANEL))
    pal.setColor(QPalette.ColorRole.Text,            QColor(FG))
    pal.setColor(QPalette.ColorRole.Button,          QColor(PANEL))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(FG))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(ACCENT))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(BG))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()