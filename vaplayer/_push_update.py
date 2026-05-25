import urllib.request, json, base64

TOKEN = "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"
REPO  = "andruilsyestems-wq/vaplayer-m3u8-extractor"
FNAME = "network_analyser_to-find_api.py"

# get current SHA (needed to update existing file)
req = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/contents/{FNAME}",
    headers={"Authorization": f"token {TOKEN}", "User-Agent": "Python"},
)
sha = json.loads(urllib.request.urlopen(req).read())["sha"]

with open(FNAME, "rb") as f:
    content = base64.b64encode(f.read()).decode()

req2 = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/contents/{FNAME}",
    data=json.dumps({"message": "add page_source.txt saving", "content": content, "sha": sha}).encode(),
    headers={"Authorization": f"token {TOKEN}", "Content-Type": "application/json", "User-Agent": "Python"},
    method="PUT",
)
try:
    res = urllib.request.urlopen(req2)
    print("[OK]", json.loads(res.read())["content"]["html_url"])
except urllib.error.HTTPError as e:
    print("[FAIL]", e.read().decode()[:300])
