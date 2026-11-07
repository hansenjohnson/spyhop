// Online map overlays (need the internet; listed in the map's layers menu, set up in
// Settings → Basemap):
//  - AIS vessels from Open Waters AIS (openwaters.io/ais), fetched for the map view through
//    Spyhop's server (/api/ais) every 30 s and when the map moves.
//  - Weather radar, US: NOAA NEXRAD base reflectivity composite, as tiles from the Iowa
//    Environmental Mesonet (Iowa State University), refreshed every 5 minutes.
//  - Weather radar, worldwide: RainViewer's latest radar frame (/api/radar/rainviewer gives the
//    frame list), refreshed every 10 minutes. Free for personal and educational use; zoom ≤ 7.
//  - Map feeds: any ArcGIS FeatureServer/MapServer or GeoJSON address the user adds (e.g. NOAA's
//    right whale Seasonal Management Areas and Slow Zones), fetched through /api/feeds/data; the
//    server keeps the last copy, so they still draw offline.
import { el, esc, api, toast, confirmBox, fmtPos, fmtDist, fmtBrg, distM, bearing, timeParts } from './util.js';

export const AIS_NAME = 'AIS vessels (Open Waters, online)';
export const RADAR_US_NAME = 'Weather radar, US (NOAA NEXRAD, online)';
export const RADAR_WORLD_NAME = 'Weather radar, worldwide (RainViewer, online)';
const PREFS = 'wsr.onlineOverlays';
const AIS_EVERY_MS = 30000;
const IEM = 'https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png';

// AIS ship and cargo type → [category, colour]
export function aisCategory(type, kind) {
  if (kind === 'aton') return ['Aid to navigation', '#c2185b'];
  if (kind === 'base') return ['Base station', '#455a64'];
  if (kind === 'sar') return ['SAR aircraft', '#f9a825'];
  const t = +type;
  if (t === 30) return ['Fishing', '#ef6c00'];
  if (t === 36) return ['Sailing', '#7b1fa2'];
  if (t === 37) return ['Pleasure craft', '#ab47bc'];
  if (t === 31 || t === 32 || t === 52) return ['Tug / towing', '#00897b'];
  if (t === 35 || (t >= 50 && t <= 59)) return ['Special craft (pilot, SAR, law enforcement…)', '#00838f'];
  if (t >= 40 && t <= 49) return ['High-speed craft', '#fbc02d'];
  if (t >= 60 && t <= 69) return ['Passenger', '#1565c0'];
  if (t >= 70 && t <= 79) return ['Cargo', '#2e7d32'];
  if (t >= 80 && t <= 89) return ['Tanker', '#c62828'];
  return ['Other / unknown', '#757575'];
}

const NAV_STATUS = ['Under way using engine', 'At anchor', 'Not under command', 'Restricted manoeuvrability',
  'Constrained by draught', 'Moored', 'Aground', 'Engaged in fishing', 'Under way sailing'];

function seenDate(v) {
  if (v === undefined || v === null || v === '') return null;
  const d = typeof v === 'number' ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v);
  return isNaN(d) ? null : d;
}

function ago(d) {
  const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  return s < 60 ? `${s} s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min ago`;
}

