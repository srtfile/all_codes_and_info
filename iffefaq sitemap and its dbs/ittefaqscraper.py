import requests
import time
import os
import sqlite3
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from tqdm import tqdm
import threading

import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==============================
# 🔧 CONFIG
# ==============================
MODE = "threadpool"   # "normal" | "threadpool" | "asyncio"

END_DATE = "2026-03-01"
RATE_LIMIT = 1
THREADS = 5

MAX_DB_SIZE = 50 * 1024 * 1024
DATA_DIR = "data"
# ==============================

BASE_URL = "https://www.ittefaq.com.bd/api/theme_engine/get_ajax_contents"

PARAMS = {
    "widget": 476,
    "count": 250,
    "page_id": 0,
    "subpage_id": 0,
    "author": 0,
    "tags": "",
    "archive_time": "",
    "filter": ""
}

HEADERS = {"User-Agent": "Mozilla/5.0"}

END_DATE_OBJ = datetime.strptime(END_DATE, "%Y-%m-%d").replace(tzinfo=None)

os.makedirs(DATA_DIR, exist_ok=True)

BATCH_FILE = os.path.join(DATA_DIR, "batch.txt")

lock = threading.Lock()

# ---------------------------
# BUILD API URL
# ---------------------------
def build_api_url(start):
    params = {**PARAMS, "start": start}
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{BASE_URL}?{query}"

# ---------------------------
# LOAD LAST START
# ---------------------------
def get_last_start():
    if not os.path.exists(BATCH_FILE):
        return 0

    last = 0
    with open(BATCH_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if "start=" in line:
                try:
                    s = int(line.split("start=")[1].split("&")[0])
                    last = max(last, s)
                except:
                    pass
    return last + 250  # resume next batch

# ---------------------------
# SAVE BATCH API URL
# ---------------------------
def save_batch(start):
    url = build_api_url(start)
    with lock:
        with open(BATCH_FILE, "a", encoding="utf-8") as f:
            f.write(url + "\n")

# ---------------------------
# DB
# ---------------------------
def get_db_path(i):
    return os.path.join(DATA_DIR, "ittefaq.db" if i == 0 else f"{i}ittefaq.db")

def create_connection(path):
    conn = sqlite3.connect(path)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS news (
        url TEXT PRIMARY KEY,
        title TEXT,
        published_at TEXT
    )
    """)
    conn.commit()
    return conn

def get_db_size(path):
    return os.path.getsize(path) if os.path.exists(path) else 0

def get_available_db():
    i = 0
    while True:
        path = get_db_path(i)
        if not os.path.exists(path) or get_db_size(path) < MAX_DB_SIZE:
            return path
        i += 1

def get_all_existing_urls():
    urls = set()
    for f in os.listdir(DATA_DIR):
        if f.endswith(".db"):
            conn = sqlite3.connect(os.path.join(DATA_DIR, f))
            rows = conn.execute("SELECT url FROM news").fetchall()
            urls.update([r[0] for r in rows])
            conn.close()
    return urls

# ---------------------------
# PARSE
# ---------------------------
def parse_html(html):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    stop = False

    for a in soup.find_all("div", class_="each"):
        link = a.find("a", class_="link_overlay")
        time_tag = a.find("span", class_="time")

        if not link or not time_tag:
            continue

        url = link.get("href")
        if url.startswith("//"):
            url = "https:" + url

        title = link.get_text(strip=True)
        published = time_tag.get("data-published")

        try:
            dt = datetime.fromisoformat(published)
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except:
            continue

        if dt < END_DATE_OBJ:
            stop = True
            break

        results.append((url, title, published, dt))

    return results, stop

# ---------------------------
# SAVE DB
# ---------------------------
def save(news, existing):
    new_count = 0

    with lock:
        for url, title, published, _ in news:
            if url in existing:
                continue

            db = get_available_db()
            conn = create_connection(db)

            try:
                conn.execute(
                    "INSERT INTO news VALUES (?, ?, ?)",
                    (url, title, published)
                )
                conn.commit()
                existing.add(url)
                new_count += 1
            except:
                pass

            conn.close()

    return new_count

# ---------------------------
# THREAD FETCH
# ---------------------------
def fetch_thread(start):
    try:
        r = requests.get(BASE_URL, params={**PARAMS, "start": start}, headers=HEADERS)
        return parse_html(r.json().get("html", "")), start
    except:
        return ([], False), start

# ---------------------------
# THREAD MODE
# ---------------------------
def run_threadpool():
    start = get_last_start()
    existing = get_all_existing_urls()
    total = 0

    print(f"🔁 Resume from start={start}")

    pbar = tqdm(desc="⚡ Thread", unit="batch")

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        while True:
            futures = [ex.submit(fetch_thread, start + i*250) for i in range(THREADS)]
            stop_all = False

            for f in as_completed(futures):
                (news, stop), s = f.result()

                save_batch(s)  # ✅ save API URL

                new = save(news, existing)
                total += new

                pbar.update(1)
                pbar.set_postfix({"new": new, "total": total})

                if stop:
                    stop_all = True

            if stop_all:
                break

            start += THREADS * 250
            time.sleep(RATE_LIMIT)

    pbar.close()

# ---------------------------
# MAIN
# ---------------------------
def scrape():
    print(f"🚀 MODE: {MODE}")
    print(f"📅 Until: {END_DATE}")

    if MODE == "threadpool":
        run_threadpool()
    else:
        print("❌ Only threadpool optimized here")

if __name__ == "__main__":
    scrape() 