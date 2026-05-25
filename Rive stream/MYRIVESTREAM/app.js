/* ═══════════════════════════════════════════════════════════════════════════
   MyRiveStream — app.js
   ═══════════════════════════════════════════════════════════════════════════ */

const TMDB_KEY  = '6fad3f86b8452ee232deb7977d7dcf58';
const TMDB_BASE = 'https://api.themoviedb.org/3';
const IMG_BASE  = 'https://image.tmdb.org/t/p';

/* ── State ─────────────────────────────────────────────────────────────────── */
let state = {
  tab:         'movie',   // 'movie' | 'tv'
  page:        1,
  currentId:   null,
  currentType: 'movie',
  currentSeason:  1,
  currentEpisode: 1,
  sandboxOn:   true,
  activeServer: null,
  serverIndex:  0,
  mediaData:   null,
  seasons:     [],
};

/* ── Embed servers (grouped, same order as embed.py) ───────────────────────── */
const SERVER_GROUPS = [
  {
    label: 'VidSrc Family',
    servers: [
      { name: 'VidSrc.me',  fn: (t,i,s,e) => t==='movie' ? `https://vidsrc.me/embed/movie/${i}` : `https://vidsrc.me/embed/tv/${i}/${s}/${e}` },
      { name: 'VidSrc.pro', fn: (t,i,s,e) => t==='movie' ? `https://vidsrc.pro/embed/movie/${i}?theme=00c1db` : `https://vidsrc.pro/embed/tv/${i}/${s}/${e}?theme=00c1db` },
      { name: 'VidSrc.cc',  fn: (t,i,s,e) => t==='movie' ? `https://vidsrc.cc/v2/embed/movie/${i}` : `https://vidsrc.cc/v2/embed/tv/${i}/${s}/${e}` },
      { name: 'VidSrc.vip', fn: (t,i,s,e) => t==='movie' ? `https://vidsrc.vip/embed/movie/${i}` : `https://vidsrc.vip/embed/tv/${i}/${s}/${e}` },
      { name: 'VidSrc.rip', fn: (t,i,s,e) => t==='movie' ? `https://vidsrc.rip/embed/movie/${i}` : `https://vidsrc.rip/embed/tv/${i}/${s}/${e}` },
      { name: 'VidSrc.nl',  fn: (t,i,s,e) => t==='movie' ? `https://player.vidsrc.nl/embed/movie/${i}` : `https://player.vidsrc.nl/embed/tv/${i}/${s}/${e}` },
      { name: 'VidSrc.su',  fn: (t,i,s,e) => t==='movie' ? `https://vidsrc.su/embed/movie/${i}` : `https://vidsrc.su/embed/tv/${i}/${s}/${e}` },
    ]
  },
  {
    label: 'MultiEmbed Family',
    servers: [
      { name: 'MultiEmbed',  fn: (t,i,s,e) => t==='movie' ? `https://multiembed.mov/directstream.php?video_id=${i}&tmdb=1` : `https://multiembed.mov/directstream.php?video_id=${i}&tmdb=1&s=${s}&e=${e}` },
      { name: 'MultiEmbed2', fn: (t,i,s,e) => t==='movie' ? `https://multiembed.mov/?video_id=${i}&tmdb=1&server=2` : `https://multiembed.mov/?video_id=${i}&tmdb=1&s=${s}&e=${e}&server=2` },
    ]
  },
  {
    label: '2Embed / 123Embed',
    servers: [
      { name: '2Embed',   fn: (t,i,s,e) => t==='movie' ? `https://www.2embed.cc/embed/${i}` : `https://www.2embed.cc/embedtv/${i}&s=${s}&e=${e}` },
      { name: '123Embed', fn: (t,i,s,e) => t==='movie' ? `https://play2.123embed.net/movie/${i}` : `https://play2.123embed.net/tv/${i}/${s}/${e}` },
    ]
  },
  {
    label: 'VidLink / VidFast / VidJoy / VidZee',
    servers: [
      { name: 'VidLink', fn: (t,i,s,e) => t==='movie' ? `https://vidlink.pro/movie/${i}` : `https://vidlink.pro/tv/${i}/${s}/${e}` },
      { name: 'VidFast', fn: (t,i,s,e) => t==='movie' ? `https://vidfast.pro/embed/movie/${i}` : `https://vidfast.pro/embed/tv/${i}/${s}/${e}` },
      { name: 'VidJoy',  fn: (t,i,s,e) => t==='movie' ? `https://vidjoy.pro/embed/movie/${i}?adFree=true` : `https://vidjoy.pro/embed/tv/${i}/${s}/${e}?adFree=true` },
      { name: 'VidZee',  fn: (t,i,s,e) => t==='movie' ? `https://player.vidzee.wtf/embed/movie/${i}` : `https://player.vidzee.wtf/embed/tv/${i}/${s}/${e}` },
      { name: 'Vidora',  fn: (t,i,s,e) => t==='movie' ? `https://vidora.su/embed/movie/${i}` : `https://vidora.su/embed/tv/${i}/${s}/${e}` },
    ]
  },
  {
    label: 'AutoEmbed / AnyEmbed / SuperFlix',
    servers: [
      { name: 'AutoEmbed',   fn: (t,i,s,e) => t==='movie' ? `https://player.autoembed.cc/embed/movie/${i}` : `https://player.autoembed.cc/embed/tv/${i}/${s}/${e}` },
      { name: 'AnyEmbed',    fn: (t,i,s,e) => t==='movie' ? `https://anyembed.xyz/embed/movie/${i}` : `https://anyembed.xyz/embed/tv/${i}/${s}/${e}` },
      { name: 'SuperFlixAPI',fn: (t,i,s,e) => t==='movie' ? `https://superflixapi.digital/movie/${i}` : `https://superflixapi.digital/tv/${i}/${s}/${e}` },
      { name: 'SmashyStream',fn: (t,i,s,e) => t==='movie' ? `https://embed.smashystream.com/playere.php?tmdb=${i}` : `https://embed.smashystream.com/playere.php?tmdb=${i}&season=${s}&episode=${e}` },
      { name: 'WarezCDN',    fn: (t,i,s,e) => t==='movie' ? `https://embed.warezcdn.com/movie/${i}` : `https://embed.warezcdn.com/serie/${i}/${s}/${e}` },
      { name: 'FrEmbed',     fn: (t,i,s,e) => t==='movie' ? `https://frembed.club/api/movie?id=${i}` : `https://frembed.club/api/tv?id=${i}&s=${s}&e=${e}` },
    ]
  },
  {
    label: 'MoviesAPI / Filmku / 111Movies',
    servers: [
      { name: 'MoviesAPI',  fn: (t,i,s,e) => t==='movie' ? `https://moviesapi.club/movie/${i}` : `https://moviesapi.club/tv/${i}-${s}-${e}` },
      { name: 'Filmku',     fn: (t,i,s,e) => t==='movie' ? `https://filmku.stream/embed/${i}` : `https://filmku.stream/embed/${i}/${s}/${e}` },
      { name: '111Movies',  fn: (t,i,s,e) => t==='movie' ? `https://111movies.com/embed/movie/${i}` : `https://111movies.com/embed/tv/${i}/${s}/${e}` },
      { name: 'StreamSito', fn: (t,i,s,e) => t==='movie' ? `https://streamsito.com/embed/movie/${i}` : `https://streamsito.com/embed/tv/${i}/${s}/${e}` },
    ]
  },
  {
    label: 'PStream / Videasy / PrimeSrc',
    servers: [
      { name: 'PStream',  fn: (t,i,s,e) => t==='movie' ? `https://iframe.pstream.mov/embed/movie/${i}` : `https://iframe.pstream.mov/embed/tv/${i}/${s}/${e}` },
      { name: 'Videasy',  fn: (t,i,s,e) => t==='movie' ? `https://player.videasy.net/movie/${i}` : `https://player.videasy.net/tv/${i}/${s}/${e}` },
      { name: 'PrimeSrc', fn: (t,i,s,e) => t==='movie' ? `https://primesrc.me/embed/movie/${i}` : `https://primesrc.me/embed/tv/${i}/${s}/${e}` },
    ]
  },
  {
    label: 'GoDrive / TurboVid / Mapple / TechNeo',
    servers: [
      { name: 'GoDrive',    fn: (t,i,s,e) => t==='movie' ? `https://godriveplayer.com/player.php?tmdb=${i}` : `https://godriveplayer.com/player.php?type=series&tmdb=${i}&season=${s}&episode=${e}` },
      { name: 'TurboVid',   fn: (t,i,s,e) => t==='movie' ? `https://turbovid.eu/embed/movie/${i}` : `https://turbovid.eu/embed/tv/${i}/${s}/${e}` },
      { name: 'Mapple',     fn: (t,i,s,e) => t==='movie' ? `https://mapple.uk/embed/movie/${i}` : `https://mapple.uk/embed/tv/${i}/${s}/${e}` },
      { name: 'TechNeo',    fn: (t,i,s,e) => t==='movie' ? `https://vid.techneo.fun/embed/movie/${i}` : `https://vid.techneo.fun/embed/tv/${i}/${s}/${e}` },
    ]
  },
  {
    label: 'InsertUnit / RGShows',
    servers: [
      { name: 'InsertUnit', fn: (t,i,s,e) => t==='movie' ? `https://api.insertunit.ws/embed/movie/${i}` : `https://api.insertunit.ws/embed/tv/${i}/${s}/${e}` },
      { name: 'RGShows',    fn: (t,i,s,e) => t==='movie' ? `https://rgshows.ru/player/movie/${i}` : `https://rgshows.ru/player/tv/${i}/${s}/${e}` },
    ]
  },
];

