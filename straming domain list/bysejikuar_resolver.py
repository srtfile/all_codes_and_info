"""Resolve direct HLS stream URLs from bysejikuar.com embeds.

pip install curl_cffi cryptography
"""
from __future__ import annotations
import base64, json, secrets, sys
from curl_cffi import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes

EMBED_URL = "https://bysejikuar.com/e/75bxqcxtwg41"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36")


def _b64u_dec(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _b64u_enc(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _decrypt(p: dict) -> dict:
    key = b"".join(_b64u_dec(k) for k in p["key_parts"])
    pt = AESGCM(key).decrypt(_b64u_dec(p["iv"]), _b64u_dec(p["payload"]), None)
    return json.loads(pt)


def _client_block() -> dict:
    return {
        "user_agent": UA, "architecture": "x86", "bitness": "64",
        "platform": "Windows", "platform_version": "10.0.0", "model": "",
        "ua_full_version": "147.0.7727.116",
        "brand_full_versions": [
            {"brand": "Google Chrome", "version": "147.0.7727.116"},
            {"brand": "Not.A/Brand", "version": "8.0.0.0"},
            {"brand": "Chromium", "version": "147.0.7727.116"},
        ],
        "pixel_ratio": 1, "screen_width": 1920, "screen_height": 1080,
        "color_depth": 24, "languages": ["en-US", "en"], "timezone": "UTC",
        "hardware_concurrency": 8, "device_memory": 8, "touch_points": 0,
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics, D3D11)",
        "canvas_hash": _b64u_enc(secrets.token_bytes(32)),
        "audio_hash": _b64u_enc(secrets.token_bytes(32)),
        "pointer_type": "fine,hover",
        "extra": {"vendor": "Google Inc.",
                  "appVersion": UA.replace("Mozilla/", "")},
    }


def resolve(embed_url: str = EMBED_URL) -> dict:
    vid = embed_url.rstrip("/").rsplit("/", 1)[-1]
    s = requests.Session(impersonate="chrome124")
    s.headers.update({"user-agent": UA, "accept-language": "en-US,en;q=0.9", "dnt": "1"})

    details = s.get(
        f"https://bysejikuar.com/api/videos/{vid}/embed/details",
        headers={"accept": "application/json", "referer": embed_url}, timeout=20,
    ).json()
    frame = details["embed_frame_url"]
    origin = "https://" + frame.split("/", 3)[2]

    s.get(frame, headers={"referer": "https://bysejikuar.com/"}, timeout=30).raise_for_status()

    viewer_id, device_id = secrets.token_hex(16), secrets.token_hex(16)
    sk = ec.generate_private_key(ec.SECP256R1())
    pn = sk.public_key().public_numbers()
    jwk = {"crv": "P-256", "ext": True, "key_ops": ["verify"], "kty": "EC",
           "x": _b64u_enc(pn.x.to_bytes(32, "big")),
           "y": _b64u_enc(pn.y.to_bytes(32, "big"))}

    api = {"accept": "*/*", "content-type": "application/json",
           "origin": origin, "referer": frame}

    ch = s.post(f"{origin}/api/videos/access/challenge", headers=api,
                json={"viewer_id": viewer_id, "device_id": device_id}, timeout=20).json()

    der = sk.sign(ch["nonce"].encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, sv = decode_dss_signature(der)
    sig = _b64u_enc(r.to_bytes(32, "big") + sv.to_bytes(32, "big"))

    att = s.post(f"{origin}/api/videos/access/attest", headers=api, json={
        "viewer_id": viewer_id, "device_id": device_id,
        "challenge_id": ch["challenge_id"], "nonce": ch["nonce"],
        "signature": sig, "public_key": jwk, "client": _client_block(),
        "storage": {"local_storage": viewer_id,
                    "indexed_db": f"{viewer_id}:{device_id}",
                    "cache_storage": f"{viewer_id}:{device_id}"},
        "attributes": {"entropy": "high"},
    }, timeout=20).json()

    pb = s.post(f"{origin}/api/videos/{vid}/embed/playback",
                headers={**api, "x-embed-parent": embed_url},
                json={"fingerprint": {"token": att["token"], "viewer_id": viewer_id,
                                       "device_id": device_id,
                                       "confidence": float(att.get("confidence", 0.9))}},
                timeout=20).json()["playback"]

    data = _decrypt(pb)
    return {
        "video_id": vid,
        "title": details.get("title"),
        "poster_url": data.get("poster_url") or details.get("poster_url"),
        "sources": [{"label": x.get("label"), "quality": x.get("quality"),
                     "height": x.get("height"), "bitrate_kbps": x.get("bitrate_kbps"),
                     "size_bytes": x.get("size_bytes"),
                     "mime_type": x.get("mime_type"), "url": x["url"]}
                    for x in data.get("sources", [])],
        "tracks": data.get("tracks", []),
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else EMBED_URL
    out = resolve(target)
    print(json.dumps(out, indent=2))
    for src in out["sources"]:
        print(f"\n[{src['label']}] {src['url']}")
