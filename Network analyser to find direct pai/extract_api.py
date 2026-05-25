"""
extract_api.py  —  CinemaOS Direct API Extractor
==================================================
Downloads the full JS chunks, finds the secret/_rk generation logic,
decrypts the captured API response, and outputs the direct stream URL.

Run:  python extract_api.py
"""

import re, json, hashlib, hmac, time, requests, binascii

# ── Known values from previous scan ──────────────────────────────────────────
PROVIDER_URL = (
    "https://cinemaos.tech/api/providerv4"
    "?type=movie&tmdbId=1318447&imdbId=tt16431404"
    "&t=Apex&ry=2026"
    "&secret=d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729"
    "&_rk=2549b22d9bf0d91847a2811baac98d0079e02dba592aea94"
)

ENCRYPTED_HEX_PARTIAL = (
    "dd32cf05b5659e931c99705d9198ced519dc9493aee504df506fabec10b086c0"
    "8020175538b4a672b88ae23df763ae0d2f0d4f60abfcc5003d24cdc2b9a8246"
    "dab9f85a0dcd290eb19efcd527cc3299ae108a7239ecca1ba80cf449df71edd0"
    "7e60d072f5025b83eac5eca450987f1a9f244df0ad79fed8d90e1b57e0938c63"
    "cbdb0e7b0e1b5ada0156238cf69efc6f7a83a947de247d90a7dfe1aef8ce8bc8"
    "dee49f9a71961f92493c9684a7cea2ffb2d6cd596de8bf8760a7d2eef4b"
)

TMDB_ID   = "1318447"
IMDB_ID   = "tt16431404"
TITLE     = "Apex"
YEAR      = "2026"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Referer":    "https://cinemaos.tech/",
    "Origin":     "https://cinemaos.tech",
    "Accept":     "application/json, */*",
}

# JS chunk URLs (the ones containing crypto logic)
JS_CHUNKS = {
    "6282":   "https://cinemaos.tech/_next/static/chunks/6282-6ec9290c43848574.js",
    "aaea2bcf": "https://cinemaos.tech/_next/static/chunks/aaea2bcf-4b7d5c47edf9795e.js",
    "a4634e51": "https://cinemaos.tech/_next/static/chunks/a4634e51-eaf6c3d6b6e58119.js",
    "9453":   "https://cinemaos.tech/_next/static/chunks/9453-08e0dc08540a303a.js",
    "1386":   "https://cinemaos.tech/_next/static/chunks/1386-e5251734b568f7de.js",
}

SEP = "=" * 70


def fetch_js(name, url):
    print(f"  [fetch] {name} ...", end="", flush=True)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        print(f" {len(r.text):,} bytes  HTTP {r.status_code}")
        return r.text
    except Exception as e:
        print(f" FAILED: {e}")
        return ""


def search_patterns(js_text, label):
    """Search a JS blob for crypto/token patterns and print findings."""
    findings = []

    patterns = [
        # secret/hash generation
        (r'secret["\s]*[:=]["\s]*([a-f0-9]{40,})',          "hardcoded secret"),
        (r'sha256[^;]{0,200}',                               "sha256 usage"),
        (r'createHash[^;]{0,200}',                           "createHash call"),
        (r'subtle\.digest[^;]{0,200}',                       "subtle.digest"),
        (r'subtle\.importKey[^;]{0,300}',                    "subtle.importKey"),
        (r'subtle\.decrypt[^;]{0,300}',                      "subtle.decrypt"),
        (r'subtle\.encrypt[^;]{0,300}',                      "subtle.encrypt"),
        # AES key material
        (r'AES[^;]{0,200}',                                  "AES reference"),
        (r'CBC[^;]{0,200}',                                  "CBC mode"),
        (r'GCM[^;]{0,200}',                                  "GCM mode"),
        (r'fromHex[^;]{0,200}',                              "fromHex"),
        (r'toHex[^;]{0,200}',                                "toHex"),
        # key strings (32-byte hex = 64 chars, 16-byte = 32 chars)
        (r'["\'][0-9a-f]{64}["\']',                          "64-char hex (256-bit key?)"),
        (r'["\'][0-9a-f]{32}["\']',                          "32-char hex (128-bit key?)"),
        # providerv4 / API construction
        (r'providerv4[^;]{0,300}',                           "providerv4 reference"),
        (r'_rk[^;]{0,200}',                                  "_rk token"),
        (r'secret[^;]{0,200}',                               "secret param"),
        # decrypt function
        (r'decrypt[^;]{0,300}',                              "decrypt call"),
        (r'encrypted[^;]{0,200}',                            "encrypted field"),
        (r'CryptoJS[^;]{0,200}',                             "CryptoJS"),
    ]

    for pat, desc in patterns:
        matches = re.findall(pat, js_text, re.I)
        for m in matches[:3]:
            m = m.strip()
            if len(m) > 10:
                findings.append((desc, m[:300]))

    if findings:
        print(f"\n  [{label}] Found {len(findings)} pattern(s):")
        seen = set()
        for desc, val in findings:
            key = desc + val[:40]
            if key not in seen:
                seen.add(key)
                print(f"    [{desc}]  {val[:200]}")
    return findings