// Flat list for auto-fallback
const ALL_SERVERS = SERVER_GROUPS.flatMap(g => g.servers);

/* ── TMDB helpers ──────────────────────────────────────────────────────────── */
async function tmdb(path, params = {}) {
  const url = new URL(`${TMDB_BASE}${path}`);
  url.searchParams.set('api_key', TMDB_KEY);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const res = await fetch(url);
  if (!res.ok) throw new Error(`TMDB ${res.status}`);
  return res.json();
}

function posterUrl(path, size = 'w342') {
  return path ? `${IMG_BASE}/${size}${path}` : null;
}
function backdropUrl(path) {
  return path ? `${IMG_BASE}/w1280${path}` : null;
}

/* ── Init ──────────────────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  loadBrowse();
  document.getElementById('searchInput').addEventListener('keydown', e => {
    if (e.key === 'Enter') doSearch();
  });
});

/* ── Tab switch ────────────────────────────────────────────────────────────── */
function switchTab(tab, btn) {
  state.tab = tab;
  state.page = 1;
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById('browseTitle').textContent =
    tab === 'movie' ? 'Trending Movies' : 'Trending TV Shows';
  document.getElementById('mediaGrid').innerHTML = '';
  loadBrowse();
}

/* ── Browse / trending ─────────────────────────────────────────────────────── */
async function loadBrowse() {
  showSkeletons('mediaGrid', 20);
  try {
    const endpoint = state.tab === 'movie'
      ? `/trending/movie/week`
      : `/trending/tv/week`;
    const data = await tmdb(endpoint, { page: state.page });
    if (state.page === 1) {
      renderHero(data.results[0]);
      renderGrid('mediaGrid', data.results.slice(1), false);
    } else {
      renderGrid('mediaGrid', data.results, true);
    }
    document.getElementById('loadMoreBtn').style.display =
      state.page < data.total_pages ? 'inline-block' : 'none';
  } catch (e) {
    showToast('Failed to load content');
  }
}

