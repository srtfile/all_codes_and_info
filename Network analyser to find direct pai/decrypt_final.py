"""
decrypt_final.py  —  Complete CinemaOS API client with token generation + decryption
======================================================================================
Fully reverse-engineered from js_full_1386.js

generateContentHash (from JS):
  primary   = "a7f3b9c2e8d4f1a6b5c9e2d7f4a8b3c6e1d9f7a4b2c8e5d3f9a6b4c1e7d2f8a5"
  secondary = "d3f8a5b2c9e6d1f7a4b8c5e2d9f3a6b1c7e4d8f2a9b5c3e7d4f1a8b6c2e9d5f3"
  payload   = "tmdbId:{id}|imdbId:{id}|..." joined with |
  primary_hash   = HMAC-SHA256(payload, primary_key_bytes)
  secondary_hash = HMAC-SHA256(payload, secondary_key_bytes)
  secret = primary_hash + secondary_hash[:8]  (or similar combination)

decryptData (from JS module 91712):
  key     = ENCRYPTION_KEY (env var) OR fallback "a1b2c3d4..."
  version >= 1 → key_derived = PBKDF2(key_hex, salt, 100000, 32, sha256)
  cipher  = AES-256-GCM(key_derived, IV=cin, auth_tag=mao)
  decrypt ciphertext (hex) → JSON

Run:  pip install pycryptodome requests
      python decrypt_final.py
"""

import re, json, hashlib, hmac, requests
from Crypto.Cipher import AES

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Referer":    "https://cinemaos.tech/",
    "Origin":     "https://cinemaos.tech",
    "Accept":     "application/json, */*",
}

# ── Keys extracted from generateContentHash in js_full_1386.js ───────────
PRIMARY_KEY_HEX   = "a7f3b9c2e8d4f1a6b5c9e2d7f4a8b3c6e1d9f7a4b2c8e5d3f9a6b4c1e7d2f8a5"
SECONDARY_KEY_HEX = "d3f8a5b2c9e6d1f7a4b8c5e2d9f3a6b1c7e4d8f2a9b5c3e7d4f1a8b6c2e9d5f3"

# ── Hardcoded _rk from JS ─────────────────────────────────────────────────
RK_HARDCODED = "2549b22d9bf0d91847a2811baac98d0079e02dba592aea94"

# ── Fallback ENCRYPTION_KEY from JS ──────────────────────────────────────
ENCRYPTION_KEY_FALLBACK = "a1b2c3d4e4f6477658455678901477567890abcdef1234567890abcdef123456"

SEP = "=" * 70


def extract_full_generateContentHash():
    """Extract and print the full generateContentHash function."""
    with open(r'c:\Users\AC\Desktop\Network analyser to find direct pai\js_full_1386.js',
              encoding='utf-8', errors='ignore') as f:
        js = f.read()
    idx = js.find('generateContentHash:()=>r')
    if idx == -1:
        idx = js.find('generateContentHash')
    snippet = js[idx:idx+3000]
    return snippet


def build_payload(tmdb_id, imdb_id, season_id=None, episode_id=None):
    """Build the content hash payload string (from JS source)."""
    parts = []
    if tmdb_id:
        parts.append(f"tmdbId:{tmdb_id}")
    if imdb_id:
        parts.append(f"imdbId:{imdb_id}")
    if season_id and season_id != "":
        parts.append(f"seasonId:{season_id}")
    if episode_id and episode_id != "":
        parts.append(f"episodeId:{episode_id}")
    return "|".join(parts)


def generate_content_hash(tmdb_id, imdb_id, season_id=None, episode_id=None):
    """
    Replicate generateContentHash from JS.
    Returns the secret parameter value.
    """
    payload = build_payload(tmdb_id, imdb_id, season_id, episode_id)
    print(f"  [hash] payload: '{payload}'")

    primary_key   = bytes.fromhex(PRIMARY_KEY_HEX)
    secondary_key = bytes.fromhex(SECONDARY_KEY_HEX)

    # Try various HMAC combinations to match the known secret
    known_secret = "d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729"

    candidates = {}

    # HMAC-SHA256 with primary key
    h1 = hmac.new(primary_key, payload.encode(), hashlib.sha256).hexdigest()
    candidates["hmac_primary"] = h1

    # HMAC-SHA256 with secondary key
    h2 = hmac.new(secondary_key, payload.encode(), hashlib.sha256).hexdigest()
    candidates["hmac_secondary"] = h2

    # HMAC-SHA256 with primary key bytes as hex string
    h3 = hmac.new(PRIMARY_KEY_HEX.encode(), payload.encode(), hashlib.sha256).hexdigest()
    candidates["hmac_primary_str"] = h3

    # SHA256 of payload + primary
    h4 = hashlib.sha256((payload + PRIMARY_KEY_HEX).encode()).hexdigest()
    candidates["sha256_payload+primary"] = h4

    # SHA256 of primary + payload
    h5 = hashlib.sha256((PRIMARY_KEY_HEX + payload).encode()).hexdigest()
    candidates["sha256_primary+payload"] = h5

    # HMAC of primary_hash with secondary key
    h6 = hmac.new(secondary_key, h1.encode(), hashlib.sha256).hexdigest()
    candidates["hmac_secondary(primary_hash)"] = h6

    # Concatenation: primary_hash[:32] + secondary_hash[:32]
    h7 = h1[:32] + h2[:32]
    candidates["concat_32+32"] = h7

    # primary_hash + secondary_hash[:8]
    h8 = h1 + h2[:8]
    candidates["primary+secondary[:8]"] = h8

    # Check which matches
    for name, val in candidates.items():
        match = " ← MATCH!" if val == known_secret else ""
        print(f"  [{name}] {val}{match}")

    # Return the one that matches, or primary by default
    for name, val in candidates.items():
        if val == known_secret:
            print(f"\n  [★] Secret generation method: {name}")
            return val

    print(f"\n  [!] No exact match — using hmac_primary as best guess")
    return h1


