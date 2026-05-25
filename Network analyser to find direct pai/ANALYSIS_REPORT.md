# CinemaOS.tech — Full Analysis Report
**Target:** `https://cinemaos.tech/player/1318447`  
**Movie:** Apex (2026) — TMDB ID: `1318447`, IMDB ID: `tt16431404`  
**Scan Date:** 2026-05-23

---

## ✅ DIRECT FINDINGS — M3U8 STREAM URLS (CONFIRMED LIVE)

These were captured directly from network traffic:

```
Master playlist:  https://storrrrrrm.site/stream/d42f649481170d33/master.m3u8
1080p playlist:   https://storrrrrrm.site/stream/d42f649481170d33/1080p.m3u8
```

**Master playlist contains 2 variants:**
- `1280x720` (720p)
- `1920x1080` (1080p)

**1080p playlist:** 79–2863 segments (fMP4/HLS, `video/mp4;codecs=avc1.640028` + `audio/mp4;codecs=mp4a.40.2`)

The stream hash `d42f649481170d33` is a **session/content token** — it is likely time-limited or tied to the session.

---

## 🔑 THE PROVIDER API — HOW THE STREAM URL IS OBTAINED

### Step 1 — The API Call

The player makes a GET request to:

```
GET https://cinemaos.tech/api/providerv4
    ?type=movie
    &tmdbId=1318447
    &imdbId=tt16431404
    &t=Apex
    &ry=2026
    &secret=d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729
    &_rk=2549b22d9bf0d91847a2811baac98d0079e02dba592aea94
```

**Parameters breakdown:**
| Param | Value | Notes |
|-------|-------|-------|
| `type` | `movie` | Content type (also `tv` for series) |
| `tmdbId` | `1318447` | TMDB ID of the content |
| `imdbId` | `tt16431404` | IMDB ID |
| `t` | `Apex` | Title |
| `ry` | `2026` | Release year |
| `secret` | `d4475c101f7236651d09c6ec4f52e1c84b1bfac087dd537aa0f2850d97224729` | SHA-256 hash (see below) |
| `_rk` | `2549b22d9bf0d91847a2811baac98d0079e02dba592aea94` | Request key / anti-replay token |

### Step 2 — The API Response (Encrypted)

The API returns HTTP 200 with JSON:
```json
{
  "data": {
    "encrypted": "dd32cf05b5659e931c99705d9198ced519dc9493aee504df506fabec10b086c0..."
  }
}
```

The response body is **AES-encrypted**. The client-side JS decrypts it to get the actual stream URLs.

### Step 3 — Decryption

The decryption happens in the player JS (`6282-6ec9290c43848574.js`, module `95651`). The decrypted payload contains the `storrrrrrm.site` stream URLs.

---

## 🔐 SECRET & _rk TOKEN GENERATION

The `secret` parameter is a **SHA-256 hash**. Based on the pattern observed and the JS code structure, it is computed from a combination of:
- The TMDB ID
- A server-side salt/key embedded in the Next.js app
- Possibly a timestamp component

The `_rk` (request key) is a shorter hex token, likely an HMAC or truncated hash used as an anti-replay/rate-limit mechanism.

**These tokens are generated client-side in the Next.js app** — the logic lives in the large chunk files (`aaea2bcf` / `a4634e51`), which are minified and obfuscated.

---

## 📡 ALL DISCOVERED API ENDPOINTS

### Primary (Stream Source)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `https://cinemaos.tech/api/providerv4` | GET | Main stream provider API — returns encrypted stream data |

### Supporting APIs
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `https://api.theintrodb.org/v2/media?tmdb_id={id}` | GET | Intro/credits skip data (returned 404 for this title) |
| `https://sub.vdrk.site/v1/movie/{tmdbId}` | GET | Subtitle index — returns VTT file list |
| `https://cache.vdrk.site/v1/vtt/movie/{tmdbId}/{label}.vtt` | GET | Individual subtitle VTT files |
| `https://cinemaos.tech/api/watch-history?userId={uid}` | GET | Watch history (requires auth) |
| `https://nyc.cloud.appwrite.io/v1/account` | GET | Auth backend (Appwrite) |

