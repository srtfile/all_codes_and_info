import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import time

BASE = "https://www.kalerkantho.com"
URL = "https://www.kalerkantho.com/archive/2026-04-30"


# =========================
# CHECK INTERNAL LINK
# =========================
def is_internal(link):
    return urlparse(link).netloc in ["", "www.kalerkantho.com", "kalerkantho.com"]


# =========================
# METHOD 1: REQUESTS
# =========================
def fetch_requests(url):
    print("[1] requests...")

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html",
        "Referer": "https://www.google.com/"
    }

    try:
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            return r.text
    except Exception as e:
        print("requests failed:", e)

    return None


# =========================
# METHOD 2: PLAYWRIGHT (ANTI-BLOCK)
# =========================
def fetch_playwright(url):
    print("[2] playwright...")

    try:
        from playwright.sync_api import sync_playwright
    except:
        print("Playwright not installed")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto(url, timeout=60000)
            time.sleep(4)

            html = page.content()
            browser.close()

            return html

    except Exception as e:
        print("playwright failed:", e)

    return None


# =========================
# EXTRACT ALL INTERNAL LINKS
# =========================
def extract_internal_links(html):
    soup = BeautifulSoup(html, "html.parser")

    links = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]

        full_url = urljoin(BASE, href)

        if is_internal(full_url):
            links.add(full_url.split("#")[0])  # remove anchors

    return sorted(list(links))


# =========================
# MAIN SCRAPER
# =========================
def get_all_internal_links(url):
    html = fetch_requests(url)

    if not html:
        html = fetch_playwright(url)

    if not html:
        print("❌ Failed to load page")
        return []

    return extract_internal_links(html)


# =========================
# RUN
# =========================
if __name__ == "__main__":
    print("Scraping internal links...\n")

    links = get_all_internal_links(URL)

    print("\n========== INTERNAL URLS ==========\n")

    for i, link in enumerate(links, 1):
        print(f"{i}. {link}")

    print("\nTotal:", len(links))