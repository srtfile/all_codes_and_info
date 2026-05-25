"""
Play a dood.watch / dood mirror video locally.

Why this exists
---------------
The CDN that actually serves the mp4 (e.g. c594sp.cloudatacdn.com) requires
the original player page as Referer on every (range) request. A normal
<video src="..."> tag in a normal page cannot set a custom Referer, so the
browser sends its own and the CDN aborts the connection.

This script:
  1. Resolves the embed via dood_extract.extract_dood().
  2. Starts a tiny localhost HTTP server that, for every incoming request,
     fetches the real CDN URL with the correct Referer + User-Agent and
     streams the bytes back. Range requests are forwarded so seeking works.
  3. Opens http://127.0.0.1:<port>/ in your default browser, which loads a
     minimal HTML5 player pointing at /stream on the same origin.

Usage:
    python dood_play.py                              # default test URL
    python dood_play.py https://dood.watch/e/<id>
    python dood_play.py fihq8fpmmvwo                 # bare id is fine too
    python dood_play.py <url> --port 8765 --no-open
"""

from __future__ import annotations

import argparse
import http.server
import socketserver
import sys
import threading
import urllib.parse
import webbrowser
from typing import Optional

import requests

from dood_extract import extract_dood, UA


PLAYER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #000; color: #ddd;
                font-family: system-ui, sans-serif; }}
  header   {{ padding: 8px 14px; background: #111; font-size: 13px;
              border-bottom: 1px solid #222; }}
  header a {{ color: #6cf; text-decoration: none; }}
  video    {{ width: 100%; height: calc(100% - 38px); background: #000; }}
  code     {{ color: #ffd479; }}
</style>
</head>
<body>
<header>
  <strong>{title}</strong>
  &nbsp;|&nbsp; source mirror: <code>{mirror}</code>
  &nbsp;|&nbsp; <a href="/stream" download="dood_{vid}.mp4">download</a>
</header>
<video id="v" src="/stream" controls autoplay playsinline></video>
<script>
  const v = document.getElementById('v');
  v.addEventListener('error', () => {{
    document.body.insertAdjacentHTML('beforeend',
      '<pre style="color:#f66;padding:14px">Playback error. '
      + 'The upstream link may have expired - rerun the script.</pre>');
  }});
</script>
</body>
</html>
"""


class StreamHandler(http.server.BaseHTTPRequestHandler):
    # Filled in by main()
    info: dict = {}
    title: str = "DoodStream"

    # Quieter logs.
    def log_message(self, fmt, *args):  # noqa: N802
        sys.stderr.write("[srv] " + (fmt % args) + "\n")

    # ------------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send_player()
        if path == "/stream":
            return self._proxy_stream()
        self.send_error(404)

    def do_HEAD(self):  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/stream":
            return self._proxy_stream(head=True)
        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            return
        self.send_error(404)

    # ------------------------------------------------------------------
    def _send_player(self) -> None:
        html = PLAYER_HTML.format(
            title=self.title,
            mirror=urllib.parse.urlparse(self.info["player_page"]).netloc,
            vid=self.info["video_id"],
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html)

    def _proxy_stream(self, head: bool = False) -> None:
        upstream = self.info["direct_mp4"]
        headers = {
            "User-Agent": UA,
            "Referer": self.info["player_page"],
            "Accept": "*/*",
            "Accept-Encoding": "identity",  # don't double-compress video
        }
        # Forward Range so the <video> element can seek.
        rng = self.headers.get("Range")
        if rng:
            headers["Range"] = rng

        try:
            method = "HEAD" if head else "GET"
            up = requests.request(
                method, upstream, headers=headers, stream=not head, timeout=30,
                allow_redirects=True,
            )
        except requests.RequestException as e:
            self.send_error(502, f"upstream error: {e}")
            return

        self.send_response(up.status_code)
        passthrough = (
            "content-type", "content-length", "content-range",
            "accept-ranges", "etag", "last-modified", "cache-control",
        )
        for h in passthrough:
            v = up.headers.get(h)
            if v:
                self.send_header(h.title(), v)
        if not up.headers.get("accept-ranges"):
            self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

        if head:
            up.close()
            return

        try:
            for chunk in up.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            # Browser closed the tab / seeked away. Normal.
            pass
        finally:
            up.close()


class _ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _extract_title(player_page_url: str) -> str:
    try:
        r = requests.get(
            player_page_url,
            headers={"User-Agent": UA, "Referer": player_page_url},
            timeout=10,
        )
        import re
        m = re.search(r"<title>([^<]+)</title>", r.text, re.I)
        if m:
            return m.group(1).strip()
    except requests.RequestException:
        pass
    return "DoodStream"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("url", nargs="?", default="https://dood.watch/e/fihq8fpmmvwo")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-open", action="store_true",
                    help="don't auto-open the browser")
    args = ap.parse_args(argv)

    print(f"[*] Resolving {args.url} ...")
    info = extract_dood(args.url)
    p = info["probe"]
    print(f"    mirror : {info['mirror']}")
    print(f"    probe  : status={p['status']} type={p['content_type']} "
          f"len={p['content_length']}")
    if p["ok"] is False:
        print("    WARN: upstream HEAD failed - playback may not work.")

    title = _extract_title(info["player_page"])
    StreamHandler.info = info
    StreamHandler.title = title

    srv = _ThreadingServer((args.host, args.port), StreamHandler)
    local_url = f"http://{args.host}:{args.port}/"
    print(f"[*] Serving at {local_url}")
    print("    /         -> HTML5 player page")
    print("    /stream   -> proxied mp4 (use this in VLC / mpv too)")
    print("    Ctrl+C to stop.")

    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(local_url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Stopping.")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
