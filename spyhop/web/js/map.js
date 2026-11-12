// Interactive chart: base layers, vessel, track, data markers, popups, measure tool.
/* global L, topojson */
import { Resights } from './resights.js';
import { el, esc, fmtCoord, fmtPos, distM, bearing, destination, fmtDist, fmtBrg, timeParts, toast, api, trackStates, trackBreaks, effortRowAt, dashFor, isOn, effortColor } from './util.js';
import { DepthProbe } from './depth.js';

const SHAPES = ['Diamond', 'Square', 'Triangle', 'Circle', 'Star'];
export { SHAPES };

export function shapeSvg(shape, color, r = 8, stroke = '#000', fill = 'filled') {
  const s = r * 2 + 4, c = s / 2;
  let body;
  switch (shape) {
    case 'Square': body = `<rect x="${c - r * 0.85}" y="${c - r * 0.85}" width="${r * 1.7}" height="${r * 1.7}"/>`; break;
    case 'Triangle': body = `<polygon points="${c},${c - r} ${c + r * 0.95},${c + r * 0.75} ${c - r * 0.95},${c + r * 0.75}"/>`; break;
    case 'Circle': body = `<circle cx="${c}" cy="${c}" r="${r * 0.9}"/>`; break;
    case 'Star': {
      const pts = [];
      for (let i = 0; i < 10; i++) {
        const rr = i % 2 ? r * 0.45 : r, a = Math.PI / 5 * i - Math.PI / 2;
        pts.push(`${(c + rr * Math.cos(a)).toFixed(1)},${(c + rr * Math.sin(a)).toFixed(1)}`);
      }
      body = `<polygon points="${pts.join(' ')}"/>`; break;
    }
    default: body = `<polygon points="${c},${c - r} ${c + r},${c} ${c},${c + r} ${c - r},${c}"/>`;
  }
  // fill: filled | hollow (an outline in the color, for resights) | faded (filled, see-through)
  if (fill === 'hollow') return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}"><g fill="#fff" fill-opacity="0.85" stroke="${esc(color)}" stroke-width="2.4">${body}</g></svg>`;
  const fo = fill === 'faded' ? ' fill-opacity="0.45"' : '';
  return `<svg width="${s}" height="${s}" viewBox="0 0 ${s} ${s}"><g fill="${esc(color)}"${fo} stroke="${stroke}" stroke-width="1.3">${body}</g></svg>`;
}

const VESSEL_SVG = (color) => `<svg width="26" height="26" viewBox="-13 -13 26 26">
  <path d="M0,-12 L6,2 L6,10 L-6,10 L-6,2 Z" fill="${color}" stroke="#fff" stroke-width="1.6"/>
  <circle r="2" fill="#fff"/></svg>`;
// the platform's marker by its type (Survey details): ship, aircraft, tower (it doesn't turn) or a dot
// Smooth vessel movement: glide over the time between fixes (within these limits), redraw at most
// about 30 times a second, and jump instead after a longer gap or a bigger jump than these.
const SMOOTH = { minMs: 250, maxMs: 2500, maxGapMs: 5000, maxJumpM: 300, frameMs: 33 };

const PLATFORM_SVG = {
  Shipboard: VESSEL_SVG,
  Aerial: (c) => `<svg width="28" height="28" viewBox="-14 -14 28 28">
  <path d="M0,-12 C1.3,-12 1.8,-10 1.8,-8 L1.8,-3 L11,2 L11,4.5 L1.8,2 L1.8,7 L5,9.5 L5,11.5 L0,10 L-5,11.5 L-5,9.5 L-1.8,7 L-1.8,2 L-11,4.5 L-11,2 L-1.8,-3 L-1.8,-8 C-1.8,-10 -1.3,-12 0,-12 Z"
    fill="${c}" stroke="#fff" stroke-width="1.3" stroke-linejoin="round"/></svg>`,
  Stationary: (c) => `<svg width="26" height="26" viewBox="-13 -13 26 26">
  <path d="M-3,-11 L3,-11 L3,-7 L-3,-7 Z M-2,-7 L2,-7 L5,11 L-5,11 Z M-3.5,-1 L3.5,-1 M-4.4,5 L4.4,5" fill="${c}" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/>
  <path d="M-3.5,-1 L3.5,-1 M-4.4,5 L4.4,5" stroke="#fff" stroke-width="1.2"/></svg>`,
  Other: (c) => `<svg width="20" height="20" viewBox="-10 -10 20 20"><circle r="6.5" fill="${c}" stroke="#fff" stroke-width="2"/></svg>`,
};

// 0.45: the icon of an "other" input (Settings → Inputs → Mapping 'Other' inputs): a shape, or a vessel or
// aircraft that turns with its heading, or a tower. A red X over it while its GPS is lost.
export const EXTERNAL_ICONS = [['circle', 'Circle'], ['square', 'Square'], ['triangle', 'Triangle'], ['diamond', 'Diamond'], ['star', 'Star'],
  ['vessel', 'Vessel (turns with heading)'], ['aircraft', 'Aircraft (turns with heading)'], ['drone', 'Drone (turns with heading)'], ['tower', 'Tower']];
// 0.47: a quadcopter seen from above: four rotors on an X frame, the front arms and a nose in the color
const droneSvg = (c) => `<svg viewBox="0 0 28 28" width="26" height="26"><g stroke="#fff" stroke-width="4.2" stroke-linecap="round"><path d="M7,7 L21,21 M21,7 L7,21"/></g>
<g stroke="${c}" stroke-width="2.4" stroke-linecap="round"><path d="M7,7 L21,21 M21,7 L7,21"/></g>
<g fill="${c}" fill-opacity="0.35" stroke="${c}" stroke-width="1.6"><circle cx="6.5" cy="6.5" r="4.6"/><circle cx="21.5" cy="6.5" r="4.6"/><circle cx="6.5" cy="21.5" r="4.6"/><circle cx="21.5" cy="21.5" r="4.6"/></g>
<rect x="10.5" y="10.5" width="7" height="7" rx="1.5" fill="${c}" stroke="#fff" stroke-width="1.2"/><path d="M14,1.5 L17,6.5 L11,6.5 Z" fill="${c}" stroke="#fff" stroke-width="1"/></svg>`;
const EXTERNAL_LOST_MS = 15000;           // no fix for this long: lost (the server stops sending it after 10 s)
function externalIconHtml(icon, color, hdg, lost) {
  const turns = icon === 'vessel' || icon === 'aircraft' || icon === 'drone';
  const svg = icon === 'vessel' ? PLATFORM_SVG.Shipboard(color) : icon === 'aircraft' ? PLATFORM_SVG.Aerial(color) : icon === 'drone' ? droneSvg(color)
    : icon === 'tower' ? PLATFORM_SVG.Stationary(color)
    : shapeSvg((icon || 'circle')[0].toUpperCase() + (icon || 'circle').slice(1), color, 7, '#fff');
  const rot = turns && hdg != null && !isNaN(hdg) ? ` style="transform: rotate(${Math.round(hdg)}deg)"` : '';
  const x = lost ? '<svg class="ext-x" viewBox="0 0 28 28" width="28" height="28"><path d="M5,5 L23,23 M23,5 L5,23" stroke="#fff" stroke-width="6" stroke-linecap="round"/><path d="M5,5 L23,23 M23,5 L5,23" stroke="#d00000" stroke-width="3.2" stroke-linecap="round"/></svg>' : '';
  return `<div class="ext-wrap${lost ? ' lost' : ''}"><div class="ext-rot"${rot}>${svg}</div>${x}</div>`;
}

export class MapView {
  constructor(app, container) {
    this.app = app;
    this.container = container;
    this.layers = {};
    this.markerLayers = {};
    this.measure = null;
    this.userMoved = 0;
    this.map = L.map(container, { zoomControl: true, attributionControl: true, worldCopyJump: true,
      zoomSnap: 0.5, wheelPxPerZoomLevel: 90, boxZoom: true }).setView([41.8, -69.9], 9);
    this.map.createPane('land').style.zIndex = 150;
    this.map.createPane('tracks').style.zIndex = 420;
    // 0.43: external inputs (drones, buoys, other vessels) sit below everything of the survey's own
    this.map.createPane('externals').style.zIndex = 405;
    this.map.createPane('externalLabels').style.zIndex = 406;
    this.map.createPane('vessel').style.zIndex = 650;
    this.map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');
    this.map.on('dragstart', () => { this.userMoved = Date.now(); this.setFollow(false); });
    this.map.on('mousemove', (e) => this.cursor(e.latlng));
    this.map.on('contextmenu', (e) => this.contextMenu(e));
    this.map.on('click', (e) => this.onClick(e));
    this.map.on('dblclick', (e) => { if (this.measure?.active) { L.DomEvent.stop(e); this.endMeasure(); } });
    this.map.on('baselayerchange', (e) => {
      try { localStorage.setItem('wsr.base', e.name); } catch {}
      this.baseLayer = e.layer; this.showDepth('');
      this.app.renderChartList?.();
      this.app.renderBasemapChoice?.();
    });
    this.map.on('mouseout', () => this.showDepth(''));
    this.map.on('overlayadd overlayremove', (e) => { this.trackToggle(e); this.saveOverlayState(); });
    this.buildLayers();
    this.buildControls();
    setInterval(() => { if (this.app.S.config.display.fade_enabled === '1') this.redrawData(); }, 60000);
    this.loadCoastline();
  }

  // ---------------------------------------------------------------- layers
  // A MapLibre style (Seascape, or a Seascape area saved in the charts folder): drawn by MapLibre GL
  // inside Leaflet. MapLibre (about 1.6 MB) is loaded the first time the layer is shown.
  glLayer(styleUrl, attribution, unit, label) {
    const grp = L.layerGroup([], { attribution: esc(attribution || '') });
    grp._depth = new DepthProbe(styleUrl, unit);
    grp.on('add', async () => {
      if (grp._gl || grp._loading) return;
      grp._loading = true;
      try {
        if (!document.querySelector('link[data-maplibre]')) {
          document.head.append(el('link', { rel: 'stylesheet', href: '/static/vendor/maplibre/maplibre-gl.css', 'data-maplibre': '1' }));
        }
        const mod = await import('/static/vendor/maplibre/leaflet-maplibre-gl.mjs');
        grp._gl = mod.maplibreGL({ style: styleUrl, interactive: false, attributionControl: false });
        grp.addLayer(grp._gl);
        const gl = grp._gl.getMaplibreMap?.();
        gl?.on('error', (e) => { const m = e?.error?.message || ''; if (m && !/204|Failed to fetch|AbortError/.test(m)) console.warn(`${label}:`, m); });
      } catch (e) {
        toast(`Couldn’t show ${label}: ${e.message}`, 'error', 8000);
      } finally { grp._loading = false; }
    });
    return grp;
  }

  unitOf(url) { try { return new URL(url).searchParams.get('unit') || 'm'; } catch { return 'm'; } }