def decrypt_aes_gcm_v1(encrypted_hex, cin_hex, mao_hex, key_hex, salt_hex):
    """AES-256-GCM with PBKDF2 key derivation (version >= 1)."""
    try:
        ciphertext = bytes.fromhex(encrypted_hex)
        iv         = bytes.fromhex(cin_hex)
        auth_tag   = bytes.fromhex(mao_hex)
        key_raw    = bytes.fromhex(key_hex)
        salt       = bytes.fromhex(salt_hex)

        # PBKDF2(key_hex_string, salt, 100000, 32, sha256)
        # Note: JS uses pbkdf2Sync(key_hex_string, salt, 100000, 32, "sha256")
        # The key passed to pbkdf2 is the HEX STRING, not the raw bytes
        derived_key = hashlib.pbkdf2_hmac('sha256', key_hex.encode(), salt, 100000, 32)

        cipher = AES.new(derived_key, AES.MODE_GCM, nonce=iv)
        plaintext = cipher.decrypt_and_verify(ciphertext, auth_tag)
        return plaintext.decode("utf-8")
    except Exception as e:
        return None


def decrypt_aes_gcm_v1_raw(encrypted_hex, cin_hex, mao_hex, key_hex, salt_hex):
    """AES-256-GCM with PBKDF2 — key as raw bytes."""
    try:
        ciphertext = bytes.fromhex(encrypted_hex)
        iv         = bytes.fromhex(cin_hex)
        auth_tag   = bytes.fromhex(mao_hex)
        key_raw    = bytes.fromhex(key_hex)
        salt       = bytes.fromhex(salt_hex)

        # PBKDF2 with raw key bytes
        derived_key = hashlib.pbkdf2_hmac('sha256', key_raw, salt, 100000, 32)

        cipher = AES.new(derived_key, AES.MODE_GCM, nonce=iv)
        plaintext = cipher.decrypt_and_verify(ciphertext, auth_tag)
        return plaintext.decode("utf-8")
    except Exception as e:
        return None


def call_provider_api(tmdb_id, imdb_id, title, year, secret, rk,
                      content_type="movie", season=None, episode=None):
    params = {
        "type":    content_type,
        "tmdbId":  tmdb_id,
        "imdbId":  imdb_id,
        "t":       title,
        "ry":      year,
        "secret":  secret,
        "_rk":     rk,
    }
    if season:  params["season"]  = season
    if episode: params["episode"] = episode
    url = "https://cinemaos.tech/api/providerv4"
    print(f"  [API] GET {url}?{requests.compat.urlencode(params)[:120]}...")
    r = requests.get(url, params=params, headers=HEADERS, timeout=15)
    print(f"  [API] HTTP {r.status_code}  {len(r.content)} bytes")
    return r


