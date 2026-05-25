import re
import sys
import requests

DEFAULT_URL = "https://streamta.site/e/1bZVvmXvZ4ueOvM"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"

_STR = re.compile(r"\s*(['\"])((?:\\.|(?!\1).)*)\1\s*")
_PAREN_STR = re.compile(r"\s*\(\s*(['\"])((?:\\.|(?!\1).)*)\1\s*\)\s*")
_SUBSTR = re.compile(r"\.substring\(\s*(\d+)(?:\s*,\s*(\d+))?\s*\)")
_PLUS = re.compile(r"\s*\+\s*")


def _read_term(s: str, i: int) -> tuple[str, int] | None:
    m = _STR.match(s, i)
    if m:
        return m.group(2), m.end()
    m = _PAREN_STR.match(s, i)
    if not m:
        return None
    lit = m.group(2)
    j = m.end()
    while True:
        sm = _SUBSTR.match(s, j)
        if not sm:
            break
        a = int(sm.group(1))
        b = int(sm.group(2)) if sm.group(2) else None
        lit = lit[a:b] if b is not None else lit[a:]
        j = sm.end()
    return lit, j


def _resolve_innerhtml(stmt: str) -> str | None:
    out_parts: list[str] = []
    i = 0
    n = len(stmt)
    while i < n:
        term = _read_term(stmt, i)
        if term is None:
            return None
        out_parts.append(term[0])
        i = term[1]
        if i >= n:
            break
        pm = _PLUS.match(stmt, i)
        if not pm:
            return None
        i = pm.end()
    return "".join(out_parts)


def extract_signed_get_video_candidates(html: str) -> list[str]:
    seen: list[str] = []
    for m in re.finditer(
        r"document\.getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)\.innerHTML\s*=\s*([^;]+);",
        html,
    ):
        resolved = _resolve_innerhtml(m.group(2).strip())
        if not resolved:
            continue
        if "/get_video?id=" not in resolved or "token=" not in resolved:
            continue
        if resolved.startswith("//"):
            resolved = "https:" + resolved
        elif resolved.startswith("/"):
            resolved = "https://streamta.site" + resolved
        if resolved not in seen:
            seen.append(resolved)
    if not seen:
        raise RuntimeError("could not deobfuscate any /get_video URL from HTML")
    return seen


def get_direct_link(page_url: str = DEFAULT_URL) -> str:
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept-Language": "en-US,en;q=0.9",
    })
    r = s.get(page_url, timeout=20)
    r.raise_for_status()

    last_err = None
    for signed in extract_signed_get_video_candidates(r.text):
        try:
            r2 = s.get(signed, headers={"Referer": page_url}, allow_redirects=False, timeout=20)
        except requests.RequestException as e:
            last_err = e
            continue
        if r2.status_code in (301, 302, 303, 307, 308) and "Location" in r2.headers:
            return r2.headers["Location"]
        if r2.status_code == 200:
            return signed
        last_err = RuntimeError(f"{r2.status_code} for {signed}")
    raise RuntimeError(f"no candidate worked: {last_err}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print(get_direct_link(target))
