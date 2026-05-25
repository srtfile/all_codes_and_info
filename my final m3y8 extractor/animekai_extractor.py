import requests
import re
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Referer": "https://animekai.to/",
    "Accept": "application/json"
}

API = "https://enc-dec.app/api"
KAI_AJAX = "https://animekai.to/ajax"


def enc(text):
    return requests.get(f"{API}/enc-kai?text={text}").json()["result"]


def dec_kai(text):
    return requests.post(f"{API}/dec-kai", json={"text": text}).json()["result"]


def dec_mega(text, user_agent):
    resp = requests.post(f"{API}/dec-mega", json={"text": text, "agent": user_agent}).json()
    if resp.get("status") != 200:
        raise Exception(f"dec-mega error: {resp.get('error', 'unknown')}")
    return resp["result"]


def parse_html(html):
    return requests.post(f"{API}/parse-html", json={"text": html}).json()["result"]


def get_episodes(content_id):
    enc_id = enc(content_id)
    resp = requests.get(
        f"{KAI_AJAX}/episodes/list?ani_id={content_id}&_={enc_id}",
        headers=HEADERS
    ).json()
    return parse_html(resp["result"])


def get_servers(token):
    enc_token = enc(token)
    resp = requests.get(
        f"{KAI_AJAX}/links/list?token={token}&_={enc_token}",
        headers=HEADERS
    ).json()
    return parse_html(resp["result"])


def get_m3u8_from_lid(lid):
    """Returns (m3u8_url, referer) for a given lid."""
    enc_lid = enc(lid)
    embed_resp = requests.get(
        f"{KAI_AJAX}/links/view?id={lid}&_={enc_lid}",
        headers=HEADERS
    ).json()
    decrypted = dec_kai(embed_resp["result"])
    embed_url = decrypted["url"]

    referer = embed_url.split("/e/")[0] + "/"
    h = {**HEADERS, "Referer": referer}

    media_url = embed_url.replace("/e/", "/media/")
    encrypted = requests.get(media_url, headers=h).json()["result"]
    decrypted_mega = dec_mega(encrypted, HEADERS["User-Agent"])

    m3u8 = decrypted_mega.get("url") or decrypted_mega.get("sources", [{}])[0].get("file")
    return m3u8, referer


def extract_all_m3u8(anime_url, season="1", episode="1"):
    """
    Extract all sub/softsub/dub m3u8 URLs for a given anime episode.

    Args:
        anime_url: Full animekai watch URL e.g. "https://animekai.to/watch/anime-slug"
        season: Season number as string (default "1")
        episode: Episode number as string (default "1")

    Returns:
        dict of { type: { server_num: { "m3u8": url, "referer": referer } } }
    """
    # Step 1: Extract content_id
    html = requests.get(anime_url, headers={**HEADERS, "Accept": "text/html"}).text
    match = re.search(r'<div[^>]*id="anime-rating"[^>]*data-id="([^"]+)"', html)
    if not match:
        raise Exception("Could not find content ID in page HTML")
    content_id = match.group(1)
    print(f"[+] Content ID: {content_id}")

    # Step 2: Get episodes
    episodes = get_episodes(content_id)
    if season not in episodes or episode not in episodes[season]:
        available = {s: list(eps.keys()) for s, eps in episodes.items()}
        raise Exception(f"Season {season} / Episode {episode} not found. Available: {available}")

    token = episodes[season][episode]["token"]
    title = episodes[season][episode].get("title", f"S{season}E{episode}")
    print(f"[+] Episode: {title} | Token: {token}")

    # Step 3: Get servers
    servers = get_servers(token)
    print(f"[+] Available types/servers: { {k: list(v.keys()) for k, v in servers.items()} }")

    # Step 4: Iterate all types and servers
    results = {}
    for type_key, server_dict in servers.items():
        results[type_key] = {}
        for server_num, server_info in server_dict.items():
            lid = server_info.get("lid")
            if not lid:
                print(f"  [-] {type_key}/server{server_num}: No lid, skipping")
                continue
            try:
                m3u8, referer = get_m3u8_from_lid(lid)
                results[type_key][server_num] = {"m3u8": m3u8, "referer": referer}
                print(f"  [✓] {type_key}/server{server_num}: {m3u8}")
            except Exception as e:
                print(f"  [✗] {type_key}/server{server_num}: Error - {e}")
                results[type_key][server_num] = {"error": str(e)}

    return results