def try_decrypt_hex(encrypted_hex, key_candidates):
    """Try AES-CBC and AES-GCM decryption with candidate keys."""
    try:
        from Crypto.Cipher import AES
        from Crypto.Util.Padding import unpad
        CRYPTO_OK = True
    except ImportError:
        print("  [!] pycryptodome not installed — run: pip install pycryptodome")
        CRYPTO_OK = False

    if not CRYPTO_OK:
        return None

    try:
        ciphertext = bytes.fromhex(encrypted_hex)
    except Exception as e:
        print(f"  [!] Invalid hex: {e}")
        return None

    print(f"\n  [decrypt] Ciphertext length: {len(ciphertext)} bytes")

    for key_hex in key_candidates:
        try:
            key = bytes.fromhex(key_hex)
        except Exception:
            try:
                key = key_hex.encode()
            except Exception:
                continue

        if len(key) not in (16, 24, 32):
            # try SHA-256 of the key string
            key = hashlib.sha256(key_hex.encode()).digest()

        print(f"  [decrypt] Trying key ({len(key)*8}-bit): {key_hex[:32]}...")

        # Try AES-CBC with first 16 bytes as IV
        try:
            iv = ciphertext[:16]
            ct = ciphertext[16:]
            cipher = AES.new(key, AES.MODE_CBC, iv)
            pt = unpad(cipher.decrypt(ct), 16)
            text = pt.decode("utf-8", errors="replace")
            if any(x in text for x in ("http", "m3u8", "stream", "url", "source")):
                print(f"\n  [★ DECRYPTED CBC] key={key_hex[:32]}  iv={iv.hex()}")
                print(f"  Plaintext: {text[:500]}")
                return text
        except Exception:
            pass

        # Try AES-CBC with last 16 bytes as IV
        try:
            iv = ciphertext[-16:]
            ct = ciphertext[:-16]
            cipher = AES.new(key, AES.MODE_CBC, iv)
            pt = unpad(cipher.decrypt(ct), 16)
            text = pt.decode("utf-8", errors="replace")
            if any(x in text for x in ("http", "m3u8", "stream", "url", "source")):
                print(f"\n  [★ DECRYPTED CBC-tail-IV] key={key_hex[:32]}")
                print(f"  Plaintext: {text[:500]}")
                return text
        except Exception:
            pass

        # Try AES-ECB
        try:
            cipher = AES.new(key, AES.MODE_ECB)
            pt = unpad(cipher.decrypt(ciphertext), 16)
            text = pt.decode("utf-8", errors="replace")
            if any(x in text for x in ("http", "m3u8", "stream", "url", "source")):
                print(f"\n  [★ DECRYPTED ECB] key={key_hex[:32]}")
                print(f"  Plaintext: {text[:500]}")
                return text
        except Exception:
            pass

    print("  [decrypt] No key worked with existing ciphertext")
    return None


