"""
enc_dec_combined.py
====================
Combined decryption/extraction script for all sites supported by enc-dec.app API.

Supported sites:
  1.  Videasy       (cineby.sc)
  2.  VidSync       (vidsync.xyz)
  3.  VidLink       (vidlink.pro)
  4.  VidFast       (vidfast.pro)
  5.  Hexa / Flixer (hexa.su / flixer.su)
  6.  LordFlix      (lordflix.org / network.hasta-la-vista.site)
  7.  Abyss         (playhydrax.com)
  8.  KissKH        (kisskh.do)
  9.  OneTouchTV    (api3.devcorp.me)
 10.  PrimeSrc      (primesrc.me)
 11.  Reanime       (reanime.to)
 12.  XPrime        (mznxiwqjdiq00239q.space)
 13.  MegaUp        (AnimeKai embed decryptor)
 14.  RapidShare    (YFlix / 1Movies embed decryptor)
 15.  AnimeKai      (animekai.to)
 16.  1Movies/YFlix (yflix.to / 1movies.sx)
 17.  Database-Kai  (enc-dec.app/db/kai  -- AnimeKai database)
 18.  Database-Flix (enc-dec.app/db/flix -- YFlix/1Movies database)

Usage:
    python enc_dec_combined.py
    An interactive menu lets you choose which site to query.

Requirements:
    pip install requests pycryptodome json5
"""

import hashlib
import json
import re
import sys
import time
import base64
from urllib.parse import quote, quote_plus

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests")

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
API = "https://enc-dec.app/api"
DATABASE = "https://enc-dec.app/db"

BASE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def validate(data: dict, path: str):
    """Check API response status and return result, or abort with an error."""
    if data.get("status") != 200:
        print(f"\n{'-'*25} API ERROR {'-'*25}\n")
        print(f"Path:        {path}")
        print(f"Status Code: {data.get('status')}")
        print(f"Error:       {data.get('error', 'unknown')}")
        raise SystemExit(1)
    return data["result"]


def print_result(title: str, referer, data):
    """Pretty-print a decrypted result."""
    sep = "-" * 25
    print(f"\n{sep} {title} {sep}\n")
    if referer:
        print(f"Referer: {referer}\n")
    print(data)


# ---------------------------------------------------------------------------
# 1. Videasy  (cineby.sc / api.videasy.net)
# ---------------------------------------------------------------------------
def run_videasy(
    title="Game of Thrones",
    media_type="tv",
    year="2011",
    imdb_id="tt0944947",
    tmdb_id="1399",
    season="1",
    episode="1",
    server="cdn",
):
    """
    Servers:
        neon    -> mb-flix          yoru    -> cdn
        cypher  -> moviebox         sage    -> 1movies
        breach  -> m4uhd            vyse    -> hdmovie (English)
        killjoy -> meine?lang=german
        harbor  -> meine?lang=italian
        chamber -> meine?lang=french (movie only)
        fade    -> hdmovie (Hindi)  omen -> lamovie
        raze    -> superflix

    Use api.videasy.net or api2.videasy.net.

    Movie: .../sources-with-title?title=...&mediaType=movie&year=...&tmdbId=...&imdbId=...
    TV:    .../sources-with-title?title=...&mediaType=tv&year=...&episodeId=...&seasonId=...&tmdbId=...&imdbId=...
    """
    headers = {
        "Accept": "*/*",
        "Origin": "https://cineby.sc",
        "Referer": "https://cineby.sc/",
        "User-Agent": BASE_UA,
    }

    # Double URL-encode the title (required by Videasy)
    enc_title = quote(quote(title, safe=""), safe="")

    url = (
        f"https://api.videasy.net/{server}/sources-with-title"
        f"?title={enc_title}&mediaType={media_type}&year={year}"
        f"&episodeId={episode}&seasonId={season}"
        f"&tmdbId={tmdb_id}&imdbId={imdb_id}"
    )
    enc_data = requests.get(url, headers=headers).text

    dec_path = f"{API}/dec-videasy"
    response = requests.post(dec_path, json={"text": enc_data, "id": tmdb_id}).json()
    decrypted = validate(response, dec_path)
    print_result("Videasy - Decrypted Data", headers["Referer"], decrypted)


