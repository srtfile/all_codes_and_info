import json
import time
import re
from playwright.sync_api import sync_playwright

# ── Config — edit these ────────────────────────────────────────────────────────
TYPE    = "movie"   # "movie" or "tv"
ID      = 45050     # TMDB ID
SEASON  = 1         # TV only
EPISODE = 1         # TV only

# Examples:
#   Movie   → TYPE="movie", ID=45050
#   TV show → TYPE="tv",    ID=13916, SEASON=1, EPISODE=1

# ── Embed server base URLs — grouped by domain family ─────────────────────────
# Each entry: (server_code, server_name, base_url)
SERVERS = [
    # ── VidSrc family (vidsrc.*) ──────────────────────────────────────────────
    ("VID",        "VidSrc.me",       "https://vidsrc.me"),
    ("PRO",        "VidSrc.pro",      "https://vidsrc.pro"),
    ("EMB",        "VidSrc.cc",       "https://vidsrc.cc"),
    ("ONE",        "VidSrc.vip",      "https://vidsrc.vip"),
    ("RIP",        "VidSrc.rip",      "https://vidsrc.rip"),
    ("VIDSRCNL",   "VidSrc.nl",       "https://player.vidsrc.nl"),
    ("VIDSRCSU",   "VidSrc.su",       "https://vidsrc.su"),

    # ── MultiEmbed family ─────────────────────────────────────────────────────
    ("MULTI",      "MultiEmbed",      "https://multiembed.mov/directstream.php"),
    ("SUP",        "MultiEmbed2",     "https://multiembed.mov"),

    # ── 2Embed / 123Embed family ──────────────────────────────────────────────
    ("2EMB",       "2Embed",          "https://www.2embed.cc"),
    ("PLAY",       "123Embed",        "https://play2.123embed.net"),

    # ── VidLink / VidFast / VidJoy / VidZee / Vidora (vid* family) ───────────
    ("VIDLINK",    "VidLink",         "https://vidlink.pro"),
    ("FAST",       "VidFast",         "https://vidfast.pro"),
    ("VIDJ",       "VidJoy",          "https://vidjoy.pro"),
    ("VIDZEE",     "VidZee",          "https://player.vidzee.wtf"),
    ("VIDORA",     "Vidora",          "https://vidora.su"),

    # ── AutoEmbed / AnyEmbed / SuperFlixAPI (embed* family) ──────────────────
    ("AUTO",       "AutoEmbed",       "https://player.autoembed.cc"),
    ("ANY",        "AnyEmbed",        "https://anyembed.xyz"),
    ("SUPER",      "SuperFlixAPI",    "https://superflixapi.digital"),
    ("SMASH",      "SmashyStream",    "https://embed.smashystream.com/playere.php"),
    ("WAREZ",      "WarezCDN",        "https://embed.warezcdn.com"),
    ("FREMBED",    "FrEmbed",         "https://frembed.club/api"),

    # ── MoviesAPI / Filmku / 111Movies (club/stream family) ──────────────────
    ("CLUB",       "MoviesAPI",       "https://moviesapi.club"),
    ("AGG",        "Filmku",          "https://filmku.stream"),
    ("111",        "111Movies",       "https://111movies.com"),
    ("STREAM",     "StreamSito",      "https://streamsito.com"),

    # ── PStream / Videasy / PrimeSrc (player.* family) ───────────────────────
    ("PSTREAM",    "PStream",         "https://iframe.pstream.mov"),
    ("EASY",       "Videasy",         "https://player.videasy.net"),
    ("PRIME",      "PrimeSrc",        "https://primesrc.me/embed"),

    # ── GoDrive / TurboVid / Mapple / TechNeo (standalone players) ───────────
    ("GOD",        "GoDrive",         "https://godriveplayer.com/player.php"),
    ("TURBO",      "TurboVid",        "https://turbovid.eu"),
    ("MAPPLE",     "Mapple",          "https://mapple.uk"),
    ("TECHNEO",    "TechNeo",         "https://vid.techneo.fun"),

    # ── InsertUnit / RGShows (misc) ───────────────────────────────────────────
    ("INSERT",     "InsertUnit",      "https://api.insertunit.ws"),
    ("RG",         "RGShows",         "https://rgshows.ru/player"),

    # ── Rivestream internal embeds ────────────────────────────────────────────
    ("TORR",       "Torrent",         "/embed/torrent"),
    ("AGGREGATOR", "Aggregator",      "/embed/agg"),
]

# ── URL builders — extracted from rivestream JS iframe src logic ───────────────

