import urllib.request, json, base64

TOKEN = "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"
REPO  = "andruilsyestems-wq/vaplayer-m3u8-extractor"

with open("README.md", "rb") as f:
    content = base64.b64encode(f.read()).decode()

req = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/contents/README.md",
    data=json.dumps({"message": "add README.md", "content": content}).encode(),
    headers={
        "Authorization": f"token {TOKEN}",
        "Content-Type":  "application/json",
        "User-Agent":    "Python",
    },
    method="PUT",
)
try:
    res = urllib.request.urlopen(req)
    data = json.loads(res.read())
    print("[OK] README.md →", data["content"]["html_url"])
except urllib.error.HTTPError as e:
    print("[FAIL]", e.read().decode()[:300])