export class OnlineOverlays {
  constructor(app) {
    this.app = app;
    const mv = app.map, map = mv.map;
    try { this.prefs = { radarOpacity: 0.6, hideStopped: false, ...JSON.parse(localStorage.getItem(PREFS) || '{}') }; } catch { this.prefs = { radarOpacity: 0.6, hideStopped: false }; }
    this.ais = L.layerGroup();
    this.radarUS = L.tileLayer(IEM + '?_={stamp}', { stamp: this.stamp(5), opacity: this.prefs.radarOpacity, maxNativeZoom: 10, zIndex: 300,
      attribution: 'Radar: NOAA NEXRAD via <a href="https://mesonet.agron.iastate.edu/" target="_blank" rel="noopener">Iowa Environmental Mesonet</a>' });
    this.radarWorld = L.layerGroup();
    this.state = { ais: '', aisCount: 0, aisAt: null, world: null };
    const layers = [[AIS_NAME, this.ais], [RADAR_US_NAME, this.radarUS], [RADAR_WORLD_NAME, this.radarWorld]];
    let on = null;
    try { on = JSON.parse(localStorage.getItem('wsr.overlays') || 'null'); } catch {}
    for (const [name, layer] of layers) {
      mv.overlays[name] = layer;
      mv.layerControl.addOverlay(layer, name);
      if (on && on.includes(name)) layer.addTo(map);
    }
    map.on('overlayadd', (e) => this.onAdd(e.layer));
    map.on('overlayremove', (e) => this.onRemove(e.layer));
    map.on('moveend', () => { if (map.hasLayer(this.ais)) { clearTimeout(this._moveT); this._moveT = setTimeout(() => this.loadAis(), 700); } });
    for (const [, layer] of layers) if (map.hasLayer(layer)) this.onAdd(layer);
    this.feeds = []; this.presets = []; this.feedLayers = {};
    this.loadFeeds(on);
    setInterval(() => { if (map.hasLayer(this.radarUS)) this.radarUS.setUrl(IEM + '?_={stamp}', false); }, 60000);
  }

  // what's switched on here, as a config pack records it (packparts.DISPLAY_KEYS)
  displayState() {
    const map = this.app.map.map;
    return { ais: this.isOn('ais'), radar_us: this.isOn('us'), radar_world: this.isOn('world'),
      feeds: Object.values(this.feedLayers).filter((fl) => map.hasLayer(fl.layer)).map((fl) => fl.feed.url),
      radar_opacity: this.prefs.radarOpacity, hide_stopped: !!this.prefs.hideStopped };
  }

  // A config pack used on this computer says which online overlays to switch on (settings
  // online_display, with a new stamp each time a pack is used). Applied once per stamp; after that
  // the person's own choices on this computer stand.
  applyPackDisplay() {
    const d = this.app.S.config.settings.online_display;
    if (!d || !d.stamp) return;
    let done = null;
    try { done = localStorage.getItem('wsr.onlineDisplayStamp'); } catch {}
    if (done === d.stamp) return;
    const map = this.app.map.map;
    if (typeof d.radar_opacity === 'number') this.setOpacity(d.radar_opacity);
    if (typeof d.hide_stopped === 'boolean') { this.prefs.hideStopped = d.hide_stopped; this.savePrefs(); }
    // feeds: by address; ones not loaded yet come on from the saved list when they are
    const want = new Set(d.feeds || []);
    const names = (this.app.S.config.settings.online_feeds || []).filter((f) => want.has(f.url)).map((f) => `${f.name} (feed)`);
    let on = [];
    try { on = JSON.parse(localStorage.getItem('wsr.overlays') || '[]') || []; } catch {}
    on = [...on.filter((n) => !/ \(feed\)$/.test(n)), ...names];
    try { localStorage.setItem('wsr.overlays', JSON.stringify(on)); } catch {}
    for (const fl of Object.values(this.feedLayers)) {
      const yes = want.has(fl.feed.url);
      if (yes && !map.hasLayer(fl.layer)) fl.layer.addTo(map);
      else if (!yes && map.hasLayer(fl.layer)) map.removeLayer(fl.layer);
    }
    this.setOn('ais', !!d.ais); this.setOn('us', !!d.radar_us); this.setOn('world', !!d.radar_world);
    try { localStorage.setItem('wsr.onlineDisplayStamp', d.stamp); } catch {}
    this.app.onlineChanged?.();
  }

  // the same value for every tile within a period (minutes), so tiles refresh once per period
  stamp(min) { return () => Math.floor(Date.now() / (min * 60000)); }

  savePrefs() { try { localStorage.setItem(PREFS, JSON.stringify(this.prefs)); } catch {} }

  isOn(which) { return this.app.map.map.hasLayer({ ais: this.ais, us: this.radarUS, world: this.radarWorld }[which]); }

  setOn(which, on) {
    const layer = { ais: this.ais, us: this.radarUS, world: this.radarWorld }[which];
    const map = this.app.map.map;
    if (on && !map.hasLayer(layer)) layer.addTo(map);          // overlayadd fires: onAdd, and the layers menu remembers it
    else if (!on && map.hasLayer(layer)) map.removeLayer(layer);
    this.app.map.saveOverlayState();
    this.app.map.layerControl._update?.();
  }

