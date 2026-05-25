# vaplayer-m3u8-extractor

A Python toolkit to extract M3U8 / HLS stream URLs from `vaplayer.ru` embed pages.  
Two approaches: browser-based (selenium) and direct API (no browser needed).

---

## Background

The target URL is:
```
https://vaplayer.ru/embed/movie/tt2948356
```

This page loads an iframe from `brightpathsignals.com`, which runs a JavaScript player that fetches stream URLs at runtime. A plain HTTP request gets you the HTML shell but no stream URL — the m3u8 is only revealed after JavaScript executes.

---

## How It Works — Discovery Process

### Step 1 — HTTP pre-scan
Fetching the page HTML reveals:
- The outer page is just a wrapper with one `<iframe src="https://brightpathsignals.com/embed/movie/tt2948356">`
- The iframe has sandbox protection and DevTools blocking

### Step 2 — Probing the iframe
Fetching the iframe with correct headers (`Referer: https://vaplayer.ru/`, `Origin: https://vaplayer.ru`) reveals:
- It loads `hls.js` for HLS playback
- It loads `/embed/assets/js/player.min.js`
- Inside `player.min.js` there are references to:
  - `https://streamdata.vaplayer.ru/api.php` ← **the real stream API**
  - `/embed/source-api.php`
  - `/hls-proxy.php`

### Step 3 — API call
```
GET https://streamdata.vaplayer.ru/api.php?imdb=tt2948356&type=movie
Headers:
  Referer: https://brightpathsignals.com/embed/movie/tt2948356
  Origin:  https://brightpathsignals.com
```

Response (JSON):
```json
{
  "status_code": "200",
  "data": {
    "title": "Zootopia 2016",
    "imdb_id": "tt2948356",
    "file_name": "Zootopia (2016) [1080p]...",
    "backdrop": "https://image.tmdb.org/...",
    "stream_urls": [
      "https://dataanalyticsacademy.site/.../master.m3u8",
      "..."
    ]
  }
}
```

The `stream_urls` array contains the actual m3u8 playlist URLs — **no browser needed**.

---

## Files

### `direct_testing.py`
Pure Python, no browser, no selenium. Calls the API directly and parses the playlist.

```bash
# movie
python direct_testing.py --imdb tt2948356 --type movie

# TV show
python direct_testing.py --imdb tt0944947 --type tv --season 1 --episode 1
```

Output includes:
- Title, IMDB ID, backdrop image
- All stream URLs from the API
- Parsed playlist details (master → quality levels, media → segments + duration)
- Ready-to-use VLC and ffmpeg commands

### `vidlayer_network_analyser.py`
Browser-based extractor using selenium + Firefox (headless).  
Use this when the direct API does not return results.

```bash
pip install selenium requests m3u8

python vidlayer_network_analyser.py --url "https://vaplayer.ru/embed/movie/tt2948356" --wait 8
python vidlayer_network_analyser.py --url "https://vaplayer.ru/embed/movie/tt2948356" --show-browser
```

**How it works:**
1. Opens Firefox (headless by default)
2. Injects a JavaScript interceptor that hooks `fetch`, `XHR`, `WebSocket`, `setAttribute`, HLS.js, JWPlayer, Video.js, Clappr, Plyr, and MediaSource
3. Captures every outgoing request including `Origin`, `Referer`, and request headers
4. Visits each iframe URL directly
5. Parses every m3u8 found
6. Prints a full report with headers needed to replay each stream

---

## Installation

```bash
pip install requests selenium m3u8
```

For `vidlayer_network_analyser.py` you also need Firefox + geckodriver installed.

---

## API Reference

| Parameter | Value |
|-----------|-------|
| Endpoint  | `https://streamdata.vaplayer.ru/api.php` |
| `imdb`    | IMDB ID e.g. `tt2948356` |
| `type`    | `movie` or `tv` |
| `season`  | Season number (TV only) |
| `episode` | Episode number (TV only) |

Required headers:
```
Referer: https://brightpathsignals.com/embed/movie/
Origin:  https://brightpathsignals.com
```

---

## Play / Download

```bash
# VLC
vlc --http-referrer="https://brightpathsignals.com/embed/movie/" "<m3u8_url>"

# ffmpeg
ffmpeg -headers "Referer: https://brightpathsignals.com/embed/movie/" \
       -i "<m3u8_url>" -c copy output.mp4
```

---

## What Was Learned

- `vaplayer.ru` is a thin wrapper — the real player is on `brightpathsignals.com`
- The stream API is at `streamdata.vaplayer.ru/api.php` and returns JSON with stream URLs
- Streams are served from `dataanalyticsacademy.site` (CDN) with token-signed URLs
- The correct `Referer` and `Origin` headers are required for the API and for replaying streams
- The player uses HLS.js for adaptive bitrate streaming with 3 quality levels (1080p / 720p / 360p)
