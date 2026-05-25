"""
final_decrypt.py  —  Complete working CinemaOS direct API client
=================================================================
SECRET = HMAC-SHA256(HMAC-SHA256(payload, PRIMARY_str), SECONDARY_str)
DECRYPT = AES-256-GCM, PBKDF2(ENCRYPTION_KEY_str, salt, 100000, 32, sha256)
"""
import re, json, hashlib, hmac, requests
from Crypto.Cipher import AES

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Referer": "https://cinemaos.tech/",
    "Origin":  "https://cinemaos.tech",
}

PRIMARY   = "a7f3b9c2e8d4f1a6b5c9e2d7f4a8b3c6e1d9f7a4b2c8e5d3f9a6b4c1e7d2f8a5"
SECONDARY = "d3f8a5b2c9e6d1f7a4b8c5e2d9f3a6b1c7e4d8f2a9b5c3e7d4f1a8b6c2e9d5f3"
RK        = "2549b22d9bf0d91847a2811baac98d0079e02dba592aea94"
ENC_KEY   = "a1b2c3d4e4f6477658455678901477567890abcdef1234567890abcdef123456"

SEP = "=" * 70


def generate_secret(tmdb_id, imdb_id, season_id=None, episode_id=None):
    parts = []
    if tmdb_id:   parts.append(f"tmdbId:{tmdb_id}")
    if imdb_id:   parts.append(f"imdbId:{imdb_id}")
    if season_id and season_id != "":  parts.append(f"seasonId:{season_id}")
    if episode_id and episode_id != "": parts.append(f"episodeId:{episode_id}")
    payload = "|".join(parts)
    inner  = hmac.new(PRIMARY.encode(),   payload.encode(), hashlib.sha256).hexdigest()
    secret = hmac.new(SECONDARY.encode(), inner.encode(),   hashlib.sha256).hexdigest()
    return secret


def call_api(tmdb_id, imdb_id, title, year, content_type="movie",
             season=None, episode=None):
    secret = generate_secret(tmdb_id, imdb_id, season, episode)
    params = {"type": content_type, "tmdbId": tmdb_id, "imdbId": imdb_id,
              "t": title, "ry": year, "secret": secret, "_rk": RK}
    if season:  params["season"]  = season
    if episode: params["episode"] = episode
    r = requests.get("https://cinemaos.tech/api/providerv4",
                     params=params, headers=HEADERS, timeout=15)
    return r, secret


def decrypt_response(data_obj, enc_key=ENC_KEY):
    encrypted_hex = data_obj.get("encrypted", "")
    cin_hex       = data_obj.get("cin", "")
    mao_hex       = data_obj.get("mao", "")
    salt_hex      = data_obj.get("salt", "")
    version       = data_obj.get("version", 0)

    ciphertext = bytes.fromhex(encrypted_hex)
    iv         = bytes.fromhex(cin_hex)
    auth_tag   = bytes.fromhex(mao_hex)

    if version >= 1 and salt_hex:
        salt = bytes.fromhex(salt_hex)
        # PBKDF2(key_hex_string, salt, 100000, 32, sha256)
        key = hashlib.pbkdf2_hmac('sha256', enc_key.encode(), salt, 100000, 32)
    else:
        key = bytes.fromhex(enc_key)

    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
    plaintext = cipher.decrypt_and_verify(ciphertext, auth_tag)
    return plaintext.decode("utf-8")


def get_stream(tmdb_id, imdb_id, title, year, content_type="movie",
               season=None, episode=None):
    print(f"\n{SEP}")
    print(f"  Fetching stream for: {title} ({year})  TMDB:{tmdb_id}")
    print(SEP)

    r, secret = call_api(tmdb_id, imdb_id, title, year, content_type, season, episode)
    print(f"  secret = {secret}")
    print(f"  HTTP {r.status_code}  {len(r.content)} bytes")

    if r.status_code != 200:
        print(f"  Error: {r.text[:200]}")
        return None

    resp = r.json()
    if "error" in resp:
        print(f"  API error: {resp['error']}")
        return None

    data_obj = resp.get("data", {})
    print(f"  Encrypted fields: {list(data_obj.keys())}")
    print(f"  version={data_obj.get('version')}  cin={data_obj.get('cin','')}  mao={data_obj.get('mao','')}")

    # Try decryption with fallback key
    for key in [ENC_KEY, PRIMARY, SECONDARY]:
        try:
            plaintext = decrypt_response(data_obj, key)
            print(f"\n  [★★★ DECRYPTED ★★★]  key={key[:16]}...")
            print(f"  Plaintext ({len(plaintext)} chars):")
            print(plaintext[:3000])

            # Save
            out = rf'c:\Users\AC\Desktop\Network analyser to find direct pai\stream_{tmdb_id}.json'
            with open(out, 'w', encoding='utf-8') as f:
                f.write(plaintext)
            print(f"\n  [saved] {out}")

            # Extract URLs
            urls = re.findall(r'https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*', plaintext)
            stream_urls = re.findall(r'https?://[^\s"\'<>\\]+/stream/[^\s"\'<>\\]*', plaintext)
            all_urls = list(dict.fromkeys(urls + stream_urls))
            if all_urls:
                print(f"\n  [★★★ STREAM URLS ★★★]:")
                for u in all_urls:
                    print(f"    {u}")
            return plaintext
        except Exception as e:
            print(f"  decrypt failed (key={key[:16]}...): {e}")

    print(f"\n  [!] Decryption failed — server uses a different ENCRYPTION_KEY")
    print(f"  Run v5.0 analyser to capture the key via crypto.subtle.importKey() hook")
    return None


if __name__ == "__main__":
    # Test with Apex (1318447)
    get_stream("1318447", "tt16431404", "Apex", "2026", "movie")

    print(f"\n{SEP}")
    print("  DIRECT API USAGE PATTERN")
    print(SEP)
    print("""
  # For any movie:
  secret = generate_secret(tmdb_id, imdb_id)
  GET https://cinemaos.tech/api/providerv4
      ?type=movie&tmdbId={id}&imdbId={imdb}&t={title}&ry={year}
      &secret={secret}&_rk=2549b22d9bf0d91847a2811baac98d0079e02dba592aea94

  # For TV:
  secret = generate_secret(tmdb_id, imdb_id, season_id, episode_id)
  GET https://cinemaos.tech/api/providerv4
      ?type=tv&tmdbId={id}&imdbId={imdb}&t={title}&ry={year}
      &season={s}&episode={e}
      &secret={secret}&_rk=2549b22d9bf0d91847a2811baac98d0079e02dba592aea94

  # Subtitles (no auth):
  GET https://sub.vdrk.site/v1/movie/{tmdbId}
  GET https://sub.vdrk.site/v1/tv/{tmdbId}/{season}/{episode}
    """)