def build_secret_candidates(tmdb_id, imdb_id, title, year):
    """Generate candidate secret/token values using common patterns."""
    candidates = []
    combos = [
        tmdb_id,
        imdb_id,
        title,
        year,
        f"{tmdb_id}{imdb_id}",
        f"{tmdb_id}{title}",
        f"{tmdb_id}{year}",
        f"{imdb_id}{year}",
        f"{title}{year}",
        f"{tmdb_id}{imdb_id}{title}",
        f"{tmdb_id}{imdb_id}{year}",
        f"movie{tmdb_id}",
        f"movie{imdb_id}",
        f"{tmdb_id}movie",
        f"cinemaos{tmdb_id}",
        f"{tmdb_id}cinemaos",
        f"provider{tmdb_id}",
        f"stream{tmdb_id}",
    ]
    for c in combos:
        candidates.append(hashlib.sha256(c.encode()).hexdigest())
        candidates.append(hashlib.md5(c.encode()).hexdigest())
        candidates.append(hashlib.sha1(c.encode()).hexdigest())
    return candidates


def call_provider_api(tmdb_id, imdb_id, title, year,
                      secret, rk, content_type="movie",
                      season=None, episode=None):
    """Call the provider API with given tokens."""
    params = {
        "type":    content_type,
        "tmdbId":  tmdb_id,
        "imdbId":  imdb_id,
        "t":       title,
        "ry":      year,
        "secret":  secret,
        "_rk":     rk,
    }
    if season:
        params["season"]  = season
    if episode:
        params["episode"] = episode

    url = "https://cinemaos.tech/api/providerv4"
    print(f"\n  [API] GET {url}")
    print(f"  [API] params: {json.dumps(params, indent=4)}")
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        print(f"  [API] HTTP {r.status_code}  size={len(r.content)} bytes")
        return r
    except Exception as e:
        print(f"  [API] FAILED: {e}")
        return None


def extract_stream_from_response(response_text):
    """Extract stream URLs from a provider API response (encrypted or plain)."""
    urls = []
    # Direct m3u8 URLs
    for m in re.findall(r'https?://[^\s"\'<>\\]+\.m3u8[^\s"\'<>\\]*', response_text):
        if m not in urls:
            urls.append(m)
    # Any stream-like URLs
    for m in re.findall(r'https?://[^\s"\'<>\\]+/stream/[^\s"\'<>\\]*', response_text):
        if m not in urls:
            urls.append(m)
    return urls


def extract_keys_from_js(js_text):
    """Extract candidate AES keys and token-generation logic from JS."""
    keys = []

    # 64-char hex strings (256-bit AES keys)
    for m in re.findall(r'["\']([0-9a-fA-F]{64})["\']', js_text):
        if m not in keys:
            keys.append(m)

    # 32-char hex strings (128-bit AES keys)
    for m in re.findall(r'["\']([0-9a-fA-F]{32})["\']', js_text):
        if m not in keys:
            keys.append(m)

    # Base64-encoded 32-byte values
    for m in re.findall(r'["\']([A-Za-z0-9+/]{43}=)["\']', js_text):
        try:
            import base64
            raw = base64.b64decode(m)
            if len(raw) in (16, 24, 32):
                keys.append(raw.hex())
        except Exception:
            pass

    # String literals that look like salts/keys
    for m in re.findall(r'["\']([a-zA-Z0-9_\-]{16,64})["\']', js_text):
        if re.search(r'[0-9]', m) and re.search(r'[a-zA-Z]', m):
            h = hashlib.sha256(m.encode()).hexdigest()
            if h not in keys:
                keys.append(h)

    return keys