# ---------------------------------------------------------------------------
# 2. VidSync  (vidsync.xyz)
# ---------------------------------------------------------------------------
def run_vidsync(
    title="Game of Thrones",
    media_type="tv",
    year="2011",
    imdb_id="tt0944947",
    tmdb_id="1399",
    season="1",
    episode="1",
    server="cinevault",
):
    """
    Server list: https://vidsync.xyz/api/stream/serverList
    Sample: cinevault, cinedub, cinebox, cineflix, cinevip, cinecloud, cine4k

    Movie: ?type=movie&title=...&mediaId={tmdb_id}&releaseYear={year}&serverName={server}
    TV:    + &season=...&episode=...
    """
    headers = {
        "Accept": "*/*",
        "Origin": "https://vidsync.xyz",
        "Referer": "https://vidsync.xyz/",
        "User-Agent": BASE_UA,
        "X-Requested-With": "XMLHttpRequest",
    }

    # Get Cloudflare Turnstile token
    enc_path = f"{API}/enc-vidsync"
    enc_data = validate(requests.get(enc_path).json(), enc_path)
    headers["X-Cf-Turnstile"] = enc_data["token"]

    enc_title = quote_plus(title)
    url = (
        f"https://vidsync.xyz/api/stream/fetch"
        f"?title={enc_title}&type={media_type}&releaseYear={year}"
        f"&mediaId={tmdb_id}&serverName={server}&season={season}&episode={episode}"
    )
    text = requests.get(url, headers=headers).text

    dec_path = f"{API}/dec-vidsync"
    decrypted = validate(
        requests.post(dec_path, json={"text": text, "id": tmdb_id}).json(), dec_path
    )
    print_result("VidSync - Decrypted Data", headers["Referer"], decrypted)


