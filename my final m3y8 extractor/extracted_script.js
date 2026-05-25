
// ══════════════════════════════════════════════════════════════════════
// CONFIG
// ══════════════════════════════════════════════════════════════════════
const JIKAN       = 'https://api.jikan.moe/v4';
const ANILIST_GQL = 'https://graphql.anilist.co';
const TMDB_KEY    = '6fad3f86b8452ee232deb7977d7dcf58';
const TMDB_BASE   = 'https://api.themoviedb.org/3';
const TMDB_IMG    = 'https://image.tmdb.org/t/p/w500';
const TMDB_IMG_BG = 'https://image.tmdb.org/t/p/original';
const ENC_API     = 'https://enc-dec.app/api';

const FALLBACK = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjMwMCIgdmlld0JveD0iMCAwIDIwMCAzMDAiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjIwMCIgaGVpZ2h0PSIzMDAiIGZpbGw9IiMwYjBiMjIiLz48dGV4dCB4PSI1MCUiIHk9IjUwJSIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMTMiIGZpbGw9IiM3YzNhZmYiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIj5ObyBJbWFnZTwvdGV4dD48L3N2Zz4=';

// ══════════════════════════════════════════════════════════════════════
// PROXY SYSTEM
// ══════════════════════════════════════════════════════════════════════
const PROXIES = {
  foxydoxy:   'https://foxy-doxy.andruilsyestems.workers.dev',
  donkabonka: 'https://donka-bonka-proxy.onrender.com',
};
let _proxy = 'foxydoxy';

function getProxyBase() {
  if (_proxy === 'custom') {
    const v = document.getElementById('proxyCustom').value.trim();
    return v && v.length > 5 ? v.replace(/\/$/, '') : PROXIES.foxydoxy;
  }
  return PROXIES[_proxy] || PROXIES.foxydoxy;
}

function buildProxyUrl(url) {
  if (!document.getElementById('useProxy').checked) return url;
  const headers = buildHeaders();
  const base = getProxyBase();
  const enc = encodeURIComponent(btoa(unescape(encodeURIComponent(url))));
  let out = `${base}/proxy?url=${enc}`;
  if (Object.keys(headers).length > 0) {
    const h = encodeURIComponent(btoa(unescape(encodeURIComponent(JSON.stringify(headers)))));
    out += `&headers=${h}`;
  }
  return out;
}

function buildHeaders() {
  const h = {};
  const ref = document.getElementById('hReferer').value.trim();
  const ori = document.getElementById('hOrigin').value.trim();
  const ua  = document.getElementById('hUA').value.trim();
  const ext = document.getElementById('hExtra').value.trim();
  if (ref) h['Referer']    = ref;
  if (ori) h['Origin']     = ori;
  if (ua)  h['User-Agent'] = ua;
  if (ext && ext.includes(':')) { const [k,...v]=ext.split(':'); h[k.trim()]=v.join(':').trim(); }
  return h;
}