  setOpacity(v) {
    this.prefs.radarOpacity = v; this.savePrefs();
    this.radarUS.setOpacity(v);
    this.worldTiles?.setOpacity(v);
  }

  onAdd(layer) {
    const fl = Object.values(this.feedLayers).find((x) => x.layer === layer);
    if (fl) { this.loadFeed(fl.feed.id); this.app.onlineChanged?.(); return; }
    if (layer === this.ais) {
      this.loadAis();
      clearInterval(this._aisTimer);
      this._aisTimer = setInterval(() => this.loadAis(), AIS_EVERY_MS);
    } else if (layer === this.radarWorld) {
      this.loadWorld();
      clearInterval(this._worldTimer);
      this._worldTimer = setInterval(() => this.loadWorld(), 10 * 60000);
    }
  }

  onRemove(layer) {
    const fl = Object.values(this.feedLayers).find((x) => x.layer === layer);
    if (fl) { clearTimeout(fl.timer); fl.layer.clearLayers(); this.app.onlineChanged?.(); return; }
    if (layer === this.ais) { clearInterval(this._aisTimer); this.ais.clearLayers(); this.setAttr('ais', ''); this.state.ais = ''; }
    else if (layer === this.radarWorld) { clearInterval(this._worldTimer); this.radarWorld.clearLayers(); this.worldTiles = null; this.setAttr('world', ''); }
    this.app.onlineChanged?.();
  }

  // one attribution line per overlay, replaced as it changes
  setAttr(key, html) {
    const ctl = this.app.map.map.attributionControl;
    this._attr = this._attr || {};
    if (this._attr[key]) ctl.removeAttribution(this._attr[key]);
    this._attr[key] = html;
    if (html) ctl.addAttribution(html);
  }

  // ------------------------------------------------------------------ AIS
  async loadAis() {
    const map = this.app.map.map;
    if (!map.hasLayer(this.ais)) return;
    const b = map.getBounds();
    const s = Math.max(-90, b.getSouth()), n = Math.min(90, b.getNorth());
    let w = b.getWest(), e = b.getEast();
    if (e - w >= 360) { w = -180; e = 180; }
    const wrap = (x) => ((x + 540) % 360) - 180;
    const bbox = [s, wrap(w), n, wrap(e)].map((x) => x.toFixed(4)).join(',');
    const seq = (this._aisSeq = (this._aisSeq || 0) + 1);
    let r;
    try {
      const res = await fetch(`/api/ais?bbox=${bbox}`);
      r = await res.json();
    } catch { r = { ok: false, error: 'Spyhop isn’t answering' }; }
    if (seq !== this._aisSeq || !map.hasLayer(this.ais)) return;
    const credit = '<a href="https://openwaters.io/ais/" target="_blank" rel="noopener">Open Waters AIS</a>';
    if (!r.ok) {
      this.state.ais = r.error;
      this.setAttr('ais', `AIS: ${credit} · <span class="attr-warn">${esc(r.error.replace(/^Couldn't get AIS vessels: /, ''))}</span>`);
      this.app.onlineChanged?.();
      return;
    }
    if (r.too_big) {
      this.ais.clearLayers();
      this.state.ais = 'Zoom in to see AIS vessels.';
      this.setAttr('ais', `AIS: ${credit} · zoom in to see vessels`);
      this.app.onlineChanged?.();
      return;
    }
    this.drawAis(r.features || []);
    const sources = [...new Set((r.features || []).map((f) => f.properties?.source).filter(Boolean))];
    this.state.ais = ''; this.state.aisAt = new Date();
    this.setAttr('ais', `AIS: ${credit}${sources.length ? ` (${esc(sources.join(', '))})` : ''} · ${this.state.aisCount} shown`);
    this.app.onlineChanged?.();
  }