function loadMore() {
  state.page++;
  loadBrowse();
}

/* ── Hero ──────────────────────────────────────────────────────────────────── */
function renderHero(item) {
  if (!item) return;
  const hero = document.getElementById('heroSection');
  const title = item.title || item.name || '';
  const year  = (item.release_date || item.first_air_date || '').slice(0, 4);
  const bg    = backdropUrl(item.backdrop_path);
  hero.style.display = 'block';
  hero.innerHTML = `
    ${bg ? `<img class="hero-img" src="${bg}" alt="${title}" loading="lazy" />` : ''}
    <div class="hero-overlay">
      <div class="hero-content">
        <span class="hero-badge">${state.tab === 'movie' ? 'MOVIE' : 'TV SHOW'}</span>
        <h1 class="hero-title">${title}</h1>
        <p class="hero-meta">⭐ ${item.vote_average?.toFixed(1) || 'N/A'} &nbsp;•&nbsp; ${year}</p>
        <p class="hero-overview">${item.overview || ''}</p>
        <button class="hero-play-btn" onclick="openPlayer(${item.id},'${state.tab}')">
          ▶ &nbsp;Watch Now
        </button>
      </div>
    </div>`;
}

/* ── Grid ──────────────────────────────────────────────────────────────────── */
function renderGrid(containerId, items, append = false) {
  const grid = document.getElementById(containerId);
  if (!append) grid.innerHTML = '';
  items.forEach(item => {
    const title  = item.title || item.name || 'Unknown';
    const year   = (item.release_date || item.first_air_date || '').slice(0, 4);
    const poster = posterUrl(item.poster_path);
    const rating = item.vote_average?.toFixed(1) || '';
    const type   = item.media_type || state.tab;
    const card   = document.createElement('div');
    card.className = 'card';
    card.onclick   = () => openPlayer(item.id, type);
    card.innerHTML = `
      ${poster
        ? `<img class="card-poster" src="${poster}" alt="${title}" loading="lazy" />`
        : `<div class="card-poster-placeholder">🎬</div>`}
      ${rating ? `<span class="card-rating">⭐ ${rating}</span>` : ''}
      <div class="card-body">
        <div class="card-title" title="${title}">${title}</div>
        <div class="card-meta">${year}</div>
      </div>`;
    grid.appendChild(card);
  });
}