def find_token_logic(js_text):
    """Find the secret/_rk generation logic in JS."""
    findings = {}

    # Look for the providerv4 fetch call construction
    prov_match = re.search(
        r'providerv4[^`"\']{0,500}(?:secret|_rk)[^`"\']{0,500}',
        js_text, re.S | re.I
    )
    if prov_match:
        findings["providerv4_call"] = prov_match.group(0)[:600]

    # Look for secret= parameter construction
    secret_match = re.search(
        r'secret["\s]*[:=+][^;,\n]{0,300}',
        js_text, re.I
    )
    if secret_match:
        findings["secret_construction"] = secret_match.group(0)[:300]

    # Look for _rk= parameter construction
    rk_match = re.search(
        r'_rk["\s]*[:=+][^;,\n]{0,300}',
        js_text, re.I
    )
    if rk_match:
        findings["_rk_construction"] = rk_match.group(0)[:300]

    # Look for hash/digest calls near tmdbId
    hash_match = re.search(
        r'(?:sha256|digest|createHash|hmac)[^;]{0,400}(?:tmdb|imdb|secret|provider)',
        js_text, re.I | re.S
    )
    if hash_match:
        findings["hash_near_tmdb"] = hash_match.group(0)[:400]

    # Look for decrypt function
    decrypt_match = re.search(
        r'(?:decrypt|decipher)[^;]{0,400}(?:encrypted|data|key)',
        js_text, re.I | re.S
    )
    if decrypt_match:
        findings["decrypt_logic"] = decrypt_match.group(0)[:400]

    return findings


def step1_fetch_and_analyse_js():
    """Step 1: Download full JS files and extract crypto/token logic."""
    print(f"\n{SEP}")
    print("  STEP 1 — Download full JS chunks and extract crypto logic")
    print(SEP)

    all_keys = []
    all_findings = {}

    for name, url in JS_CHUNKS.items():
        js = fetch_js(name, url)
        if not js:
            continue

        # Save full file
        out = f"c:\\Users\\AC\\Desktop\\Network analyser to find direct pai\\js_full_{name}.js"
        with open(out, "w", encoding="utf-8", errors="replace") as f:
            f.write(js)
        print(f"  [saved] {out}  ({len(js):,} bytes)")

        # Search for patterns
        search_patterns(js, name)

        # Extract keys
        keys = extract_keys_from_js(js)
        if keys:
            print(f"  [keys] Found {len(keys)} candidate key(s) in {name}")
            for k in keys[:5]:
                print(f"    {k[:64]}")
            all_keys.extend(keys)

        # Find token logic
        logic = find_token_logic(js)
        if logic:
            print(f"\n  [TOKEN LOGIC in {name}]:")
            for k, v in logic.items():
                print(f"    [{k}]  {v[:300]}")
            all_findings[name] = logic

    return all_keys, all_findings


def step2_call_live_api():
    """Step 2: Call the provider API with the known tokens from the scan."""
    print(f"\n{SEP}")
    print("  STEP 2 — Call provider API with captured tokens")
    print(SEP)

    # Use the exact tokens from the previous scan
    secret = "d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729"
    rk     = "2549b22d9bf0d91847a2811baac98d0079e02dba592aea94"

    r = call_provider_api(TMDB_ID, IMDB_ID, TITLE, YEAR, secret, rk)
    if r is None:
        return None, None

    try:
        data = r.json()
        print(f"  [API] Response JSON keys: {list(data.keys())}")
        encrypted = data.get("data", {}).get("encrypted", "")
        if encrypted:
            print(f"  [API] Encrypted field length: {len(encrypted)} chars")
            print(f"  [API] First 80 chars: {encrypted[:80]}")
            # Check if it's hex
            if re.match(r'^[0-9a-fA-F]+$', encrypted):
                print(f"  [API] Format: HEX  ({len(encrypted)//2} bytes)")
            else:
                print(f"  [API] Format: non-hex (base64 or other)")
        return data, encrypted
    except Exception as e:
        print(f"  [API] Not JSON: {e}")
        print(f"  [API] Raw: {r.text[:300]}")
        return None, None