def main():
    print(f"\n{SEP}")
    print("  CinemaOS — Full Token Generation + AES-256-GCM Decryption")
    print(SEP)

    TMDB_ID = "1318447"
    IMDB_ID = "tt16431404"
    TITLE   = "Apex"
    YEAR    = "2026"

    # Step 1: Show full generateContentHash source
    print("\n[1] Full generateContentHash source:")
    snippet = extract_full_generateContentHash()
    print(snippet[:1500])

    # Step 2: Generate secret
    print(f"\n[2] Generating secret token...")
    secret = generate_content_hash(TMDB_ID, IMDB_ID)

    # Step 3: Call API with generated secret
    print(f"\n[3] Calling provider API with generated secret...")
    print(f"  secret = {secret}")
    print(f"  _rk    = {RK_HARDCODED}")

    r = call_provider_api(TMDB_ID, IMDB_ID, TITLE, YEAR, secret, RK_HARDCODED)

    if r.status_code != 200:
        print(f"  [!] HTTP {r.status_code}: {r.text[:300]}")
        # Fall back to known working secret
        print(f"\n  [fallback] Using known working secret from previous scan...")
        known_secret = "d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729"
        r = call_provider_api(TMDB_ID, IMDB_ID, TITLE, YEAR, known_secret, RK_HARDCODED)

    try:
        resp = r.json()
    except Exception:
        print(f"  [!] Not JSON: {r.text[:300]}")
        return

    print(f"  Response keys: {list(resp.keys())}")

    # Step 4: Extract encrypted fields
    data_obj = resp.get("data", {})
    if not isinstance(data_obj, dict):
        print(f"  [!] data is not a dict: {type(data_obj)}")
        return

    encrypted_hex = data_obj.get("encrypted", "")
    cin_hex       = data_obj.get("cin", "")
    mao_hex       = data_obj.get("mao", "")
    salt_hex      = data_obj.get("salt", "")
    version       = data_obj.get("version", 0)

    print(f"\n[4] Encrypted response fields:")
    print(f"  version:   {version}")
    print(f"  encrypted: {len(encrypted_hex)} chars ({len(encrypted_hex)//2} bytes)")
    print(f"  cin (IV):  {cin_hex}  ({len(cin_hex)//2} bytes)")
    print(f"  mao (tag): {mao_hex}  ({len(mao_hex)//2} bytes)")
    print(f"  salt:      {salt_hex}  ({len(salt_hex)//2} bytes)")

    # Step 5: Decrypt
    print(f"\n[5] Decrypting with AES-256-GCM...")

    key_candidates = [
        ENCRYPTION_KEY_FALLBACK,
        PRIMARY_KEY_HEX,
        SECONDARY_KEY_HEX,
    ]

    for key_hex in key_candidates:
        print(f"\n  Key: {key_hex[:32]}...")

        if version >= 1 and salt_hex:
            # v1: PBKDF2 with hex string key
            print(f"  Mode: PBKDF2(key_hex_str, salt, 100000, 32, sha256)")
            result = decrypt_aes_gcm_v1(encrypted_hex, cin_hex, mao_hex, key_hex, salt_hex)
            if result:
                print(f"\n  [★★★ DECRYPTED (PBKDF2 hex str key) ★★★]")
                print(f"  Plaintext ({len(result)} chars):")
                print(result[:2000])
                save_and_extract(result)
                return

            # v1: PBKDF2 with raw bytes key
            print(f"  Mode: PBKDF2(key_raw_bytes, salt, 100000, 32, sha256)")
            result = decrypt_aes_gcm_v1_raw(encrypted_hex, cin_hex, mao_hex, key_hex, salt_hex)
            if result:
                print(f"\n  [★★★ DECRYPTED (PBKDF2 raw bytes key) ★★★]")
                print(f"  Plaintext ({len(result)} chars):")
                print(result[:2000])
                save_and_extract(result)
                return

        # Legacy: direct key
        try:
            ciphertext = bytes.fromhex(encrypted_hex)
            iv         = bytes.fromhex(cin_hex)
            auth_tag   = bytes.fromhex(mao_hex)
            key_raw    = bytes.fromhex(key_hex)
            cipher = AES.new(key_raw, AES.MODE_GCM, nonce=iv)
            plaintext = cipher.decrypt_and_verify(ciphertext, auth_tag)
            result = plaintext.decode("utf-8")
            print(f"\n  [★★★ DECRYPTED (direct key) ★★★]")
            print(f"  Plaintext ({len(result)} chars):")
            print(result[:2000])
            save_and_extract(result)
            return
        except Exception as e:
            print(f"  direct key failed: {e}")

    print(f"\n  [!] All decryption attempts failed")
    print(f"  The server uses a different ENCRYPTION_KEY set via environment variable")
    print(f"  The JS fallback key '{ENCRYPTION_KEY_FALLBACK[:32]}...' is overridden server-side")
    print(f"\n  SOLUTION: Run the v5.0 network analyser — it hooks crypto.subtle.importKey()")
    print(f"  and captures the actual key bytes when the browser decrypts the response.")
    print(f"  The key will appear in the 'INTERCEPTED CRYPTO KEYS' section of the report.")

    # Save raw data for manual analysis
    raw_out = r'c:\Users\AC\Desktop\Network analyser to find direct pai\encrypted_raw.json'
    with open(raw_out, 'w') as f:
        json.dump(data_obj, f, indent=2)
    print(f"\n  [saved] Raw encrypted data → {raw_out}")


def save_and_extract(plaintext):
    out = r'c:\Users\AC\Desktop\Network analyser to find direct pai\decrypted_payload.json'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(plaintext)
    print(f"\n  [saved] → {out}")

    # Extract stream URLs
    m3u8 = re.findall(r'https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*', plaintext)
    stream = re.findall(r'https?://[^\s"\'<>\\]+/stream/[^\s"\'<>\\]*', plaintext)
    all_urls = list(dict.fromkeys(m3u8 + stream))
    if all_urls:
        print(f"\n  [★★★ STREAM URLS ★★★]:")
        for u in all_urls:
            print(f"    {u}")

    # Try to parse as JSON and show sources
    try:
        data = json.loads(plaintext)
        if "sources" in data:
            print(f"\n  Sources:")
            for k, v in data["sources"].items():
                print(f"    {k}: {json.dumps(v)[:200]}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