function showSkeletons(containerId, count) {
  const grid = document.getElementById(containerId);
  grid.innerHTML = Array(count).fill(
    `<div class="skeleton skeleton-card"></div>`
  ).join('');
}

/* ── Search ────────────────────────────────────────────────────────────────── */
async function doSearch() {
  const q = document.getElementById('searchInput').value.trim();
  if (!q) return;
  document.getElementById('homeSection').style.display   = 'none';
  document.getElementById('playerSection').style.display = 'none';
  document.getElementById('searchSection').style.display = 'block';
  document.getElementById('searchTitle').textContent = `Results for "${q}"`;
  showSkeletons('searchGrid', 10);
  try {
    const data = await tmdb('/search/multi', { query: q, include_adult: false });
    const items = data.results.filter(r => r.media_type === 'movie' || r.media_type === 'tv');
    document.getElementById('searchGrid').innerHTML = '';
    if (items.length === 0) {
      document.getElementById('searchGrid').innerHTML =
        '<p style="color:var(--text2);grid-column:1/-1">No results found.</p>';
    } else {
      renderGrid('searchGrid', items, false);
    }
  } catch (e) {
    showToast('Search failed');
  }
}

/* ── Show home ─────────────────────────────────────────────────────────────── */
function showHome() {
  document.getElementById('homeSection').style.display   = 'block';
  document.getElementById('searchSection').style.display = 'none';
  document.getElementById('playerSection').style.display = 'none';
  document.getElementById('searchInput').value = '';
  // Stop iframe
  const frame = document.getElementById('playerFrame');
  frame.src = '';
}