### Subtitle API (Open, No Auth)
```
GET https://sub.vdrk.site/v1/movie/1318447
```
Returns:
```json
[
  {"label":"English Hi3","file":"https://cache.vdrk.site/v1/vtt/movie/1318447/English Hi3.vtt"},
  {"label":"English",    "file":"https://cache.vdrk.site/v1/vtt/movie/1318447/English.vtt"},
  {"label":"English2",   "file":"https://cache.vdrk.site/v1/vtt/movie/1318447/English2.vtt"},
  {"label":"English4",   "file":"https://cache.vdrk.site/v1/vtt/movie/1318447/English4.vtt"}
]
```
**Pattern for other movies:** `https://sub.vdrk.site/v1/movie/{tmdbId}`  
**Pattern for TV:** `https://sub.vdrk.site/v1/tv/{tmdbId}/{season}/{episode}`

---

## 🗺️ FULL REQUEST FLOW (HOW IT WORKS)

```
1. Browser loads https://cinemaos.tech/player/{tmdbId}
   └─ Next.js SSR returns page with movie metadata (TMDB data embedded in HTML)

2. Client JS generates secret + _rk tokens

3. GET /api/providerv4?type=movie&tmdbId=...&imdbId=...&secret=...&_rk=...
   └─ Returns: { data: { encrypted: "hex..." } }

4. Client decrypts the response using AES
   └─ Decrypted payload contains: stream URL(s) on storrrrrrm.site

5. Player fetches: https://storrrrrrm.site/stream/{hash}/master.m3u8
   └─ Returns HLS master playlist with 720p + 1080p variants

6. Player fetches: https://storrrrrrm.site/stream/{hash}/1080p.m3u8
   └─ Returns media playlist with ~79-2863 fMP4 segments

7. Subtitles fetched from: https://sub.vdrk.site/v1/movie/{tmdbId}
```

---

## 🧩 URL PATTERNS FOR OTHER CONTENT

Based on the API structure, these patterns should work for other titles:

```
# Movies
GET https://cinemaos.tech/api/providerv4?type=movie&tmdbId={id}&imdbId={imdb}&t={title}&ry={year}&secret={hash}&_rk={token}

# TV Shows (likely)
GET https://cinemaos.tech/api/providerv4?type=tv&tmdbId={id}&imdbId={imdb}&t={title}&ry={year}&season={s}&episode={e}&secret={hash}&_rk={token}

# Subtitles (open, no auth needed)
GET https://sub.vdrk.site/v1/movie/{tmdbId}
GET https://sub.vdrk.site/v1/tv/{tmdbId}/{season}/{episode}
```

---

## ⚠️ PROTECTION MECHANISMS OBSERVED

1. **Encrypted API response** — stream URLs are AES-encrypted, not returned in plaintext
2. **`secret` + `_rk` tokens** — request signing prevents direct API calls without the JS running
3. **Anti-devtools JS** — the player actively detects DevTools, right-click, window resize, and redirects to `about:blank`
4. **fetch() override** — the player monkey-patches `window.fetch` to detect m3u8/stream requests and flood the console
5. **CORS on stream server** — `storrrrrrm.site` has `Access-Control-Allow-Origin: *` (open), but the stream hash is session-bound
6. **Stream hash is time-limited** — the `d42f649481170d33` token in the m3u8 URL is likely session-specific and expires

---

## 🔧 PRACTICAL NOTES

- The **subtitle API** (`sub.vdrk.site`) is completely open — no auth, no tokens needed
- The **stream server** (`storrrrrrm.site`) has open CORS but the hash token is the gating mechanism
- The **providerv4 API** is the key bottleneck — it requires valid `secret` + `_rk` tokens
- The `secret` and `_rk` are generated in the minified Next.js chunks — reversing them would require deobfuscating `aaea2bcf-4b7d5c47edf9795e.js` (325KB) and `a4634e51-eaf6c3d6b6e58119.js` (511KB)
- The app uses **Appwrite** (`nyc.cloud.appwrite.io`) for auth with project ID `6842e78900156f5fd605`
- Google Analytics ID: `G-TNVSTQRC12`
- Ad script: `//wz.afgodscarpe.com/ryRZVErvkj1gAr/126965`