  drawAis(features) {
    this.ais.clearLayers();
    let n = 0;
    for (const f of features) {
      const c = f.geometry?.coordinates, p = f.properties || {};
      if (!Array.isArray(c) || c.length < 2 || !Number.isFinite(+c[0]) || !Number.isFinite(+c[1])) continue;
      const ll = [+c[1], +c[0]];
      const kind = p.kind || 'vessel';
      const moving = Number.isFinite(+p.sog) && +p.sog >= 0.5;
      if (this.prefs.hideStopped && kind === 'vessel' && !moving) continue;
      const [, color] = aisCategory(p.type, kind);
      const dir = Number.isFinite(+p.heading) && +p.heading < 360 ? +p.heading : (Number.isFinite(+p.cog) && +p.cog < 360 ? +p.cog : null);
      let svg;
      if (kind === 'aton') svg = `<svg viewBox="0 0 12 12" width="12" height="12"><path d="M6 1 11 6 6 11 1 6Z" fill="${color}" stroke="#fff" stroke-width="1"/></svg>`;
      else if (kind === 'base') svg = `<svg viewBox="0 0 12 12" width="11" height="11"><rect x="1.5" y="1.5" width="9" height="9" fill="${color}" stroke="#fff" stroke-width="1"/></svg>`;
      else if (moving && dir !== null) svg = `<svg viewBox="0 0 16 20" width="14" height="18" style="transform:rotate(${dir}deg)"><path d="M8 1 14 18 8 14.5 2 18Z" fill="${color}" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/></svg>`;
      else svg = `<svg viewBox="0 0 12 12" width="11" height="11"><circle cx="6" cy="6" r="4.5" fill="${color}" stroke="#fff" stroke-width="1.2"/></svg>`;
      const icon = L.divIcon({ className: 'ais-icon', html: svg, iconSize: [18, 18], iconAnchor: [9, 9] });
      L.marker(ll, { icon, keyboard: false, zIndexOffset: -200 })
        .bindTooltip(esc(p.name || `MMSI ${p.mmsi}`), { direction: 'top', offset: [0, -8] })
        .bindPopup(() => this.aisPopup(ll, p), { minWidth: 220, maxWidth: 320 })
        .addTo(this.ais);
      n++;
    }
    this.state.aisCount = n;
  }