/* ── Open player ───────────────────────────────────────────────────────────── */
async function openPlayer(id, type) {
  state.currentId   = id;
  state.currentType = type;
  state.currentSeason  = 1;
  state.currentEpisode = 1;
  state.serverIndex    = 0;
  state.activeServer   = null;

  document.getElementById('homeSection').style.display   = 'none';
  document.getElementById('searchSection').style.display = 'none';
  document.getElementById('playerSection').style.display = 'block';
  window.scrollTo({ top: 0, behavior: 'smooth' });

  // Reset player
  showPlaceholder(true, 'Loading…');
  document.getElementById('playerFrame').src = '';

  // Fetch metadata
  try {
    const endpoint = type === 'movie' ? `/movie/${id}` : `/tv/${id}`;
    const data = await tmdb(endpoint, { append_to_response: 'credits' });
    state.mediaData = data;
    renderMediaInfo(data, type);
    renderServerGroups();

    if (type === 'tv') {
      state.seasons = data.seasons?.filter(s => s.season_number > 0) || [];
      renderSeasonSelect();
      await loadEpisodes();
      document.getElementById('episodeSection').style.display = 'block';
    } else {
      document.getElementById('episodeSection').style.display = 'none';
    }

    // Auto-play first server
    playServer(0);
  } catch (e) {
    showToast('Failed to load media info');
    renderServerGroups();
    playServer(0);
  }
}

/* ── Media info ────────────────────────────────────────────────────────────── */
function renderMediaInfo(data, type) {
  const title   = data.title || data.name || '';
  const year    = (data.release_date || data.first_air_date || '').slice(0, 4);
  const rating  = data.vote_average?.toFixed(1) || 'N/A';
  const runtime = data.runtime ? `${data.runtime} min` : (data.episode_run_time?.[0] ? `${data.episode_run_time[0]} min/ep` : '');
  const genres  = (data.genres || []).map(g => `<span class="genre-tag">${g.name}</span>`).join('');
  const poster  = posterUrl(data.poster_path, 'w185');

  document.getElementById('mediaInfo').innerHTML = `
    ${poster ? `<img class="media-poster" src="${poster}" alt="${title}" />` : ''}
    <div class="media-details">
      <h1 class="media-title">${title}</h1>
      <p class="media-meta">
        ⭐ ${rating} &nbsp;•&nbsp; ${year}
        ${runtime ? `&nbsp;•&nbsp; ${runtime}` : ''}
        &nbsp;•&nbsp; ${type === 'movie' ? 'Movie' : 'TV Show'}
      </p>
      <p class="media-overview">${data.overview || ''}</p>
      <div class="media-genres">${genres}</div>
    </div>`;
}

/* ── Server groups ─────────────────────────────────────────────────────────── */
function renderServerGroups() {
  const container = document.getElementById('serverGroups');
  container.innerHTML = '';
  SERVER_GROUPS.forEach((group, gi) => {
    const groupEl = document.createElement('div');
    groupEl.className = 'server-group';
    groupEl.innerHTML = `<div class="server-group-label">${group.label}</div>`;
    const btnsEl = document.createElement('div');
    btnsEl.className = 'server-btns';
    group.servers.forEach((srv, si) => {
      const flatIdx = ALL_SERVERS.indexOf(srv);
      const btn = document.createElement('button');
      btn.className = 'server-btn';
      btn.id = `srv-btn-${flatIdx}`;
      btn.innerHTML = `<span class="dot"></span>${srv.name}`;
      btn.onclick = () => playServer(flatIdx, true);
      btnsEl.appendChild(btn);
    });
    groupEl.appendChild(btnsEl);
    container.appendChild(groupEl);
  });
}

