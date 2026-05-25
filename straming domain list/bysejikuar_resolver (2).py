"""
Resolver for bysejikuar.com / rupertisdivingintoocean.com video embeds.

Pipeline (mirrors the captured browser flow):

  bysejikuar.com/e/{ID}                    -- embed page (HTML, JS resolves the real provider)
  bysejikuar.com/api/videos/{ID}/embed/details
        --> { embed_frame_url: "https://<provider>/<rand>/{ID}" }   (public, no auth)
  GET <embed_frame_url>                    -- warm session + cf_clearance
  POST <provider>/api/videos/access/challenge   { viewer_id, device_id }
        --> { challenge_id, nonce }
  POST <provider>/api/videos/access/attest      { ..., signature, public_key, client, ... }
        --> { token: "<JWT>" }
  POST <provider>/api/videos/{ID}/embed/playback { fingerprint:{ token, viewer_id, device_id, confidence } }
        --> AES-256-GCM encrypted JSON containing HLS sources

Decryption: key = b64url(key_parts[0]) + b64url(key_parts[1])  (16 + 16 = 32 bytes)
            iv  = b64url(iv)  (12 bytes)
            cipher = b64url(payload)   (last 16 bytes are the GCM tag)

Requires:  pip install curl_cffi cryptography
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import sys
from typing import Any

from curl_cffi import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes


# Hardcoded target embed URL
EMBED_URL = "https://bysejikuar.com/e/75bxqcxtwg41"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)


# ---------- helpers ----------

def b64url_decode(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def rand_hex(n: int) -> str:
    return secrets.token_hex(n)


# ---------- crypto ----------

def make_signing_key():
    """Generate a P-256 keypair and return (private_key, jwk_public)."""
    sk = ec.generate_private_key(ec.SECP256R1())
    nums = sk.public_key().public_numbers()
    x = nums.x.to_bytes(32, "big")
    y = nums.y.to_bytes(32, "big")
    jwk = {
        "crv": "P-256",
        "ext": True,
        "key_ops": ["verify"],
        "kty": "EC",
        "x": b64url_encode(x),
        "y": b64url_encode(y),
    }
    return sk, jwk


def sign_nonce(sk, nonce_b64url: str) -> str:
    """ECDSA-P256-SHA256 signature in raw r||s (64 bytes), base64url-encoded.

    The browser feeds the *raw bytes* of the base64url nonce string (UTF-8) to
    SubtleCrypto.sign, which is what we replicate here.
    """
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    der = sk.sign(nonce_b64url.encode("ascii"), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return b64url_encode(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def decrypt_playback(playback: dict) -> dict:
    key = b"".join(b64url_decode(p) for p in playback["key_parts"])
    iv = b64url_decode(playback["iv"])
    ct = b64url_decode(playback["payload"])
    plain = AESGCM(key).decrypt(iv, ct, None)
    return json.loads(plain)


# ---------- fingerprint payload ----------

def build_client_block() -> dict:
    return {
        "user_agent": UA,
        "architecture": "x86",
        "bitness": "64",
        "platform": "Windows",
        "platform_version": "10.0.0",
        "model": "",
        "ua_full_version": "147.0.7727.116",
        "brand_full_versions": [
            {"brand": "Google Chrome", "version": "147.0.7727.116"},
            {"brand": "Not.A/Brand", "version": "8.0.0.0"},
            {"brand": "Chromium", "version": "147.0.7727.116"},
        ],
        "pixel_ratio": 1,
        "screen_width": 1920,
        "screen_height": 1080,
        "color_depth": 24,
        "languages": ["en-US", "en"],
        "timezone": "UTC",
        "hardware_concurrency": 8,
        "device_memory": 8,
        "touch_points": 0,
        "webgl_vendor": "Google Inc. (Intel)",
        "webgl_renderer": "ANGLE (Intel, Intel(R) UHD Graphics, D3D11)",
        "canvas_hash": b64url_encode(secrets.token_bytes(32)),
        "audio_hash": b64url_encode(secrets.token_bytes(32)),
        "pointer_type": "fine,hover",
        "extra": {
            "vendor": "Google Inc.",
            "appVersion": UA.replace("Mozilla/", ""),
        },
    }


# ---------- main resolver ----------

class BysejikuarResolver:
    def __init__(self, embed_url: str):
        # Accept either /e/{ID} embed URL or just the ID
        self.embed_url = embed_url
        self.video_id = embed_url.rstrip("/").rsplit("/", 1)[-1]

        # curl_cffi session with Chrome 124 TLS fingerprint -> bypasses CF JS-less checks
        self.s = requests.Session(impersonate="chrome124")
        self.s.headers.update({
            "user-agent": UA,
            "accept-language": "en-US,en;q=0.9",
            "dnt": "1",
        })

        self.viewer_id = rand_hex(16)
        self.device_id = rand_hex(16)
        self.sk, self.jwk = make_signing_key()

    # ---- step 1: resolve actual provider ----
    def resolve_provider(self) -> str:
        r = self.s.get(
            f"https://bysejikuar.com/api/videos/{self.video_id}/embed/details",
            headers={"accept": "application/json", "referer": f"https://bysejikuar.com/e/{self.video_id}"},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()
        frame = data.get("embed_frame_url")
        if not frame:
            raise RuntimeError(f"embed_frame_url missing in details: {data}")
        return frame  # e.g. https://rupertisdivingintoocean.com/qvuv/{ID}

    # ---- step 2: warm the session ----
    def warm(self, frame_url: str) -> tuple[str, str]:
        r = self.s.get(frame_url, headers={"referer": "https://bysejikuar.com/"}, timeout=30)
        r.raise_for_status()
        # provider origin & this exact frame URL are used as referer for API calls
        origin = "https://" + frame_url.split("/", 3)[2]
        return origin, frame_url

    # ---- step 3+4: challenge + attest ----
    def attest(self, origin: str, referer: str) -> tuple[str, float]:
        api_headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": origin,
            "referer": referer,
        }
        r = self.s.post(
            f"{origin}/api/videos/access/challenge",
            headers=api_headers,
            json={"viewer_id": self.viewer_id, "device_id": self.device_id},
            timeout=20,
        )
        r.raise_for_status()
        ch = r.json()
        nonce = ch["nonce"]
        challenge_id = ch["challenge_id"]

        signature = sign_nonce(self.sk, nonce)

        attest_body = {
            "viewer_id": self.viewer_id,
            "device_id": self.device_id,
            "challenge_id": challenge_id,
            "nonce": nonce,
            "signature": signature,
            "public_key": self.jwk,
            "client": build_client_block(),
            "storage": {
                "local_storage": self.viewer_id,
                "indexed_db": f"{self.viewer_id}:{self.device_id}",
                "cache_storage": f"{self.viewer_id}:{self.device_id}",
            },
            "attributes": {"entropy": "high"},
        }
        r = self.s.post(
            f"{origin}/api/videos/access/attest",
            headers=api_headers,
            json=attest_body,
            timeout=20,
        )
        r.raise_for_status()
        att = r.json()
        return att["token"], float(att.get("confidence", 0.9))

    # ---- step 5: playback ----
    def playback(self, origin: str, referer: str, token: str, confidence: float) -> dict:
        api_headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": origin,
            "referer": referer,
            "x-embed-parent": f"https://bysejikuar.com/e/{self.video_id}",
        }
        body = {
            "fingerprint": {
                "token": token,
                "viewer_id": self.viewer_id,
                "device_id": self.device_id,
                "confidence": confidence,
            }
        }
        r = self.s.post(
            f"{origin}/api/videos/{self.video_id}/embed/playback",
            headers=api_headers,
            json=body,
            timeout=20,
        )
        r.raise_for_status()
        return r.json()["playback"]

    # ---- orchestrate ----
    def resolve(self) -> dict:
        frame = self.resolve_provider()
        origin, referer = self.warm(frame)
        token, conf = self.attest(origin, referer)
        playback = self.playback(origin, referer, token, conf)
        decrypted = decrypt_playback(playback)
        return {
            "video_id": self.video_id,
            "provider": origin,
            "sources": decrypted.get("sources", []),
            "tracks": decrypted.get("tracks", []),
            "poster_url": decrypted.get("poster_url"),
        }


def main(argv: list[str]) -> int:
    # Use CLI arg if provided, otherwise the hardcoded EMBED_URL
    target = argv[1] if len(argv) > 1 else EMBED_URL
    r = BysejikuarResolver(target)
    out = r.resolve()
    print(json.dumps(out, indent=2))
    if out["sources"]:
        print("\nDirect stream URL:")
        print(out["sources"][0]["url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
