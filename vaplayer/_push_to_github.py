"""Push files to GitHub using the REST API — no git install needed."""
import urllib.request, json, base64

TOKEN = "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"
REPO  = "andruilsyestems-wq/vaplayer-m3u8-extractor"
FILES = [
    "vidlayer_network_analyser.py",
    "direct_testing.py",
]

def api(path, data):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"token {TOKEN}",
            "Content-Type":  "application/json",
            "User-Agent":    "Python",
        },
        method="PUT",
    )
    try:
        res = urllib.request.urlopen(req)
        return json.loads(res.read()), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()

for fname in FILES:
    with open(fname, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    result, err = api(
        f"/repos/{REPO}/contents/{fname}",
        {
            "message": f"add {fname}",
            "content": content,
        }
    )
    if err:
        print(f"[FAIL] {fname}: {err[:200]}")
    else:
        print(f"[OK]   {fname} → {result['content']['html_url']}")