def step3_try_decrypt(encrypted_hex, all_keys):
    """Step 3: Try to decrypt the encrypted response."""
    print(f"\n{SEP}")
    print("  STEP 3 — Attempt AES decryption")
    print(SEP)

    if not encrypted_hex:
        print("  [!] No encrypted data to decrypt")
        return None

    # Build key candidates: from JS + from known values
    key_candidates = list(set(all_keys))

    # Add candidates derived from known values
    known_salts = [
        "cinemaos", "CinemaOS", "provider", "stream",
        TMDB_ID, IMDB_ID, TITLE, YEAR,
        f"{TMDB_ID}{IMDB_ID}", f"cinemaos{TMDB_ID}",
        "d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729",
        "2549b22d9bf0d91847a2811baac98d0079e02dba592aea94",
    ]
    for s in known_salts:
        key_candidates.append(hashlib.sha256(s.encode()).hexdigest())
        key_candidates.append(hashlib.md5(s.encode()).hexdigest())

    # Deduplicate
    key_candidates = list(dict.fromkeys(key_candidates))
    print(f"  [decrypt] Testing {len(key_candidates)} key candidates...")

    return try_decrypt_hex(encrypted_hex, key_candidates)


def step4_generate_fresh_tokens():
    """Step 4: Try to generate fresh tokens by reverse-engineering the pattern."""
    print(f"\n{SEP}")
    print("  STEP 4 — Reverse-engineer token generation")
    print(SEP)

    # Known: secret = d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729
    # Known: _rk    = 2549b22d9bf0d91847a2811baac98d0079e02dba592aea94
    # secret is 64 hex chars = SHA-256 output
    # _rk is 48 hex chars = could be SHA-1 (40) padded, or HMAC-SHA-1 (40), or truncated SHA-256

    known_secret = "d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729"
    known_rk     = "2549b22d9bf0d91847a2811baac98d0079e02dba592aea94"

    print(f"  Known secret ({len(known_secret)} chars = {len(known_secret)//2} bytes = SHA-256)")
    print(f"  Known _rk    ({len(known_rk)} chars = {len(known_rk)//2} bytes)")

    # Try to find what input produces the known secret
    test_inputs = [
        TMDB_ID, IMDB_ID, TITLE, YEAR,
        f"{TMDB_ID}{IMDB_ID}", f"{TMDB_ID}{TITLE}", f"{TMDB_ID}{YEAR}",
        f"{IMDB_ID}{TITLE}", f"{IMDB_ID}{YEAR}", f"{TITLE}{YEAR}",
        f"movie{TMDB_ID}", f"movie{IMDB_ID}",
        f"{TMDB_ID}movie", f"{IMDB_ID}movie",
        f"cinemaos{TMDB_ID}", f"{TMDB_ID}cinemaos",
        f"provider{TMDB_ID}", f"stream{TMDB_ID}",
        f"{TMDB_ID}{IMDB_ID}{TITLE}",
        f"{TMDB_ID}{IMDB_ID}{YEAR}",
        f"{TMDB_ID}{IMDB_ID}{TITLE}{YEAR}",
        f"movie{TMDB_ID}{IMDB_ID}",
        f"movie{TMDB_ID}{IMDB_ID}{TITLE}",
        f"movie{TMDB_ID}{IMDB_ID}{YEAR}",
        f"movie{TMDB_ID}{IMDB_ID}{TITLE}{YEAR}",
    ]

    print(f"\n  Testing {len(test_inputs)} input combinations for secret match...")
    for inp in test_inputs:
        h = hashlib.sha256(inp.encode()).hexdigest()
        if h == known_secret:
            print(f"  [★ SECRET MATCH] input='{inp}'  sha256='{h}'")
            return inp
        # Also try with different encodings
        for enc in ["utf-8", "ascii", "latin-1"]:
            try:
                h2 = hashlib.sha256(inp.encode(enc)).hexdigest()
                if h2 == known_secret:
                    print(f"  [★ SECRET MATCH] input='{inp}' enc={enc}")
                    return inp
            except Exception:
                pass

    print("  [secret] No simple combination matched — token uses a server-side salt")
    print(f"  [secret] The salt is embedded in the JS chunks (need full JS analysis)")

    # Try _rk
    print(f"\n  Testing _rk pattern ({len(known_rk)} hex chars)...")
    for inp in test_inputs:
        # SHA-1 = 40 hex, but _rk is 48 — could be HMAC-SHA-1 truncated or other
        h_sha1   = hashlib.sha1(inp.encode()).hexdigest()
        h_sha256 = hashlib.sha256(inp.encode()).hexdigest()[:48]
        h_md5    = hashlib.md5(inp.encode()).hexdigest()
        if h_sha256 == known_rk:
            print(f"  [★ _rk MATCH] input='{inp}'  sha256[:48]='{h_sha256}'")
        if h_sha1 == known_rk[:40]:
            print(f"  [★ _rk MATCH] input='{inp}'  sha1='{h_sha1}'")

    return None