# ---------------------------------------------------------------------------
# 3. VidLink  (vidlink.pro)
# ---------------------------------------------------------------------------
def run_vidlink(
    title="Cyberpunk: Edgerunners",
    media_type="tv",
    year="2022",
    imdb_id="tt12590266",
    tmdb_id="105248",
    season="1",
    episode="1",
):
    """
    Movie: https://vidlink.pro/api/b/movie/{encrypted_id}
    TV:    https://vidlink.pro/api/b/tv/{encrypted_id}/{season}/{episode}
    """
    headers = {
        "User-Agent": BASE_UA,
        "Origin": "https://vidlink.pro",
        "Referer": "https://vidlink.pro/",
    }

    enc_path = f"{API}/enc-vidlink?text={tmdb_id}"
    encrypted = validate(requests.get(enc_path).json(), enc_path)

    url = f"https://vidlink.pro/api/b/{media_type}/{encrypted}/{season}/{episode}"
    data = requests.get(url, headers=headers).json()
    print_result("VidLink - Data", headers["Referer"], json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# 4. VidFast  (vidfast.pro)
# ---------------------------------------------------------------------------
def run_vidfast(
    title="Game of Thrones",
    media_type="tv",
    year="2011",
    imdb_id="tt0944947",
    tmdb_id="1399",
    season="1",
    episode="1",
    version="1",
):
    """
    Movie: https://vidfast.pro/movie/{IMDB_or_TMDB}
    TV:    https://vidfast.pro/tv/{IMDB_or_TMDB}/{season}/{episode}/
    """
    headers = {
        "User-Agent": BASE_UA,
        "Referer": "https://vidfast.pro/",
        "X-Requested-With": "XMLHttpRequest",
    }

    base_url = f"https://vidfast.pro/{media_type}/{tmdb_id}/{season}/{episode}/"
    response = requests.get(base_url).text

    match = re.search(r'\\"en\\":\\"(.*?)\\"', response)
    if not match:
        print("VidFast: Could not extract encoded text from page.")
        return
    text = match.group(1)

    enc_path = f"{API}/enc-vidfast?text={text}&version={version}"
    parts = validate(requests.get(enc_path).json(), enc_path)
    headers["X-CSRF-Token"] = parts["token"]

    # Decrypt servers list
    servers_encrypted = requests.post(parts["servers"], headers=headers).text
    dec_path = f"{API}/dec-vidfast"
    servers_decrypted = validate(
        requests.post(dec_path, json={"text": servers_encrypted, "version": version}).json(),
        dec_path,
    )

    # Use first server
    server = servers_decrypted[0]
    stream_url = f"{parts['stream']}/{server['data']}"
    stream_encrypted = requests.post(stream_url, headers=headers).text
    stream_decrypted = validate(
        requests.post(dec_path, json={"text": stream_encrypted, "version": version}).json(),
        dec_path,
    )
    print_result("VidFast - Decrypted Stream", headers["Referer"], stream_decrypted)


# ---------------------------------------------------------------------------
# 5. Hexa / Flixer  (hexa.su / flixer.su)
# ---------------------------------------------------------------------------
def run_hexa(
    title="Cyberpunk: Edgerunners",
    media_type="tv",
    year="2022",
    imdb_id="tt12590266",
    tmdb_id="105248",
    season="1",
    episode="1",
):
    """
    Also works with https://flixer.su/
    Movie: https://theemoviedb.hexa.su/api/tmdb/movie/{tmdb_id}/images
    TV:    https://theemoviedb.hexa.su/api/tmdb/tv/{tmdb_id}/season/{s}/episode/{e}/images
    """
    try:
        from Crypto.Random import get_random_bytes
    except ImportError:
        sys.exit("Missing dependency: pip install pycryptodome")

    headers = {
        "User-Agent": BASE_UA,
        "Referer": "https://hexa.su/",
        "Accept": "text/plain",
        "X-Fingerprint-Lite": "e9136c41504646444",
    }

    key = get_random_bytes(32).hex()
    headers["X-Api-Key"] = key

    enc_path = f"{API}/enc-hexa"
    token = validate(requests.get(enc_path).json(), enc_path)["token"]
    headers["X-Cap-Token"] = token

    if media_type == "movie":
        url = f"https://theemoviedb.hexa.su/api/tmdb/movie/{tmdb_id}/images"
    else:
        url = (
            f"https://theemoviedb.hexa.su/api/tmdb/tv/{tmdb_id}"
            f"/season/{season}/episode/{episode}/images"
        )

    encrypted = requests.get(url, headers=headers).text

    dec_path = f"{API}/dec-hexa"
    decrypted = validate(
        requests.post(dec_path, json={"text": encrypted, "key": key}).json(), dec_path
    )
    print_result("Hexa - Decrypted Data", headers["Referer"], decrypted)


# ---------------------------------------------------------------------------
# 6. LordFlix  (lordflix.org / network.hasta-la-vista.site)
# ---------------------------------------------------------------------------
def run_lordflix(
    title="Game of Thrones",
    media_type="series",
    year="2011",
    imdb_id="tt0944947",
    tmdb_id="1399",
    season="1",
    episode="1",
    server="Berlin",
):
    """
    Server list: https://network.hasta-la-vista.site/servers
    Sample: Berlin, Tokyo, Bogota, Oslo, Luna, LordFlix, Sakura, Rio, Ativa

    Movie:  ?title=...&type=movie&year=...&imdb=...&tmdb=...&server=...
    Series: ?title=...&type=series&...&server=...&season=...&episode=...
    """
    headers = {
        "Accept": "*/*",
        "Origin": "https://lordflix.org",
        "Referer": "https://lordflix.org/",
        "User-Agent": BASE_UA,
    }

    url = (
        f"https://network.hasta-la-vista.site/"
        f"?title={quote(title)}&type={media_type}&year={year}"
        f"&imdb={imdb_id}&tmdb={tmdb_id}&server={server}"
        f"&season={season}&episode={episode}"
    )

    enc_path = f"{API}/enc-lordflix?url={quote(url)}"
    data = validate(requests.get(enc_path).json(), enc_path)

    encrypted = requests.get(data["url"], headers=headers).text
    dec_path = f"{API}/dec-lordflix"
    decrypted = validate(
        requests.post(dec_path, json={"text": encrypted, "sign": data["sign"]}).json(),
        dec_path,
    )
    print_result("LordFlix - Decrypted Data", headers["Referer"], decrypted)


# ---------------------------------------------------------------------------
# 7. Abyss  (playhydrax.com)https://streaming-integrale.com/episode/tune-in-to-the-midnight-heart-saison-1-episode-1/
# ---------------------------------------------------------------------------
def run_abyss(content_id="K8R6OOjS7"):
    """
    content_id -- the 'v' query parameter on playhydrax.com
    """
    headers = {
        "User-Agent": BASE_UA,
        "Origin": "https://playhydrax.com",
        "Referer": "https://playhydrax.com/",
    }

    url = f"https://playhydrax.com/?v={content_id}"
    response = requests.get(url, headers=headers).text
    match = re.search(r'const\s+datas\s*=\s*"([^"]*)"', response)
    if not match:
        print("Abyss: Could not find 'datas' variable in page.")
        return
    encrypted = match.group(1)

    dec_path = f"{API}/dec-abyss"
    decrypted = validate(
        requests.post(dec_path, json={"text": encrypted}).json(), dec_path
    )
    print_result("Abyss - Decrypted Data", headers["Referer"], decrypted)


# ---------------------------------------------------------------------------
# 8. KissKH  (kisskh.do)
# ---------------------------------------------------------------------------
def run_kisskh(content_id="192143"):
    """
    content_id -- episode ID on kisskh.do
    """
    headers = {
        "User-Agent": BASE_UA,
        "Accept": "application/json",
    }

    # Video stream key
    enc_vid_path = f"{API}/enc-kisskh?text={content_id}&type=vid"
    vid_key = validate(requests.get(enc_vid_path).json(), enc_vid_path)
    video_url = (
        f"https://kisskh.do/api/DramaList/Episode/{content_id}.png"
        f"?err=false&ts=&time=&kkey={vid_key}"
    )
    video_response = requests.get(video_url, headers=headers).json()

    # Subtitle key
    enc_sub_path = f"{API}/enc-kisskh?text={content_id}&type=sub"
    sub_key = validate(requests.get(enc_sub_path).json(), enc_sub_path)
    sub_url = f"https://kisskh.do/api/Sub/{content_id}?kkey={sub_key}"
    subtitle_response = requests.get(sub_url, headers=headers).json()

    # Decrypt first subtitle
    subtitle_src = subtitle_response[0]["src"]
    subtitle_decrypt = requests.get(f"{API}/dec-kisskh?url={quote(subtitle_src)}").text

    print(f"\n{'-'*25} KissKH Sample Response {'-'*25}\n")
    print("Video:\n", json.dumps(video_response, indent=2))
    print("\nSubtitles:\n", json.dumps(subtitle_response, indent=2))
    print("\nDecrypted subtitle (first 200 chars):\n", subtitle_decrypt[:200])


# ---------------------------------------------------------------------------
# 9. OneTouchTV  (api3.devcorp.me)
# ---------------------------------------------------------------------------
def run_onetouchtv(
    content_url="https://api3.devcorp.me/web/vod/150294-ghost-train-2024/episode/1",
):
    """
    content_url -- full API URL for the specific episode.
    """
    headers = {"User-Agent": BASE_UA}

    encrypted = requests.get(content_url, headers=headers).text
    dec_path = f"{API}/dec-onetouchtv"
    decrypted = validate(
        requests.post(dec_path, json={"text": encrypted}).json(), dec_path
    )
    print_result("OneTouchTV - Decrypted Data", None, decrypted)


# ---------------------------------------------------------------------------
# 10. PrimeSrc  (primesrc.me)
# ---------------------------------------------------------------------------
def run_primesrc(
    title="Game of Thrones",
    media_type="tv",
    year="2011",
    imdb_id="tt0944947",
    tmdb_id="1399",
    season="1",
    episode="1",
):
    """
    Movie: https://primesrc.me/api/v1/s?imdb={imdb_id}&type=movie
    TV:    https://primesrc.me/api/v1/s?imdb={imdb_id}&season={s}&episode={e}&type=tv
    """
    headers = {"User-Agent": BASE_UA}

    primesrc_api = (
        f"https://primesrc.me/api/v1/s"
        f"?imdb={imdb_id}&season={season}&episode={episode}&type={media_type}"
    )
    response = requests.get(primesrc_api, headers=headers).json()

    # Use first server (multiple options with different sizes/qualities available)
    server = response["servers"][0]
    name = server["name"]
    key = server["key"]

    embed_api = f"https://primesrc.me/api/v1/l?key={key}"
    solve_path = f"{API}/solve-primesrc?url={quote(embed_api)}"
    link = validate(requests.get(solve_path).json(), solve_path)

    print(f"\n{'-'*25} PrimeSrc - Link {'-'*25}\n")
    print(f"Host: {name}")
    print(f"Link: {link}")
    print("\nNote: use an embed-specific decryptor for the returned link.")


# ---------------------------------------------------------------------------
# 11. Reanime  (reanime.to)
# ---------------------------------------------------------------------------
def run_reanime(
    title="Cyberpunk Edgerunners",
    anilist_id="120377",
    episode="1",
):
    """
    Requires json5: pip install json5
    Multiple server options may be available with different audio languages.
    """
    try:
        import json5 as j5
    except ImportError:
        sys.exit("Missing dependency: pip install json5")
    from urllib.parse import urlparse

    headers = {
        "User-Agent": BASE_UA,
        "Referer": "https://reanime.to/",
    }

    response = requests.get(
        f"https://reanime.to/api/flix/{anilist_id}/{episode}", headers=headers
    ).json()
    servers = response["servers"]
    server_url = servers[0]["dataLink"]
    domain = urlparse(server_url).netloc

    page = requests.get(server_url, headers=headers).text
    match = re.search(r'type:\s*"data",\s*data:\s*(\{.*?\})\s*,\s*uses:', page, re.S)
    if not match:
        print("Reanime: Could not extract embedded data from page.")
        return
    data = j5.loads(match.group(1))
    subtitles = data.pop("subtitles", None)

    # Step 1 - resolve stream state
    resolve_path = f"{API}/dec-reanime?type=resolve"
    resolved = validate(
        requests.post(resolve_path, json={"data": data}).json(), resolve_path
    )

    # Step 2 - fetch encrypted stream token
    referer = f"https://{domain}/"
    stream_headers = {**headers, "Referer": referer}
    token_response = requests.get(
        f"https://{domain}/api/m3u8/{resolved['token']}", headers=stream_headers
    ).json()

    # Step 3 - decrypt
    decrypt_path = f"{API}/dec-reanime?type=decrypt"
    decrypted = validate(
        requests.post(
            decrypt_path,
            json={"data": {"state": resolved["state"], "token_response": token_response}},
        ).json(),
        decrypt_path,
    )
    print_result("Reanime - Decrypted Data", referer, decrypted)
    if subtitles:
        print(f"\nSubtitles available: {subtitles}")


# ---------------------------------------------------------------------------
# 12. XPrime  (mznxiwqjdiq00239q.space)
# ---------------------------------------------------------------------------
def _xprime_solve_altcha():
    """Solve XPrime's Proof-of-Work Altcha challenge."""
    url = "https://mznxiwqjdiq00239q.space/altcha/challenge"
    challenge = requests.get(url).json()

    algorithm = challenge["algorithm"]
    ch = challenge["challenge"]
    salt = challenge["salt"]
    maxnumber = challenge["maxnumber"]

    threshold = hex(((1 << 256) - 1) // (maxnumber + 1))[2:].rjust(64, "0")
    start = time.time()
    number = -1
    for n in range(maxnumber * 10 + 1):
        h = hashlib.sha256(f"{algorithm}:{ch}:{salt}:{n}".encode()).hexdigest()
        if h <= threshold:
            number = n
            break

    if number < 0:
        raise RuntimeError("XPrime: Altcha PoW solving failed.")

    took = int((time.time() - start) * 1000)
    payload = {
        "algorithm": algorithm,
        "challenge": ch,
        "maxnumber": maxnumber,
        "number": number,
        "salt": salt,
        "signature": challenge["signature"],
        "took": took,
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def run_xprime(
    title="Cyberpunk: Edgerunners",
    media_type="tv",
    year="2022",
    imdb_id="tt12590266",
    tmdb_id="105248",
    season="1",
    episode="1",
    server="primebox",
):
    """
    Server list: https://mznxiwqjdiq00239q.space/servers
    Sample: primenet, finger, primebox, king, facile, lighter, fed, eek

    Movie: ?name={title}&year={year}&id={tmdb_id}&imdb={imdb_id}
    TV:    + &season={s}&episode={e}
    """
    headers = {
        "User-Agent": BASE_UA,
        "Referer": "https://mznxiwqjdiq00239q.space/",
    }

    print("XPrime: Solving Altcha PoW challenge (may take a moment)...")
    altcha = _xprime_solve_altcha()

    url = (
        f"https://mznxiwqjdiq00239q.space/{server}"
        f"?name={quote(title)}&year={year}&id={tmdb_id}&imdb={imdb_id}"
        f"&season={season}&episode={episode}&altcha={altcha}"
    )
    encrypted = requests.get(url, headers=headers).text

    dec_path = f"{API}/dec-xprime"
    decrypted = validate(
        requests.post(dec_path, json={"text": encrypted}).json(), dec_path
    )
    print_result("XPrime - Decrypted Data", headers["Referer"], decrypted)


# ---------------------------------------------------------------------------
# 13. MegaUp  (AnimeKai embed decryptor)
# ---------------------------------------------------------------------------
def run_megaup(
    view_url=(
        "https://animekai.to/ajax/links/view"
        "?id=dIG98qei6A"
        "&_=xQm9tJfLwGhz_0Eq8S_YAHYkwp-qSvLfm50W5X1nyd2NnAcpzTUWyAgck4I"
    ),
):
    """
    Works with any AnimeKai /ajax/links/view URL regardless of domain.
    Flow: dec-kai -> extract embed URL -> /media/ endpoint -> dec-mega -> HLS streams.
    """
    headers = {
        "User-Agent": BASE_UA,
        "Accept": "application/json",
    }

    enc = requests.get(view_url, headers=headers).json()["result"]
    dec = requests.post(f"{API}/dec-kai", json={"text": enc}).json()["result"]
    embed = dec["url"]

    referer = embed.split("/e/")[0] + "/"
    headers["Referer"] = referer
    media = embed.replace("/e/", "/media/")

    encrypted = requests.get(media, headers=headers).json()["result"]
    dec_path = f"{API}/dec-mega"
    decrypted = validate(
        requests.post(dec_path, json={"text": encrypted, "agent": BASE_UA}).json(),
        dec_path,
    )
    print_result("MegaUp - Decrypted Data", referer, decrypted)


# ---------------------------------------------------------------------------
# 14. RapidShare  (YFlix / 1Movies embed decryptor)
# ---------------------------------------------------------------------------
def run_rapidshare(
    view_url=(
        "https://yflix.to/ajax/links/view"
        "?id=cYe--KWj5g"
        "&_=VU7EzW-r3IptzPzkwFi43K6fMXG1W-twXRnEjr7jYvY2mi6oJTqlmYTf"
    ),
):
    """
    Works with any YFlix / 1Movies /ajax/links/view URL regardless of domain.
    Flow: dec-movies-flix -> extract embed URL -> /media/ endpoint -> dec-rapid -> HLS streams.
    """
    headers = {
        "User-Agent": BASE_UA,
        "Accept": "application/json",
    }

    enc = requests.get(view_url, headers=headers).json()["result"]
    dec = requests.post(f"{API}/dec-movies-flix", json={"text": enc}).json()["result"]
    embed = dec["url"]

    referer = embed.split("/e/")[0] + "/"
    headers["Referer"] = referer
    media = embed.replace("/e/", "/media/")

    encrypted = requests.get(media, headers=headers).json()["result"]
    dec_path = f"{API}/dec-rapid"
    decrypted = validate(
        requests.post(dec_path, json={"text": encrypted, "agent": BASE_UA}).json(),
        dec_path,
    )
    print_result("RapidShare - Decrypted Data", referer, decrypted)


# ---------------------------------------------------------------------------
# 15. AnimeKai  (animekai.to) -- full episode to server flow
# ---------------------------------------------------------------------------
def run_animekai(
    url="https://animekai.to/watch/cyberpunk-edgerunners-x6qm",
    season="1",
    episode="1",
    sub_type="softsub",
    server_id="1",
):
    """
    sub_type options: sub | softsub | dub
    server_id options: "1" | "2"
    After decryption, pass the embed URL to run_megaup() for HLS streams.
    """
    headers = {
        "User-Agent": BASE_UA,
        "Referer": "https://animekai.to/",
        "Accept": "application/json",
    }
    KAI_AJAX = "https://animekai.to/ajax"

    # Extract content ID
    html = requests.get(url, headers=headers).text
    content_id = re.search(
        r'<div[^>]*id="anime-rating"[^>]*data-id="([^"]+)"', html
    ).group(1)

    # Get episodes list
    enc_id = requests.get(f"{API}/enc-kai?text={content_id}").json()["result"]
    episodes_resp = requests.get(
        f"{KAI_AJAX}/episodes/list?ani_id={content_id}&_={enc_id}", headers=headers
    ).json()
    episodes = requests.post(
        f"{API}/parse-html", json={"text": episodes_resp["result"]}
    ).json()["result"]

    # Get servers list
    token = episodes[season][episode]["token"]
    enc_token = requests.get(f"{API}/enc-kai?text={token}").json()["result"]
    servers_resp = requests.get(
        f"{KAI_AJAX}/links/list?token={token}&_={enc_token}", headers=headers
    ).json()
    servers = requests.post(
        f"{API}/parse-html", json={"text": servers_resp["result"]}
    ).json()["result"]

    # Get embed
    lid = servers[sub_type][server_id]["lid"]
    enc_lid = requests.get(f"{API}/enc-kai?text={lid}").json()["result"]
    embed_resp = requests.get(
        f"{KAI_AJAX}/links/view?id={lid}&_={enc_lid}", headers=headers
    ).json()

    decrypted = requests.post(
        f"{API}/dec-kai", json={"text": embed_resp["result"]}
    ).json()["result"]
    print_result("AnimeKai - Decrypted Embed", None, decrypted)
    print("\nNext step: pass the embed URL to run_megaup().")


# ---------------------------------------------------------------------------
# 16. 1Movies / YFlix  (yflix.to / 1movies.sx) -- full episode to server flow
# ---------------------------------------------------------------------------
def run_yflix(
    url="https://yflix.to/watch/cyberpunk-edgerunners.b4d24",
    season="1",
    episode="1",
    link_type="default",
    server_id="1",
):
    """
    link_type options: default
    server_id options: "1" | "2"
    After decryption, pass the embed URL to run_rapidshare() for HLS streams.
    Note: subtitles URL is passed as a URL-encoded sub.list parameter.
    """
    headers = {
        "User-Agent": BASE_UA,
        "Referer": "https://yflix.to/",
        "Accept": "application/json",
    }
    YFLIX_AJAX = "https://yflix.to/ajax"

    # Extract content ID
    html = requests.get(url, headers=headers).text
    content_id = re.search(
        r'<div[^>]*id="movie-rating"[^>]*data-id="([^"]+)"', html
    ).group(1)

    # Get episodes list
    enc_id = requests.get(f"{API}/enc-movies-flix?text={content_id}").json()["result"]
    episodes_resp = requests.get(
        f"{YFLIX_AJAX}/episodes/list?id={content_id}&_={enc_id}", headers=headers
    ).json()
    episodes = requests.post(
        f"{API}/parse-html", json={"text": episodes_resp["result"]}
    ).json()["result"]

    # Get servers list
    eid = episodes[season][episode]["eid"]
    enc_eid = requests.get(f"{API}/enc-movies-flix?text={eid}").json()["result"]
    servers_resp = requests.get(
        f"{YFLIX_AJAX}/links/list?eid={eid}&_={enc_eid}", headers=headers
    ).json()
    servers = requests.post(
        f"{API}/parse-html", json={"text": servers_resp["result"]}
    ).json()["result"]

    # Get embed
    lid = servers[link_type][server_id]["lid"]
    enc_lid = requests.get(f"{API}/enc-movies-flix?text={lid}").json()["result"]
    embed_resp = requests.get(
        f"{YFLIX_AJAX}/links/view?id={lid}&_={enc_lid}", headers=headers
    ).json()

    decrypted = requests.post(
        f"{API}/dec-movies-flix", json={"text": embed_resp["result"]}
    ).json()["result"]
    print_result("YFlix/1Movies - Decrypted Embed", None, decrypted)
    print("\nNext step: pass the embed URL to run_rapidshare().")


# ---------------------------------------------------------------------------
# 17. Database -- AnimeKai  (enc-dec.app/db/kai)
# ---------------------------------------------------------------------------
def run_database_kai(
    mal_id="42310",
    season="1",
    episode="1",
    sub_type="sub",
    server="server1",
):
    """
    Database endpoints:
        Statistics:  https://enc-dec.app/db/kai/
        By ID:       https://enc-dec.app/db/kai/find?mal_id=...
                     https://enc-dec.app/db/kai/find?anilist_id=...
                     https://enc-dec.app/db/kai/find?kai_id=...
        By title:    https://enc-dec.app/db/kai/search?query=...&type=tv&year=...

    sub_type options: sub | softsub | dub
    server options:   server1 | server2

    The 'episodes' field contains:
        - title under 'title' key
        - token under 'token' key  (fallback: use animekai.py flow)
        - scraped sources and skips under 'sources' key
    """
    entries = requests.get(f"{DATABASE}/kai/find?mal_id={mal_id}").json()
    entry = entries[0]

    mirrors = entry["info"]["mirrors"]
    megaup_mirror = mirrors["megaup"][0]

    episodes = entry["episodes"]
    media = episodes[season][episode]["sources"][sub_type][server]
    stream_url = f"{megaup_mirror}{media}"

    print(f"\n{'-'*25} Database-Kai - Loaded URL {'-'*25}\n")
    print(stream_url)
    print("\nNext step: pass this URL to run_megaup().")


# ---------------------------------------------------------------------------
# 18. Database -- YFlix/1Movies  (enc-dec.app/db/flix)
# ---------------------------------------------------------------------------
def run_database_flix(
    tmdb_id="1399",
    season="1",
    episode="1",
    link_type="default",
    server_id="1",
):
    """
    Database endpoints:
        Statistics:  https://enc-dec.app/db/flix/
        By ID:       https://enc-dec.app/db/flix/find?tmdb_id=...
                     https://enc-dec.app/db/flix/find?imdb_id=...
                     https://enc-dec.app/db/flix/find?flix_id=...
        By title:    https://enc-dec.app/db/flix/search?query=...&type=tv&year=...

    Unlike the kai database, the flix database does NOT include pre-scraped sources.
    The eid must be used to load servers live from YFlix.
    """
    headers = {
        "User-Agent": BASE_UA,
        "Referer": "https://yflix.to/",
        "Accept": "application/json",
    }
    YFLIX_AJAX = "https://yflix.to/ajax"

    entries = requests.get(f"{DATABASE}/flix/find?tmdb_id={tmdb_id}").json()
    episodes = entries[0]["episodes"]
    eid = episodes[season][episode]["eid"]

    # Load servers live
    enc_eid = requests.get(f"{API}/enc-movies-flix?text={eid}").json()["result"]
    servers_resp = requests.get(
        f"{YFLIX_AJAX}/links/list?eid={eid}&_={enc_eid}", headers=headers
    ).json()
    servers = requests.post(
        f"{API}/parse-html", json={"text": servers_resp["result"]}
    ).json()["result"]

    lid = servers[link_type][server_id]["lid"]
    enc_lid = requests.get(f"{API}/enc-movies-flix?text={lid}").json()["result"]
    embed_resp = requests.get(
        f"{YFLIX_AJAX}/links/view?id={lid}&_={enc_lid}", headers=headers
    ).json()

    decrypted = requests.post(
        f"{API}/dec-movies-flix", json={"text": embed_resp["result"]}
    ).json()["result"]
    print_result("Database-Flix - Decrypted Embed", None, decrypted)
    print("\nNext step: pass the embed URL to run_rapidshare().")


# ---------------------------------------------------------------------------
# Interactive menu
# ---------------------------------------------------------------------------
MENU = [
    ("Videasy           (cineby.sc)",                       run_videasy),
    ("VidSync           (vidsync.xyz)",                     run_vidsync),
    ("VidLink           (vidlink.pro)",                     run_vidlink),
    ("VidFast           (vidfast.pro)",                     run_vidfast),
    ("Hexa / Flixer     (hexa.su / flixer.su)",             run_hexa),
    ("LordFlix          (lordflix.org)",                    run_lordflix),
    ("Abyss             (playhydrax.com)",                  run_abyss),
    ("KissKH            (kisskh.do)",                       run_kisskh),
    ("OneTouchTV        (api3.devcorp.me)",                 run_onetouchtv),
    ("PrimeSrc          (primesrc.me)",                     run_primesrc),
    ("Reanime           (reanime.to)",                      run_reanime),
    ("XPrime            (mznxiwqjdiq00239q.space)",         run_xprime),
    ("MegaUp            (AnimeKai embed)",                  run_megaup),
    ("RapidShare        (YFlix/1Movies embed)",             run_rapidshare),
    ("AnimeKai          (animekai.to - full flow)",         run_animekai),
    ("YFlix / 1Movies   (yflix.to - full flow)",            run_yflix),
    ("Database-Kai      (enc-dec.app/db/kai)",              run_database_kai),
    ("Database-Flix     (enc-dec.app/db/flix)",             run_database_flix),
]


def main():
    print("\n" + "=" * 60)
    print("   enc-dec.app -- Combined Decryptor  (18 sites)")
    print("=" * 60)
    for i, (name, _) in enumerate(MENU, 1):
        print(f"  {i:2}. {name}")
    print("   0. Exit")
    print("=" * 60)

    choice = input("\nSelect a site (number): ").strip()
    if choice == "0":
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(MENU):
            raise ValueError
    except ValueError:
        print("Invalid selection.")
        return

    name, func = MENU[idx]
    print(f"\nRunning [{name.strip()}] with default sample parameters...\n")
    try:
        func()
    except SystemExit:
        pass
    except Exception as exc:
        print(f"\nError: {exc}")


if __name__ == "__main__":
    main()