  // a file in the charts folder: an MBTiles chart, or an area saved by a download
  chartLayer(m) {
    if (m.kind === 'style') {
      const src = this.app.S.config.tile_sources.find((t) => t.name === m.source);
      return this.glLayer(`${location.origin}/tiles/off/${encodeURIComponent(m.file)}/style.json`,
        src?.attribution || m.name, this.unitOf(src?.url || ''), m.name);
    }
    const opts = { maxNativeZoom: m.maxzoom, minNativeZoom: m.minzoom, maxZoom: 20,
      attribution: esc(this.app.S.config.tile_sources.find((t) => t.name === m.source)?.attribution || m.name) };
    if (m.bounds) opts.bounds = [[m.bounds[1], m.bounds[0]], [m.bounds[3], m.bounds[2]]];
    return L.tileLayer(`/tiles/mb/${encodeURIComponent(m.file)}/{z}/{x}/{y}`, opts);
  }

  // the layers-menu name; two files with the same name are told apart by their file names
  chartLabel(m) {
    const same = (this.app.S.mbtiles || []).filter((x) => x.name === m.name).length > 1;
    if (same) return `${m.name} (${m.file})`;
    return this.app.S.config.tile_sources.some((t) => t.name === m.name) ? `${m.name} (offline)` : m.name;
  }

  buildLayers() {
    const S = this.app.S;
    const bases = {}, overlays = {};
    S.config.tile_sources.forEach((t, i) => {
      const layer = t.kind === 'style' ? this.glLayer(`${location.origin}/tiles/gl/${i}/style.json`, t.attribution, this.unitOf(t.url), t.name)
        : L.tileLayer(`/tiles/s/${i}/{z}/{x}/{y}`, {
          attribution: esc(t.attribution || ''), maxZoom: 20, maxNativeZoom: +t.max_zoom || 18,
          crossOrigin: false, errorTileUrl: '' });
      layer._group = 'online';
      if (t.overlay === '1') overlays[t.name] = layer; else bases[t.name] = layer;
    });
    this.chartLayers = {};
    for (const m of S.mbtiles || []) {
      if (m.error) continue;
      const layer = this.chartLayers[m.file] = this.chartLayer(m);
      layer._group = 'offline';
      layer._info = { tiles: m.tiles, created: m.created };
      if (m.overlay) overlays[this.chartLabel(m)] = layer; else bases[this.chartLabel(m)] = layer;
    }
    // the bundled Natural Earth coastline: a base map that needs no internet and no downloads
    this.layers.land = L.layerGroup();
    bases['Coastline (offline)'] = this.layers.land;
    bases['Coastline (offline)']._group = 'builtin';
    this.bases = bases;

    this.layers.track = L.layerGroup();
    this.layers.rings = L.layerGroup();
    this.layers.lines = L.layerGroup();
    this.layers.fidlines = L.layerGroup();
    this.layers.relines = L.layerGroup();
    for (const tab of ['sightings', 'events', 'marks']) this.markerLayers[tab] = L.layerGroup();
    // 0.51: resights (their markers, the lines to them from the vessel and through them) as a layer of their own
    this.layers.resights = L.layerGroup();
    this.layers.imported = L.layerGroup();
    this.layers.graticule = L.layerGroup();
    this.layers.vessel = L.layerGroup().addTo(this.map);

    // 0.43: the platform, its track (the on- and off-effort parts: Settings → General → Map display) in the menu
    overlays['Platform icon'] = this.layers.vessel;
    this.layers.effortOn = L.layerGroup();
    this.layers.effortOff = L.layerGroup();
    overlays['Effort (on-effort track)'] = this.layers.effortOn;
    overlays['Track (off effort)'] = this.layers.effortOff;
    overlays['Sightings'] = this.markerLayers.sightings;
    overlays['Resights'] = this.layers.resights;
    overlays['Events'] = this.markerLayers.events;
    overlays['Waypoints'] = this.markerLayers.marks;
    overlays['Imported overlays'] = this.layers.imported;
    overlays['Range rings'] = this.layers.rings;
    overlays['Graticule (lat/lon grid)'] = this.layers.graticule;
    this.overlays = overlays;

    let saved = null, ov = null;
    try { saved = localStorage.getItem('wsr.base'); ov = JSON.parse(localStorage.getItem('wsr.overlays') || 'null'); } catch {}
    const base = bases[saved] || bases['Seascape depths (feet)'] || bases['Esri Ocean'] || Object.values(bases)[0];
    base.addTo(this.map);
    this.baseLayer = base;
    // track and sighting/FieldID lines are always on the map; Settings decides what they draw
    for (const k of ['track', 'lines', 'fidlines', 'relines']) this.layers[k].addTo(this.map);
    const defaultsOn = ['Platform icon', 'Sightings', 'Resights', 'Events', 'Waypoints', 'Imported overlays'];
    let seen = null;
    try { seen = JSON.parse(localStorage.getItem('wsr.overlays.seen') || 'null'); } catch {}
    const disp = this.app.S.config.display;
    for (const [name, layer] of Object.entries(overlays)) {
      if (layer === this.layers.effortOn || layer === this.layers.effortOff) continue;
      // a name new to this computer's saved list starts as its default
      const on = ov && (!seen || seen.includes(name)) && (seen || name !== 'Platform icon') ? ov.includes(name) : defaultsOn.includes(name);
      if (on) layer.addTo(this.map);
    }
    this._trackSync = true;
    if (disp.show_track_on !== '0') this.layers.effortOn.addTo(this.map);
    if (disp.show_track_off !== '0') this.layers.effortOff.addTo(this.map);
    this._trackSync = false;
    // 0.43: map tiles are chosen in Settings → Basemap; the menu has the layers only
    this.layerControl = new GroupedLayers({}, overlays, { position: 'topright', collapsed: true }).addTo(this.map);
    this.externals = new Map();
  }

  // the charts folder changed (a download finished, or Rescan): update the layers menu
  syncCharts(list) {
    const byFile = Object.fromEntries((list || []).filter((m) => !m.error).map((m) => [m.file, m]));
    for (const [file, layer] of Object.entries(this.chartLayers || {})) {
      if (byFile[file] && byFile[file].tiles === layer._info?.tiles && byFile[file].created === layer._info?.created) continue;
      const wasBase = this.baseLayer === layer;
      this.layerControl.removeLayer(layer);
      for (const d of [this.bases, this.overlays]) for (const k of Object.keys(d)) if (d[k] === layer) delete d[k];
      if (this.map.hasLayer(layer)) this.map.removeLayer(layer);
      delete this.chartLayers[file];
      if (wasBase) this._restoreBase = file;
    }
    for (const m of Object.values(byFile)) {
      if (this.chartLayers[m.file]) continue;
      const layer = this.chartLayers[m.file] = this.chartLayer(m);
      layer._info = { tiles: m.tiles, created: m.created };
      layer._group = 'offline';
      if (m.overlay) { this.overlays[this.chartLabel(m)] = layer; this.layerControl.addOverlay(layer, this.chartLabel(m)); }
      else { this.bases[this.chartLabel(m)] = layer; this.app.renderBasemapChoice?.(); }
      if (this._restoreBase === m.file) { this.setBase(layer, this.chartLabel(m)); this._restoreBase = null; }
    }
    if (this._restoreBase) { const first = this.bases['Seascape depths (feet)'] || Object.values(this.bases)[0]; this.setBase(first); this._restoreBase = null; }
  }

  setBase(layer, name) {
    if (this.baseLayer && this.baseLayer !== layer && this.map.hasLayer(this.baseLayer)) this.map.removeLayer(this.baseLayer);
    if (!this.map.hasLayer(layer)) layer.addTo(this.map);
    name ||= Object.entries(this.bases).find(([, l]) => l === layer)?.[0];
    this.map.fire('baselayerchange', { layer, name });
  }

  // Show a chart file on its own and zoom to the area it covers
  previewChart(m) {
    const layer = this.chartLayers?.[m.file];
    if (!layer) return false;
    if (this.app.S.config.settings.follow_vessel) this.setFollow(false);
    if (m.overlay) layer.addTo(this.map); else this.setBase(layer, this.chartLabel(m));
    if (m.bounds) {
      const b = L.latLngBounds([[m.bounds[1], m.bounds[0]], [m.bounds[3], m.bounds[2]]]);
      const go = () => { if (!b.contains(this.map.getCenter())) this.map.fitBounds(b, { padding: [20, 20], maxZoom: Math.max(m.minzoom, Math.min(m.maxzoom, 14)) }); };
      if (this.map._animatingZoom) this.map.once('zoomend', go); else go();     // a zoom under way would swallow it
    }
    return true;
  }

  // the Effort / Track entries switch the on- and off-effort track (Settings → General → Map display)
  trackToggle(e) {
    if (this._trackSync || !e?.layer) return;
    const key = e.layer === this.layers.effortOn ? 'show_track_on' : e.layer === this.layers.effortOff ? 'show_track_off' : null;
    if (!key) return;
    const v = e.type === 'overlayadd' ? '1' : '0';
    if ((this.app.S.config.display[key] !== '0' ? '1' : '0') !== v) this.app.saveDisplay({ [key]: v });
  }

  // the display settings changed: tick or untick the Effort / Track entries to match
  syncTrackToggles() {
    const disp = this.app.S.config.display;
    this._trackSync = true;
    for (const [layer, key] of [[this.layers.effortOn, 'show_track_on'], [this.layers.effortOff, 'show_track_off']]) {
      const want = disp[key] !== '0';
      if (want && !this.map.hasLayer(layer)) layer.addTo(this.map);
      if (!want && this.map.hasLayer(layer)) this.map.removeLayer(layer);
    }
    this._trackSync = false;
    this.layerControl?._update?.();
  }

  saveOverlayState() {
    const on = Object.entries(this.overlays).filter(([n, l]) => this.map.hasLayer(l) && l !== this.layers.effortOn && l !== this.layers.effortOff).map(([n]) => n);
    try { localStorage.setItem('wsr.overlays.seen', JSON.stringify(Object.keys(this.overlays))); } catch {}
    // keep names not (yet) in the menu, e.g. map feeds still loading, so they come back on
    let before = [];
    try { before = JSON.parse(localStorage.getItem('wsr.overlays') || '[]') || []; } catch {}
    const keep = before.filter((n) => !(n in this.overlays) && / \(feed\)$/.test(n));
    try { localStorage.setItem('wsr.overlays', JSON.stringify([...on, ...keep])); } catch {}
    if (this.map.hasLayer(this.layers.rings)) this.drawRings();
  }