def step5_direct_stream_test():
    """Step 5: Test the known stream URLs directly."""
    print(f"\n{SEP}")
    print("  STEP 5 — Test known stream URLs directly")
    print(SEP)

    stream_urls = [
        "https://storrrrrrm.site/stream/d42f649481170d33/master.m3u8",
        "https://storrrrrrm.site/stream/d42f649481170d33/1080p.m3u8",
        "https://storrrrrrm.site/stream/d42f649481170d33/720p.m3u8",
    ]

    live_streams = []
    for url in stream_urls:
        print(f"\n  [test] {url}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            print(f"  HTTP {r.status_code}  size={len(r.content)}  ct={r.headers.get('Content-Type','')}")
            if r.status_code == 200 and "#EXTM3U" in r.text:
                print(f"  [★ LIVE] Valid M3U8 playlist!")
                print(f"  First 300 chars:\n{r.text[:300]}")
                live_streams.append(url)
            elif r.status_code == 200:
                print(f"  Content: {r.text[:200]}")
            else:
                print(f"  [expired] Stream hash has expired")
        except Exception as e:
            print(f"  [error] {e}")

    return live_streams


def step6_analyse_full_js_for_decrypt(js_texts):
    """Step 6: Deep-scan full JS for the decrypt function and key."""
    print(f"\n{SEP}")
    print("  STEP 6 — Deep scan full JS for decrypt function + key")
    print(SEP)

    combined = "\n".join(js_texts.values())

    # Look for the decrypt call pattern used by cinemaos
    # Pattern: fetch providerv4 → get encrypted → decrypt with key
    decrypt_patterns = [
        # CryptoJS style
        r'CryptoJS\.AES\.decrypt\s*\([^)]{0,300}\)',
        # Web Crypto API style
        r'crypto\.subtle\.decrypt\s*\([^)]{0,300}\)',
        # Custom hex decode + AES
        r'fromHex\s*\([^)]{0,200}\)',
        # Key derivation
        r'(?:key|KEY)\s*=\s*["\'][0-9a-fA-F]{32,64}["\']',
        # IV extraction
        r'(?:iv|IV)\s*=\s*[^;]{0,100}',
        # The encrypted field access
        r'\.encrypted[^;]{0,200}',
        r'\["encrypted"\][^;]{0,200}',
        # Hex to bytes conversion
        r'(?:hexToBytes|hexDecode|fromHex)\s*\([^)]{0,200}\)',
    ]

    print(f"  Scanning {len(combined):,} chars of combined JS...")
    for pat in decrypt_patterns:
        matches = re.findall(pat, combined, re.I | re.S)
        for m in matches[:2]:
            m = m.strip()
            if len(m) > 15:
                print(f"\n  [PATTERN] {pat[:50]}")
                print(f"  MATCH: {m[:400]}")

    # Specifically look for the key used with the encrypted field
    # The pattern is: get response.data.encrypted → decrypt with some key
    key_near_encrypted = re.findall(
        r'(?:encrypted|decrypt)[^;]{0,500}(?:["\'][0-9a-fA-F]{32,64}["\'])',
        combined, re.I | re.S
    )
    if key_near_encrypted:
        print(f"\n  [★ KEY NEAR ENCRYPTED FIELD]:")
        for m in key_near_encrypted[:3]:
            print(f"  {m[:400]}")

    # Extract ALL hex strings of key length from the combined JS
    all_hex_keys = set()
    for length in [32, 48, 64]:
        for m in re.findall(rf'["\']([0-9a-fA-F]{{{length}}})["\']', combined):
            all_hex_keys.add(m)

    print(f"\n  Found {len(all_hex_keys)} unique hex strings of key length:")
    for k in sorted(all_hex_keys)[:20]:
        print(f"    {k}")

    return list(all_hex_keys)


def save_direct_api_client(stream_urls, provider_url, encrypted, decrypted=None):
    """Save a ready-to-use direct API client script."""
    out = "c:\\Users\\AC\\Desktop\\Network analyser to find direct pai\\direct_api_client.py"

    lines = [
        '"""',
        'direct_api_client.py  —  CinemaOS Direct Stream Client',
        '========================================================',
        'Auto-generated by extract_api.py',
        f'Generated: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        '',
        'Usage:',
        '  pip install requests pycryptodome',
        '  python direct_api_client.py',
        '"""',
        '',
        'import requests, re, json, hashlib, time',
        '',
        'HEADERS = {',
        '    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",',
        '    "Referer":    "https://cinemaos.tech/",',
        '    "Origin":     "https://cinemaos.tech",',
        '}',
        '',
        '# ── SUBTITLE API (open, no auth) ─────────────────────────────────────',
        'def get_subtitles(tmdb_id, content_type="movie", season=None, episode=None):',
        '    if content_type == "movie":',
        '        url = f"https://sub.vdrk.site/v1/movie/{tmdb_id}"',
        '    else:',
        '        url = f"https://sub.vdrk.site/v1/tv/{tmdb_id}/{season}/{episode}"',
        '    r = requests.get(url, headers=HEADERS, timeout=10)',
        '    return r.json() if r.status_code == 200 else []',
        '',
    ]

    if stream_urls:
        lines += [
            '# ── KNOWN LIVE STREAM URLS (from previous scan) ─────────────────────',
            '# NOTE: These stream hashes expire — re-run extract_api.py to get fresh ones',
        ]
        for u in stream_urls:
            lines.append(f'# {u}')
        lines += [
            '',
            f'MASTER_M3U8 = "{stream_urls[0]}"',
            '',
            'def get_stream_direct():',
            '    """Fetch the known stream URL directly."""',
            '    r = requests.get(MASTER_M3U8, headers=HEADERS, timeout=15)',
            '    if r.status_code == 200 and "#EXTM3U" in r.text:',
            '        print("Stream is LIVE:")',
            '        print(r.text[:500])',
            '        return r.text',
            '    else:',
            '        print(f"Stream expired (HTTP {r.status_code}) — need fresh tokens")',
            '        return None',
            '',
        ]

    lines += [
        '# ── PROVIDER API (requires fresh secret + _rk tokens) ───────────────',
        '# The tokens are generated by the site JS — use the network analyser',
        '# with v5.0 to capture fresh tokens automatically.',
        '',
        'PROVIDER_API = "https://cinemaos.tech/api/providerv4"',
        '',
        '# Last captured tokens (from scan 2026-05-23):',
        f'LAST_SECRET = "d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729"',
        f'LAST_RK     = "2549b22d9bf0d91847a2811baac98d0079e02dba592aea94"',
        '',
        'def call_provider(tmdb_id, imdb_id, title, year, secret, rk,',
        '                  content_type="movie", season=None, episode=None):',
        '    params = {',
        '        "type":   content_type,',
        '        "tmdbId": tmdb_id,',
        '        "imdbId": imdb_id,',
        '        "t":      title,',
        '        "ry":     year,',
        '        "secret": secret,',
        '        "_rk":    rk,',
        '    }',
        '    if season:  params["season"]  = season',
        '    if episode: params["episode"] = episode',
        '    r = requests.get(PROVIDER_API, params=params, headers=HEADERS, timeout=15)',
        '    print(f"Provider API: HTTP {r.status_code}  {len(r.content)} bytes")',
        '    return r',
        '',
    ]

    if decrypted:
        lines += [
            '# ── DECRYPTED PAYLOAD (from previous scan) ───────────────────────────',
            f'DECRYPTED_PAYLOAD = {repr(decrypted[:2000])}',
            '',
        ]

    lines += [
        '# ── MAIN ─────────────────────────────────────────────────────────────',
        'if __name__ == "__main__":',
        '    tmdb_id = "1318447"',
        '    imdb_id = "tt16431404"',
        '    title   = "Apex"',
        '    year    = "2026"',
        '',
        '    print("=== CinemaOS Direct API Client ===")',
        '    print()',
        '',
        '    # 1. Get subtitles (always works, no auth)',
        '    print("[1] Fetching subtitles...")',
        '    subs = get_subtitles(tmdb_id)',
        '    for s in subs:',
        '        print(f"  Subtitle: {s}")',
        '',
    ]

    if stream_urls:
        lines += [
            '    # 2. Test known stream URL',
            '    print()',
            '    print("[2] Testing known stream URL...")',
            '    get_stream_direct()',
            '',
        ]

    lines += [
        '    # 3. Call provider API with last known tokens',
        '    print()',
        '    print("[3] Calling provider API with last known tokens...")',
        '    print("    (tokens may be expired — use v5.0 analyser for fresh ones)")',
        '    r = call_provider(tmdb_id, imdb_id, title, year, LAST_SECRET, LAST_RK)',
        '    try:',
        '        data = r.json()',
        '        enc = data.get("data", {}).get("encrypted", "")',
        '        if enc:',
        '            print(f"  Encrypted response: {len(enc)} chars")',
        '            print(f"  First 80: {enc[:80]}")',
        '            print()',
        '            print("  To decrypt: run extract_api.py with pycryptodome installed")',
        '    except Exception as e:',
        '        print(f"  Response: {r.text[:300]}")',
    ]

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n  [saved] Direct API client → {out}")
    return out


def main():
    print(f"\n{SEP}")
    print("  CinemaOS Direct API Extractor")
    print(f"  Target: https://cinemaos.tech/player/{TMDB_ID}")
    print(SEP)

    # Step 1: Download and analyse full JS
    all_keys, all_findings = step1_fetch_and_analyse_js()

    # Step 2: Call live provider API
    api_data, encrypted = step2_call_live_api()

    # Step 3: Try to decrypt
    decrypted = None
    if encrypted:
        decrypted = step3_try_decrypt(encrypted, all_keys)

    # Step 4: Reverse-engineer token generation
    step4_generate_fresh_tokens()

    # Step 5: Test known stream URLs
    live_streams = step5_direct_stream_test()

    # Step 6: Deep JS scan for decrypt logic
    js_texts = {}
    for name in JS_CHUNKS:
        path = f"c:\\Users\\AC\\Desktop\\Network analyser to find direct pai\\js_full_{name}.js"
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                js_texts[name] = f.read()
        except Exception:
            pass
    if js_texts:
        extra_keys = step6_analyse_full_js_for_decrypt(js_texts)
        if extra_keys and encrypted and not decrypted:
            print("\n  [retry] Trying extra keys from deep JS scan...")
            decrypted = try_decrypt_hex(encrypted, extra_keys)

    # Save client
    save_direct_api_client(live_streams, PROVIDER_URL, encrypted, decrypted)

    # Final summary
    print(f"\n{SEP}")
    print("  RESULTS SUMMARY")
    print(SEP)
    print(f"  JS chunks downloaded : {len(js_texts)}")
    print(f"  Crypto keys found    : {len(all_keys)}")
    print(f"  Token logic found    : {len(all_findings)} chunks")
    print(f"  API response         : {'encrypted (' + str(len(encrypted)) + ' chars)' if encrypted else 'N/A'}")
    print(f"  Decrypted            : {'YES — ' + str(len(decrypted)) + ' chars' if decrypted else 'NO'}")
    print(f"  Live streams         : {len(live_streams)}")
    if live_streams:
        print(f"\n  ★ LIVE STREAM URLS:")
        for u in live_streams:
            print(f"    {u}")
    if decrypted:
        print(f"\n  ★ DECRYPTED PAYLOAD (first 500 chars):")
        print(f"    {decrypted[:500]}")
        urls = extract_stream_from_response(decrypted)
        if urls:
            print(f"\n  ★ STREAM URLS FROM DECRYPTED DATA:")
            for u in urls:
                print(f"    {u}")
    print(SEP)


if __name__ == "__main__":
    main()