# ─── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    anime_url = "https://anikai.to/watch/naruto-9r5k#ep=1"
    season    = "1"
    episode   = "1"

    print(f"\nExtracting M3U8 URLs for: {anime_url}")
    print(f"Season {season}, Episode {episode}\n" + "─" * 50)

    results = extract_all_m3u8(anime_url, season=season, episode=episode)

    print("\n" + "═" * 50)
    print("RESULTS")
    print("═" * 50)
    for type_key, servers in results.items():
        for server_num, data in servers.items():
            if "m3u8" in data:
                print(f"[{type_key.upper()}] Server {server_num}")
                print(f"  M3U8   : {data['m3u8']}")
                print(f"  Referer: {data['referer']}")
            else:
                print(f"[{type_key.upper()}] Server {server_num} — ERROR: {data.get('error')}")




# import re
# import requests
# from urllib.parse import urlparse
# from pprint import pprint

# HEADERS = {
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
#     "Origin": "https://vidlink.pro",
#     "Referer": "https://vidlink.pro/",
#     "Accept": "application/json",
# }

# API = "https://enc-dec.app/api"


# def validate(data, path):
#     if data.get("status") != 200:
#         raise RuntimeError(
#             f"API error at {path} | status={data.get('status')} | error={data.get('error', 'unknown')}"
#         )
#     return data["result"]


# def encrypt_tmdb_id(tmdb_id: str) -> str:
#     path = f"{API}/enc-vidlink?text={tmdb_id}"
#     response = requests.get(path, timeout=20)
#     response.raise_for_status()
#     return validate(response.json(), path)


# def parse_vidlink_page_url(page_url: str):
#     parsed = urlparse(page_url)
#     if parsed.netloc not in {"vidlink.pro", "www.vidlink.pro"}:
#         raise ValueError("URL must be from vidlink.pro")

#     path = parsed.path.strip("/")
#     parts = path.split("/")

#     if len(parts) >= 2 and parts[0] == "movie":
#         return {
#             "content_type": "movie",
#             "tmdb_id": parts[1],
#             "season": None,
#             "episode": None,
#         }

#     if len(parts) >= 4 and parts[0] == "tv":
#         return {
#             "content_type": "tv",
#             "tmdb_id": parts[1],
#             "season": parts[2],
#             "episode": parts[3],
#         }

#     raise ValueError("Unsupported Vidlink URL format")


# def build_vidlink_api_url(content_type: str, encrypted_id: str, season=None, episode=None) -> str:
#     if content_type == "movie":
#         return f"https://vidlink.pro/api/b/movie/{encrypted_id}"
#     if content_type == "tv":
#         if season is None or episode is None:
#             raise ValueError("season and episode are required for tv")
#         return f"https://vidlink.pro/api/b/tv/{encrypted_id}/{season}/{episode}"
#     raise ValueError("content_type must be 'movie' or 'tv'")


# def fetch_vidlink_payload_from_page(page_url: str):
#     info = parse_vidlink_page_url(page_url)
#     encrypted = encrypt_tmdb_id(info["tmdb_id"])
#     api_url = build_vidlink_api_url(
#         info["content_type"],
#         encrypted,
#         info["season"],
#         info["episode"],
#     )

#     response = requests.get(api_url, headers=HEADERS, timeout=20)
#     response.raise_for_status()
#     data = response.json()

#     return {
#         "page_url": page_url,
#         "request_url": api_url,
#         "referer": HEADERS["Referer"],
#         "parsed": info,
#         "status_code": response.status_code,
#         "top_level_keys": list(data.keys()) if isinstance(data, dict) else None,
#         "payload": data,
#     }


# if __name__ == "__main__":
#     page_url = "https://vidlink.pro/movie/280?autoplay=true&title=true"
#     result = fetch_vidlink_payload_from_page(page_url)
#     pprint(result)