  // The world coastline has ~400,000 points. Drawing it whole made every pan and zoom
  // re-project all of them, so only the land in view is drawn, simplified to about a
  // pixel at the current zoom, on a canvas. Redrawn after each move or zoom.
  async loadCoastline() {
    try {
      const topo = await (await fetch('/static/vendor/land-10m.json')).json();
      const gj = topojson.feature(topo, topo.objects.land);
      this.landPolys = [];
      for (const f of gj.features) {
        const g = f.geometry;
        if (!g) continue;
        for (const poly of g.type === 'MultiPolygon' ? g.coordinates : [g.coordinates]) {
          // Outlines that cross 180° (Eurasia, Fiji, Antarctica…) jump from +180 to −180 part way round,
          // which draws a line across the whole map. Make them continuous instead (longitudes may then
          // run past ±180, which the world copies in drawLand() handle).
          const unwrap = (ring) => {
            let k = 0;
            const out = ring.map(([x, y], j) => {
              if (j) {
                const d = x + k - (ring[j - 1][0] + k);
                if (d > 180) k -= 360; else if (d < -180) k += 360;
              }
              return [x + k, y];
            });
            // a ring that goes right round a pole (Antarctica) is closed along the pole
            const span = out[out.length - 1][0] - out[0][0];
            if (Math.abs(span) > 180) {
              const pole = out.reduce((a2, q) => a2 + q[1], 0) / out.length < 0 ? -89.9 : 89.9;
              out.push([out[out.length - 1][0], pole], [out[0][0], pole]);
            }
            return out;
          };
          const outer = unwrap(poly[0]);
          let w = Infinity, s = 90, e = -Infinity, n = -90;
          for (const [x, y] of outer) { if (x < w) w = x; if (x > e) e = x; if (y < s) s = y; if (y > n) n = y; }
          const holes = poly.slice(1).map((h) => {
            const r = unwrap(h);
            const shift = r[0][0] < w ? 360 : r[0][0] > e ? -360 : 0;     // keep each hole inside its outline
            return shift ? r.map(([x, y]) => [x + shift, y]) : r;
          });
          this.landPolys.push({ bbox: [w, s, e, n], rings: [outer, ...holes] });
        }
      }
      this.landCache = new Map();          // zoom -> Map(polygon index -> simplified [lat,lng] rings)
      this.landRenderer = L.canvas({ pane: 'land', padding: 0.4 });
      this.map.on('moveend', () => this.drawLand());
      this.layers.land.on('add', () => this.drawLand());
      this.drawLand();
    } catch (e) { console.warn('coastline', e); }
  }

  drawLand() {
    if (!this.landPolys || !this.map.hasLayer(this.layers.land)) return;
    const z = Math.max(0, Math.round(this.map.getZoom()));
    const tol = 360 / (256 * 2 ** z);      // about one screen pixel, in degrees
    // clip box: 60% of the view beyond each side, in screen pixels, so it lies outside the
    // canvas (which reaches 40% beyond) and the cut edges are never drawn on screen
    const sz = this.map.getSize();
    const nw = this.map.containerPointToLatLng([-sz.x * 0.6, -sz.y * 0.6]);
    const se = this.map.containerPointToLatLng([sz.x * 1.6, sz.y * 1.6]);
    const W = nw.lng, E = se.lng, N = Math.min(nw.lat, 90), S = Math.max(se.lat, -90);
    // clip a ring ([lng,lat] points) to the box W..E, S..N (Sutherland–Hodgman)
    const clip = (ring, off) => {
      let pts = off ? ring.map(([x, y]) => [x + off, y]) : ring;
      const edges = [[(q) => q[0] >= W, (a, c) => [W, a[1] + (c[1] - a[1]) * (W - a[0]) / (c[0] - a[0])]],
        [(q) => q[0] <= E, (a, c) => [E, a[1] + (c[1] - a[1]) * (E - a[0]) / (c[0] - a[0])]],
        [(q) => q[1] >= S, (a, c) => [a[0] + (c[0] - a[0]) * (S - a[1]) / (c[1] - a[1]), S]],
        [(q) => q[1] <= N, (a, c) => [a[0] + (c[0] - a[0]) * (N - a[1]) / (c[1] - a[1]), N]]];
      for (const [inside, cut] of edges) {
        if (!pts.length) break;
        const out = [];
        let prev = pts[pts.length - 1];
        for (const cur of pts) {
          const ci = inside(cur), pi = inside(prev);
          if (ci) { if (!pi) out.push(cut(prev, cur)); out.push(cur); } else if (pi) out.push(cut(prev, cur));
          prev = cur;
        }
        pts = out;
      }
      return pts;
    };
    if (!this.landCache.has(z)) {
      if (this.landCache.size > 6) this.landCache.delete(this.landCache.keys().next().value);
      this.landCache.set(z, new Map());
    }
    const cache = this.landCache.get(z);
    const simplify = (ring) => {
      const out = [];
      let px = Infinity, py = Infinity;
      for (const [x, y] of ring) {
        if (Math.abs(x - px) > tol || Math.abs(y - py) > tol) { out.push([y, x]); px = x; py = y; }
      }
      return out;
    };
    const shapes = [];
    // the view can run past ±180° (the map wraps), so check copies one world either side
    for (const off of [-720, -360, 0, 360, 720]) {
      this.landPolys.forEach((p, i) => {
        const [w, s, e, n] = p.bbox;
        if (e + off < W || w + off > E || n < S || s > N) return;
        if (e - w < tol * 2 && n - s < tol * 2) return;            // smaller than a couple of pixels
        const inside = w + off >= W && e + off <= E && s >= S && n <= N;
        let rings;
        if (inside) {                                              // whole polygon in view: simplify once per zoom
          rings = cache.get(i);
          if (!rings) {
            rings = p.rings.map(simplify).filter((r) => r.length >= 3);
            cache.set(i, rings);
          }
          if (off) rings = rings.map((r) => r.map(([la, lo]) => [la, lo + off]));
        } else {                                                   // big polygon (e.g. a continent): just the part in view
          rings = p.rings.map((r) => simplify(clip(r, off))).filter((r) => r.length >= 3);
        }
        if (rings.length) shapes.push(rings);
      });
    }
    if (!this.landLayer) {
      this.landLayer = L.polygon(shapes, { renderer: this.landRenderer, pane: 'land', interactive: false,
        color: '#6b5b3e', weight: 1, fillColor: '#e8dcb5', fillOpacity: 1 }).addTo(this.layers.land);
    } else {
      this.landLayer.setLatLngs(shapes);
    }
  }

  // ---------------------------------------------------------------- controls
  buildControls() {
    const self = this;
    const Btns = L.Control.extend({
      options: { position: 'topleft' },
      onAdd() {
        const box = L.DomUtil.create('div', 'leaflet-bar map-tools');
        const mk = (id, glyph, title, fn) => {
          const a = L.DomUtil.create('a', '', box);
          a.href = '#'; a.id = id; a.title = title; a.innerHTML = glyph; a.setAttribute('role', 'button');
          L.DomEvent.on(a, 'click', (e) => { L.DomEvent.stop(e); fn(); });
          return a;
        };
        self.followBtn = mk('btn-follow', '⌖', 'Follow the vessel (Mod+Shift+C centers once)', () => self.setFollow(!self.app.S.config.settings.follow_vessel, true));
        self.measureBtn = mk('btn-measure', '📏', 'Measure bearing and distance: click points, double-click or Esc to finish', () => self.toggleMeasure());
        mk('btn-rings', '◎', 'Range rings around the vessel', () => self.toggleLayer(self.layers.rings));
        mk('btn-fit', '⤢', 'Zoom to the whole survey', () => self.fitSurvey());
        L.DomEvent.disableClickPropagation(box);
        return box;
      },
    });
    new Btns().addTo(this.map);

    const Readout = L.Control.extend({
      options: { position: 'bottomleft' },
      onAdd() {
        const d = L.DomUtil.create('div', 'map-readout');
        d.innerHTML = '<div id="cursor-pos">—</div><div id="cursor-rel"></div><div class="nmscale"><div id="nmscale-bar"></div><span id="nmscale-label"></span><span id="cursor-depth" title="Seascape depth below chart datum at the cursor. Not for navigation."></span></div>';
        L.DomEvent.disableClickPropagation(d);
        return d;
      },
    });
    new Readout().addTo(this.map);
    this.map.on('zoomend moveend', () => { this.updateScale(); this.drawGraticule(); });
    this.map.on('overlayadd resize', () => this.drawGraticule());
    setTimeout(() => this.updateScale(), 0);
    this.setFollow(this.app.S.config.settings.follow_vessel, false);
  }

  toggleLayer(layer) {
    if (this.map.hasLayer(layer)) this.map.removeLayer(layer); else layer.addTo(this.map);
  }

  // Lat/lon grid with labels; spacing adapts to the zoom so there are roughly 4–8 lines.
  drawGraticule() {
    const g = this.layers.graticule;
    g.clearLayers();
    if (!this.map.hasLayer(g)) return;
    const b = this.map.getBounds(), sz = this.map.getSize();
    const S = Math.max(b.getSouth(), -85), N = Math.min(b.getNorth(), 85), W = b.getWest(), E = b.getEast();
    const steps = [30, 20, 10, 5, 2, 1, 30 / 60, 20 / 60, 10 / 60, 5 / 60, 2 / 60, 1 / 60, 0.5 / 60, 0.2 / 60, 0.1 / 60];
    const latStep = steps.find((s) => (N - S) / s >= 4) || steps.at(-1);
    const lonStep = steps.find((s) => s <= latStep && (E - W) / s <= 14) || latStep;
    const style = { color: '#1f3b57', weight: 0.8, opacity: 0.55, interactive: false };
    const lab = (txt, ll, cls) => L.marker(ll, { interactive: false, keyboard: false,
      icon: L.divIcon({ className: `grat-label ${cls}`, html: txt, iconSize: null }) }).addTo(g);
    const right = this.map.containerPointToLatLng([sz.x - 4, 0]).lng;
    const top = this.map.containerPointToLatLng([0, 4]).lat;      // longitude labels along the top edge
    for (let lat = Math.ceil(S / latStep) * latStep; lat <= N + 1e-9; lat += latStep) {
      L.polyline([[lat, W - 1], [lat, E + 1]], style).addTo(g);
      lab(gratText(lat, true, latStep), [lat, right], 'grat-lat');
    }
    for (let lon = Math.ceil(W / lonStep) * lonStep; lon <= E + 1e-9; lon += lonStep) {
      L.polyline([[S - 1, lon], [N + 1, lon]], style).addTo(g);
      lab(`<span>${gratText(lon, false, lonStep)}</span>`, [top, lon], 'grat-lon');
    }
  }