  aisPopup(ll, p) {
    const app = this.app, fmt = app.S.config.settings.latlon_format;
    const [cat] = aisCategory(p.type, p.kind);
    const rows = [['MMSI', p.mmsi], ['Type', `${cat}${p.type !== undefined && p.kind !== 'aton' ? ` (${p.type})` : ''}`],
      ['Position', fmtPos(ll[0], ll[1], fmt)]];
    if (Number.isFinite(+p.sog)) rows.push(['Speed', `${(+p.sog).toFixed(1)} kn`]);
    if (Number.isFinite(+p.cog) && +p.cog < 360) rows.push(['Course', `${Math.round(+p.cog).toString().padStart(3, '0')}°T`]);
    if (Number.isFinite(+p.heading) && +p.heading < 360) rows.push(['Heading', `${Math.round(+p.heading).toString().padStart(3, '0')}°T`]);
    if (Number.isFinite(+p.nav_status) && NAV_STATUS[+p.nav_status]) rows.push(['Status', NAV_STATUS[+p.nav_status]]);
    const seen = seenDate(p.seen);
    if (seen) { const t = timeParts(seen, app.clock()); rows.push(['Last heard', `${t.time.slice(0, 5)} ${t.abbr} (${ago(seen)})`]); }
    if (p.source) rows.push(['Source', p.source]);
    const wrap = el('div', { html: `<b>${esc(p.name || 'Unnamed vessel')}</b><table class="pop">${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(String(v))}</td></tr>`).join('')}</table>` });
    const v = app.S.vessel;
    if (v && v.lat !== null && v.lat !== undefined) wrap.append(el('div', { class: 'pop-rel' }, `${fmtDist(distM([v.lat, v.lon], ll), app.unit())} from the vessel, bearing ${fmtBrg(bearing([v.lat, v.lon], ll))}T`));
    wrap.append(el('div', { class: 'hint' }, 'From Open Waters AIS, online; may be minutes old or incomplete. Not for navigation or collision avoidance.'));
    return wrap;
  }

  // ------------------------------------------------------------------ RainViewer
  async loadWorld() {
    const map = this.app.map.map;
    let r;
    try { r = await api('/api/radar/rainviewer'); } catch (e) {
      this.setAttr('world', `Radar: <a href="https://www.rainviewer.com/" target="_blank" rel="noopener">RainViewer</a> · <span class="attr-warn">not available</span>`);
      return;
    }
    if (!map.hasLayer(this.radarWorld)) return;
    const f = r.frames[r.frames.length - 1];
    if (!f) return;
    if (this.state.world === f.path && this.worldTiles) return;
    this.state.world = f.path;
    const tiles = L.tileLayer(`${r.host}${f.path}/256/{z}/{x}/{y}/2/1_1.png`, { opacity: this.prefs.radarOpacity, maxNativeZoom: 7, zIndex: 299 });
    this.radarWorld.clearLayers();
    tiles.addTo(this.radarWorld);
    this.worldTiles = tiles;
    const t = timeParts(new Date(f.time * 1000), this.app.clock());
    this.state.worldTime = `${t.time.slice(0, 5)} ${t.abbr}`;
    this.setAttr('world', `Radar ${esc(this.state.worldTime)}: <a href="https://www.rainviewer.com/" target="_blank" rel="noopener">Weather data by RainViewer</a>`);
    this.app.onlineChanged?.();
  }

  // ------------------------------------------------------------------ map feeds
  async loadFeeds(initialOn = null) {
    let r;
    try { r = await api('/api/feeds'); } catch { return; }
    this.feeds = r.feeds; this.presets = r.presets; this.feedsFolder = r.folder;
    const mv = this.app.map, map = mv.map;
    let on = initialOn;
    if (!on) { try { on = JSON.parse(localStorage.getItem('wsr.overlays') || 'null'); } catch {} }
    const ids = new Set(this.feeds.map((f) => f.id));
    for (const [id, fl] of Object.entries(this.feedLayers)) {
      if (ids.has(id)) continue;
      clearTimeout(fl.timer);
      mv.layerControl.removeLayer(fl.layer); map.removeLayer(fl.layer);
      delete mv.overlays[fl.label]; delete this.feedLayers[id];
    }
    for (const f of this.feeds) {
      const label = `${f.name} (feed)`;
      let fl = this.feedLayers[f.id];
      if (fl && fl.label !== label) { mv.layerControl.removeLayer(fl.layer); delete mv.overlays[fl.label]; mv.overlays[label] = fl.layer; mv.layerControl.addOverlay(fl.layer, label); fl.label = label; }
      if (!fl) {
        fl = this.feedLayers[f.id] = { feed: f, label, layer: L.geoJSON(null, { style: (ft) => this.feedStyle(f.id, ft),
          pointToLayer: (ft, ll) => L.circleMarker(ll, { radius: 6 }),
          onEachFeature: (ft, lay) => lay.bindPopup(() => this.feedPopup(f.id, ft), { maxWidth: 340 }) }) };
        mv.overlays[label] = fl.layer;
        mv.layerControl.addOverlay(fl.layer, label);
        if (on && on.includes(label)) fl.layer.addTo(map);
      } else {
        const recolor = fl.feed.color !== f.color;
        fl.feed = f;
        if (recolor) fl.layer.setStyle((ft) => this.feedStyle(f.id, ft));
      }
    }
    this.applyPackDisplay();
    this.app.onlineChanged?.();
  }

  async loadFeed(id, force = false) {
    const fl = this.feedLayers[id];
    if (!fl) return;
    clearTimeout(fl.timer);
    const map = this.app.map.map;
    if (!map.hasLayer(fl.layer)) return;
    let r;
    try {
      const res = await fetch(`/api/feeds/data?id=${encodeURIComponent(id)}${force ? '&force=1' : ''}`);
      r = await res.json();
    } catch { r = { ok: false, error: 'Spyhop isn’t answering' }; }
    if (!this.feedLayers[id] || !map.hasLayer(fl.layer)) return;
    if (r.ok) {
      fl.layer.clearLayers();
      try { fl.layer.addData({ type: 'FeatureCollection', features: r.features }); } catch (e) { r.error = `Couldn’t draw it: ${e.message}`; }
      fl.fetched = r.fetched; fl.count = r.features.length;
    }
    fl.error = r.ok ? (r.stale ? r.error : '') : r.error;
    fl.timer = setTimeout(() => this.loadFeed(id), Math.max(5, fl.feed.refresh_min) * 60000);
    this.app.onlineChanged?.();
  }

  // Seasonal areas (fields st_mo, st_day, end_mo, end_day, as NOAA's SMAs): in effect today?
  seasonActive(p) {
    const n = (k) => +p[k];
    if (![n('st_mo'), n('st_day'), n('end_mo'), n('end_day')].every((x) => x > 0)) return null;
    const d = new Date(), today = (d.getMonth() + 1) * 100 + d.getDate();
    const a = n('st_mo') * 100 + n('st_day'), b = n('end_mo') * 100 + n('end_day');
    return a <= b ? today >= a && today <= b : today >= a || today <= b;
  }

  feedStyle(id, ft) {
    const color = this.feedLayers[id]?.feed.color || '#1565c0';
    const active = this.seasonActive(ft?.properties || {});
    return active === false
      ? { color, weight: 1.5, dashArray: '4 5', fillColor: color, fillOpacity: 0.04, opacity: 0.7 }
      : { color, weight: 2, fillColor: color, fillOpacity: 0.18, opacity: 0.95 };
  }

  feedPopup(id, ft) {
    const fl = this.feedLayers[id], p = ft.properties || {};
    const skip = /^(OBJECTID|FID|gid|Shape__Area|Shape__Length|Shape_Area|Shape_Length|GlobalID|_layer)$/i;
    const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const val = (k, v) => {
      if (typeof v === 'number' && v > 1e11 && v < 1e13 && /date|time|expir|start|end|effect|creat|edit/i.test(k)) {
        const t = timeParts(new Date(v), this.app.clock()); return `${t.date} ${t.time.slice(0, 5)} ${t.abbr}`;
      }
      return String(v);
    };
    const title = p.zone_name || p.name || p.NAME || p.Name || p.title || p._layer || fl?.feed.name || 'Feature';
    const rows = Object.entries(p).filter(([k, v]) => !skip.test(k) && v !== null && v !== '' && typeof v !== 'object');
    const active = this.seasonActive(p);
    const wrap = el('div', {}, el('b', {}, String(title)));
    if (active !== null) {
      const span = `${MONTHS[+p.st_mo - 1]} ${+p.st_day} – ${MONTHS[+p.end_mo - 1]} ${+p.end_day}`;
      wrap.append(el('div', { class: active ? 'feed-active' : 'hint' }, active ? `In effect now (${span})` : `Not in effect now (${span})`));
    }
    wrap.append(el('div', { html: `<table class="pop">${rows.slice(0, 16).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(val(k, v))}</td></tr>`).join('')}</table>` }));
    if (fl?.fetched) {
      const t = timeParts(new Date(fl.fetched * 1000), this.app.clock());
      wrap.append(el('div', { class: 'hint' }, `${fl.feed.name} · updated ${t.date} ${t.time.slice(0, 5)} ${t.abbr}${fl.error ? ' (saved copy: couldn’t update)' : ''}. Check official notices before relying on it.`));
    }
    return wrap;
  }

  async addFeed(feed) {
    let r;
    try { r = await api('/api/feeds/add', { feed }); } catch { return false; }
    if (r.warning) toast(r.warning, 'warn', 7000); else toast(`Added “${r.feed.name}”${r.count !== null ? ` (${r.count} feature${r.count === 1 ? '' : 's'})` : ''}. It’s on the map.`);
    await this.loadFeeds();
    const fl = this.feedLayers[r.feed.id];
    if (fl) { fl.layer.addTo(this.app.map.map); this.app.map.saveOverlayState(); }
    return true;
  }

  async updateFeed(feed) {
    try { await api('/api/feeds/update', { feed }); } catch { return; }
    await this.loadFeeds();
    if (feed.url) this.loadFeed(feed.id, true);
  }

  async removeFeed(f) {
    if (!await confirmBox('Remove the feed?', `Remove “${f.name}” and its saved copy?`, 'Remove', true)) return;
    try { await api('/api/feeds/delete', { id: f.id }); } catch { return; }
    await this.loadFeeds();
  }

  zoomFeed(id) {
    const fl = this.feedLayers[id];
    if (!fl) return;
    const map = this.app.map.map;
    if (!map.hasLayer(fl.layer)) { fl.layer.addTo(map); this.app.map.saveOverlayState(); }
    const go = () => { const b = fl.layer.getBounds(); if (b.isValid()) { this.app.map.setFollow?.(false, true); map.fitBounds(b.pad(0.1), { maxZoom: 11 }); } };
    if (fl.count) go(); else setTimeout(go, 1500);
  }

  feedsBlock() {
    const map = this.app.map.map;
    const fmtT = (sec) => { const t = timeParts(new Date(sec * 1000), this.app.clock()); return `${t.date} ${t.time.slice(0, 5)}`; };
    const rows = this.feeds.map((f) => {
      const fl = this.feedLayers[f.id];
      const shown = fl && map.hasLayer(fl.layer);
      const fetched = fl?.fetched || f.fetched, count = fl?.count ?? f.count;
      const err = fl?.error ? fl.error.replace(`${f.name}: `, '') : '';
      return el('tr', { 'data-feed': f.id },
        el('td', {}, el('input', { type: 'checkbox', checked: !!shown, title: 'Show on the map',
          onchange: (e) => { if (e.target.checked) fl.layer.addTo(map); else map.removeLayer(fl.layer); this.app.map.saveOverlayState(); } })),
        el('td', {}, el('input', { type: 'color', value: f.color, title: 'Colour', onchange: (e) => this.updateFeed({ id: f.id, color: e.target.value }) })),
        el('td', { class: 'feed-name' }, el('b', {}, f.name),
          el('div', { class: 'hint' }, err ? el('span', { class: 'warn-text' }, `${err}${fetched ? ` · showing the copy from ${fmtT(fetched)}` : ''}`)
            : fetched ? `${count} feature${count === 1 ? '' : 's'} · updated ${fmtT(fetched)}` : 'Not loaded yet'),
          el('div', { class: 'hint feed-url' }, f.url),
          el('div', { class: 'btnrow feed-actions' },
            el('label', { class: 'inline' }, 'Refresh ', el('select', { title: 'How often to fetch it again', onchange: (e) => this.updateFeed({ id: f.id, refresh_min: +e.target.value }) },
              [[15, 'every 15 min'], [60, 'hourly'], [360, 'every 6 hours'], [1440, 'daily'], [10080, 'weekly']].map(([v, l]) => el('option', { value: v, selected: +f.refresh_min === v }, l)),
              [15, 60, 360, 1440, 10080].includes(+f.refresh_min) ? null : el('option', { value: f.refresh_min, selected: true }, `every ${f.refresh_min} min`))),
            el('button', { onclick: () => { if (!map.hasLayer(fl.layer)) { fl.layer.addTo(map); this.app.map.saveOverlayState(); } this.loadFeed(f.id, true); } }, 'Update now'),
            el('button', { onclick: () => this.zoomFeed(f.id) }, 'Zoom to'),
            el('button', { class: 'danger-outline', onclick: () => this.removeFeed(f) }, 'Remove'))));
    });
    const have = new Set(this.feeds.map((f) => f.url));
    const presets = this.presets.filter((p) => !have.has(p.url));
    const nameIn = el('input', { type: 'text', placeholder: 'Name', style: 'width:14em' });
    const urlIn = el('input', { type: 'text', placeholder: 'https://…/FeatureServer/0  or  …/data.geojson', style: 'flex:1;min-width:18em' });
    const colorIn = el('input', { type: 'color', value: '#1565c0' });
    const add = el('button', { onclick: async () => {
      add.disabled = true;
      const ok = await this.addFeed({ name: nameIn.value, url: urlIn.value, color: colorIn.value, refresh_min: 60 });
      add.disabled = false;
      if (ok) { nameIn.value = ''; urlIn.value = ''; }
    } }, 'Add feed');
    return el('div', { class: 'feeds' },
      el('h4', {}, 'Map feeds'),
      el('p', { class: 'hint' }, 'Areas, lines or points from the web, such as management zones, drawn as map overlays. Spyhop keeps the last copy of each, so they still show offline (marked if it couldn’t update).'),
      rows.length ? el('div', { class: 'table-scroll' }, el('table', { class: 'summary feeds-table' },
        el('thead', {}, el('tr', {}, ['Show', '', 'Feed'].map((h) => el('th', {}, h)))), el('tbody', {}, rows)))
        : el('p', { class: 'hint' }, 'No feeds yet.'),
      presets.length ? el('div', { class: 'feed-presets' }, el('b', {}, 'Add a ready-made feed:'),
        presets.map((p) => el('div', { class: 'feed-preset' },
          el('button', { onclick: (e) => { e.target.disabled = true; this.addFeed({ name: p.name, url: p.url, color: p.color, refresh_min: p.refresh_min }).finally(() => { e.target.disabled = false; }); } }, `+ ${p.name}`),
          el('span', { class: 'hint' }, ` ${p.about}`)))) : null,
      el('div', { class: 'btnrow feed-add' }, el('b', {}, 'Or any feed:'), nameIn, urlIn, colorIn, add),
      el('p', { class: 'hint' }, 'An ArcGIS Online or ArcGIS Server address ending in /FeatureServer/<number> (one layer), /FeatureServer (every layer of the service) or /MapServer/<number>, or a link to a GeoJSON file. Areas whose attributes give a season (st_mo, st_day, end_mo, end_day, as NOAA’s Seasonal Management Areas) are drawn solid while in effect and dashed otherwise.'));
  }

  // ------------------------------------------------------------------ Settings → Inputs
  section() {
    const chk = (which, label, hint) => el('label', { class: 'check' },
      el('input', { type: 'checkbox', checked: this.isOn(which), onchange: (e) => { this.setOn(which, e.target.checked); this.app.renderInputs?.(); } }),
      el('span', {}, el('b', {}, label), el('br'), el('span', { class: 'hint' }, hint)));
    const op = el('input', { type: 'range', min: 0.2, max: 1, step: 0.05, value: this.prefs.radarOpacity,
      oninput: (e) => this.setOpacity(+e.target.value) });
    const status = [];
    if (this.isOn('ais')) status.push(this.state.ais || (this.state.aisAt ? `AIS: ${this.state.aisCount} vessels in view, updated ${timeParts(this.state.aisAt, this.app.clock()).time.slice(0, 5)}.` : 'AIS: loading…'));
    if (this.isOn('world') && this.state.worldTime) status.push(`Worldwide radar frame: ${this.state.worldTime}.`);
    return el('section', { class: 'settings-sec', id: 'online-overlays' }, el('h3', {}, 'Online overlays'),
      el('p', { class: 'hint' }, 'Live data from the internet, drawn over the map; each is also in the map’s layers menu. AIS and radar aren’t kept for offline use.'),
      el('div', { class: 'grid2 checks' },
        chk('ais', 'AIS vessels', 'Open Waters AIS (openwaters.io/ais): free, from coastal authorities and volunteer receivers. Updated every 30 s for the area in view; zoom in if nothing shows. Coverage depends on the receivers nearby.'),
        chk('us', 'Weather radar, US', 'NOAA NEXRAD base reflectivity mosaic for the US, via the Iowa Environmental Mesonet. Updated every 5 minutes.'),
        chk('world', 'Weather radar, worldwide', 'RainViewer’s latest radar frame (every 10 minutes), where radars exist. Free for personal and educational use; detail stops at about zoom 7.')),
      el('div', { class: 'grid2' },
        el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Radar opacity'), op),
        el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!this.prefs.hideStopped,
          onchange: (e) => { this.prefs.hideStopped = e.target.checked; this.savePrefs(); this.loadAis(); } }), el('span', {}, 'Hide AIS vessels that aren’t moving'))),
      status.length ? el('p', { class: 'hint', id: 'online-status' }, status.join(' ')) : null,
      el('p', { class: 'hint' }, 'AIS colours: cargo green, tanker red, passenger blue, fishing orange, sailing and pleasure purple, tugs and special craft teal, other grey; a triangle points the way a moving vessel is heading, a dot is a vessel that isn’t moving, a diamond an aid to navigation. AIS from the internet can be minutes old and misses vessels without AIS or out of receiver range: not for navigation or collision avoidance.'),
      this.feedsBlock());
  }
}
