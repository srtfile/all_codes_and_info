#!/usr/bin/env python3
"""Verify m3u8 extraction for streamwish.to → playnixes.com."""
import re, requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def _to_base(n, base):
    if n == 0: return "0"
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = []
    while n: out.append(chars[n % base]); n //= base
    return "".join(reversed(out))


def unpack(packed):
    m = re.search(
        r"}\s*\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:[^'\\]|\\.)*)'\s*\.split\(",
        packed, re.DOTALL,
    )
    payload = m.group(1).replace("\\'", "'")
    base = int(m.group(2))
    keys = m.group(4).split("|")
    lookup = {_to_base(i, base): w for i, w in enumerate(keys) if w}
    return re.sub(r'\b\w+\b', lambda mo: lookup.get(mo.group(0), mo.group(0)), payload)


s = requests.Session()
s.headers.update({"User-Agent": UA})

# Hit playnixes (the actual host) with streamwish as referer
r = s.get(
    "https://playnixes.com/e/6kwa9hp2pvok",
    headers={"Referer": "https://streamwish.to/"},
)
print(f"playnixes status={r.status_code}")

packed = re.search(
    r"(eval\(function\(p,a,c,k,e,d\)\{.*?\.split\('\|'\)[^)]*\)\))",
    r.text, re.DOTALL,
).group(1)

decoded = unpack(packed)
print(f"\nDecoded jwplayer config (first 800 chars):")
print(decoded[:800])

# Find every URL of interest
m3u8 = re.findall(r'https?://[^\s"\']+\.(?:m3u8|txt)\??[^\s"\']*', decoded)
mp4  = re.findall(r'https?://[^\s"\']+\.mp4[^\s"\']*', decoded)
print(f"\nm3u8/txt URLs found: {m3u8}")
print(f"mp4 URLs found: {mp4}")

# Test the URL with proper CDN headers
if m3u8:
    url = m3u8[0]
    print(f"\nTesting CDN access: {url[:90]}...")
    r2 = s.get(url, headers={
        "Origin":  "https://playnixes.com",
        "Referer": "https://playnixes.com/",
    })
    print(f"CDN status: {r2.status_code}, content-type: {r2.headers.get('Content-Type')}")
    print(f"First 400 bytes:\n{r2.text[:400]}")
