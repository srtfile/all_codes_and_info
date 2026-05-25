#!/usr/bin/env python3
"""
mitm_analyze.py  –  Analyze captured mitm_toolkit.jsonl output
================================================================
Usage:
  python mitm_analyze.py [--file mitm_captured.jsonl] [--mode MODE]

Modes:
  summary    (default)  high-level stats
  apis                  unique endpoints discovered
  auth                  all auth headers / tokens found
  signed                signed / CDN URLs
  ws                    WebSocket frame dump
  replay-list           print curl commands to replay each request
  export-postman        export a Postman v2.1 collection JSON
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


# ─── Loader ──────────────────────────────────────────────────────────────────

def load_records(path: Path):
    records = []
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"  [WARN] line {i}: {exc}", file=sys.stderr)
    return records


# ─── Modes ───────────────────────────────────────────────────────────────────

def mode_summary(records):
    types   = Counter(r["type"] for r in records)
    methods = Counter(r["method"] for r in records if r["type"] == "request")
    hosts   = Counter(r["host"]   for r in records if r["type"] == "request")
    statuses = Counter(r["status"] for r in records if r["type"] == "response")
    auth_req = [r for r in records if r["type"] == "request" and r.get("auth_found")]
    signed   = [r for r in records if r["type"] == "request" and r.get("signed_url")]

    print("=" * 60)
    print("  CAPTURE SUMMARY")
    print("=" * 60)
    print(f"  Total records    : {len(records)}")
    for t, n in types.most_common():
        print(f"    {t:<18} {n}")
    print()
    print("  HTTP Methods:")
    for m, n in methods.most_common():
        print(f"    {m:<10} {n}")
    print()
    print("  Top Hosts:")
    for h, n in hosts.most_common(10):
        print(f"    {h:<45} {n}")
    print()
    print("  Response Status Codes:")
    for s, n in sorted(statuses.items()):
        print(f"    {s}  {n}")
    print()
    print(f"  Auth headers found in   : {len(auth_req)} requests")
    print(f"  Signed/CDN URLs         : {len(signed)} requests")
    print("=" * 60)


def mode_apis(records):
    seen = {}
    for r in records:
        if r["type"] != "request":
            continue
        parsed = urlparse(r["url"])
        key = (r["method"], parsed.scheme + "://" + r["host"] + parsed.path)
        if key not in seen:
            seen[key] = {
                "method": r["method"],
                "base":   key[1],
                "count":  0,
                "auth":   bool(r.get("auth_found")),
                "signed": r.get("signed_url", False),
            }
        seen[key]["count"] += 1

    print(f"\n  UNIQUE API ENDPOINTS ({len(seen)} total)\n")
    print(f"  {'#':>5}  {'AUTH':5}  {'SIGN':5}  METHOD    ENDPOINT")
    print("  " + "-" * 80)
    for ep in sorted(seen.values(), key=lambda x: -x["count"]):
        print(
            f"  {ep['count']:>5}  "
            f"{'✓' if ep['auth'] else '·':5}  "
            f"{'✓' if ep['signed'] else '·':5}  "
            f"{ep['method']:<9} {ep['base']}"
        )


def mode_auth(records):
    print("\n  AUTH HEADERS / TOKENS DISCOVERED\n")
    printed = set()
    for r in records:
        if r["type"] != "request" or not r.get("auth_found"):
            continue
        for header, value in r["auth_found"].items():
            key = (header.lower(), value[:80])
            if key in printed:
                continue
            printed.add(key)
            host = r.get("host", "?")
            print(f"  Host   : {host}")
            print(f"  Header : {header}")
            print(f"  Value  : {value[:120]}{'…' if len(value) > 120 else ''}")
            print()


def mode_signed(records):
    print("\n  SIGNED / PRESIGNED / CDN URLS\n")
    for r in records:
        if r["type"] == "request" and r.get("signed_url"):
            print(f"  [{r['method']}] {r['url'][:200]}")
    print()


def mode_ws(records):
    print("\n  WEBSOCKET FRAMES\n")
    for r in records:
        if r["type"] != "ws_frame":
            continue
        direction = r.get("direction", "?")
        content   = str(r.get("content", ""))
        print(f"  [{r['ts']}] {direction}")
        print(f"  {content[:300]}")
        print()


def mode_replay_list(records):
    print("\n  CURL REPLAY COMMANDS\n")
    for r in records:
        if r["type"] != "request":
            continue
        header_flags = " ".join(
            f"-H '{k}: {v}'"
            for k, v in r.get("headers", {}).items()
            if k.lower() not in ("content-length", "transfer-encoding", "host")
        )
        body_flag = ""
        if r.get("body_raw"):
            escaped = r["body_raw"].replace("'", "'\\''")
            body_flag = f" --data '{escaped[:500]}'"
        print(f"curl -X {r['method']} '{r['url']}' {header_flags}{body_flag}")
        print()


def mode_resources(records):
    """Break down all captured traffic by resource type."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in records:
        if r["type"] not in ("request", "response"):
            continue
        rtype = r.get("resource_type", "other")
        buckets[rtype].append(r)

    type_order = ["xhr/api", "html", "js", "css", "image", "media", "font", "binary", "text", "other"]
    print("\n  ALL CAPTURED RESOURCES BY TYPE\n")
    for rtype in type_order + [k for k in buckets if k not in type_order]:
        items = buckets.get(rtype, [])
        if not items:
            continue
        print(f"\n  ── {rtype.upper()} ({len(items)}) " + "─" * 40)
        seen_urls = set()
        for r in items:
            url = r.get("url", "")
            method = r.get("method", r.get("type", ""))
            status = r.get("status", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            status_str = f"  [{status}]" if status else ""
            print(f"  {method:<8}{status_str:<8} {url[:120]}")
    print()


def mode_export_postman(records, outfile="postman_collection.json"):
    items = []
    seen  = set()
    for r in records:
        if r["type"] != "request":
            continue
        key = (r["method"], r["url"])
        if key in seen:
            continue
        seen.add(key)
        parsed = urlparse(r["url"])
        item = {
            "name": f"{r['method']} {parsed.path or '/'}",
            "request": {
                "method": r["method"],
                "header": [
                    {"key": k, "value": v}
                    for k, v in r.get("headers", {}).items()
                    if k.lower() not in ("content-length", "transfer-encoding")
                ],
                "url": {
                    "raw":      r["url"],
                    "protocol": parsed.scheme,
                    "host":     parsed.netloc.split("."),
                    "path":     [p for p in parsed.path.split("/") if p],
                },
            },
        }
        if r.get("body_raw"):
            item["request"]["body"] = {
                "mode": "raw",
                "raw":  r["body_raw"],
            }
        items.append(item)

    collection = {
        "info": {
            "name":        "mitmproxy Captured APIs",
            "description": "Auto-generated by mitm_analyze.py",
            "schema":      "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": items,
    }
    Path(outfile).write_text(json.dumps(collection, indent=2, ensure_ascii=False))
    print(f"\n  Postman collection written to: {outfile}")
    print(f"  Items: {len(items)}\n")


# ─── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file",  default="mitm_captured.jsonl", help="JSONL capture file")
    parser.add_argument("--mode",  default="summary",
                        choices=["summary", "apis", "auth", "signed", "ws",
                                 "replay-list", "export-postman", "resources"])
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    records = load_records(path)

    dispatch = {
        "summary":        mode_summary,
        "apis":           mode_apis,
        "auth":           mode_auth,
        "signed":         mode_signed,
        "ws":             mode_ws,
        "replay-list":    mode_replay_list,
        "export-postman": lambda r: mode_export_postman(r),
        "resources":      mode_resources,
    }
    dispatch[args.mode](records)


if __name__ == "__main__":
    main()
