import logging
import random
import re
import time
import warnings
from urllib.parse import urljoin, urlparse

from urllib3.exceptions import InsecureRequestWarning

try:
    from curl_cffi.requests import Session as CffiSession
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

try:
    import niquests
    HAS_NIQUESTS = True
except ImportError:
    HAS_NIQUESTS = False

try:
    from ...config import DEFAULT_USER_AGENT
except ImportError:
    from aniworld.config import DEFAULT_USER_AGENT

warnings.simplefilter("ignore", InsecureRequestWarning)

# -----------------------------
# Constants
# -----------------------------
RANDOM_STRING_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
PASS_MD5_PATTERN = r"\$\.get\('([^']*\/pass_md5\/[^']*)'"
TOKEN_PATTERN = r"token=([a-zA-Z0-9]+)"

# curl_cffi browser impersonation target — mimics Chrome 124 TLS fingerprint
IMPERSONATE = "chrome124"


# -----------------------------
# Helper Functions
# -----------------------------
def _get_base_url(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _make_headers(referer, base_url, xhr=False):
    h = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": referer,
        "Origin": base_url,
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
    }
    if xhr:
        h["Accept"] = "*/*"
        h["X-Requested-With"] = "XMLHttpRequest"
        h["Sec-Fetch-Dest"] = "empty"
        h["Sec-Fetch-Mode"] = "cors"
        h["Sec-Fetch-Site"] = "same-origin"
    else:
        h["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        h["Upgrade-Insecure-Requests"] = "1"
        h["Sec-Fetch-Dest"] = "document"
        h["Sec-Fetch-Mode"] = "navigate"
        h["Sec-Fetch-Site"] = "same-origin"
    return h


def _extract_regex(pattern, content, name, url):
    match = re.search(pattern, content)
    if not match:
        raise ValueError(f"{name} not found in {url}")
    return match.group(1)


def _generate_random_string(length=10):
    return "".join(random.choices(RANDOM_STRING_CHARS, k=length))


def _create_session():
    """
    Create a session that bypasses Cloudflare.
    Prefers curl_cffi (real Chrome TLS fingerprint) over niquests.
    curl_cffi install: pip install curl_cffi
    """
    if HAS_CURL_CFFI:
        logging.info("Using curl_cffi session (Cloudflare bypass enabled)")
        session = CffiSession(impersonate=IMPERSONATE, verify=False)
        return session, True
    elif HAS_NIQUESTS:
        logging.warning(
            "curl_cffi not found — falling back to niquests. "
            "Install curl_cffi for Cloudflare bypass: pip install curl_cffi"
        )
        session = niquests.Session()
        session.verify = False
        return session, False
    else:
        raise ImportError("Neither curl_cffi nor niquests is installed.")


def _get(session, url, headers, **kwargs):
    """Unified get() that works for both curl_cffi and niquests sessions."""
    return session.get(url, headers=headers, allow_redirects=True, **kwargs)


# -----------------------------
# Main Doodstream Function
# -----------------------------
def get_direct_link_from_doodstream(embed_url):
    """Extract the direct video link from a Doodstream embed URL."""
    if not embed_url:
        raise ValueError("Embed URL cannot be empty")

    logging.info(f"Extracting Doodstream direct link from: {embed_url}")

    session, using_cffi = _create_session()

    # ----------------------------------------------------------------
    # Step 1: resolve the full redirect chain to find the real domain
    # ----------------------------------------------------------------
    resp = _get(session, embed_url, headers={"User-Agent": DEFAULT_USER_AGENT})
    final_embed_url = str(resp.url)
    final_base = _get_base_url(final_embed_url)
    logging.info(f"Resolved final URL: {final_embed_url}")

    # ----------------------------------------------------------------
    # Step 2: homepage visit on the final domain (cookie warm-up)
    # ----------------------------------------------------------------
    try:
        _get(session, f"{final_base}/", headers=_make_headers(f"{final_base}/", final_base))
    except Exception:
        pass

    # ----------------------------------------------------------------
    # Step 3: fetch the embed page with proper browser headers
    # ----------------------------------------------------------------
    embed_resp = _get(
        session,
        final_embed_url,
        headers=_make_headers(f"{final_base}/", final_base),
    )
    embed_resp.raise_for_status()
    embed_html = embed_resp.text

    # ----------------------------------------------------------------
    # Step 4: extract pass_md5 URL and token
    # ----------------------------------------------------------------
    pass_md5_path = _extract_regex(PASS_MD5_PATTERN, embed_html, "pass_md5 URL", final_embed_url)
    pass_md5_url = pass_md5_path if pass_md5_path.startswith("http") else urljoin(final_base, pass_md5_path)
    token = _extract_regex(TOKEN_PATTERN, embed_html, "token", final_embed_url)
    logging.info(f"pass_md5: {pass_md5_url} | token: {token}")

    # ----------------------------------------------------------------
    # Step 5: XHR-style request to pass_md5 endpoint
    # ----------------------------------------------------------------
    md5_resp = _get(
        session,
        pass_md5_url,
        headers=_make_headers(final_embed_url, final_base, xhr=True),
    )
    md5_resp.raise_for_status()
    video_base_url = md5_resp.text.strip()

    if not video_base_url:
        raise ValueError(f"Empty video base URL from {pass_md5_url}")

    # ----------------------------------------------------------------
    # Step 6: build direct link
    # expiry in milliseconds (13 digits) to match what Doodstream expects
    # ----------------------------------------------------------------
    expiry = int(time.time() * 1000)
    direct_link = f"{video_base_url}{_generate_random_string(10)}?token={token}&expiry={expiry}"

    logging.info("Successfully extracted Doodstream direct link")
    return direct_link, final_base


def get_preview_image_link_from_doodstream(embed_url):
    raise NotImplementedError("Preview image extraction is not implemented yet.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if not HAS_CURL_CFFI:
        print("⚠️  Warning: curl_cffi not installed. Cloudflare-protected mirrors will fail.")
        print("   Fix: pip install curl_cffi\n")

    link = input("Enter Doodstream Link: ").strip()
    if not link:
        print("Error: No link provided")
        exit(1)

    try:
        print("=" * 25)
        direct_link, final_base = get_direct_link_from_doodstream(link)
        print("Direct link:", direct_link)
        print("=" * 25)

        try:
            preview_img = get_preview_image_link_from_doodstream(link)
            print("Preview image:", preview_img)
        except NotImplementedError:
            print("Preview image: Not implemented")
        print("=" * 25)

        print(f"mpv --http-header-fields='Referer: {final_base}/' '{direct_link}'")
        print("=" * 25)

    except Exception as e:
        logging.exception("Extraction failed")
        print("Error:", e)
        exit(1)