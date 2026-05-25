"""
MegaPlayer Server
=================
Flask backend that proxies HLS manifests and segments with the correct
Referer / Origin headers so CORS is never an issue in the browser.

Run:  python megaplayer_server.py
Then: http://localhost:6789
"""

import re
import json
import urllib.parse
import webbrowser
import threading
import requests
import urllib3
from flask import Flask, Response, request, send_file, jsonify
import os

urllib3.disable_warnings()

app = Flask(__name__, static_folder=None)
PORT = 6789

# ── Default headers injected into every upstream HLS request ─────────────
DEFAULT_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer":         "https://megaplay.buzz/",
    "Origin":          "https://megaplay.buzz",
    "Accept":          "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Site":  "cross-site",
    "Sec-Fetch-Mode":  "cors",
    "Sec-Fetch-Dest":  "empty",
}

SESSION = requests.Session()
SESSION.verify = False

# ── Helper: rewrite m3u8 so all URLs go through our proxy ────────────────
def rewrite_m3u8(content: str, original_url: str, referer: str, origin: str) -> str:
    base = original_url.rsplit("/", 1)[0] + "/"
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            # Rewrite URI= attributes inside tags
            def replace_uri(m):
                uri = m.group(1)
                abs_uri = urllib.parse.urljoin(base, uri)
                proxied = f"/proxy?url={urllib.parse.quote(abs_uri, safe='')}&ref={urllib.parse.quote(referer, safe='')}&origin={urllib.parse.quote(origin, safe='')}"
                return f'URI="{proxied}"'
            line = re.sub(r'URI="([^"]+)"', replace_uri, line)
            lines.append(line)
        elif stripped and not stripped.startswith("#"):
            # Segment / sub-manifest URL
            abs_url = urllib.parse.urljoin(base, stripped)
            proxied = f"/proxy?url={urllib.parse.quote(abs_url, safe='')}&ref={urllib.parse.quote(referer, safe='')}&origin={urllib.parse.quote(origin, safe='')}"
            lines.append(proxied)
        else:
            lines.append(line)
    return "\n".join(lines)


# ── /proxy  — fetches any URL with spoofed headers ───────────────────────
@app.route("/proxy")
def proxy():
    url     = request.args.get("url", "")
    referer = request.args.get("ref",    DEFAULT_HEADERS["Referer"])
    origin  = request.args.get("origin", DEFAULT_HEADERS["Origin"])

    if not url:
        return Response("Missing url param", 400)

    headers = {**DEFAULT_HEADERS, "Referer": referer, "Origin": origin}

    try:
        upstream = SESSION.get(url, headers=headers, timeout=20, stream=True)
    except Exception as e:
        return Response(f"Proxy error: {e}", 502)

    content_type = upstream.headers.get("Content-Type", "application/octet-stream")

    # If it's an m3u8 manifest, rewrite internal URLs
    if "mpegurl" in content_type.lower() or url.split("?")[0].endswith(".m3u8"):
        body = upstream.content.decode("utf-8", errors="ignore")
        rewritten = rewrite_m3u8(body, url, referer, origin)
        return Response(
            rewritten,
            status=upstream.status_code,
            content_type="application/vnd.apple.mpegurl",
            headers={"Access-Control-Allow-Origin": "*"}
        )

    # For segments / subtitles — stream through
    def generate():
        for chunk in upstream.iter_content(chunk_size=65536):
            if chunk:
                yield chunk

    resp = Response(
        generate(),
        status=upstream.status_code,
        content_type=content_type,
    )
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


# ── /api/extract  — run pure_extractor inline ────────────────────────────
@app.route("/api/extract")
def api_extract():
    page_url = request.args.get("url", "")
    if not page_url:
        return jsonify({"error": "Missing url param"}), 400
    try:
        # Import and run the extractor
        import importlib.util, sys, os
        spec = importlib.util.spec_from_file_location(
            "pure_extractor",
            os.path.join(os.path.dirname(__file__), "pure_extractor.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.extract(page_url)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── / — serve the player HTML ─────────────────────────────────────────────
@app.route("/")
def index():
    return send_file(os.path.join(os.path.dirname(__file__), "megaplayer.html"))


# ── /results  — serve last results.json ──────────────────────────────────
@app.route("/results")
def results():
    path = os.path.join(os.path.dirname(__file__), "results.json")
    if os.path.exists(path):
        return send_file(path, mimetype="application/json")
    return jsonify({}), 404


if __name__ == "__main__":
    def open_browser():
        import time; time.sleep(1.2)
        webbrowser.open(f"http://localhost:{PORT}")
    threading.Thread(target=open_browser, daemon=True).start()
    print(f"\n  ╔══════════════════════════════════════╗")
    print(f"  ║   MegaPlayer  →  http://localhost:{PORT}  ║")
    print(f"  ╚══════════════════════════════════════╝")
    print(f"  Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