  updateScale() {
    const bar = document.getElementById('nmscale-bar');
    if (!bar) return;
    const y = this.map.getSize().y / 2;
    const a = this.map.containerPointToLatLng([0, y]), b = this.map.containerPointToLatLng([100, y]);
    const nmPer100 = distM([a.lat, a.lng], [b.lat, b.lng]) / 1852;
    const nice = [0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
    const v = nice.filter((n) => n <= nmPer100 * 1.2).at(-1) || nice[0];
    bar.style.width = `${Math.round(100 * v / nmPer100)}px`;
    document.getElementById('nmscale-label').textContent = `${v} nm`;
  }

  setFollow(on, center = false) {
    this.app.S.config.settings.follow_vessel = on;
    this.followBtn?.classList.toggle('active', on);
    if (on && center) this.centerVessel();
    clearTimeout(this._followSave);
    this._followSave = setTimeout(() => api('/api/settings', { updates: { follow_vessel: on } }).catch(() => {}), 800);
  }

  centerVessel() {
    const v = this.app.S.vessel;
    if (v && v.lat !== null) this.map.panTo([v.lat, v.lon]);
    else toast('No vessel position yet.', 'warn');
  }

  cursor(ll) {
    const fmt = this.app.S.config.settings.latlon_format;
    document.getElementById('cursor-pos').textContent = fmtPos(ll.lat, ll.lng, fmt);
    const v = this.app.S.vessel;
    const rel = document.getElementById('cursor-rel');
    if (v && v.lat !== null) {
      const d = distM([v.lat, v.lon], [ll.lat, ll.lng]);
      const b = bearing([v.lat, v.lon], [ll.lat, ll.lng]);
      rel.textContent = `From vessel: ${fmtBrg(b)}T ${this.magText(b)} · ${fmtDist(d, this.app.unit())}`;
    } else rel.textContent = '';
    if (this.measure?.active && this.measure.pts.length) this.drawMeasure(ll);
    this.probeDepth(ll);
  }

  // Depth at the cursor, when the base map is a style with a depth model (Seascape).
  // One lookup at a time; the latest position is looked up when the previous one finishes.
  probeDepth(ll) {
    const probe = this.baseLayer?._depth;
    if (!probe) { this.showDepth(''); return; }
    this._depthNext = [ll.lat, ll.lng, this.map.getZoom(), probe];
    if (this._depthBusy) return;
    this._depthBusy = true;
    (async () => {
      while (this._depthNext) {
        const [lat, lon, z, p] = this._depthNext;
        this._depthNext = null;
        const r = await p.at(lat, lon, z).catch(() => null);
        if (this.baseLayer?._depth === p) this.showDepth(p.text(r));
      }
    })().finally(() => {
      this._depthBusy = false;
      if (this._depthNext) { const [lat, lng] = this._depthNext; this.probeDepth({ lat, lng }); }
    });
  }

  showDepth(text) {
    const d = document.getElementById('cursor-depth');
    if (d) { d.textContent = text; d.hidden = !text; }
  }

  magText(trueB) {
    const v = this.app.variation();
    return v === null ? '' : `(${fmtBrg((trueB - v + 360) % 360)}M)`;
  }

  // ---------------------------------------------------------------- vessel
  // A new position from the server (about once a second). With Smooth vessel movement on (Settings →
  // General → Map display; this computer only) the icon, heading vector and range rings glide from where
  // they're drawn to the new fix instead of hopping. Only the drawing is smoothed: the data, popups,
  // measurements and Follow vessel all use the real latest fix.
  // the secondary GPS / NMEA inputs chosen to show on the map (0.41): a point and its name each, where
  // that input says it is (drawing only; nothing is recorded in the tables). "Other" sources (0.43; "external" before 0.44) have
  // their own layers instead: see updateExternal.
  updateOthers(list) {
    if (!this.layers.others) this.layers.others = L.layerGroup().addTo(this.map);
    this._others = this._others || new Map();
    const seen = new Set();
    for (const o of list || []) {
      if (o.lat == null || o.lon == null) continue;
      if (o.other) { this.updateExternal(o); continue; }
      seen.add(o.name);
      let m = this._others.get(o.name);
      const ll = [o.lat, o.lon];
      if (!m) {
        m = L.circleMarker(ll, { pane: 'vessel', radius: 6, color: '#ffffff', weight: 2, fillColor: '#7b3fbf', fillOpacity: 0.9, className: 'secondary-input' })
          .bindTooltip(o.name, { permanent: true, direction: 'right', offset: [8, 0], className: 'secondary-label' });
        m.addTo(this.layers.others);
        this._others.set(o.name, m);
      } else {
        m.setLatLng(ll);
      }
    }
    for (const [name, m] of this._others) {
      if (!seen.has(name)) { this.layers.others.removeLayer(m); this._others.delete(name); }
    }
    this.checkExternalsLost();
  }

  // ---------------------------------------------------------------- "other" inputs (0.43)
  // (a drone, a buoy, a second vessel: "external" before 0.44; the code still says external.) Each one in use
  // that shows on the map has a layer of its own in the menu ("<name> (other)"):
  // its trail and its latest position (and name), in its own color and line, below all of the survey's own layers.
  externalLabel(name) { return `${name} (other)`; }

  // the inputs changed (or the app loaded): one layer per external shown on the map, styled as its input says
  syncExternals(inputs) {
    const want = new Map((inputs || []).filter((x) => x.role === 'other' && x.enabled !== false && x.show_on_map !== false).map((x) => [x.name, x]));
    for (const [name, x] of this.externals) {
      if (want.has(name)) continue;
      this.layerControl.removeLayer(x.group);
      delete this.overlays[this.externalLabel(name)];
      if (this.map.hasLayer(x.group)) this.map.removeLayer(x.group);
      this.externals.delete(name);
    }
    let ov = null, seen = null;
    try { ov = JSON.parse(localStorage.getItem('wsr.overlays') || 'null'); seen = JSON.parse(localStorage.getItem('wsr.overlays.seen') || 'null'); } catch {}
    for (const [name, inp] of want) {
      let x = this.externals.get(name);
      if (!x) {
        const group = L.layerGroup();
        group._group = 'offline';
        x = { group, pts: x?.pts || [], style: inp,
          line: L.polyline([], { pane: 'externals', interactive: false }).addTo(group),
          dot: L.marker([0, 0], { pane: 'externals', keyboard: false }) };
        x.dot.bindPopup(() => this.externalPopup(name), { className: 'external-popup' });     // 0.44
        this.externals.set(name, x);
        const label = this.externalLabel(name);
        this.overlays[label] = group;
        this.layerControl.addOverlay(group, label);
        const on = ov && seen?.includes(label) ? ov.includes(label) : true;
        if (on) group.addTo(this.map);
      }
      x.style = inp;
      this.styleExternal(name);
    }
    this.saveOverlayState();
  }

  styleExternal(name) {
    const x = this.externals.get(name);
    if (!x) return;
    const s = x.style || {};
    const w = +s.width || 2;
    x.line.setStyle({ color: s.color || '#e07000', weight: w, dashArray: dashFor(s.line || 'solid', w), opacity: 0.9 });
    x.iconKey = null;
    this.iconExternal(name);
    if (s.label !== false) {
      if (!x.dot.getTooltip()) x.dot.bindTooltip(name, { permanent: true, direction: 'right', offset: [12, 0], pane: 'externalLabels', className: 'secondary-label external-label' });
    } else if (x.dot.getTooltip()) x.dot.unbindTooltip();
    this.drawExternal(name);
  }

  // the trail: all of it, the last N minutes, or none (the point only)
  drawExternal(name) {
    const x = this.externals.get(name);
    if (!x) return;
    const t = x.style?.trail ?? 'all';
    const from = t === 'all' ? -Infinity : t === 'none' ? Infinity : Date.now() - (+t) * 60000;
    x.line.setLatLngs(x.pts.filter((p) => p[0] >= from).map((p) => [p[1], p[2]]));
    const last = x.pts[x.pts.length - 1];
    if (last) {
      x.dot.setLatLng([last[1], last[2]]);
      if (!x.group.hasLayer(x.dot)) x.dot.addTo(x.group);
    } else if (x.group.hasLayer(x.dot)) x.group.removeLayer(x.dot);
  }

  // its icon: shape, color, heading and lost (rebuilt only when one of them changes)
  iconExternal(name) {
    const x = this.externals.get(name);
    if (!x) return;
    const s = x.style || {}, color = s.color || '#e07000', icon = s.icon || 'circle';
    const lost = this.externalLost(x);
    const hdg = x.fix ? (x.fix.heading ?? x.fix.cog) : null;
    const key = `${icon}|${color}|${lost}|${hdg == null ? '' : Math.round(hdg)}`;
    if (key === x.iconKey) return;
    x.iconKey = key;
    x.dot.setIcon(L.divIcon({ className: `external-input${lost ? ' external-lost' : ''}`, html: externalIconHtml(icon, color, hdg, lost), iconSize: [28, 28], iconAnchor: [14, 14] }));
  }

  // 0.45: lost = no fix for EXTERNAL_LOST_MS (or none since its trail was read back from the file)
  externalLost(x) { return !x.lastFixMs || Date.now() - x.lastFixMs > EXTERNAL_LOST_MS; }

  // every vessel message: an "other" input that wasn't in it may have just been lost
  checkExternalsLost() {
    for (const [name, x] of this.externals) {
      const lost = this.externalLost(x);
      if (lost === x.wasLost) continue;
      x.wasLost = lost;
      this.iconExternal(name);
      if (x.dot.isPopupOpen()) x.dot.setPopupContent(this.externalPopup(name));
    }
  }

  // a new fix from an external (the 1 s vessel message)
  updateExternal(o) {
    const x = this.externals.get(o.name);
    if (!x) return;
    x.lastFixMs = Date.now() - (o.age || 0) * 1000;
    const last = x.pts[x.pts.length - 1];
    if (!last || last[1] !== o.lat || last[2] !== o.lon) {
      x.pts.push([Date.now() - (o.age || 0) * 1000, o.lat, o.lon]);
      if (x.pts.length > 50000) x.pts.splice(0, x.pts.length - 50000);
    }
    x.fix = o;
    this.drawExternal(o.name);
    this.iconExternal(o.name);
    if (x.dot.isPopupOpen()) x.dot.setPopupContent(this.externalPopup(o.name));
  }

  // 0.44: click an "other" source's point: its name, position, speed, heading, and bearing and distance
  // from the platform (live while the popup is open)
  externalPopup(name) {
    const x = this.externals.get(name);
    if (!x) return '';
    const f = x.fix || {}, last = x.pts[x.pts.length - 1];
    const lat = f.lat ?? last?.[1], lon = f.lon ?? last?.[2];
    const fmt = this.app.S.config.settings.latlon_format, v = this.app.S.vessel;
    const num = (n, d) => (n === null || n === undefined || isNaN(n) ? '—' : (+n).toFixed(d));
    let rel = '<tr><th>From platform</th><td>— (no platform position)</td></tr>';
    if (lat != null && v?.lat != null) {
      const b = bearing([v.lat, v.lon], [lat, lon]), d = distM([v.lat, v.lon], [lat, lon]);
      rel = `<tr><th>Bearing from platform</th><td>${fmtBrg(b)}T ${this.magText(b)}</td></tr>
      <tr><th>Distance from platform</th><td>${fmtDist(d, this.app.unit())}</td></tr>`;
    }
    // 0.45: when it was last heard from (its last fix; from the recorded trail after a restart)
    const lastMs = x.lastFixMs || last?.[0], lost = this.externalLost(x);
    let updated = '—';
    if (lastMs) {
      const tp = timeParts(new Date(lastMs).toISOString(), this.app.clock()), ago = Math.max(0, Math.round((Date.now() - lastMs) / 1000));
      const agoText = ago < 120 ? `${ago} s ago` : ago < 7200 ? `${Math.round(ago / 60)} min ago` : `${(ago / 3600).toFixed(1)} h ago`;
      updated = `${tp.date !== timeParts(new Date().toISOString(), this.app.clock()).date ? tp.date + ' ' : ''}${tp.time} ${tp.abbr} (${agoText})`;
    }
    const lostRow = lost ? '<tr><th></th><td class="ext-lost-note">✕ GPS lost: no position for over 15 s</td></tr>' : '';
    return `<b>${esc(name)}</b> <span class="hint">(other source)</span><table class="pop">
      <tr><th>Position</th><td>${lat != null ? fmtPos(lat, lon, fmt) : '—'}</td></tr>
      <tr><th>Speed</th><td>${num(f.sog, 1)} kn</td></tr>
      <tr><th>Heading</th><td>${fmtBrg(f.heading ?? f.cog)}T</td></tr>
      ${rel}
      <tr><th>Last updated</th><td class="ext-updated">${updated}</td></tr>${lostRow}</table>`;
  }

  // the trails so far, from the server (at start, and when a survey is started, opened or closed)
  async loadExternals() {
    if (!this.externals?.size) return;
    let r;
    try { r = await api('/api/externals'); } catch { return; }
    for (const [name, x] of this.externals) {
      x.pts = (r.tracks || {})[name] || [];
      this.drawExternal(name);
      this.iconExternal(name);
    }
  }

  updateVessel(v) {
    const disp = this.app.S.config.display;
    if (!v || v.lat === null || v.lat === undefined) return;
    const ll = [v.lat, v.lon];
    const hdg = v.best_heading ?? v.cog ?? 0;
    const color = v.lost ? '#888' : (disp.vessel_color || '#d00');
    const kind = PLATFORM_SVG[this.app.platformType()] ? this.app.platformType() : 'Shipboard';
    const turns = kind === 'Shipboard' || kind === 'Aerial';          // a tower or a dot isn't rotated
    if (!this.vessel) {
      this.vesselIcon = (c, k) => L.divIcon({ className: `vessel-icon platform-${k.toLowerCase()}`, iconSize: [28, 28], iconAnchor: [14, 14],
        html: `<div class="vessel-rot" style="width:28px;height:28px;display:flex;align-items:center;justify-content:center">${PLATFORM_SVG[k](c)}</div>` });
      this.vessel = L.marker(ll, { icon: this.vesselIcon(color, kind), pane: 'vessel', keyboard: false })
        .addTo(this.layers.vessel).bindPopup(() => this.vesselPopup());
      // 0.44: Leaflet makes the icon afresh (unrotated) when the Platform icon layer is switched back on,
      // so set its rotation again then
      this.vessel.on('add', () => {
        this._drawnHdg = null;
        if (this._drawn && this._lastTo) this.placeVessel(this._drawn.ll, this._drawn.hdg, this._lastTo);
      });
      this.predictor = L.polyline([ll, ll], { color, weight: 2, dashArray: '6 4', pane: 'vessel', interactive: false }).addTo(this.layers.vessel);
      this._lastIcon = `${color}${kind}`;
      if (this.app.S.config.settings.follow_vessel) this.map.setView(ll, Math.max(this.map.getZoom(), 11));
    } else if (this._lastIcon !== `${color}${kind}`) {
      this.vessel.setIcon(this.vesselIcon(color, kind));
      this._lastIcon = `${color}${kind}`;
      this._drawnHdg = null;                                           // the new icon needs its rotation set
    }
    this.predictor.setStyle({ color });
    this.glideVessel({ ll, hdg, sog: v.sog || 0, turns, lost: !!v.lost });
    if (this.app.S.config.settings.follow_vessel && Date.now() - this.userMoved > 1500) {
      const pt = this.map.latLngToContainerPoint(ll), sz = this.map.getSize();
      if (pt.x < sz.x * 0.25 || pt.x > sz.x * 0.75 || pt.y < sz.y * 0.25 || pt.y > sz.y * 0.75) this.map.panTo(ll);
    }
    if (this.vessel.isPopupOpen()) this.vessel.setPopupContent(this.vesselPopup());
    const op = this.openRowPopup;
    if (op && op.m.isPopupOpen()) op.m.setPopupContent(this.rowPopup(op.tab, op.id));     // live distance
  }

  smoothVessel() { return this.app.S.config.settings.smooth_vessel !== false; }

  // Move the drawn vessel to the fix `to` {ll, hdg, sog, turns, lost}: at once, or gliding over about
  // the time since the previous fix. It jumps instead after a gap, a big jump (another input, a GPS
  // glitch), a lost GPS or while the window is hidden.
  glideVessel(to) {
    const now = performance.now();
    this._lastTo = to;
    const gap = this._lastFixAt ? now - this._lastFixAt : Infinity;
    this._lastFixAt = now;
    cancelAnimationFrame(this._glideRaf);
    this._glideRaf = null;
    const from = this._drawn;
    const jump = !from || !this.smoothVessel() || to.lost || document.hidden || gap > SMOOTH.maxGapMs
      || distM(from.ll, to.ll) > SMOOTH.maxJumpM;
    if (jump) { this.placeVessel(to.ll, to.hdg, to); return; }
    const dur = Math.min(SMOOTH.maxMs, Math.max(SMOOTH.minMs, gap));
    const t0 = now, dh = ((to.hdg - from.hdg + 540) % 360) - 180;     // the short way round
    let lastDraw = 0;
    const step = (t) => {
      const f = Math.min(1, (t - t0) / dur);
      if (f >= 1 || t - lastDraw >= SMOOTH.frameMs) {
        lastDraw = t;
        this.placeVessel([from.ll[0] + (to.ll[0] - from.ll[0]) * f, from.ll[1] + (to.ll[1] - from.ll[1]) * f],
          (from.hdg + dh * f + 360) % 360, to);
      }
      this._glideRaf = f < 1 ? requestAnimationFrame(step) : null;
    };
    this._glideRaf = requestAnimationFrame(step);
  }

  // Draw the vessel, its heading vector and the range rings at ll, pointing hdg.
  placeVessel(ll, hdg, fix) {
    this._drawn = { ll, hdg };
    this.vessel.setLatLng(ll);
    const rot = fix.turns ? Math.round(hdg * 10) / 10 : 0;
    if (this._drawnHdg !== rot) {
      const inner = this.vessel.getElement()?.querySelector('.vessel-rot');
      if (inner) { inner.style.transform = rot ? `rotate(${rot}deg)` : ''; this._drawnHdg = rot; }
    }
    // heading vector: length = distance covered in N minutes at the current speed
    const disp = this.app.S.config.display;
    if (disp.heading_vector === '0' || !fix.turns) this.predictor.setLatLngs([]);
    else {
      const mins = Math.max(0, +disp.heading_vector_min || 6);
      this.predictor.setLatLngs([ll, destination(ll, hdg, fix.sog * 1852 * mins / 60)]);
    }
    if (this.map.hasLayer(this.layers.rings)) this.placeRings(ll);
  }

  // where the vessel is drawn (mid-glide, between fixes), or null before the first fix
  drawnVessel() { return this._drawn ? [...this._drawn.ll] : null; }

  vesselPopup() {
    const v = this.app.S.vessel, fmt = this.app.S.config.settings.latlon_format;
    const title = { Shipboard: 'Vessel', Aerial: 'Aircraft', Stationary: 'Station', Other: 'Platform' }[this.app.platformType()] || 'Vessel';
    return `<b>${title}</b><table class="pop">
      <tr><th>Position</th><td>${fmtPos(v.lat, v.lon, fmt)}</td></tr>
      <tr><th>SOG</th><td>${v.sog ?? '—'} kn</td></tr><tr><th>COG</th><td>${fmtBrg(v.cog)}T</td></tr>
      <tr><th>Heading</th><td>${fmtBrg(v.heading)}T</td></tr>
      <tr><th>Variation</th><td>${this.app.variation()?.toFixed(1) ?? '—'}°</td></tr>
      <tr><th>Source</th><td>${esc(v.source || '—')}</td></tr>
      <tr><th>Fix age</th><td>${v.age ?? '—'} s ${v.lost ? '(LOST)' : ''}</td></tr></table>`;
  }

  // Range rings round the vessel (drawn where the vessel icon is). Rebuilt when switched on or the
  // map unit changes; while the vessel moves only their centers move (placeRings).
  drawRings() {
    this.layers.rings.clearLayers();
    this._rings = null;
    const ll = this._drawn?.ll || (this.app.S.vessel?.lat != null ? [this.app.S.vessel.lat, this.app.S.vessel.lon] : null);
    if (!ll) return;
    const unit = this._ringUnit = this.app.unit();
    const steps = unit === 'km' ? [0.5, 1, 2, 3] : unit === 'm' || unit === 'yd' ? [250, 500, 1000, 2000] : [0.25, 0.5, 1, 2];
    this._rings = steps.map((s) => {
      const r = s * ({ nm: 1852, km: 1000, m: 1, mi: 1609.344, yd: 0.9144 }[unit] || 1852);
      const circle = L.circle(ll, { radius: r, color: '#c00', weight: 1, fill: false, dashArray: '3 4', interactive: false }).addTo(this.layers.rings);
      const label = L.marker(destination(ll, 0, r), { interactive: false, icon: L.divIcon({ className: 'ring-label', html: `${s} ${unit}`, iconSize: null }) }).addTo(this.layers.rings);
      return { r, circle, label };
    });
  }

  placeRings(ll) {
    if (!this._rings || this._ringUnit !== this.app.unit()) { this._drawn = { ...this._drawn, ll }; this.drawRings(); return; }
    for (const g of this._rings) { g.circle.setLatLng(ll); g.label.setLatLng(destination(ll, 0, g.r)); }
  }

  // ---------------------------------------------------------------- track
  // True when fading is on and the timestamp is older than the chosen number of hours.
  isOld(iso) {
    const d = this.app.S.config.display;
    if (d.fade_enabled !== '1' || !iso) return false;
    const t = new Date(iso).getTime();
    return !isNaN(t) && Date.now() - t > (+d.fade_min || 30) * 60000;
  }

  redrawData() {
    for (const t of ['sightings', 'events', 'marks']) this.drawMarkers(t);
    this.drawTrack();
  }

  // Zoom to the whole open survey (its trackline, sightings and events), e.g. after opening an old one.
  fitSurvey() {
    const S = this.app.S, pts = [];
    for (const p of S.track || []) { const a = +p.Lat, b = +p.Lon; if (Number.isFinite(a) && Number.isFinite(b) && (a || b)) pts.push([a, b]); }
    for (const tab of ['sightings', 'events']) {
      for (const r of S.tables[tab]?.rows || []) { const ll = this.rowPos(tab, r); if (ll) pts.push(ll); }
    }
    if (!pts.length) return false;
    if (S.config.settings.follow_vessel) { this.setFollow(false, true); toast('Stopped following the vessel to show the whole survey (⌖ turns it back on).', 'info', 5000); }
    const b = L.latLngBounds(pts);
    if (b.getNorth() - b.getSouth() < 1e-4 && b.getEast() - b.getWest() < 1e-4) this.map.setView(b.getCenter(), 13);
    else this.map.fitBounds(b.pad(0.1), { maxZoom: 14 });
    return true;
  }

  drawTrack() {
    this.layers.track.clearLayers();
    this.trackSeg = null;
    this.trackPrev = null;
    const S = this.app.S;
    const rows = S.tables.effort?.rows;
    const states = trackStates(S.track, rows), brks = trackBreaks(S.track, rows);
    S.track.forEach((p, i) => this.appendTrack(p, false, states[i], brks[i]));
    this.drawSurveyLabels();
  }

  // 0.47: "Start" and "End" labels where the survey started and ended (Settings → General → Map display
  // → Trackline: label_survey_start / label_survey_end, on by default)
  drawSurveyLabels() {
    const S = this.app.S, disp = S.config.display;
    this.layers.surveyLabels ??= L.layerGroup().addTo(this.map);
    this.layers.surveyLabels.clearLayers();
    const rows = S.tables.effort?.rows || [];
    const at = (r, pt) => (r && r.Lat !== '' && !isNaN(+r.Lat) && r.Lon !== '' ? [+r.Lat, +r.Lon] : pt ? [+pt.Lat, +pt.Lon] : null);
    const label = (ll, text, when, cls) => {
      if (!ll || isNaN(ll[0])) return;
      const t = timeParts(when, this.app.clock());
      L.circleMarker(ll, { pane: 'tracks', radius: 4, color: '#ffffff', weight: 1.5, fillColor: '#222', fillOpacity: 1, interactive: false })
        .bindTooltip(`${text}${t ? ` ${t.time.slice(0, 5)}` : ''}`, { permanent: true, direction: 'top', offset: [0, -5], className: `survey-label ${cls}` })
        .addTo(this.layers.surveyLabels);
    };
    const start = rows.find((r) => r.Effort === 'Start'), end = rows.at(-1)?.Effort === 'End' ? rows.at(-1) : null;
    if (disp.label_survey_start !== '0' && (start || S.track[0])) label(at(start, S.track[0]), 'Start', start?.DateTime || S.track[0]?.DateTime, 'survey-start');
    if (disp.label_survey_end !== '0' && end) label(at(end, S.track.at(-1)), 'End', end.DateTime, 'survey-end');
  }

  // Add a point to the drawn trackline. The line is broken (not joined to the previous point) only at
  // ERROR rows in the Effort table (trackBreaks; 0.45: no hidden breaks; Error check → Fix adds them).
  // 0.47: the stretch marked ERROR (from the last good point, through any points inside it, to the next
  // good one) is hidden, or drawn in ERROR's color when Map display → Trackline says so (show_track_errors).
  appendTrack(p, live = true, state = p.Effort, brk = null) {
    const disp = this.app.S.config.display;
    const ll = [+p.Lat, +p.Lon];
    if (isNaN(ll[0])) return;
    const prev = this.trackPrev;
    if (live) {                                   // a new point: its state and break from the Effort table now
      const rows = this.app.S.tables.effort?.rows;
      state = trackStates([p], rows)[0];
      brk = prev ? trackBreaks([prev.p, p], rows)[1] : false;
    }
    this.trackPrev = { p, state };
    if (prev && (brk || state === 'ERROR')) {
      // this step is inside an ERROR stretch
      if (disp.show_track_errors === '1') {
        if (this.trackSeg?.key !== 'ERROR') {
          const w = +disp.track_width || 3;
          const line = L.polyline([[+prev.p.Lat, +prev.p.Lon]], { color: effortColor('ERROR'), weight: w, pane: 'tracks', opacity: 0.9, className: 'track-error' })
            .addTo(this.layers.track);
          const at = p.DateTime;                    // a time inside the stretch: its ERROR row is in force
          line.on('click', (e) => this.trackPopup(e, null, at));   // 0.48: says Effort: ERROR
          this.trackSeg = { line, key: 'ERROR', last: [+prev.p.Lat, +prev.p.Lon] };
        }
        this.trackSeg.line.addLatLng(ll);
        this.trackSeg.last = ll;
      } else this.trackSeg = null;
      if (state === 'ERROR') return;                 // still inside it
      // the first good point after it: a new line starts here
      if (this.trackSeg?.key !== 'ERROR') this.trackSeg = null;
    } else if (state === 'ERROR') { this.trackSeg = null; return; }
    const on = isOn(state), old = this.isOld(p.DateTime), color = effortColor(state), key = `${on}|${color}|${old}`;
    if (!this.trackSeg || this.trackSeg.key !== key) {
      const start = this.trackSeg ? [this.trackSeg.last] : [];
      let line = null;
      if (disp[on ? 'show_track_on' : 'show_track_off'] !== '0') {
        const w = on ? (+disp.track_width || 3) : (+disp.track_off_width || 1.5);
        const style = (on ? disp.track_on_style : disp.track_off_style) || 'solid';
        line = L.polyline([...start, ll], {
          color,              // the Effort value's color (Settings → Dropdowns → Effort)
          weight: w, pane: 'tracks', dashArray: dashFor(style, w), lineCap: style === 'dotted' ? 'round' : 'butt',
          opacity: old ? 0.3 : 1 }).addTo(this.layers.track);
        line.on('click', (e) => this.trackPopup(e));
      }
      this.trackSeg = { line, key, last: ll };
    } else {
      this.trackSeg.line?.addLatLng(ll);
      this.trackSeg.last = ll;
    }
  }

  // errorAt (0.48): the click was on a stretch flagged with a GPS error: Effort ERROR and its segment
  trackPopup(e, point = null, errorAt = null) {
    const pts = this.app.S.track;
    if (!pts.length) return;
    let best = point, bd = Infinity;
    if (!best) for (const p of pts) {
      const d = distM([e.latlng.lat, e.latlng.lng], [+p.Lat, +p.Lon]);
      if (d < bd) { bd = d; best = p; }
    }
    // 0.46: the effort and segment in force at that point, from the Effort table as it is now
    const rows = this.app.S.tables.effort?.rows;
    const errRow = errorAt ? [...(rows || [])].filter((r) => r.Effort === 'ERROR' && new Date(r.DateTime) <= new Date(errorAt)).at(-1) : null;
    const er = errRow || effortRowAt(rows, best.DateTime);
    const st = errRow ? 'ERROR' : trackStates([best], rows)[0];
    const fmt = this.app.S.config.settings.latlon_format, t = timeParts(best.DateTime, this.app.clock());
    L.popup().setLatLng(errRow ? e.latlng : [+best.Lat, +best.Lon]).setContent(`<b>${errRow ? 'Effort: ERROR' : 'Track point'}</b>${errRow ? '<div class="hint">Flagged with a GPS error (nearest track point below)</div>' : ''}<table class="pop">
      <tr><th>Time</th><td>${t ? `${t.date} ${t.time} ${t.abbr}` : esc(best.DateTime)}</td></tr>
      <tr><th>Position</th><td>${fmtPos(best.Lat, best.Lon, fmt)}</td></tr>
      <tr><th>SOG</th><td>${esc(best.SOG)} kn</td></tr><tr><th>COG</th><td>${esc(best.COG)}°T</td></tr>
      <tr><th>Effort</th><td>${esc(st)}</td></tr>
      <tr><th>Segment</th><td>${er?.Segment ? esc(er.Segment) : '—'}</td></tr>
      ${errRow?.Notes ? `<tr><th>Notes</th><td>${esc(errRow.Notes)}</td></tr>` : ''}</table>`).openOn(this.map);
  }

  // ---------------------------------------------------------------- markers
  rowPos(tab, r) {
    const pairs = { sightings: [['SigLat', 'SigLon'], ['Lat', 'Lon']],
      events: [['Lat', 'Lon']], marks: [['Lat', 'Lon']] }[tab] || [];
    for (const [a, b] of pairs) if (r[a] !== '' && r[b] !== '' && !isNaN(+r[a]) && !isNaN(+r[b]) && r[a] !== undefined) return [+r[a], +r[b]];
    return null;
  }

  markerColor(tab, r) {
    const S = this.app.S, disp = S.config.display;
    if (disp.use_species_colors !== '0') {
      if (tab === 'sightings') {
        const sp = r.Species;
        const c = (S.config.lists.species || []).find((s) => s.name === sp)?.color;
        if (c) return c;
      }
      if (tab === 'events') {
        const c = (S.config.lists.event_types || []).find((s) => s.name === r.EventType)?.color;
        if (c) return c;
      }
    }
    if (tab === 'marks' && r.Color) return r.Color;
    return disp[`${tab}_marker_color`] || 'orange';
  }

  label(tab, r) {
    if (tab === 'sightings') {
      // species code (short name), plus the FieldID when there is one
      const sp = (this.app.S.config.lists.species || []).find((s) => s.name === r.Species);
      const code = sp?.species_code || r.Species || '';
      return [code, r.FieldID].filter(Boolean).join(' ') || r.SightNo;
    }
    if (tab === 'events') {
      const code = (this.app.S.config.lists.event_types || []).find((e) => e.name === r.EventType)?.event_code || '';
      return [code, r.ID].filter(Boolean).join(' ') || (r.EventNo ? `E${r.EventNo}` : '');
    }
    return { marks: r.Name }[tab] || '';
  }

  drawMarkers(tab) {
    const layer = this.markerLayers[tab];
    if (!layer) return;
    layer.clearLayers();
    if (tab === 'sightings') { this.layers.lines.clearLayers(); this.layers.fidlines.clearLayers(); this.layers.relines.clearLayers(); this.layers.resights.clearLayers(); }
    const byFid = {};
    const disp = this.app.S.config.display;
    const rad = +disp.marker_radius || 8, lsize = +disp.label_size || 12;
    const shape = disp[`${tab}_marker_shape`] || 'Diamond';
    this.markerIndex = this.markerIndex || {};
    const rs = tab === 'sightings' ? new Resights(this.app.S.tables.sightings?.rows) : null;
    for (const r of this.app.S.tables[tab]?.rows || []) {
      if (r.Map === '0') continue;
      const pos = this.rowPos(tab, r);
      if (!pos) continue;
      const color = this.markerColor(tab, r);
      const look = this.markerLook(tab, r, rs);
      if (!look) continue;                      // resights set to "Not shown"
      const s = look.r * 2 + 4;
      const label = look.label ? `<span class="mlabel" style="font-size:${lsize}px;left:${s}px">${esc(this.label(tab, r))}</span>` : '';
      const icon = L.divIcon({ className: 'data-marker', iconSize: [s, s], iconAnchor: [s / 2, s / 2],
        html: `${shapeSvg(look.shape, color, look.r, '#000', look.fill)}${label}` });
      const old = tab !== 'marks' && this.isOld(r.DateTime);      // waypoints never fade
      const isRe = tab === 'sightings' && rs.isResight(r);
      const m = L.marker(pos, { icon, title: this.title(tab, r), riseOnHover: true, opacity: old ? 0.35 : 1 }).addTo(isRe ? this.layers.resights : layer);
      m.bindPopup(() => this.rowPopup(tab, r.RowID), { minWidth: 200, maxWidth: 320 });
      m.on('popupopen', () => { this.openRowPopup = { m, tab, id: r.RowID }; });
      m.on('popupclose', () => { if (this.openRowPopup?.m === m) this.openRowPopup = null; });
      this.markerIndex[`${tab}:${r.RowID}`] = m;
      if (tab === 'sightings' && disp.sighting_lines !== '0' && r.SigLat && r.Lat) {
        const w = +disp.sighting_lines_width || 1.5;
        L.polyline([[+r.Lat, +r.Lon], pos], { color, weight: w, dashArray: dashFor(disp.sighting_lines_style || 'dashed', w), interactive: false,
          opacity: old ? 0.3 : 1 }).addTo(isRe ? this.layers.resights : this.layers.lines);
      }
      if (tab === 'sightings' && r.FieldID) (byFid[r.FieldID] = byFid[r.FieldID] || []).push({ r, pos, color });
    }
    // dotted line from each sighting through its resights, oldest to newest (in the sighting's color)
    if (tab === 'sightings' && disp.resight_lines !== '0') {
      for (const g of rs.groups()) {
        const pts = g.filter((r) => r.Map !== '0').sort((a, b) => new Date(a.DateTime) - new Date(b.DateTime))
          .map((r) => this.rowPos(tab, r)).filter(Boolean);
        if (pts.length < 2) continue;
        const last = g.at(-1);
        const w = +disp.resight_lines_width || 2.5;
        L.polyline(pts, { color: this.markerColor(tab, g[0]), weight: w, dashArray: dashFor(disp.resight_lines_style || 'dotted', w), lineCap: 'round',
          opacity: this.isOld(last.DateTime) ? 0.35 : 0.9 })
          .bindTooltip(`Sighting ${esc(g[0].SightNo)}: ${g.length - 1} resight${g.length === 2 ? '' : 's'}`, { sticky: true })
          .addTo(this.layers.resights);
      }
    }
    // dotted line joining re-sightings of the same FieldID, oldest to newest
    if (tab === 'sightings' && disp.fieldid_lines === '1') {
      for (const [fid, list] of Object.entries(byFid)) {
        if (list.length < 2) continue;
        list.sort((a, b) => new Date(a.r.DateTime) - new Date(b.r.DateTime));
        const last = list.at(-1);
        const w = +disp.fieldid_lines_width || 2.5;
        L.polyline(list.map((x) => x.pos), { color: last.color, weight: w, dashArray: dashFor(disp.fieldid_lines_style || 'dotted', w), lineCap: 'round',
          opacity: this.isOld(last.r.DateTime) ? 0.35 : 0.9 })
          .bindTooltip(`${esc(fid)}: ${list.length} sightings`, { sticky: true })
          .addTo(this.layers.fidlines);
      }
    }
  }

  // a marker's shape, radius, fill and whether it is labelled; resights follow Settings → General → Resights.
  // null: not drawn
  markerLook(tab, r, rs) {
    const disp = this.app.S.config.display, rad = +disp.marker_radius || 8;
    const shape = tab === 'marks' && r.Shape ? r.Shape : disp[`${tab}_marker_shape`] || 'Diamond';
    if (tab !== 'sightings' || !rs?.isResight(r)) return { shape, r: rad, fill: 'filled', label: true };
    const sh = disp.resight_marker_shape || 'same';
    if (sh === 'hidden') return null;
    const pct = Math.max(30, Math.min(150, +disp.resight_marker_size || 70));
    return { shape: sh === 'same' ? shape : sh, r: Math.max(3, rad * pct / 100), fill: disp.resight_marker_fill || 'hollow',
      label: disp.resight_labels === '1' };
  }

  title(tab, r) {
    return { sightings: `Sighting ${r.SightNo}${r.ResightOf ? ` (resight of ${r.ResightOf})` : ''}${r.FieldID ? ` (${r.FieldID})` : ''}: ${r.Species || 'unidentified'}`,
      events: `Event ${r.EventNo}: ${r.EventType}${r.ID ? ` ${r.ID}` : ''}`, marks: r.Name }[tab];
  }

  // The essentials only: what, when, where, how many, and where it is from the vessel now.
  popupFields(tab, r) {
    const fmt = this.app.S.config.settings.latlon_format;
    const pos = this.rowPos(tab, r);
    const p = r.DateTime && timeParts(r.DateTime, this.app.clock());
    const time = p ? `${p.date} ${p.time} ${p.abbr}` : '';
    const where = pos ? `${fmtCoord(pos[0], true, fmt)} ${fmtCoord(pos[1], false, fmt)}` : '';
    if (tab === 'sightings') {
      const n = r.Count ? `${r.Count}${+r.Calves > 0 ? ` (${r.Calves} calf${+r.Calves === 1 ? '' : 'ves'})` : ''}` : '';
      return [['Time', time], ['Position', where], ['Species', r.Species || 'not entered'], ['Number', n]];
    }
    if (tab === 'events') return [['Time', time], ['Position', where], ['Event', r.EventType], ['ID', r.ID]];
    return [['Position', where], ['Time', time], ['Notes', r.Notes]];
  }

  popupHeading(tab, r) {
    if (tab === 'sightings') return `Sighting ${r.SightNo || ''}${r.ResightOf ? ` · resight of ${r.ResightOf}` : ''}${r.FieldID ? ` · ${r.FieldID}` : ''}`;
    if (tab === 'events') return `Event ${r.EventNo || ''}`;
    return r.Name || 'Waypoint';
  }

  rowPopup(tab, id) {
    const r = this.app.S.tables[tab].rows.find((x) => x.RowID === id);
    if (!r) return 'Row deleted';
    const rows = this.popupFields(tab, r).filter(([, v]) => v).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('');
    const wrap = el('div', { html: `<b>${esc(this.popupHeading(tab, r))}</b><table class="pop">${rows}</table>` });
    const v = this.app.S.vessel, pos = this.rowPos(tab, r);
    if (v && v.lat !== null && v.lat !== undefined && pos) {
      const d = distM([v.lat, v.lon], pos), b = bearing([v.lat, v.lon], pos);
      wrap.append(el('div', { class: 'pop-rel' }, `Now ${fmtDist(d, this.app.unit())} from the vessel, bearing ${fmtBrg(b)}T`));
    }
    const what = { sightings: 'Sightings', events: 'Events', marks: 'Waypoints' }[tab];
    wrap.append(el('div', { class: 'pop-btns' },
      el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.map.closePopup(); this.app.selectRow(tab, id); } }, `Show in the ${what} table`)));
    return wrap;
  }

  focusRow(tab, id) {
    const m = this.markerIndex?.[`${tab}:${id}`];
    if (m && this.map.hasLayer(m)) {
      // Settings → General → Map display: "Move the map to a row selected in its table"
      if (this.app.S.config.display.focus_selected !== '0' && !this.map.getBounds().pad(-0.1).contains(m.getLatLng())) this.map.panTo(m.getLatLng());
      const elx = m.getElement();
      if (elx) { elx.classList.remove('pulse'); void elx.offsetWidth; elx.classList.add('pulse'); }
    }
  }

  // ---------------------------------------------------------------- measure
  toggleMeasure() {
    if (this.measure?.active) this.endMeasure();
    else if (this.measure) this.clearMeasure();   // second click on the ruler clears the finished line
    else this.startMeasure();
  }

  startMeasure(from) {
    this.clearMeasure();
    this.measure = { active: true, pts: [], layer: L.layerGroup().addTo(this.map) };
    this.measureBtn?.classList.add('active');
    this.container.classList.add('measuring');
    this.map.doubleClickZoom.disable();
    if (from) this.measure.pts.push(L.latLng(from));
    toast('Measuring: click points on the chart; double-click or Esc to finish. Click the ruler again to clear.', 'info', 3500);
  }

  // A tool (the Route tab) can take over map clicks: setClickHook(fn) / setClickHook(null).
  setClickHook(fn, cursor = 'crosshair') {
    this.clickHook = fn;
    this.map.getContainer().style.cursor = fn ? cursor : '';
  }

  onClick(e) {
    this.hideContext();
    if (this.clickHook && !this.measure?.active) { this.clickHook(e.latlng); return; }
    if (!this.measure?.active) return;
    this.measure.pts.push(e.latlng);
    this.drawMeasure();
  }

  drawMeasure(cursorLL) {
    const ms = this.measure;
    ms.layer.clearLayers();
    const pts = cursorLL ? [...ms.pts, cursorLL] : ms.pts;
    if (!pts.length) return;
    L.polyline(pts, { color: '#111', weight: 2, dashArray: '5 3', interactive: false }).addTo(ms.layer);
    let total = 0;
    for (let i = 0; i < pts.length; i++) {
      L.circleMarker(pts[i], { radius: 3, color: '#111', fillColor: '#fff', fillOpacity: 1, interactive: false }).addTo(ms.layer);
      if (i === 0) continue;
      const a = [pts[i - 1].lat, pts[i - 1].lng], b = [pts[i].lat, pts[i].lng];
      const d = distM(a, b), br = bearing(a, b);
      total += d;
      const txt = `${fmtBrg(br)}T ${this.magText(br)}<br>${fmtDist(d, this.app.unit())}${i > 1 ? `<br><i>Σ ${fmtDist(total, this.app.unit())}</i>` : ''}`;
      L.marker(pts[i], { interactive: false, icon: L.divIcon({ className: 'measure-label', html: txt, iconSize: null, iconAnchor: [-8, 10] }) }).addTo(ms.layer);
    }
  }

  endMeasure() {
    if (!this.measure) return;
    this.measure.active = false;
    this.drawMeasure();
    this.measureBtn?.classList.remove('active');
    this.container.classList.remove('measuring');
    this.map.doubleClickZoom.enable();
  }

  clearMeasure() {
    if (this.measure) { this.measure.layer.remove(); this.measure = null; }
    this.measureBtn?.classList.remove('active');
    this.container.classList.remove('measuring');
  }

  // ---------------------------------------------------------------- context menu
  contextMenu(e) {
    this.hideContext();
    const ll = e.latlng, fmt = this.app.S.config.settings.latlon_format;
    const item = (label, fn) => el('div', { class: 'ctx-item', onclick: () => { this.hideContext(); fn(); } }, label);
    const menu = el('div', { class: 'ctx-menu' },
      el('div', { class: 'ctx-head' }, fmtPos(ll.lat, ll.lng, fmt)),
      item('Add sighting here', () => this.app.addRow('sightings', {}, ll)),
      item('Add event here', () => this.app.addRow('events', {}, ll)),
      item('Add waypoint here', () => this.app.addRow('marks', {}, ll)),
      item('Measure from here', () => this.startMeasure(ll)),
      item('Center map here', () => this.map.panTo(ll)),
      item('Copy position', () => navigator.clipboard?.writeText(fmtPos(ll.lat, ll.lng, fmt)).then(() => toast('Position copied'))));
    const p = e.containerPoint;
    menu.style.left = `${p.x}px`; menu.style.top = `${p.y}px`;
    this.container.append(menu);
    this.ctx = menu;
    L.DomEvent.disableClickPropagation(menu);
  }

  hideContext() { this.ctx?.remove(); this.ctx = null; }

  // ---------------------------------------------------------------- imported overlays
  // Each overlay file can be shown or hidden (Tools → Overlays); hidden ones are remembered.
  hiddenOverlays() { try { return new Set(JSON.parse(localStorage.getItem('wsr.overlayHidden') || '[]')); } catch { return new Set(); } }
  overlayVisible(name) { return !this.hiddenOverlays().has(name); }
  // colors chosen in Tools → Overlays (map display: overlay_colors), else one made from the file name
  overlayColors() {
    try { const c = JSON.parse(this.app.S.config.display.overlay_colors || '{}'); return c && typeof c === 'object' ? c : {}; } catch { return {}; }
  }
  customOverlayColor(name) { const c = this.overlayColors()[name]; return /^#[0-9a-f]{6}$/i.test(c || '') ? c : null; }
  overlayColor(name) { return this.customOverlayColor(name) || hslToHex(colorFor(name)); }
  async setOverlayColor(name, hex) {
    const all = this.overlayColors();
    if (hex) all[name] = hex; else delete all[name];
    this.app.S.config.display.overlay_colors = JSON.stringify(all);      // at once; the broadcast confirms it
    await this.app.saveDisplay({ overlay_colors: this.app.S.config.display.overlay_colors });
    this.restyleOverlays();
  }
  overlayStyle(name, f) {
    const custom = this.customOverlayColor(name), color = custom || colorFor(name);
    return { color: (!custom && f?.properties?.stroke) || color, weight: +f?.properties?.['stroke-width'] || 2.5, opacity: 0.9,
      fillOpacity: 0.1, dashArray: f?.properties?.dash || null };
  }
  overlayMarkerColor(name, f) { const custom = this.customOverlayColor(name); return (!custom && f?.properties?.['marker-color']) || custom || colorFor(name); }
  // after a color change (here, from another window or from a template)
  restyleOverlays() {
    for (const [name, gl] of Object.entries(this.overlayLayers || {})) {
      gl.eachLayer((l) => {
        if (l instanceof L.CircleMarker) { const c = this.overlayMarkerColor(name, l.feature); l.setStyle({ color: c, fillColor: c }); }
        else if (l.setStyle) l.setStyle(this.overlayStyle(name, l.feature));
      });
    }
  }
  setOverlayVisible(name, on) {
    const hidden = this.hiddenOverlays();
    if (on) hidden.delete(name); else hidden.add(name);
    try { localStorage.setItem('wsr.overlayHidden', JSON.stringify([...hidden])); } catch {}
    const layer = this.overlayLayers?.[name];
    if (!layer) return;
    if (on) this.layers.imported.addLayer(layer); else this.layers.imported.removeLayer(layer);
  }
  zoomToOverlay(name) {
    const b = this.overlayLayers?.[name]?.getBounds?.();
    if (!b?.isValid()) return;
    if (!this.map.hasLayer(this.layers.imported)) { this.layers.imported.addTo(this.map); this.saveOverlayState(); }
    if (this.app.S.config.settings.follow_vessel) this.setFollow(false);
    this.map.fitBounds(b, { padding: [24, 24], maxZoom: 14 });
  }

  async loadOverlays(names) {
    this.layers.imported.clearLayers();
    this.overlayLayers = {};
    const hidden = this.hiddenOverlays();
    for (const name of names) {
      try {
        const txt = await (await fetch(`/overlays/${encodeURIComponent(name)}`)).text();
        const gj = toGeoJSON(name, txt);
        const gl = L.geoJSON(gj, {
          style: (f) => this.overlayStyle(name, f),
          pointToLayer: (f, ll) => {
            const c = this.overlayMarkerColor(name, f);
            return L.circleMarker(ll, { radius: +f.properties?.['marker-radius'] || 5, color: c, fillColor: c, fillOpacity: 0.8 });
          },
          onEachFeature: (f, layer) => {
            const props = Object.entries(f.properties || {}).filter(([, v]) => v !== null && v !== '' && typeof v !== 'object');
            layer.bindPopup(`<b>${esc(f.properties?.name || name)}</b><table class="pop">${props.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</table><div class="hint">${esc(name)}</div>`);
            if (f.properties?.name) layer.bindTooltip(esc(f.properties.name), { permanent: false });
          },
        });
        this.overlayLayers[name] = gl;
        if (!hidden.has(name)) gl.addTo(this.layers.imported);
      } catch (e) { toast(`Couldn't load overlay ${name}: ${e.message}`, 'error'); }
    }
  }

  invalidate() { setTimeout(() => this.map.invalidateSize(), 50); }
}

