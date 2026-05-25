"""
crack_secret.py  —  Crack the exact generateContentHash algorithm
From JS: r = HMAC-SHA256(HMAC-SHA256(payload, primary), secondary)
         where primary/secondary are the hex strings used as keys
"""
import hashlib, hmac, requests

PRIMARY   = "a7f3b9c2e8d4f1a6b5c9e2d7f4a8b3c6e1d9f7a4b2c8e5d3f9a6b4c1e7d2f8a5"
SECONDARY = "d3f8a5b2c9e6d1f7a4b8c5e2d9f3a6b1c7e4d8f2a9b5c3e7d4f1a8b6c2e9d5f3"
RK        = "2549b22d9bf0d91847a2811baac98d0079e02dba592aea94"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Referer": "https://cinemaos.tech/",
}

# JS code (exact):
# let r = n().createHmac("sha256", t).update(s).digest("hex")
# return n().createHmac("sha256", a).update(r).digest("hex")
# where t = primary (string), a = secondary (string), s = payload (string)
# n() = require('crypto') — Node.js crypto
# createHmac("sha256", key) where key is a STRING (the hex string itself, not bytes)

payload = "tmdbId:1318447|imdbId:tt16431404"

print(f"Payload: {payload}")
print()

# The JS uses the hex strings directly as HMAC keys (as strings, not decoded to bytes)
# Node.js crypto.createHmac("sha256", "a7f3b9...") uses the string as-is

# Step 1: inner = HMAC-SHA256(payload, primary_as_string)
inner = hmac.new(PRIMARY.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
print(f"inner HMAC (primary str key): {inner}")

# Step 2: secret = HMAC-SHA256(inner, secondary_as_string)
secret = hmac.new(SECONDARY.encode('utf-8'), inner.encode('utf-8'), hashlib.sha256).hexdigest()
print(f"secret (double HMAC):         {secret}")
print()

# Test it
print(f"Testing secret={secret[:32]}... _rk={RK[:16]}...")
r = requests.get(
    "https://cinemaos.tech/api/providerv4",
    params={
        "type": "movie", "tmdbId": "1318447", "imdbId": "tt16431404",
        "t": "Apex", "ry": "2026", "secret": secret, "_rk": RK
    },
    headers=HEADERS, timeout=15
)
print(f"HTTP {r.status_code}  {len(r.content)} bytes")
print(f"Response: {r.text[:200]}")

if r.status_code == 200 and "error" not in r.text:
    print("\n[★★★ SUCCESS — Secret generation cracked! ★★★]")
    try:
        data = r.json()
        print(f"Keys: {list(data.keys())}")
        if "data" in data:
            d = data["data"]
            if isinstance(d, dict):
                print(f"data keys: {list(d.keys())}")
                print(f"encrypted: {str(d.get('encrypted',''))[:80]}...")
                print(f"cin: {d.get('cin','')}")
                print(f"mao: {d.get('mao','')}")
                print(f"salt: {d.get('salt','')}")
                print(f"version: {d.get('version','')}")
    except Exception as e:
        print(f"Parse error: {e}")
