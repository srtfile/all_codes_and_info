"""
Simple Videasy Extractor
========================

Default URL:
https://player.videasy.net/movie/280

Requirements:
    pip install requests
"""

import sys
import json
import argparse
import requests
from urllib.parse import urlparse

ENC_DEC_API = "https://enc-dec.app/api"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)

VIDEASY_SERVERS = [
    ("mb-flix", "api"),
    ("1movies", "api"),
    ("moviebox", "api"),
    ("cdn", "api"),
    ("primesrcme", "api"),
    ("primewire", "api2"),
    ("m4uhd", "api2"),
    ("hdmovie", "api"),
    ("lamovie", "api"),
    ("superflix", "api"),
    ("cuevana", "api2"),
    ("overflix", "api2"),
    ("visioncine", "api"),
    ("meine", "api"),
]


class ExtractorError(Exception):
    pass


def get(url, headers=None, timeout=30):

    h = {
        "User-Agent": DEFAULT_UA,
        "Accept": "*/*"
    }

    if headers:
        h.update(headers)

    r = requests.get(
        url,
        headers=h,
        timeout=timeout,
        allow_redirects=True
    )

    r.raise_for_status()
    return r


def post_json(url, payload, timeout=30):

    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    r = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=timeout
    )

    r.raise_for_status()

    try:
        return r.json()
    except ValueError:
        raise ExtractorError("Invalid JSON response")


def api_unwrap(data, label):

    if not isinstance(data, dict):
        raise ExtractorError(f"[{label}] invalid response")

    if data.get("status") != 200:
        raise ExtractorError(
            f"[{label}] status={data.get('status')} "
            f"error={data.get('error', 'unknown')}"
        )

    return data["result"]


def find_streams(obj):

    found = []
    seen = set()

    def walk(node):

        if isinstance(node, dict):

            for k, v in node.items():

                if (
                    isinstance(v, str)
                    and v.startswith("http")
                    and v not in seen
                ):
                    if ".m3u8" in v or "/master" in v:
                        found.append(v)
                        seen.add(v)

                walk(v)

        elif isinstance(node, list):

            for item in node:
                walk(item)

    walk(obj)
    return found


def extract_videasy(movie_url):

    parsed = urlparse(movie_url)

    if parsed.netloc.lower() != "player.videasy.net":
        raise ExtractorError(
            "Only player.videasy.net supported"
        )

    parts = [
        p for p in parsed.path.strip("/").split("/")
        if p
    ]

    if len(parts) < 2 or parts[0] != "movie":
        raise ExtractorError(
            "URL format must be:\n"
            "https://player.videasy.net/movie/<tmdb_id>"
        )

    tmdb_id = parts[1]

    headers = {
        "Accept": "*/*",
        "Origin": "https://cineby.sc",
        "Referer": "https://cineby.sc/",
        "User-Agent": DEFAULT_UA,
    }

    errors = []

    for server, api_sub in VIDEASY_SERVERS:

        api_url = (
            f"https://{api_sub}.videasy.net/"
            f"{server}/sources-with-title"
            f"?mediaType=movie&tmdbId={tmdb_id}"
        )

        try:

            print(f"[+] Trying server: {server}")

            encrypted = get(
                api_url,
                headers=headers
            ).text

            if not encrypted or len(encrypted.strip()) < 10:
                errors.append(f"{server}: empty response")
                continue

            response = post_json(
                f"{ENC_DEC_API}/dec-videasy",
                {
                    "text": encrypted,
                    "id": str(tmdb_id)
                }
            )

            decrypted = api_unwrap(
                response,
                f"dec-videasy/{server}"
            )

            streams = find_streams(decrypted)

            if streams:

                return {
                    "tmdb_id": tmdb_id,
                    "server": server,
                    "streams": streams,
                    "raw": decrypted
                }

        except Exception as e:

            errors.append(f"{server}: {e}")
            continue

    raise ExtractorError(
        "All servers failed.\n\n"
        + "\n".join(errors[-5:])
    )


def print_result(result, json_mode=False):

    if json_mode:

        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False
            )
        )

        return

    print("\n" + "=" * 60)
    print("VIDEASY STREAM EXTRACTED")
    print("=" * 60)

    print(f"TMDB ID : {result['tmdb_id']}")
    print(f"Server  : {result['server']}")

    print("\nStreams:\n")

    for stream in result["streams"]:
        print(stream)

    print()


def main():

    parser = argparse.ArgumentParser(
        description="Videasy Extractor"
    )

    parser.add_argument(
        "url",
        nargs="?",
        default="https://player.videasy.net/movie/280",
        help="Videasy movie URL"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON"
    )

    args = parser.parse_args()

    try:

        print("\n[+] Starting extractor...\n")

        result = extract_videasy(args.url)

        print_result(
            result,
            json_mode=args.json
        )

    except ExtractorError as e:

        print(f"\n[ERROR] {e}")
        sys.exit(1)

    except requests.exceptions.RequestException as e:

        print(f"\n[NETWORK ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()