function gratText(v, isLat, step) {
  const hemi = isLat ? (v >= 0 ? 'N' : 'S') : (v >= 0 ? 'E' : 'W');
  let a = Math.abs(v);
  let d = Math.floor(a + 1e-9), m = (a - d) * 60;
  if (m > 59.95) { d += 1; m = 0; }
  if (step >= 1) return `${d}°${hemi}`;
  const mtxt = step * 60 >= 1 ? String(Math.round(m)).padStart(2, '0') : m.toFixed(1).padStart(4, '0');
  return `${d}°${mtxt}'${hemi}`;
}

// "hsl(h,s%,l%)" → "#rrggbb" (for <input type=color>)
function hslToHex(hsl) {
  const m = /hsl\((\d+(?:\.\d+)?),\s*(\d+)%,\s*(\d+)%\)/.exec(hsl || '');
  if (!m) return hsl;
  const h = +m[1], s = +m[2] / 100, l = +m[3] / 100;
  const k = (n) => (n + h / 30) % 12, a = s * Math.min(l, 1 - l);
  const f = (n) => Math.round(255 * (l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1)))).toString(16).padStart(2, '0');
  return `#${f(0)}${f(8)}${f(4)}`;
}

function colorFor(name) {
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h},75%,38%)`;
}

// Convert GPX / KML / GeoJSON text to GeoJSON.
export function toGeoJSON(name, txt) {
  const ext = name.split('.').pop().toLowerCase();
  if (ext === 'geojson' || ext === 'json') return JSON.parse(txt);
  const doc = new DOMParser().parseFromString(txt, 'application/xml');
  const feats = [];
  const txtOf = (n, tag) => n.getElementsByTagName(tag)[0]?.textContent?.trim() || '';
  if (ext === 'gpx') {
    for (const w of doc.getElementsByTagName('wpt')) feats.push({ type: 'Feature', properties: { name: txtOf(w, 'name'), desc: txtOf(w, 'desc') },
      geometry: { type: 'Point', coordinates: [+w.getAttribute('lon'), +w.getAttribute('lat')] } });
    for (const tag of ['rte', 'trk']) {
      for (const r of doc.getElementsByTagName(tag)) {
        const pts = [...r.getElementsByTagName(tag === 'rte' ? 'rtept' : 'trkpt')].map((p) => [+p.getAttribute('lon'), +p.getAttribute('lat')]);
        if (pts.length) feats.push({ type: 'Feature', properties: { name: txtOf(r, 'name') }, geometry: { type: 'LineString', coordinates: pts } });
        if (tag === 'rte') for (const p of r.getElementsByTagName('rtept')) {
          if (txtOf(p, 'name')) feats.push({ type: 'Feature', properties: { name: txtOf(p, 'name') }, geometry: { type: 'Point', coordinates: [+p.getAttribute('lon'), +p.getAttribute('lat')] } });
        }
      }
    }
  } else if (ext === 'kml') {
    const parse = (s) => s.trim().split(/\s+/).map((t) => t.split(',').slice(0, 2).map(Number));
    for (const pm of doc.getElementsByTagName('Placemark')) {
      const props = { name: txtOf(pm, 'name'), description: txtOf(pm, 'description') };
      for (const p of pm.getElementsByTagName('Point')) feats.push({ type: 'Feature', properties: props, geometry: { type: 'Point', coordinates: parse(txtOf(p, 'coordinates'))[0] } });
      for (const l of pm.getElementsByTagName('LineString')) feats.push({ type: 'Feature', properties: props, geometry: { type: 'LineString', coordinates: parse(txtOf(l, 'coordinates')) } });
      for (const pg of pm.getElementsByTagName('Polygon')) feats.push({ type: 'Feature', properties: props, geometry: { type: 'Polygon', coordinates: [parse(txtOf(pg, 'coordinates'))] } });
    }
  }
  return { type: 'FeatureCollection', features: feats };
}

// The layers menu with base layers in sections: online map tiles, then offline ones (files in the
// charts folder, and the built-in coastline). Each layer carries _group: 'online' | 'offline' | 'builtin'.
// Overlays go in two sections too: offline overlays (survey data, waypoints, routes, imported
// files, chart overlays…) first, then online ones (layers with _group 'online': AIS, radar, map feeds,
// online tile overlays).
const GROUP_RANK = { online: 0, offline: 1, builtin: 2 };
const rankOf = (l) => (l._isOverlay ? (l._group === 'online' ? 1 : 0) : (GROUP_RANK[l._group] ?? 0));
const GroupedLayers = L.Control.Layers.extend({
  initialize(bases, overlays, options) {
    let n = 0;
    for (const l of [...Object.values(bases || {}), ...Object.values(overlays || {})]) l._order ??= n++;
    L.Control.Layers.prototype.initialize.call(this, bases, overlays, {
      ...options, sortLayers: true,
      sortFunction: (a, b) => rankOf(a) - rankOf(b) || (a._order ?? 1e9) - (b._order ?? 1e9),
    });
  },
  _addLayer(layer, name, overlay) {
    layer._order ??= (this._nextOrder = (this._nextOrder || 1000) + 1);
    layer._isOverlay = !!overlay;
    return L.Control.Layers.prototype._addLayer.call(this, layer, name, overlay);
  },
  _update() {
    L.Control.Layers.prototype._update.call(this);
    if (!this._baseLayersList) return this;
    const labels = [...this._baseLayersList.children];
    let last = null;
    labels.forEach((lab, i) => {
      const obj = this._layers.filter((x) => !x.overlay)[i];
      const g = obj?.layer?._group === 'online' ? 'online' : 'offline';
      if (g !== last) {
        const h = L.DomUtil.create('div', 'layers-heading');
        h.textContent = g === 'online' ? 'Online map tiles' : 'Offline map tiles';
        this._baseLayersList.insertBefore(h, lab);
        last = g;
      }
    });
    const ovs = this._layers.filter((x) => x.overlay);
    let lastOv = null;
    [...this._overlaysList.children].forEach((lab, i) => {
      const g = ovs[i]?.layer?._group === 'online' ? 'online' : 'offline';
      if (g !== lastOv) {
        const h = L.DomUtil.create('div', 'layers-heading');
        h.textContent = g === 'online' ? 'Online overlays' : 'Layers';
        this._overlaysList.insertBefore(h, lab);
        lastOv = g;
      }
    });
    return this;
  },
});
