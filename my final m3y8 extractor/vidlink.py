import requests
from urllib.parse import urlparse

API = "https://enc-dec.app/api"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Origin": "https://vidlink.pro",
    "Referer": "https://vidlink.pro/",
    "Accept": "application/json",
}


def validate(data, path):
    if data.get("status") != 200:
        raise RuntimeError(
            f"API error at {path} | status={data.get('status')} | error={data.get('error', 'unknown')}"
        )
    return data["result"]


def encrypt_tmdb_id(tmdb_id: str) -> str:
    url = f"{API}/enc-vidlink?text={tmdb_id}"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    return validate(r.json(), url)


def parse_vidlink_url(page_url: str):
    parsed = urlparse(page_url)

    if parsed.netloc not in {"vidlink.pro", "www.vidlink.pro"}:
        raise ValueError("Only vidlink.pro URLs are supported")

    parts = parsed.path.strip("/").split("/")

    if parts[0] == "movie":
        return {
            "type": "movie",
            "tmdb_id": parts[1],
            "season": None,
            "episode": None,
        }

    if parts[0] == "tv":
        return {
            "type": "tv",
            "tmdb_id": parts[1],
            "season": parts[2],
            "episode": parts[3],
        }

    raise ValueError("Unsupported URL format")


def build_api_url(content_type, enc_id, season=None, episode=None):
    if content_type == "movie":
        return f"https://vidlink.pro/api/b/movie/{enc_id}"

    if content_type == "tv":
        if not season or not episode:
            raise ValueError("Season and episode required for TV")
        return f"https://vidlink.pro/api/b/tv/{enc_id}/{season}/{episode}"

    raise ValueError("Invalid content type")


def get_m3u8_url(page_url: str) -> str:
    info = parse_vidlink_url(page_url)
    encrypted_id = encrypt_tmdb_id(info["tmdb_id"])
    api_url = build_api_url(
        info["type"],
        encrypted_id,
        info["season"],
        info["episode"],
    )

    r = requests.get(api_url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()

    # 🔥 ONLY extract playlist (m3u8)
    return data["stream"]["playlist"]


if __name__ == "__main__":
    page_url = "https://vidlink.pro/movie/45050?autoplay=true&title=true"

    try:
        m3u8 = get_m3u8_url(page_url)
        print(m3u8)
    except Exception as e:
        print("Error:", e)