function clearHeaders() {
  ['hReferer','hOrigin','hUA','hExtra'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('profileName').value='';
  toast('Headers cleared','⚠️');
}

function onProxyChange(radio) {
  _proxy = radio.value;
  document.querySelectorAll('.proxy-opt').forEach(el=>el.classList.remove('sel'));
  document.getElementById('popt-'+radio.value.replace(/-/g,''))?.classList.add('sel');
  document.getElementById('custom-wrap').style.display = radio.value==='custom' ? 'block' : 'none';
  const label = radio.value==='foxydoxy'?'Foxy Doxy':radio.value==='donkabonka'?'Donka Bonka':'Custom';
  document.getElementById('hdr-plbl').textContent = label;
  checkProxies();
}

async function pingProxy(key, baseUrl) {
  const dot = document.getElementById('pd-'+key.replace(/-/g,''));
  const lbl = document.getElementById('pl-'+key.replace(/-/g,''));
  try {
    const r = await fetch(baseUrl, { method:'HEAD', signal:AbortSignal.timeout(5000) });
    const ok = r.status < 500;
    if(dot){ dot.className='pdot '+(ok?'online':'offline'); }
    if(lbl) lbl.textContent = ok ? 'online' : 'offline';
    return ok;
  } catch {
    if(dot){ dot.className='pdot offline'; }
    if(lbl) lbl.textContent = 'offline';
    return false;
  }
}
async function checkProxies() {
  const [a,b] = await Promise.all([pingProxy('foxydoxy',PROXIES.foxydoxy),pingProxy('donkabonka',PROXIES.donkabonka)]);
  const dot = document.getElementById('hdr-pdot');
  if(dot) dot.className = 'pdot-sm '+(a||b?'':'off');
}
checkProxies();
setInterval(checkProxies, 30000);

function toggleProxyPanel() {
  document.getElementById('proxyPanel').classList.toggle('open');
  renderProfiles();
}

// ══════════════════════════════════════════════════════════════════════
// HEADER PROFILES
// ══════════════════════════════════════════════════════════════════════
const PROF_KEY = 'sv_profiles_v2';
function loadProfiles(){ try{ return JSON.parse(localStorage.getItem(PROF_KEY))||[]; }catch{ return []; } }
function saveProfilesLS(arr){ try{ localStorage.setItem(PROF_KEY,JSON.stringify(arr)); }catch{} }

function extractDomain(url) {
  try { return new URL(url.trim()).hostname; }
  catch { const m=url.match(/^(?:https?:\/\/)?([^\/\s:?#]+)/i); return m?m[1]:url.slice(0,40); }
}

function saveProfile() {
  const name = document.getElementById('profileName').value.trim();
  if (!name) { toast('Enter a profile name','⚠️'); return; }
  const ref = document.getElementById('hReferer').value.trim();
  const ori = document.getElementById('hOrigin').value.trim();
  const ua  = document.getElementById('hUA').value.trim();
  const ext = document.getElementById('hExtra').value.trim();
  if (!ref&&!ori&&!ua&&!ext) { toast('No headers to save','⚠️'); return; }
  const url = (document.getElementById('sinput').value||'').trim();
  const domain = url ? extractDomain(url) : '';
  const profiles = loadProfiles();
  const idx = profiles.findIndex(p=>p.name.toLowerCase()===name.toLowerCase());
  const p = { id: idx>=0?profiles[idx].id:Date.now(), name, domain, referer:ref, origin:ori, ua, extra:ext, savedAt:new Date().toISOString() };
  if(idx>=0) profiles[idx]=p; else profiles.unshift(p);
  saveProfilesLS(profiles);
  document.getElementById('profileName').value='';
  renderProfiles();
  toast('Profile saved: '+name,'✅');
}

function applyProfile(id) {
  const p = loadProfiles().find(x=>x.id===id);
  if(!p) return;
  document.getElementById('hReferer').value = p.referer||'';
  document.getElementById('hOrigin').value  = p.origin||'';
  document.getElementById('hUA').value      = p.ua||'';
  document.getElementById('hExtra').value   = p.extra||'';
  toast('Applied: '+p.name,'✅');
}

function deleteProfile(id) {
  if(!confirm('Delete this profile?')) return;
  saveProfilesLS(loadProfiles().filter(x=>x.id!==id));
  renderProfiles();
  toast('Profile deleted','⚠️');
}

function renderProfiles() {
  const body = document.getElementById('profilesBody');
  if (!body) return;
  const q = (document.getElementById('profileSearch')?.value||'').toLowerCase();
  const profiles = loadProfiles().filter(p=>p.name.toLowerCase().includes(q)||(p.domain||'').toLowerCase().includes(q));
  if (!profiles.length) { body.innerHTML='<div style="color:var(--muted);font-size:11.5px;padding:8px 0">No profiles saved.</div>'; return; }
  body.innerHTML = profiles.map(p=>`
    <div class="pcard">
      <div class="pcard-hd">
        <div><div class="pcard-name">${esc(p.name)}</div><div class="pcard-domain">${p.domain?'🌐 '+esc(p.domain):''}</div></div>
        <div class="pcard-acts">
          <button class="pcard-btn load" title="Apply" onclick="applyProfile(${p.id})">▶</button>
          <button class="pcard-btn del" title="Delete" onclick="deleteProfile(${p.id})">✕</button>
        </div>
      </div>
      <div class="pcard-body">
        ${p.referer?`<div class="pcard-row"><span class="pk">referer</span><span class="pv">${esc(p.referer)}</span></div>`:''}
        ${p.origin?`<div class="pcard-row"><span class="pk">origin</span><span class="pv">${esc(p.origin)}</span></div>`:''}
        ${p.ua?`<div class="pcard-row"><span class="pk">ua</span><span class="pv">${esc(p.ua)}</span></div>`:''}
        ${p.extra?`<div class="pcard-row"><span class="pk">extra</span><span class="pv">${esc(p.extra)}</span></div>`:''}
      </div>
    </div>`).join('');
}

let _matchedProfId = null;
function checkUrlForProfile(url) {
  const bar = document.getElementById('matchBar');
  if (!url) { bar.classList.remove('on'); _matchedProfId=null; return; }
  const domain = extractDomain(url);
  const match = loadProfiles().find(p=>p.domain&&domain.includes(p.domain));
  if (match) { _matchedProfId=match.id; document.getElementById('matchName').textContent=match.name; bar.classList.add('on'); }
  else { bar.classList.remove('on'); _matchedProfId=null; }
}
function applyMatchedProfile() { if(_matchedProfId) applyProfile(_matchedProfId); }

function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ══════════════════════════════════════════════════════════════════════
// HLS PLAYER ENGINE
// ══════════════════════════════════════════════════════════════════════
let hlsInstances = { a: null, t: null };

function isStreamUrl(url) {
  if (typeof url !== 'string') return false;
  const lc = url.toLowerCase();
  return lc.includes('.m3u8') || lc.includes('.mp4') || lc.includes('m3u8') || lc.includes('/hls/');
}

function openHlsLayer(scope, streamUrl, label) {
  const layer   = scope === 'a' ? document.getElementById('hls-layer') : document.getElementById('t-hls-layer');
  const video   = document.getElementById('hls-video-'+scope);
  const loading = document.getElementById('hls-loading-'+scope);
  const errEl   = document.getElementById('hls-err-'+scope);
  const lblEl   = document.getElementById('hls-lbl-'+scope);

  if (hlsInstances[scope]) { try{ hlsInstances[scope].destroy(); }catch{} hlsInstances[scope]=null; }
  video.pause(); video.src='';
  if (lblEl) lblEl.textContent = label||streamUrl;
  loading.classList.remove('hidden');
  errEl.style.display='none';
  layer.style.display='flex';

  setStreamStatus(scope,'loading','Connecting…');

  // Resolve hlsforge proxy
  let finalUrl = streamUrl;
  try {
    const u = new URL(streamUrl);
    if (u.hostname==='hlsforge.com') { const r=u.searchParams.get('url'); if(r) finalUrl=decodeURIComponent(r); }
  } catch{}

  // Optionally proxy
  const proxied = buildProxyUrl(finalUrl);

  function onError() {
    loading.classList.add('hidden');
    errEl.style.display='flex';
    setStreamStatus(scope,'error','Stream failed');
    toast('Stream failed to load','❌');
  }

  const lc = finalUrl.toLowerCase();
  if (lc.includes('.mp4') || lc.includes('mp4')) {
    video.src = proxied;
    video.onloadeddata = ()=>{ loading.classList.add('hidden'); setStreamStatus(scope,'live','Playing'); };
    video.onerror = onError;
    video.play().catch(()=>{});
  } else {
    if (typeof Hls !== 'undefined' && Hls.isSupported()) {
      hlsInstances[scope] = new Hls({ enableWorker:true });
      hlsInstances[scope].loadSource(proxied);
      hlsInstances[scope].attachMedia(video);
      hlsInstances[scope].on(Hls.Events.MANIFEST_PARSED, ()=>{
        loading.classList.add('hidden');
        video.play().catch(()=>{});
        setStreamStatus(scope,'live','Playing — HLS');
      });
      hlsInstances[scope].on(Hls.Events.ERROR, (e,d)=>{ if(d.fatal) onError(); });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = proxied;
      video.onloadeddata = ()=>{ loading.classList.add('hidden'); setStreamStatus(scope,'live','Playing'); };
      video.onerror = onError;
      video.play().catch(()=>{});
    } else { onError(); }
  }
}

function closeHlsLayer(scope) {
  const layer = scope==='a'? document.getElementById('hls-layer') : document.getElementById('t-hls-layer');
  const video = document.getElementById('hls-video-'+scope);
  layer.style.display='none';
  video.pause(); video.src='';
  if (hlsInstances[scope]) { try{ hlsInstances[scope].destroy(); }catch{} hlsInstances[scope]=null; }
  setStreamStatus(scope,'','idle');
}

function setStreamStatus(scope, state, txt) {
  const dot = document.getElementById(scope+'-ss-dot');
  const el  = document.getElementById(scope+'-ss-txt');
  if(dot) dot.className='ss-dot '+(state||'');
  if(el) el.textContent=txt;
}

// PostMessage stream interceptor
window.addEventListener('message', evt => {
  let data = evt.data;
  if (typeof data === 'string') {
    if (isStreamUrl(data)) {
      const scope = document.getElementById('v-tmdb-watch').classList.contains('on')?'t':'a';
      openHlsLayer(scope, data, data);
      return;
    }
    try{ data=JSON.parse(data); }catch{ return; }
  }
  if (typeof data === 'object' && data) {
    const url = data.url||data.stream||data.src||data.href||'';
    if (url && isStreamUrl(url)) {
      const scope = document.getElementById('v-tmdb-watch').classList.contains('on')?'t':'a';
      openHlsLayer(scope, url, data.title||url);
    }
  }
  // Episode ended detection (anime)
  if (document.getElementById('v-watch').classList.contains('on')) {
    const flat = typeof evt.data==='string'?evt.data.toLowerCase():JSON.stringify(data).toLowerCase();
    const endSigs = ['"ended"','episode:ended','videoended','"complete"','playbackended','"finish"'];
    if (endSigs.some(s=>flat.includes(s))) { if(SETTINGS.autonext) onEpEnded(); }
  }
});

// ══════════════════════════════════════════════════════════════════════
// ENC-DEC SERVER EXTRACTION
// ══════════════════════════════════════════════════════════════════════

// TMDB server definitions — use enc-dec.app API to get real HLS streams
const TMDB_SERVERS = [
  {
    id:'vidlink', label:'VidLink', icon:'🔗',
    async getUrl(tmdbId, type, season, ep) {
      try {
        const resp = await fetch(`${ENC_API}/enc-vidlink?text=${tmdbId}`);
        const d = await resp.json();
        if(d.status!==200) throw 'enc failed';
        const enc = d.result;
        let apiUrl;
        if(type==='movie') apiUrl=`https://vidlink.pro/api/b/movie/${enc}`;
        else apiUrl=`https://vidlink.pro/api/b/tv/${enc}/${season}/${ep}`;
        const r2 = await fetch(apiUrl, {headers:{Origin:'https://vidlink.pro',Referer:'https://vidlink.pro/','User-Agent':navigator.userAgent}});
        const data = await r2.json();
        return extractStreamFromData(data);
      } catch(e){ console.warn('vidlink:',e); return null; }
    }
  },
  {
    id:'vidsync', label:'VidSync', icon:'⚡',
    async getUrl(tmdbId, type, season, ep) {
      try {
        const resp = await fetch(`${ENC_API}/enc-vidsync`);
        const d = await resp.json();
        if(d.status!==200) throw 'enc failed';
        const q = type==='movie'
          ? `?title=&type=movie&releaseYear=&mediaId=${tmdbId}&serverName=cinevault`
          : `?title=&type=tv&releaseYear=&mediaId=${tmdbId}&serverName=cinevault&season=${season}&episode=${ep}`;
        const r2 = await fetch('https://vidsync.xyz/api/stream/fetch'+q, {headers:{'X-Cf-Turnstile':d.result.token,'X-Requested-With':'XMLHttpRequest',Origin:'https://vidsync.xyz',Referer:'https://vidsync.xyz/'}});
        const text = await r2.text();
        const r3 = await fetch(ENC_API+'/dec-vidsync', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,id:tmdbId})});
        const d3 = await r3.json();
        if(d3.status!==200) throw 'dec failed';
        return extractStreamFromData(d3.result);
      } catch(e){ console.warn('vidsync:',e); return null; }
    }
  },
  {
    id:'rivestream', label:'RiveStream', icon:'🎬',
    async getUrl(tmdbId, type, season, ep) {
      // Served via iframe since it's a download page — returns null here, iframe handles
      return null;
    },
    getIframeUrl(tmdbId, type, season, ep) {
      if(type==='movie') return `https://rivestream.ru/download?type=movie&id=${tmdbId}`;
      return `https://rivestream.ru/download?type=tv&id=${tmdbId}&season=${season}&episode=${ep}`;
    }
  },
  {
    id:'vidsrc', label:'VidSrc', icon:'📺',
    async getUrl(tmdbId, type, season, ep) {
      // VidSrc.to — embed, return null for iframe
      return null;
    },
    getIframeUrl(tmdbId, type, season, ep) {
      if(type==='movie') return `https://vidsrc.to/embed/movie/${tmdbId}`;
      return `https://vidsrc.to/embed/tv/${tmdbId}/${season}/${ep}`;
    }
  },
  {
    id:'embed2',label:'EmbedSU',icon:'🎭',
    async getUrl(){ return null; },
    getIframeUrl(tmdbId,type,season,ep){
      if(type==='movie') return `https://embed.su/embed/movie/${tmdbId}`;
      return `https://embed.su/embed/tv/${tmdbId}/${season}/${ep}`;
    }
  }
];

function extractStreamFromData(data) {
  if (!data) return null;
  const str = typeof data==='string'?data:JSON.stringify(data);
  // Look for m3u8 or mp4
  const m3u8 = str.match(/https?:\/\/[^\s"',]+\.m3u8[^\s"',]*/i);
  if (m3u8) return m3u8[0];
  const mp4 = str.match(/https?:\/\/[^\s"',]+\.mp4[^\s"',]*/i);
  if (mp4) return mp4[0];
  // Check for stream object
  if (typeof data==='object') {
    if (data.stream) return data.stream;
    if (data.url && isStreamUrl(data.url)) return data.url;
    if (data.sources) {
      const src = Array.isArray(data.sources)?data.sources[0]:data.sources;
      if (typeof src==='string' && isStreamUrl(src)) return src;
      if (src?.url && isStreamUrl(src.url)) return src.url;
      if (src?.file && isStreamUrl(src.file)) return src.file;
    }
  }
  return null;
}

// MAL-based anime servers
const MAL_SERVERS = [
  { id:'mp-mal-dub',  label:'MegaPlay DUB', icon:'🇺🇸', buildUrl:(id,ep)=>`https://megaplay.buzz/stream/mal/${id}/${ep}/dub` },
  { id:'mp-mal-sub',  label:'MegaPlay SUB', icon:'🎌', buildUrl:(id,ep)=>`https://megaplay.buzz/stream/mal/${id}/${ep}/sub` },
  { id:'vw-mal-dub',  label:'VidWish DUB',  icon:'🔊', buildUrl:(id,ep)=>`https://vidwish.live/stream/mal/${id}/${ep}/dub` },
  { id:'vw-mal-sub',  label:'VidWish SUB',  icon:'📺', buildUrl:(id,ep)=>`https://vidwish.live/stream/mal/${id}/${ep}/sub` },
];
const AL_SERVERS = [
  { id:'mp-al-dub', label:'AniList DUB', icon:'🇺🇸', buildUrl:(id,ep)=>`https://megaplay.buzz/stream/ani/${id}/${ep}/dub` },
  { id:'mp-al-sub', label:'AniList SUB', icon:'🎌', buildUrl:(id,ep)=>`https://megaplay.buzz/stream/ani/${id}/${ep}/sub` },
];
const DEFAULT_SRV = 'mp-mal-dub';

// ══════════════════════════════════════════════════════════════════════
// STATE
// ══════════════════════════════════════════════════════════════════════
let CUR = { anime:null, ep:1, malId:null, alId:null, srvId:DEFAULT_SRV };
let TMDB_CUR = { content:null, type:'movie', season:1, ep:1, srv:'rivestream' };
let heroArr=[], heroIdx=0, heroTmr=null;
const CACHE = {};
let SETTINGS = { autoplay:true, autonext:true };
let currentMode = 'anime';
let anRaf=null, anStart=null;
let endedHandledForEp = -1;
const AN_SECS = 10;

function loadSettings(){ try{ const s=JSON.parse(localStorage.getItem('sv_settings3')); if(s) Object.assign(SETTINGS,s); }catch{} }
function saveSettings(){ try{ localStorage.setItem('sv_settings3',JSON.stringify(SETTINGS)); }catch{} }
loadSettings();

// ══════════════════════════════════════════════════════════════════════
// AUTO-NEXT
// ══════════════════════════════════════════════════════════════════════
function onEpEnded() {
  if(endedHandledForEp===CUR.ep) return;
  endedHandledForEp=CUR.ep;
  const total=CUR.anime?.episodes||1;
  if(CUR.ep>=total){ toast('🎉 Last episode!','🎉'); return; }
  if(SETTINGS.autonext) showANOverlay();
  else showEndedBar();
}
function showANOverlay() {
  const nextEp=CUR.ep+1;
  document.getElementById('anEp').textContent=`Episode ${nextEp}`;
  document.getElementById('anNum').textContent=AN_SECS;
  document.getElementById('anBar').style.width='100%';
  document.getElementById('anOv').classList.add('on');
  anStart=performance.now();
  if(anRaf) cancelAnimationFrame(anRaf);
  function tick(){
    const e=performance.now()-anStart, rem=Math.max(0,AN_SECS*1000-e);
    document.getElementById('anNum').textContent=Math.ceil(rem/1000);
    document.getElementById('anBar').style.width=((rem/(AN_SECS*1000))*100).toFixed(2)+'%';
    if(rem<=0){ hideAN(); playNextNow(); } else anRaf=requestAnimationFrame(tick);
  }
  tick();
}
function hideAN(){ document.getElementById('anOv').classList.remove('on'); if(anRaf){cancelAnimationFrame(anRaf);anRaf=null;} }
function playNextNow(){
  hideAN(); dismissEnded();
  if(CUR.ep>=(CUR.anime?.episodes||1)) return;
  CUR.ep++; endedHandledForEp=-1;
  document.querySelectorAll('#a-epgrid .epbtn').forEach((b,i)=>b.classList.toggle('on',i+1===CUR.ep));
  playCurrentAnimeEp(); toast(`▶ Episode ${CUR.ep}`,'🎬');
}
function cancelAN(){ hideAN(); toast('Auto Next cancelled','⏹️'); }
function showEndedBar(){ if(CUR.ep<(CUR.anime?.episodes||1)) document.getElementById('epEnded').classList.add('on'); }
function dismissEnded(){ document.getElementById('epEnded').classList.remove('on'); }
function toggleAutoplay(){ SETTINGS.autoplay=!SETTINGS.autoplay; setToggle('autoplayToggle',SETTINGS.autoplay); saveSettings(); toast(SETTINGS.autoplay?'Autoplay ON':'Autoplay OFF'); }
function toggleAutonext(){ SETTINGS.autonext=!SETTINGS.autonext; setToggle('autonextToggle',SETTINGS.autonext); saveSettings(); if(!SETTINGS.autonext)hideAN(); toast(SETTINGS.autonext?'Auto Next ON':'Auto Next OFF'); }
function setToggle(id,on){ document.getElementById(id)?.classList.toggle('on',on); }

// ══════════════════════════════════════════════════════════════════════
// TOAST
// ══════════════════════════════════════════════════════════════════════
let _tTimer=null;
function toast(msg, icon='✅', dur=2800) {
  const c=document.getElementById('toastWrap');
  const t=document.createElement('div'); t.className='toast';
  t.innerHTML=`<span>${icon}</span><span>${msg}</span>`;
  c.appendChild(t);
  setTimeout(()=>{ t.classList.add('out'); setTimeout(()=>t.remove(),300); },dur);
}

// ══════════════════════════════════════════════════════════════════════
// VIEWS
// ══════════════════════════════════════════════════════════════════════
function showView(id) {
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('on'));
  document.getElementById(id).classList.add('on');
  window.scrollTo(0,0);
  document.getElementById('modeRow').style.display = id==='v-home'?'none':'block';
  if(id!=='v-tmdb-watch') closeHlsLayer('t');
  if(id!=='v-watch') closeHlsLayer('a');
}
function goHome(){ showView('v-home'); document.getElementById('modeRow').style.display='none'; }

function setMode(mode) {
  currentMode=mode;
  document.getElementById('tab-anime').classList.toggle('on',mode==='anime');
  document.getElementById('tab-tmdb').classList.toggle('on',mode==='tmdb');
}

// ══════════════════════════════════════════════════════════════════════
// JIKAN / ANIME
// ══════════════════════════════════════════════════════════════════════
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function jikan(path) {
  if(CACHE['j_'+path]) return CACHE['j_'+path];
  await sleep(340);
  try{
    const r=await fetch(JIKAN+path);
    if(!r.ok) throw r.status;
    const d=await r.json();
    CACHE['j_'+path]=d; return d;
  }catch{ return null; }
}
function getImg(a){ return a?.images?.jpg?.large_image_url||a?.images?.jpg?.image_url||FALLBACK; }
function getTitle(a){ return a.title_english||a.title||'Unknown'; }

// ══════════════════════════════════════════════════════════════════════
// TMDB
// ══════════════════════════════════════════════════════════════════════
async function tmdb(path) {
  const k='t_'+path;
  if(CACHE[k]) return CACHE[k];
  try{
    const r=await fetch(`${TMDB_BASE}${path}${path.includes('?')?'&':'?'}api_key=${TMDB_KEY}`);
    if(!r.ok) throw r.status;
    const d=await r.json();
    CACHE[k]=d; return d;
  }catch{ return null; }
}
function getTmdbImg(path){ return path?`${TMDB_IMG}${path}`:FALLBACK; }
function getTmdbBg(path){ return path?`${TMDB_IMG_BG}${path}`:''; }
function getTmdbTitle(c){ return c.title||c.name||'Unknown'; }
function getTmdbYear(c){ const d=c.release_date||c.first_air_date; return d?new Date(d).getFullYear():''; }

// ══════════════════════════════════════════════════════════════════════
// SEARCH DISPATCHER
// ══════════════════════════════════════════════════════════════════════
async function doSearch() {
  const q=document.getElementById('sinput').value.trim();
  if(!q) return;
  if(currentMode==='tmdb') await doTmdbSearch(q);
  else await doAnimeSearch(q);
}

async function doAnimeSearch(q) {
  document.getElementById('search-ttl').textContent=`Search: "${q}"`;
  document.getElementById('search-grid').innerHTML='<div class="loading-st"><div class="spin"></div></div>';
  showView('v-search');
  const d=await jikan(`/anime?q=${encodeURIComponent(q)}&limit=24`);
  const g=document.getElementById('search-grid'); g.innerHTML='';
  (d?.data||[]).forEach(a=>g.appendChild(makeAnimeCard(a)));
  if(!d?.data?.length) g.innerHTML='<div class="err-st">No results.</div>';
}

async function doTmdbSearch(q) {
  document.getElementById('tmdb-ttl').textContent=`Search: "${q}"`;
  document.getElementById('tmdb-grid').innerHTML='<div class="loading-st"><div class="spin"></div></div>';
  showView('v-tmdb-search');
  const d=await tmdb(`/search/multi?query=${encodeURIComponent(q)}&language=en-US&page=1`);
  const g=document.getElementById('tmdb-grid'); g.innerHTML='';
  const results=(d?.results||[]).filter(r=>r.media_type==='movie'||r.media_type==='tv');
  if(!results.length){ g.innerHTML='<div class="err-st">No results.</div>'; return; }
  results.forEach(r=>g.appendChild(makeTmdbCard(r)));
}

// ══════════════════════════════════════════════════════════════════════
// CARDS
// ══════════════════════════════════════════════════════════════════════
function makeAnimeCard(a) {
  const c=document.createElement('div'); c.className='acard';
  c.innerHTML=`<img src="${getImg(a)}" class="acard-img" loading="lazy" onerror="this.src='${FALLBACK}'"><div class="acard-ov"><div class="acard-play"><i class="fas fa-play"></i></div><div class="acard-ttl">${getTitle(a)}</div><div class="acard-sub">⭐ ${a.score||'N/A'} · ${a.episodes||'?'} eps</div></div>${a.score?`<span class="acard-score">⭐ ${a.score}</span>`:''}`;
  c.onclick=()=>openAnime(a); return c;
}
function makeTmdbCard(r) {
  const c=document.createElement('div'); c.className='acard';
  const poster=getTmdbImg(r.poster_path);
  const title=getTmdbTitle(r);
  const year=getTmdbYear(r);
  const type=r.media_type==='movie'?'Movie':'TV';
  c.innerHTML=`<img src="${poster}" class="acard-img" loading="lazy" onerror="this.src='${FALLBACK}'"><div class="acard-ov"><div class="acard-play"><i class="fas fa-play"></i></div><span class="acard-type-badge">${type}</span><div class="acard-ttl">${title}</div><div class="acard-sub">${year}</div></div>${r.vote_average?`<span class="acard-score">⭐ ${r.vote_average.toFixed(1)}</span>`:''}`;
  c.onclick=()=>openTmdbContent(r); return c;
}

// ══════════════════════════════════════════════════════════════════════
// OPEN ANIME
// ══════════════════════════════════════════════════════════════════════
function openAnime(a) {
  CUR={anime:a, ep:1, malId:a.mal_id, alId:null, srvId:DEFAULT_SRV};
  endedHandledForEp=-1;
  showView('v-watch');
  renderAnimeInfo(a);
  buildEpGrid(a);
  buildAnimeServerTabs();
  setToggle('autoplayToggle',SETTINGS.autoplay);
  setToggle('autonextToggle',SETTINGS.autonext);
  playCurrentAnimeEp();
  getAnilistId(CUR.malId).then(alId=>{
    if(alId){ CUR.alId=alId; document.getElementById('wbadge').innerHTML=`<i class="fas fa-fingerprint"></i> MAL ${CUR.malId} · AL ${alId}`; appendALTabs(alId); }
  });
  loadAnimeRelated(CUR.malId);
}

function renderAnimeInfo(a) {
  const t=getTitle(a);
  const syn=(a.synopsis||'No synopsis.').replace(/\[Written.*?\]/gs,'').trim();
  const genres=(a.genres||[]).slice(0,4).map(g=>`<span class="itag">${g.name}</span>`).join('');
  document.getElementById('wtitle').textContent=t;
  document.getElementById('wbadge').innerHTML=`<i class="fas fa-fingerprint"></i> MAL ${a.mal_id}`;
  document.getElementById('a-info-card').innerHTML=`<img src="${getImg(a)}" class="info-poster" alt="${t}" onerror="this.src='${FALLBACK}'"><div class="info-body"><div class="info-ttl">${t}</div><div class="imeta"><span class="itag a">⭐ ${a.score||'N/A'}</span><span class="itag b">${a.episodes||'?'} eps</span><span class="itag c">MAL #${a.mal_id}</span>${a.year?`<span class="itag">${a.year}</span>`:''}<span class="itag">${a.status||''}</span>${genres}</div><div class="info-syn">${syn}</div></div>`;
}

function buildEpGrid(a) {
  const total=Math.max(a.episodes||1,1);
  const g=document.getElementById('a-epgrid'); g.innerHTML='';
  document.getElementById('a-epcnt').textContent=`${total} eps`;
  for(let i=1;i<=total;i++){
    const btn=document.createElement('button');
    btn.className='epbtn'+(i===1?' on':'');
    btn.textContent=i; btn.id=`aep-${i}`;
    btn.onclick=()=>{
      document.querySelectorAll('#a-epgrid .epbtn').forEach(b=>b.classList.remove('on'));
      btn.classList.add('on'); CUR.ep=i; dismissEnded(); endedHandledForEp=-1;
      playCurrentAnimeEp();
    };
    g.appendChild(btn);
  }
}

function buildAnimeServerTabs() {
  const el=document.getElementById('a-srv-tabs'); el.innerHTML='';
  MAL_SERVERS.forEach(s=>{
    const btn=document.createElement('button');
    btn.className='stab'+(s.id===DEFAULT_SRV?' on':'');
    btn.dataset.sid=s.id;
    btn.innerHTML=`<span class="sdot"></span>${s.icon} ${s.label}`;
    btn.onclick=()=>{
      document.querySelectorAll('#a-srv-tabs .stab').forEach(b=>b.classList.remove('on'));
      btn.classList.add('on'); CUR.srvId=s.id; endedHandledForEp=-1;
      playCurrentAnimeEp();
    };
    el.appendChild(btn);
  });
}
function appendALTabs(alId) {
  const el=document.getElementById('a-srv-tabs');
  const sep=document.createElement('span'); sep.style='display:inline-flex;align-items:center;padding:0 4px;color:var(--muted);font-size:10px;font-family:var(--ff-mono)'>'; sep.textContent='|'; el.appendChild(sep);
  AL_SERVERS.forEach(s=>{
    const btn=document.createElement('button'); btn.className='stab';
    btn.innerHTML=`<span class="sdot"></span>${s.icon} ${s.label}`;
    btn.onclick=()=>{
      document.querySelectorAll('#a-srv-tabs .stab').forEach(b=>b.classList.remove('on'));
      btn.classList.add('on'); CUR.srvId=s.id; endedHandledForEp=-1;
      playCurrentAnimeEp();
    };
    el.appendChild(btn);
  });
}

function playCurrentAnimeEp() {
  dismissEnded();
  const malSrv=MAL_SERVERS.find(s=>s.id===CUR.srvId);
  const alSrv=AL_SERVERS.find(s=>s.id===CUR.srvId);
  let url, label;
  if(malSrv){ url=malSrv.buildUrl(CUR.malId,CUR.ep); label=`${malSrv.label} · Ep ${CUR.ep}`; }
  else if(alSrv&&CUR.alId){ url=alSrv.buildUrl(CUR.alId,CUR.ep); label=`${alSrv.label} · Ep ${CUR.ep}`; }
  else{ url=MAL_SERVERS[0].buildUrl(CUR.malId,CUR.ep); label=`${MAL_SERVERS[0].label} · Ep ${CUR.ep}`; }
  document.getElementById('vplayer').src=url;
  document.getElementById('weplbl').textContent=label;
  document.querySelectorAll('#a-epgrid .epbtn').forEach((b,i)=>b.classList.toggle('on',i+1===CUR.ep));
  const btn=document.getElementById(`aep-${CUR.ep}`);
  if(btn) btn.scrollIntoView({block:'nearest',behavior:'smooth'});
  setStreamStatus('a','','Iframe loaded');
}

async function getAnilistId(malId) {
  if(CACHE['al_'+malId]) return CACHE['al_'+malId];
  try{
    const r=await fetch(ANILIST_GQL,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:`{Media(idMal:${malId},type:ANIME){id}}`})});
    const d=await r.json();
    const id=d?.data?.Media?.id||null;
    CACHE['al_'+malId]=id; return id;
  }catch{ return null; }
}

async function loadAnimeRelated(malId) {
  const el=document.getElementById('a-rellist');
  el.innerHTML='<div class="loading-st"><div class="spin"></div></div>';
  const d=await jikan(`/anime/${malId}/recommendations`);
  el.innerHTML='';
  const list=d?.data||[];
  if(!list.length){ el.innerHTML='<p style="color:var(--muted);padding:10px;font-size:12.5px">No recommendations.</p>'; return; }
  list.slice(0,7).forEach(r=>{
    const a=r.entry;
    const div=document.createElement('div'); div.className='relitem';
    div.innerHTML=`<img src="${a.images?.jpg?.image_url||FALLBACK}" class="relthumb" onerror="this.src='${FALLBACK}'"><div class="relinfo"><div class="relttl">${a.title}</div><div class="relsub">MAL #${a.mal_id}</div></div><i class="fas fa-play" style="color:var(--acc);font-size:11px"></i>`;
    div.onclick=async()=>{ const full=await jikan(`/anime/${a.mal_id}`); if(full?.data) openAnime(full.data); };
    el.appendChild(div);
  });
}

// ══════════════════════════════════════════════════════════════════════
// OPEN TMDB CONTENT
// ══════════════════════════════════════════════════════════════════════
async function openTmdbContent(r) {
  TMDB_CUR={content:r,type:r.media_type,season:1,ep:1,srv:'rivestream'};
  showView('v-tmdb-watch');
  renderTmdbInfo(r);
  buildTmdbServerTabs();

  if(r.media_type==='tv'){
    document.getElementById('tw-eppanel').style.display='block';
    await loadTmdbSeasons(r.id);
  } else {
    document.getElementById('tw-eppanel').style.display='none';
    await playTmdbContent();
  }
  loadTmdbSimilar(r.id,r.media_type);
}

function renderTmdbInfo(r) {
  const title=getTmdbTitle(r);
  const year=getTmdbYear(r);
  const score=r.vote_average?r.vote_average.toFixed(1):'N/A';
  const overview=(r.overview||'No overview.').slice(0,300);
  const type=r.media_type==='movie'?'Movie':'TV Show';
  const poster=getTmdbImg(r.poster_path);
  const bg=getTmdbBg(r.backdrop_path||r.poster_path);
  document.getElementById('tw-title').textContent=title;
  document.getElementById('tw-badge').innerHTML=`<i class="fas fa-film"></i> TMDB ${r.id}`;
  document.getElementById('tw-ep-lbl').textContent=type+(year?` · ${year}`:'');
  document.getElementById('tw-info-card').innerHTML=`${bg?`<img src="${bg}" class="info-poster" style="aspect-ratio:16/9;object-position:center 20%" onerror="this.src='${poster}'">`:`<img src="${poster}" class="info-poster" onerror="this.src='${FALLBACK}'">`}<div class="info-body"><div class="info-ttl">${title}</div><div class="imeta"><span class="itag a">⭐ ${score}</span><span class="itag b">${type}</span>${year?`<span class="itag">${year}</span>`:''}</div><div class="info-syn">${overview}</div></div>`;
}

function buildTmdbServerTabs() {
  const el=document.getElementById('t-srv-tabs'); el.innerHTML='';
  TMDB_SERVERS.forEach((s,i)=>{
    const btn=document.createElement('button');
    btn.className='stab'+(i===0?' on':'');
    btn.dataset.sid=s.id;
    btn.innerHTML=`<span class="sdot"></span>${s.icon} ${s.label}`;
    btn.onclick=async()=>{
      document.querySelectorAll('#t-srv-tabs .stab').forEach(b=>b.classList.remove('on'));
      btn.classList.add('on'); TMDB_CUR.srv=s.id;
      closeHlsLayer('t');
      btn.classList.add('loading-srv');
      await playTmdbContent();
      btn.classList.remove('loading-srv');
    };
    el.appendChild(btn);
  });
}

async function loadTmdbSeasons(tmdbId) {
  const sel=document.getElementById('tw-season-sel'); sel.innerHTML='';
  const d=await tmdb(`/tv/${tmdbId}?language=en-US`);
  if(!d) return;
  const seasons=(d.seasons||[]).filter(s=>s.season_number>0);
  seasons.forEach(s=>{
    const o=document.createElement('option');
    o.value=s.season_number;
    o.textContent=`Season ${s.season_number} (${s.episode_count} ep)`;
    sel.appendChild(o);
  });
  if(seasons.length){ TMDB_CUR.season=seasons[0].season_number; await loadTmdbEps(); }
}

async function loadTmdbEps() {
  const g=document.getElementById('tw-epgrid'); g.innerHTML='';
  const d=await tmdb(`/tv/${TMDB_CUR.content.id}/season/${TMDB_CUR.season}?language=en-US`);
  const eps=d?.episodes||[];
  document.getElementById('tw-epcnt').textContent=`${eps.length} eps`;
  eps.forEach((ep,i)=>{
    const btn=document.createElement('button'); btn.className='epbtn'+(i===0?' on':'');
    btn.textContent=ep.episode_number; btn.id=`tep-${ep.episode_number}`;
    btn.onclick=async()=>{
      document.querySelectorAll('#tw-epgrid .epbtn').forEach(b=>b.classList.remove('on'));
      btn.classList.add('on'); TMDB_CUR.ep=ep.episode_number;
      closeHlsLayer('t'); await playTmdbContent(); updateTmdbEpLbl();
    };
    g.appendChild(btn);
  });
  if(eps.length){ TMDB_CUR.ep=eps[0].episode_number; await playTmdbContent(); updateTmdbEpLbl(); }
}

async function onTmdbSeasonChange() {
  TMDB_CUR.season=parseInt(document.getElementById('tw-season-sel').value);
  closeHlsLayer('t');
  await loadTmdbEps();
}

function updateTmdbEpLbl() {
  const t=TMDB_CUR.type==='tv'?`Season ${TMDB_CUR.season} · Episode ${TMDB_CUR.ep}`:'';
  document.getElementById('tw-ep-lbl').textContent=(TMDB_CUR.type==='tv'?'TV Show':'Movie')+(t?` · ${t}`:'');
}

async function playTmdbContent() {
  const srv=TMDB_SERVERS.find(s=>s.id===TMDB_CUR.srv)||TMDB_SERVERS[0];
  const {content,type,season,ep}=TMDB_CUR;
  const id=content.id;

  setStreamStatus('t','loading','Fetching stream…');

  // Try to get direct stream URL first
  let streamUrl=null;
  if(srv.getUrl) {
    try { streamUrl=await srv.getUrl(id,type,season,ep); }
    catch(e){ console.warn('server getUrl error:',e); }
  }

  if(streamUrl) {
    // Got a direct stream URL — play inline
    openHlsLayer('t', streamUrl, `${srv.label} — ${getTmdbTitle(content)}`);
    // Mark in tab
    document.querySelectorAll('#t-srv-tabs .stab').forEach(b=>b.classList.toggle('found',b.dataset.sid===srv.id));
    updateTmdbEpLbl();
    toast(`Stream found via ${srv.label}`,'✅');
    return;
  }

  // No direct stream — use iframe
  if(srv.getIframeUrl) {
    const iurl=srv.getIframeUrl(id,type,season,ep);
    document.getElementById('tvplayer').src=iurl;
    document.getElementById('t-hls-layer').style.display='none';
    setStreamStatus('t','','Iframe loaded — click a link to play inline');
    updateTmdbEpLbl();
    // If iframe-only servers fail, try next server automatically
    return;
  }

  // Fallback: try all servers sequentially
  toast('Trying next server…','🔄');
  const idx=TMDB_SERVERS.findIndex(s=>s.id===srv.id);
  const next=TMDB_SERVERS[(idx+1)%TMDB_SERVERS.length];
  if(next&&next.id!==srv.id){
    TMDB_CUR.srv=next.id;
    document.querySelectorAll('#t-srv-tabs .stab').forEach(b=>b.classList.toggle('on',b.dataset.sid===next.id));
    await playTmdbContent();
  }
}

async function loadTmdbSimilar(id,type) {
  const el=document.getElementById('tw-rellist');
  el.innerHTML='<div class="loading-st"><div class="spin"></div></div>';
  const d=await tmdb(`/${type}/${id}/similar?language=en-US&page=1`);
  el.innerHTML='';
  const list=(d?.results||[]).slice(0,7);
  if(!list.length){ el.innerHTML='<p style="color:var(--muted);padding:10px;font-size:12.5px">No similar titles.</p>'; return; }
  list.forEach(r=>{
    const div=document.createElement('div'); div.className='relitem';
    div.innerHTML=`<img src="${getTmdbImg(r.poster_path)}" class="relthumb" onerror="this.src='${FALLBACK}'"><div class="relinfo"><div class="relttl">${getTmdbTitle(r)}</div><div class="relsub">${getTmdbYear(r)}</div></div><i class="fas fa-play" style="color:var(--acc);font-size:11px"></i>`;
    div.onclick=()=>openTmdbContent({...r,media_type:type});
    el.appendChild(div);
  });
}

// ══════════════════════════════════════════════════════════════════════
// HERO
// ══════════════════════════════════════════════════════════════════════
async function loadHero() {
  const d=await jikan('/top/anime?filter=airing&limit=10');
  if(!d?.data) return;
  heroArr=d.data.filter(a=>a.images?.jpg?.large_image_url).slice(0,8);
  const sl=document.getElementById('hslides'), dt=document.getElementById('hdots');
  sl.innerHTML=''; dt.innerHTML='';
  heroArr.forEach((a,i)=>{
    const t=getTitle(a), bg=getImg(a);
    const desc=(a.synopsis||'').replace(/\[Written.*?\]/gs,'').trim().slice(0,210);
    const sc=a.score?`<span class="sc">⭐ ${a.score}</span>`:'';
    const slide=document.createElement('div'); slide.className='hslide'+(i===0?' on':'');
    slide.innerHTML=`<div class="hslide-bg" style="background-image:url('${bg}')"></div><div class="hslide-grad"></div><div class="hcont"><div class="hbadge"><i class="fas fa-fire"></i>&nbsp;Trending Anime</div><div class="htitle">${t}</div><div class="hmeta">${sc}<span>${a.episodes||'?'} eps</span><span>${a.year||''}</span></div><div class="hdesc">${desc||'No description.'}</div><div class="hbtns"><button class="hbtn hbtn-p" onclick="openAnime(heroArr[${i}])"><i class="fas fa-play"></i> Watch Now</button><button class="hbtn hbtn-s" onclick="openAnime(heroArr[${i}])"><i class="fas fa-plus"></i> Details</button></div></div>`;
    sl.appendChild(slide);
    const dot=document.createElement('button'); dot.className='hdot'+(i===0?' on':'');
    dot.onclick=()=>{
      document.querySelectorAll('.hslide').forEach((s,j)=>s.classList.toggle('on',j===i));
      document.querySelectorAll('.hdot').forEach((d,j)=>d.classList.toggle('on',j===i));
      heroIdx=i;
    };
    dt.appendChild(dot);
  });
  clearInterval(heroTmr);
  heroTmr=setInterval(()=>{
    heroIdx=(heroIdx+1)%heroArr.length;
    document.querySelectorAll('.hslide').forEach((s,j)=>s.classList.toggle('on',j===heroIdx));
    document.querySelectorAll('.hdot').forEach((d,j)=>d.classList.toggle('on',j===heroIdx));
  },6500);
}

// ══════════════════════════════════════════════════════════════════════
// HOME SECTIONS
// ══════════════════════════════════════════════════════════════════════
async function loadTrending(){
  const d=await jikan('/top/anime?filter=bypopularity&limit=14');
  const el=document.getElementById('trending-row'); el.innerHTML='';
  (d?.data||[]).forEach(a=>{
    const c=document.createElement('div'); c.className='scard';
    c.innerHTML=`<img src="${getImg(a)}" loading="lazy" onerror="this.src='${FALLBACK}'"><div class="scard-info"><div class="scard-ttl">${getTitle(a)}</div></div>`;
    c.onclick=()=>openAnime(a); el.appendChild(c);
  });
}
async function loadTop10(){
  const d=await jikan('/top/anime?limit=10');
  const el=document.getElementById('top10'); el.innerHTML='';
  (d?.data||[]).forEach((a,i)=>{
    const rc=i===0?'g':i===1?'s':i===2?'b':'n';
    const div=document.createElement('div'); div.className='t10item';
    div.innerHTML=`<span class="t10rank ${rc}">${i+1}</span><img src="${getImg(a)}" class="t10img" onerror="this.src='${FALLBACK}'"><div class="t10info"><div class="t10ttl">${getTitle(a)}</div><div class="t10meta">⭐ ${a.score||'N/A'} · ${a.episodes||'?'} eps · ${a.year||''}</div></div>`;
    div.onclick=()=>openAnime(a); el.appendChild(div);
  });
}
async function loadSeasonal(){
  const now=new Date(), yr=now.getFullYear();
  const s=['winter','winter','spring','spring','spring','summer','summer','summer','fall','fall','fall','winter'][now.getMonth()];
  const d=await jikan(`/seasons/${yr}/${s}?limit=12`);
  const el=document.getElementById('seasonal-grid'); el.innerHTML='';
  (d?.data||[]).slice(0,12).forEach(a=>el.appendChild(makeAnimeCard(a)));
  if(!d?.data?.length) el.innerHTML='<div class="err-st">Failed to load.</div>';
}
async function loadAiring(){
  const d=await jikan('/anime?status=airing&order_by=score&sort=desc&limit=14');
  const el=document.getElementById('airing-row'); el.innerHTML='';
  (d?.data||[]).forEach(a=>{
    const c=document.createElement('div'); c.className='scard';
    c.innerHTML=`<img src="${getImg(a)}" loading="lazy" onerror="this.src='${FALLBACK}'"><div class="scard-info"><div class="scard-ttl">${getTitle(a)}</div></div>`;
    c.onclick=()=>openAnime(a); el.appendChild(c);
  });
}
async function loadMovies(){
  const d=await jikan('/top/anime?type=movie&limit=12');
  const el=document.getElementById('movies-grid'); el.innerHTML='';
  (d?.data||[]).slice(0,12).forEach(a=>el.appendChild(makeAnimeCard(a)));
}

async function goTopAnime(){
  document.getElementById('search-ttl').textContent='Top Rated Anime';
  document.getElementById('search-grid').innerHTML='<div class="loading-st"><div class="spin"></div></div>';
  showView('v-search');
  const d=await jikan('/top/anime?limit=25');
  const g=document.getElementById('search-grid'); g.innerHTML='';
  (d?.data||[]).forEach(a=>g.appendChild(makeAnimeCard(a)));
}
async function goSeasonal(){
  const now=new Date(), yr=now.getFullYear();
  const sn=['winter','winter','spring','spring','spring','summer','summer','summer','fall','fall','fall','winter'][now.getMonth()];
  document.getElementById('search-ttl').textContent=`${sn.charAt(0).toUpperCase()+sn.slice(1)} ${yr}`;
  document.getElementById('search-grid').innerHTML='<div class="loading-st"><div class="spin"></div></div>';
  showView('v-search');
  const d=await jikan(`/seasons/${yr}/${sn}?limit=25`);
  const g=document.getElementById('search-grid'); g.innerHTML='';
  (d?.data||[]).forEach(a=>g.appendChild(makeAnimeCard(a)));
}
async function filterGenre(gid,btn){
  document.querySelectorAll('.gpill').forEach(p=>p.classList.remove('on')); btn.classList.add('on');
  if(!gid){ goHome(); return; }
  document.getElementById('search-ttl').textContent=btn.textContent+' Anime';
  document.getElementById('search-grid').innerHTML='<div class="loading-st"><div class="spin"></div></div>';
  showView('v-search');
  const d=await jikan(`/anime?genres=${gid}&order_by=score&sort=desc&limit=25`);
  const g=document.getElementById('search-grid'); g.innerHTML='';
  (d?.data||[]).forEach(a=>g.appendChild(makeAnimeCard(a)));
}

// ══════════════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════════════
document.getElementById('sinput').addEventListener('keypress',e=>{ if(e.key==='Enter') doSearch(); });
setToggle('autoplayToggle',SETTINGS.autoplay);
setToggle('autonextToggle',SETTINGS.autonext);
renderProfiles();

async function init(){
  await loadHero();
  await loadTrending();
  await loadTop10();
  await loadSeasonal();
  await loadAiring();
  await loadMovies();
}
init();