def build_embed_url(code, base, tmdb_id, content_type, season, episode, imdb_id=""):
    t = content_type  # "movie" or "tv"
    i = str(tmdb_id)
    s = str(season)
    e = str(episode)
    im = imdb_id

    if code == "AGG":
        # filmku.stream/embed/{id} or /embed/{id}/{s}/{e}
        return f"{base}/embed/{i}" if t == "movie" else f"{base}/embed/{i}/{s}/{e}"

    elif code == "VID":
        # vidsrc.me/embed/movie/{id} or /embed/tv/{id}/{s}/{e}
        return f"{base}/embed/{t}/{i}" if t == "movie" else f"{base}/embed/{t}/{i}/{s}/{e}"

    elif code == "PRO":
        # vidsrc.pro/embed/movie/{id}?theme=00c1db
        return (f"{base}/embed/{t}/{i}?theme=00c1db" if t == "movie"
                else f"{base}/embed/{t}/{i}/{s}/{e}?theme=00c1db")

    elif code == "EMB":
        # vidsrc.cc/v2/embed/movie/{id}
        return (f"{base}/v2/embed/{t}/{i}" if t == "movie"
                else f"{base}/v2/embed/{t}/{i}/{s}/{e}")

    elif code == "MULTI":
        # multiembed.mov/directstream.php?video_id={id}&tmdb=1
        return (f"{base}?video_id={i}&tmdb=1" if t == "movie"
                else f"{base}?video_id={i}&tmdb=1&s={s}&e={e}")

    elif code == "GOD":
        # godriveplayer.com/player.php?tmdb={id}
        return (f"{base}?tmdb={i}" if t == "movie"
                else f"{base}?type=series&tmdb={i}&season={s}&episode={e}")

    elif code == "VIDJ":
        # vidjoy.pro/embed/movie/{id}?adFree=true
        return (f"{base}/embed/{t}/{i}?adFree=true" if t == "movie"
                else f"{base}/embed/{t}/{i}/{s}/{e}?adFree=true")

    elif code == "EASY":
        # player.videasy.net/movie/{id}
        return (f"{base}/{t}/{i}" if t == "movie"
                else f"{base}/{t}/{i}/{s}/{e}")

    elif code == "SUP":
        # multiembed.mov/?video_id={id}&tmdb=1&server=2
        return (f"{base}/?video_id={i}&tmdb=1&server=2" if t == "movie"
                else f"{base}/?video_id={i}&tmdb=1&s={s}&e={e}&server=2")

    elif code == "CLUB":
        # moviesapi.club/movie/{id} or /tv/{id}-{s}-{e}
        return (f"{base}/movie/{i}" if t == "movie"
                else f"{base}/tv/{i}-{s}-{e}")

    elif code == "SMASH":
        # embed.smashystream.com/playere.php?tmdb={id}
        return (f"{base}?tmdb={i}?btPosition=10" if t == "movie"
                else f"{base}?tmdb={i}&season={s}&episode={e}?btPosition=10")

    elif code == "PLAY":
        # play2.123embed.net/movie/{id}
        return (f"{base}/movie/{i}" if t == "movie"
                else f"{base}/tv/{i}/{s}/{e}")

    elif code == "ONE":
        # vidsrc.vip/embed/movie/{id}
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "ANY":
        # anyembed.xyz/embed/movie/{id}
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "PRIME":
        # primesrc.me/embed/movie/{id}
        return (f"{base}/movie/{i}" if t == "movie"
                else f"{base}/tv/{i}/{s}/{e}")

    elif code == "RG":
        # rgshows.ru/player/movie/{id}
        return (f"{base}/movie/{i}" if t == "movie"
                else f"{base}/tv/{i}/{s}/{e}")

    elif code == "INSERT":
        # api.insertunit.ws/embed/movie/{id}
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "STREAM":
        # streamsito.com/embed/movie/{id}
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "SUPER":
        # superflixapi.digital/movie/{id}
        return (f"{base}/movie/{i}" if t == "movie"
                else f"{base}/tv/{i}/{s}/{e}")

    elif code == "AUTO":
        # player.autoembed.cc/embed/movie/{id}
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "PSTREAM":
        # iframe.pstream.mov/embed/movie/{id}
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "VIDLINK":
        # vidlink.pro/movie/{id}
        return (f"{base}/movie/{i}" if t == "movie"
                else f"{base}/tv/{i}/{s}/{e}")

    elif code == "VIDSRCNL":
        # player.vidsrc.nl/embed/movie/{id}
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "2EMB":
        # www.2embed.cc/embed/{id}
        return (f"{base}/embed/{i}" if t == "movie"
                else f"{base}/embedtv/{i}&s={s}&e={e}")

    elif code == "RIP":
        # vidsrc.rip/embed/movie/{id}
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "WAREZ":
        # embed.warezcdn.com/movie/{id}
        return (f"{base}/movie/{i}" if t == "movie"
                else f"{base}/serie/{i}/{s}/{e}")

    elif code == "VIDORA":
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "VIDSRCSU":
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "TURBO":
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "FAST":
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "MAPPLE":
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "111":
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "TECHNEO":
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "VIDZEE":
        return (f"{base}/embed/movie/{i}" if t == "movie"
                else f"{base}/embed/tv/{i}/{s}/{e}")

    elif code == "FREMBED":
        return (f"{base}/movie?id={i}" if t == "movie"
                else f"{base}/tv?id={i}&s={s}&e={e}")

    elif code == "TORR":
        return (f"{base}?type=movie&id={i}" if t == "movie"
                else f"{base}?type=tv&id={i}&season={s}&episode={e}")

    elif code == "AGGREGATOR":
        return (f"{base}?type=movie&id={i}" if t == "movie"
                else f"{base}?type=tv&id={i}&season={s}&episode={e}")

    return f"{base}/{i}"


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    t_start = time.time()

    print("=" * 60)
    print("  EMBED SERVER EXTRACTOR")
    print("=" * 60)
    print(f"  Type    : {TYPE.upper()}")
    print(f"  ID      : {ID}")
    if TYPE == "tv":
        print(f"  Season  : {SEASON}  Episode: {EPISODE}")
    print("=" * 60)

    # Fetch IMDB ID from rivestream API (needed by some servers)
    imdb_id = ""
    print("\n[+] Fetching movie metadata for IMDB ID...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137.0.0.0 Safari/537.36"
            )
            # Sniff the secret key from the watch page request
            secret_key = None
            page = context.new_page()

            def on_request(request):
                nonlocal secret_key
                if "backendfetch" in request.url and secret_key is None:
                    m = re.search(r'secretKey=([^&]+)', request.url)
                    if m and m.group(1) != "rive":
                        secret_key = m.group(1)

            page.on("request", on_request)
            page.goto(
                f"https://rivestream.ru/watch?type={TYPE}&id={ID}",
                wait_until="domcontentloaded", timeout=30000
            )
            page.wait_for_timeout(3000)

            if secret_key:
                r = context.request.get(
                    "https://rivestream.ru/api/backendfetch",
                    params={
                        "requestID": "movieData" if TYPE == "movie" else "tvData",
                        "id": ID,
                        "language": "en-US",
                        "secretKey": secret_key,
                        "proxyMode": "undefined",
                    },
                    headers={"Referer": "https://rivestream.ru/", "User-Agent": "Mozilla/5.0"}
                )
                data = r.json()
                imdb_id = data.get("imdb_id", "")
                title   = data.get("title") or data.get("name", "")
                print(f"[+] Title   : {title}")
                print(f"[+] IMDB ID : {imdb_id}")
            browser.close()
    except Exception as e:
        print(f"[!] Metadata fetch failed: {e}")

    # Build all embed URLs
    print(f"\n[+] Building embed URLs for {len(SERVERS)} servers...\n")

    GROUP_HEADERS = {
        "VID":        "── VidSrc family ──────────────────────────────────────",
        "MULTI":      "── MultiEmbed family ──────────────────────────────────",
        "2EMB":       "── 2Embed / 123Embed family ───────────────────────────",
        "VIDLINK":    "── VidLink / VidFast / VidJoy / VidZee / Vidora ───────",
        "AUTO":       "── AutoEmbed / AnyEmbed / SuperFlixAPI / Smash / Warez ─",
        "CLUB":       "── MoviesAPI / Filmku / 111Movies / StreamSito ─────────",
        "PSTREAM":    "── PStream / Videasy / PrimeSrc ────────────────────────",
        "GOD":        "── GoDrive / TurboVid / Mapple / TechNeo ───────────────",
        "INSERT":     "── InsertUnit / RGShows ────────────────────────────────",
        "TORR":       "── Rivestream internal ─────────────────────────────────",
    }

    results = []
    for code, name, base in SERVERS:
        if code in GROUP_HEADERS:
            print(f"\n  {GROUP_HEADERS[code]}")
        url = build_embed_url(code, base, ID, TYPE, SEASON, EPISODE, imdb_id)
        results.append((name, url))
        print(f"  [{name:20s}] {url}")

    # Save results
    out_file = "embed_urls.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"# Embed servers for {TYPE.upper()} ID={ID}")
        if TYPE == "tv":
            f.write(f" S{SEASON}E{EPISODE}")
        f.write(f"\n# IMDB: {imdb_id}\n\n")
        for name, url in results:
            f.write(f"{name}: {url}\n")

    elapsed = time.time() - t_start
    print(f"\n[+] Total servers : {len(results)}")
    print(f"[+] Time taken    : {elapsed:.1f}s")
    print(f"[+] Saved to      : {out_file}")


if __name__ == "__main__":
    main()