/* ── Play server ───────────────────────────────────────────────────────────── */
function playServer(flatIdx, manual = false) {
  if (flatIdx >= ALL_SERVERS.length) {
    showPlaceholder(true, '⚠️ No more servers available');
    showToast('All servers tried — none available');
    return;
  }

  const srv = ALL_SERVERS[flatIdx];
  state.activeServer = flatIdx;
  state.serverIndex  = flatIdx;

  // Update button states
  document.querySelectorAll('.server-btn').forEach(b => b.classList.remove('active'));
  const activeBtn = document.getElementById(`srv-btn-${flatIdx}`);
  if (activeBtn) activeBtn.classList.add('active');

  // Build URL
  const url = srv.fn(
    state.currentType,
    state.currentId,
    state.currentSeason,
    state.currentEpisode
  );

  showPlaceholder(true, `Loading ${srv.name}…`);

  const frame = document.getElementById('playerFrame');
  frame.src = '';

  // Apply sandbox
  applySandbox(frame);
  frame.src = url;

  // Hide placeholder after short delay (iframe load event unreliable cross-origin)
  setTimeout(() => showPlaceholder(false), 3000);

  if (!manual) {
    showToast(`Playing on ${srv.name}`);
  }
}

/* ── Sandbox ───────────────────────────────────────────────────────────────── */
function applySandbox(frame) {
  if (state.sandboxOn) {
    frame.setAttribute('sandbox',
      'allow-scripts allow-same-origin allow-forms allow-presentation allow-pointer-lock'
    );
  } else {
    frame.removeAttribute('sandbox');
  }
}

function toggleSandbox() {
  state.sandboxOn = !document.getElementById('sandboxToggle').checked;
  const status = document.getElementById('sandboxStatus');
  const hint   = document.getElementById('sandboxHint');
  if (state.sandboxOn) {
    status.textContent = 'ON';
    status.className   = 'badge badge-on';
    hint.textContent   = 'Disable if server won\'t load';
  } else {
    status.textContent = 'OFF';
    status.className   = 'badge badge-off';
    hint.textContent   = 'Sandbox disabled — ads/popups may appear';
  }
  // Reload current server with new sandbox setting
  if (state.activeServer !== null) {
    playServer(state.activeServer, true);
  }
}

/* ── Placeholder ───────────────────────────────────────────────────────────── */
function showPlaceholder(show, msg = 'Loading player…') {
  const ph = document.getElementById('playerPlaceholder');
  ph.classList.toggle('hidden', !show);
  if (show) {
    ph.innerHTML = `<div class="spinner"></div><p>${msg}</p>`;
  }
}

/* ── Season / Episode ──────────────────────────────────────────────────────── */
function renderSeasonSelect() {
  const sel = document.getElementById('seasonSelect');
  sel.innerHTML = '';
  state.seasons.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.season_number;
    opt.textContent = `Season ${s.season_number}`;
    sel.appendChild(opt);
  });
}

async function loadEpisodes() {
  const season = parseInt(document.getElementById('seasonSelect').value) || 1;
  state.currentSeason  = season;
  state.currentEpisode = 1;
  const grid = document.getElementById('episodeGrid');
  grid.innerHTML = '<div class="spinner" style="margin:12px auto"></div>';
  try {
    const data = await tmdb(`/tv/${state.currentId}/season/${season}`);
    grid.innerHTML = '';
    (data.episodes || []).forEach(ep => {
      const btn = document.createElement('button');
      btn.className = 'ep-btn' + (ep.episode_number === 1 ? ' active' : '');
      btn.textContent = `E${ep.episode_number}`;
      btn.title = ep.name || '';
      btn.onclick = () => selectEpisode(ep.episode_number, btn);
      grid.appendChild(btn);
    });
  } catch (e) {
    grid.innerHTML = '<p style="color:var(--text2)">Failed to load episodes</p>';
  }
}

function selectEpisode(epNum, btn) {
  state.currentEpisode = epNum;
  document.querySelectorAll('.ep-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  playServer(state.activeServer ?? 0, true);
}

/* ── Toast ─────────────────────────────────────────────────────────────────── */
let toastTimer;
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3000);
}
