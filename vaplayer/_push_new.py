import urllib.request, json, base64

TOKEN = "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"
REPO  = "andruilsyestems-wq/vaplayer-m3u8-extractor"

for fname in ["network_analyser_to-find_api.py"]:
    with open(fname, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/{fname}",
        data=json.dumps({"message": f"add {fname}", "content": content}).encode(),
        headers={"Authorization": f"token {TOKEN}", "Content-Type": "application/json", "User-Agent": "Python"},
        method="PUT",
    )
    try:
        res = urllib.request.urlopen(req)
        print("[OK]", json.loads(res.read())["content"]["html_url"])
    except urllib.error.HTTPError as e:
        print("[FAIL]", e.read().decode()[:200])
