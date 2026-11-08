// Tools → Routes: design a trackline (manual clicks or a systematic parallel-leg
// pattern), see each leg's distance and time, activate it (locked and shown on the map
// from every tab), style it, and export GPX. Routes are saved in the routes folder (one GPX
// file each, server routes.py); the Saved routes list opens one to edit, or shows any of
// them on the map from every tab.
import { el, esc, api, toast, confirmBox, promptBox, fmtCoord, fmtPos, fmtDist, fmtBrg, distM, bearing, destination, timeParts, dashFor, LINE_STYLES } from './util.js';

// "45 min", "1 h 42 min" — clearer for passage times than 0:45:00
export function fmtDuration(sec) {
  const m = Math.round(Math.max(0, sec) / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${String(m % 60).padStart(2, '0')} min` : ''}`;
}

const M_PER_NM = 1852;
const STORE = 'wsr.plan';
const SHOWN = 'wsr.routesShown';     // saved routes shown on the map
export const STYLE_DEFAULTS = { color: '#6b6b6b', point: 18, width: 3, line: 'dotted' };
const OLD_DEFAULT_STYLE = { color: '#d35400', point: 22, width: 3, line: 'dashed' };   // before 0.8.0
const DEFAULTS = {
  mode: 'manual', speed: 10, start: 'first', name: 'Route 1',
  manual: { points: [] },
  sys: { start: null, bearing: 0, legs: 4, legNm: 10, spacingNm: 2, side: 'starboard' },
  // sawtooth (zig-zag): starts at sys.start, like the parallel legs
  saw: { direction: 0, angle: 90, legs: 6, legNm: 5, side: 'starboard', ret: false },
  active: false, locked: null,      // an activated route: its waypoints, frozen
  file: null, savedKey: null,       // the saved route this was opened from / saved as, and its design then
  layerOn: true,                    // the "Routes" entry in the map's layers menu (current and saved routes)
  style: { ...STYLE_DEFAULTS },
};

// Read a typed position: decimal degrees (-70.33), degrees + decimal minutes (70 19.8 W)
// or degrees minutes seconds (70 19 48 W); N/S/E/W or a sign.
export function parseCoord(text, isLat) {
  const t = String(text || '').trim().toUpperCase().replace(/[°'"′″]/g, ' ').replace(/,/g, '.');
  if (!t) return null;
  const hemi = (t.match(/[NSEW]/) || [''])[0];
  const nums = (t.match(/-?\d+(\.\d+)?/g) || []).map(Number);
  if (!nums.length || nums.length > 3) return null;
  let v = Math.abs(nums[0]) + (nums[1] || 0) / 60 + (nums[2] || 0) / 3600;
  if (nums[0] < 0 || hemi === 'S' || hemi === 'W') v = -v;
  if (hemi && (isLat ? !'NS'.includes(hemi) : !'EW'.includes(hemi))) return null;
  return Math.abs(v) <= (isLat ? 90 : 180) ? v : null;
}

// Parallel legs ("lawnmower"): leg 1 from the start along the bearing, then a crossing of
// `spacing` to the chosen side, then leg 2 back the other way, and so on.
export function systematicPoints(start, brg, legs, legM, spacingM, side) {
  const pts = [{ ll: start, name: 'L1 start' }];
  const off = side === 'port' ? -90 : 90;
  let p = start;
  for (let i = 1; i <= legs; i++) {
    const dir = i % 2 ? brg : (brg + 180) % 360;
    p = destination(p, dir, legM);
    pts.push({ ll: p, name: `L${i} end` });
    if (i < legs) {
      p = destination(p, (brg + off + 360) % 360, spacingM);
      pts.push({ ll: p, name: `L${i + 1} start` });
    }
  }
  return pts;
}

// Sawtooth (zig-zag). The pattern advances along `dir`; consecutive legs meet at `angle` degrees,
// so each leg runs (180 − angle)/2 off `dir`, the first to the chosen side. The waypoints alternate
// between the start line and a line `width` to that side. With `ret`, a crossover leg straight
// across (at right angles to `dir`) leads onto the reciprocal sawtooth (its waypoints on the
// opposite line from the outbound ones), which comes back through the outbound pattern, crossing
// each leg at its middle, and ends level with the start on the far line.
// Worked out on a flat plane around the start (metres along, metres to starboard): over a survey
// area the difference from great circles is negligible, and the two patterns line up exactly.
export function sawtoothPoints(start, dir, legs, legM, angle, side, ret) {
  const rad = Math.PI / 180;
  const sg = side === 'port' ? -1 : 1;
  const th = (180 - angle) / 2 * rad;
  const dx = legM * Math.cos(th), w = legM * Math.sin(th) * sg;
  const a = dir * rad, kx = 111320 * Math.cos(start[0] * rad), ky = 110540;
  // (along, to starboard) → lat/lon
  const toLL = ([x, y]) => [+(start[0] + (x * Math.cos(a) - y * Math.sin(a)) / ky).toFixed(6),
    +(start[1] + (x * Math.sin(a) + y * Math.cos(a)) / kx).toFixed(6)];
  const P = Array.from({ length: legs + 1 }, (_, k) => [k * dx, k % 2 ? w : 0]);
  const pts = P.map((q, k) => ({ ll: k ? toLL(q) : start, name: k === 0 ? 'Start' : k === legs ? (ret ? 'Far end' : 'End') : `Turn ${k}`,
    ...(k ? { leg: `Leg ${k}`, survey: true } : {}) }));
  if (ret) {
    // the reciprocal pattern's waypoints: on the opposite line from the outbound ones
    const C = P.map(([x, y]) => [x, w - y]);
    // the crossover: straight across from the far end, at right angles to the survey direction
    pts.push({ ll: toLL(C[legs]), name: 'Return start', leg: 'Crossover', survey: false });
    for (let k = legs - 1, j = 1; k >= 0; k--, j++) {
      pts.push({ ll: toLL(C[k]), name: k === 0 ? 'End' : `Return turn ${j}`, leg: `Return leg ${j}`, survey: true });
    }
  }
  return pts;
}

// a sawtooth design from 0.23 (bearing of leg 1 and the turn at each waypoint) in today's terms
export function sawFromOld(w) {
  if (!w || w.direction !== undefined || w.bearing === undefined) return w;
  const turn = Math.max(1, Math.min(179, +w.turn || 90)), s = w.side === 'port' ? -1 : 1;
  const { bearing, turn: _t, ...rest } = w;
  return { ...rest, direction: ((((+bearing || 0) + s * turn / 2) % 360) + 360) % 360, angle: 180 - turn,
    side: w.side === 'port' ? 'starboard' : 'port' };        // leg 1 was on the other side of the line it advanced along
}

export const MODE_LABELS = { manual: 'Manual', systematic: 'Systematic – parallel legs', sawtooth: 'Systematic – sawtooth' };

export class Planner {
  constructor(app) {
    this.app = app;
    this.state = this.load();
    this.layer = L.layerGroup();
    this.adding = false;          // manual: clicks on the map add points
    this.picking = false;         // systematic: the next click sets the start
    this.inTab = false;           // the Routes tab is open
    this.saved = null;            // the routes folder: [{file, name, mode, points, nm, ...}]
    this.savedCache = {};         // file -> {modified, points, style, name}
    try { this.shown = new Set(JSON.parse(localStorage.getItem(SHOWN) || '[]')); } catch { this.shown = new Set(); }
    this.savedLayer = L.layerGroup();
    // one "Routes" entry in the layers menu for the current route and the saved routes shown;
    // which ones are drawn is chosen in the Routes tab
    this.routesLayer = L.layerGroup([this.savedLayer]);
    const m = app.map;
    m.layerControl.addOverlay(this.routesLayer, 'Routes');
    if (this.state.layerOn) this.routesLayer.addTo(m.map);
    m.map.on('overlayadd overlayremove', (e) => {
      if (e.layer !== this.routesLayer || this._syncing) return;
      this.state.layerOn = e.type === 'overlayadd';
      this.save();
      this.sync(); this.drawSaved();
      if (this.inTab) this.render();
    });
    this.sync();
    if (this.shown.size) this.loadSaved();
  }

  // The route is on the map while the Routes tab is open, and from every tab once activated
  // (unless "Route" is unticked in the layers menu).
  sync() {
    const map = this.app.map.map;
    this._syncing = true;
    try {
      if (this.state.layerOn && !map.hasLayer(this.routesLayer)) this.routesLayer.addTo(map);
      else if (!this.state.layerOn && map.hasLayer(this.routesLayer)) map.removeLayer(this.routesLayer);
    } finally { this._syncing = false; }
    const want = this.inTab || this.state.active;
    if (want && !this.routesLayer.hasLayer(this.layer)) this.routesLayer.addLayer(this.layer);
    else if (!want && this.routesLayer.hasLayer(this.layer)) this.routesLayer.removeLayer(this.layer);
    this.draw();
  }

  // the current route is drawn now (Routes on in the layers menu, and the tab open or the route active)
  currentShown() { return this.app.map.map.hasLayer(this.routesLayer) && this.routesLayer.hasLayer(this.layer); }

  load() {
    try {
      const s = JSON.parse(localStorage.getItem(STORE) || 'null');
      if (s) {
        // a style never changed from the old orange default takes the new grey dotted one
        const st = s.style && Object.keys(OLD_DEFAULT_STYLE).every((k) => s.style[k] === OLD_DEFAULT_STYLE[k]) ? null : s.style;
        return { ...DEFAULTS, ...s, manual: { ...DEFAULTS.manual, ...s.manual }, sys: { ...DEFAULTS.sys, ...s.sys }, saw: { ...DEFAULTS.saw, ...sawFromOld(s.saw) }, style: { ...STYLE_DEFAULTS, ...st } };
      }
    } catch {}
    return structuredClone(DEFAULTS);
  }

  save() { try { localStorage.setItem(STORE, JSON.stringify(this.state)); } catch {} }

  vesselLL() {
    const v = this.app.S.vessel;
    return v && v.lat !== null && v.lat !== undefined ? [v.lat, v.lon] : null;
  }

  // The plan as waypoints: [{ ll, name, fixed }]
  route() {
    const s = this.state;
    if (s.active && Array.isArray(s.locked)) return s.locked.map((p) => ({ ...p }));
    const vessel = s.start === 'vessel' ? this.vesselLL() : null;
    if (s.mode === 'manual') {
      const pts = s.manual.points.map((ll, i) => ({ ll, name: `WP${i + 1}`, index: i }));
      return vessel ? [{ ll: vessel, name: 'Start (vessel)', fixed: true }, ...pts] : pts;
    }
    const start = vessel || s.sys.start;
    if (!start) return [];
    if (s.mode === 'sawtooth') {
      const w = s.saw;
      return sawtoothPoints(start, ((+w.direction || 0) % 360 + 360) % 360, Math.max(1, Math.min(200, Math.round(+w.legs || 1))),
        Math.max(0, +w.legNm || 0) * M_PER_NM, Math.max(1, Math.min(179, +w.angle || 90)), w.side, !!w.ret);
    }
    const legs = Math.max(1, Math.min(200, Math.round(+s.sys.legs || 1)));
    return systematicPoints(start, ((+s.sys.bearing || 0) % 360 + 360) % 360, legs,
      Math.max(0, +s.sys.legNm || 0) * M_PER_NM, Math.max(0, +s.sys.spacingNm || 0) * M_PER_NM, s.sys.side);
  }

  legs(route) {
    const speed = Math.max(0.1, +this.state.speed || 10);
    let total = 0, totalS = 0;
    const out = [];
    for (let i = 0; i + 1 < route.length; i++) {
      const a = route[i], b = route[i + 1];
      const m = distM(a.ll, b.ll);
      const sec = m / M_PER_NM / speed * 3600;
      total += m; totalS += sec;
      const kind = b.leg || (this.state.mode === 'systematic' ? (i % 2 ? 'Crossing' : `Leg ${i / 2 + 1}`) : `Leg ${i + 1}`);
      const survey = b.survey ?? (this.state.mode !== 'systematic' || i % 2 === 0);
      out.push({ kind, from: a.name, to: b.name, course: bearing(a.ll, b.ll), m, sec, total, totalS, survey });
    }
    return out;
  }

  // ------------------------------------------------------------------ map
  show() {
    this.inTab = true;
    if (!this.state.layerOn) { this.state.layerOn = true; this.save(); }   // you're editing it: show it
    this.sync();
    this.updateClickMode();
  }

  hide() {
    this.inTab = false;
    this.adding = false; this.picking = false;
    this.app.map.setClickHook(null);
    this.sync();
  }

  updateClickMode() {
    const on = this.inTab && !this.state.active && (this.adding || this.picking);
    this.app.map.setClickHook(on ? (ll) => this.onMapClick(ll) : null);
  }

  onMapClick(ll) {
    const p = [+ll.lat.toFixed(6), +ll.lng.toFixed(6)];
    if (this.picking) {
      this.state.sys.start = p;
      this.picking = false;
      if (this.state.start === 'vessel') this.state.start = 'first';
      this.changed(true);
      return;
    }
    if (this.adding) {
      this.state.manual.points.push(p);
      this.changed(false);
    }
  }

  draw() {
    this.layer.clearLayers();
    if (!this.currentShown()) return;
    const r = this.route();
    const st = this.state.style;
    if (r.length > 1) {
      L.polyline(r.map((p) => p.ll), { color: st.color, weight: +st.width || 3, dashArray: dashFor(st.line, st.width),
        lineCap: st.line === 'dotted' ? 'round' : 'butt', interactive: false }).addTo(this.layer);
    }
    const manual = this.state.mode === 'manual';
    const editable = this.inTab && !this.state.active;
    const size = Math.max(4, Math.min(48, +st.point || 22));
    r.forEach((p, i) => {
      const draggable = editable && ((manual && !p.fixed) || (!manual && i === 0 && this.state.start !== 'vessel'));
      const label = p.fixed ? '⛴' : i + (r[0]?.fixed ? 0 : 1);
      const m = L.marker(p.ll, {
        draggable, keyboard: false,
        icon: L.divIcon({ className: `plan-wp${draggable ? ' drag' : ''}`, iconSize: [size, size], iconAnchor: [size / 2, size / 2],
          html: `<span style="background:${st.color};font-size:${Math.max(7, Math.round(size * 0.5))}px">${size >= 14 ? label : ''}</span>` }),
      }).bindTooltip(this.state.active ? `${p.name} (active route)` : p.name, { direction: 'top', offset: [0, -size / 2] });
      if (this.state.active) {
        m.bindPopup(() => this.waypointPopup(r, i), { minWidth: 210, maxWidth: 320 });
        m.on('popupopen', () => { this._popup = { m, i }; });
        m.on('popupclose', () => { if (this._popup?.m === m) this._popup = null; });
      }
      if (draggable) {
        m.on('dragend', () => {
          const ll = m.getLatLng(), q = [+ll.lat.toFixed(6), +ll.lng.toFixed(6)];
          if (manual) this.state.manual.points[p.index] = q; else this.state.sys.start = q;
          this.changed(true);
        });
      }
      m.addTo(this.layer);
    });
  }

  fit() {
    const r = this.route();
    if (!r.length) return;
    const m = this.app.map;
    if (this.app.S.config.settings.follow_vessel) { m.setFollow(false, true); toast('Stopped following the vessel so the route stays in view (⌖ turns it back on).', 'info', 5000); }
    m.map.fitBounds(L.latLngBounds(r.map((p) => p.ll)).pad(0.25), { maxZoom: 13 });
  }

  // popup of an active route's waypoint: name, position, distance and bearing from the vessel
  waypointPopup(r, i) {
    const p = r[i];
    if (!p) return 'Waypoint removed';
    const app = this.app, fmt = app.S.config.settings.latlon_format;
    const num = p.fixed ? '' : `${i + (r[0]?.fixed ? 0 : 1)}. `;
    const rows = [['Position', fmtPos(p.ll[0], p.ll[1], fmt)]];
    const legs = this.legs(r);
    if (i > 0 && legs[i - 1]) rows.push(['From the previous', `${(legs[i - 1].m / M_PER_NM).toFixed(2)} nm, ${Math.round(legs[i - 1].course).toString().padStart(3, '0')}°T`]);
    if (i > 0 && legs[i - 1]) rows.push(['Along the route', `${(legs[i - 1].total / M_PER_NM).toFixed(2)} nm`]);
    const wrap = el('div', { html: `<b>${esc(`${num}${p.name}`)}</b> <span class="hint">· ${esc(this.state.name)}</span>`
      + `<table class="pop">${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</table>` });
    const v = this.vesselLL();
    if (v) wrap.append(el('div', { class: 'pop-rel' }, `Now ${fmtDist(distM(v, p.ll), app.unit())} from the vessel, bearing ${fmtBrg(bearing(v, p.ll))}T`));
    const eta = this.etaAlongRoute(r, i);
    if (eta) {
      if (eta.passed) wrap.append(el('div', { class: 'pop-rel' }, 'ETA: passed (the vessel is beyond this waypoint on the route)'));
      else {
        const t = timeParts(new Date(Date.now() + eta.seconds * 1000), app.clock());
        wrap.append(el('div', { class: 'pop-rel pop-eta' }, el('b', {}, `ETA ${t.time.slice(0, 5)} ${t.abbr}`),
          ` · in ${fmtDuration(eta.seconds)} · ${(eta.metres / M_PER_NM).toFixed(1)} nm along the route at ${this.state.speed} kn`));
      }
    }
    wrap.append(el('div', { class: 'pop-btns' }, el('a', { href: '#', onclick: (e) => {
      e.preventDefault(); app.map.map.closePopup(); app.showTab('route');
    } }, 'View the route')));
    return wrap;
  }

  // Time for the vessel to reach waypoint i following the route at the survey speed. The vessel
  // is placed on the nearest leg (or before the start, if it hasn't reached the route yet), then
  // goes along the rest of that leg and the following ones. {passed} if the waypoint is behind it.
  etaAlongRoute(r, i) {
    const v = this.vesselLL(), kn = +this.state.speed;
    if (!v || !(kn > 0) || r.length < 2 || !r[i]) return null;
    const cos = Math.cos(v[0] * Math.PI / 180);
    const xy = (ll) => [(ll[1] - v[1]) * cos, ll[0] - v[0]];      // local plane around the vessel (degrees)
    let best = { k: 0, d: Infinity, t: 0 };
    for (let k = 0; k < r.length - 1; k++) {
      const [ax, ay] = xy(r[k].ll), [bx, by] = xy(r[k + 1].ll);
      const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
      const t = len2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2)) : 0;
      const d = Math.hypot(ax + t * dx, ay + t * dy);
      if (d < best.d - 1e-12) best = { k, d, t };
    }
    const leg = (j) => distM(r[j].ll, r[j + 1].ll);
    let metres;
    if (best.k === 0 && best.t === 0) {                  // not on the route yet: go to its start first
      metres = distM(v, r[0].ll);
      for (let j = 0; j < i; j++) metres += leg(j);
    } else {
      if (i <= best.k) return { passed: true };
      metres = distM(v, r[best.k + 1].ll);
      for (let j = best.k + 1; j < i; j++) metres += leg(j);
    }
    return { metres, seconds: metres / (kn * M_PER_NM / 3600) };
  }

  // the vessel moved: refresh an open waypoint popup; redraw a draft that starts at the vessel
  onVessel() {
    if (this._popup?.m.isPopupOpen()) {
      const now = Date.now();
      if (!this._lastPop || now - this._lastPop > 1000) { this._lastPop = now; this._popup.m.setPopupContent(this.waypointPopup(this.route(), this._popup.i)); }
    }
    if (!this.inTab || this.state.active || this.state.start !== 'vessel') return;
    const now = Date.now();
    if (this._lastVessel && now - this._lastVessel < 2000) return;
    this._lastVessel = now;
    this.draw();
    this.renderTables();
  }

  changed() {
    this.save();
    this.draw();
    this.drawSaved();   // the saved copy is hidden while it's being edited
    this.render();      // the whole tab: the Route status buttons depend on the number of waypoints
  }

  // ------------------------------------------------------------------ the routes folder
  designKey() { const d = this.design(); delete d.spyhop; return JSON.stringify(d); }
  unsaved() { const s = this.state; return this.route().length > 0 && (!s.file || s.savedKey !== this.designKey()); }

  async loadSaved() {
    let r;
    try { r = await api('/api/routes'); } catch { return; }
    this.saved = r.routes; this.folder = r.folder;
    const files = new Set(this.saved.map((x) => x.file));
    let pruned = false;
    for (const f of [...this.shown]) if (!files.has(f)) { this.shown.delete(f); pruned = true; }
    if (pruned) this.saveShown();
    if (this.state.file && !files.has(this.state.file)) { this.state.file = null; this.state.savedKey = null; this.save(); }
    await this.drawSaved();
    if (this.inTab) this.render();
  }

  saveShown() { try { localStorage.setItem(SHOWN, JSON.stringify([...this.shown])); } catch {} }

  async savedRoute(file) {
    const meta = this.saved?.find((x) => x.file === file);
    const c = this.savedCache[file];
    if (c && meta && c.modified === meta.modified) return c;
    let r;
    try { r = await api(`/api/routes/file?file=${encodeURIComponent(file)}`); } catch { return null; }
    const res = parseRouteGpx(r.gpx, file);
    if (res.error) { toast(res.error, 'error'); return null; }
    return (this.savedCache[file] = { modified: meta?.modified, design: res.design, exact: res.exact, points: res.points,
      style: { ...STYLE_DEFAULTS, ...(res.design.style || {}) }, name: res.design.name || meta?.name || file });
  }

  // the shown saved routes, read-only, on the map from every tab (not the one being edited)
  async drawSaved() {
    const seq = (this._savedSeq = (this._savedSeq || 0) + 1);
    const map = this.app.map.map;
    const items = [];
    for (const f of this.shown) {
      if (f === this.state.file && this.currentShown()) continue;
      const c = await this.savedRoute(f);
      if (c) items.push([f, c]);
    }
    if (seq !== this._savedSeq) return;
    this.savedLayer.clearLayers();
    if (!map.hasLayer(this.routesLayer)) return;
    for (const [f, c] of items) {
      const st = c.style, pts = c.points;
      if (pts.length > 1) {
        L.polyline(pts, { color: st.color, weight: +st.width || 3, dashArray: dashFor(st.line, st.width), opacity: 0.85,
          lineCap: st.line === 'dotted' ? 'round' : 'butt' }).bindTooltip(c.name, { sticky: true }).addTo(this.savedLayer);
      }
      const size = Math.max(4, Math.min(36, Math.round((+st.point || 18) * 0.8)));
      pts.forEach((ll, i) => {
        L.marker(ll, { keyboard: false, icon: L.divIcon({ className: 'plan-wp saved', iconSize: [size, size], iconAnchor: [size / 2, size / 2],
          html: `<span style="background:${st.color};font-size:${Math.max(7, Math.round(size * 0.5))}px">${size >= 14 ? i + 1 : ''}</span>` }) })
          .bindTooltip(`${c.name} · ${i + 1}`, { direction: 'top', offset: [0, -size / 2] })
          .bindPopup(() => this.savedPopup(f, c, i)).addTo(this.savedLayer);
      });
    }
  }

  savedPopup(file, c, i) {
    const fmt = this.app.S.config.settings.latlon_format;
    const ll = c.points[i];
    const v = this.vesselLL();
    return el('div', {}, el('b', {}, `${c.name} · waypoint ${i + 1}`),
      el('div', {}, fmtPos(ll[0], ll[1], fmt)),
      v ? el('div', { class: 'pop-rel' }, `${fmtDist(distM(v, ll), this.app.unit())} from the vessel, bearing ${fmtBrg(bearing(v, ll))}T`) : null,
      el('div', { class: 'pop-btns' }, el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.app.map.map.closePopup(); this.openSaved(file); } }, 'Open to edit')));
  }

  setShown(file, on) {
    if (on) this.shown.add(file); else this.shown.delete(file);
    this.saveShown();
    if (on && !this.state.layerOn) { this.state.layerOn = true; this.save(); this.sync(); }
    this.drawSaved();
    if (this.inTab) this.render();
  }

  async zoomSaved(file) {
    const c = await this.savedRoute(file);
    if (!c || !c.points.length) return;
    if (!this.shown.has(file) && file !== this.state.file) this.setShown(file, true);
    const m = this.app.map;
    if (this.app.S.config.settings.follow_vessel) m.setFollow(false, true);
    m.map.fitBounds(L.latLngBounds(c.points).pad(0.25), { maxZoom: 13 });
  }

  // Load a design into the editor (from a saved route or an imported GPX file).
  applyDesign(d, file = null) {
    const s = this.state;
    Object.assign(s, {
      mode: MODE_LABELS[d.mode] ? d.mode : 'manual', speed: +d.speed > 0 ? +d.speed : s.speed,
      start: d.start === 'vessel' ? 'vessel' : 'first', name: d.name || s.name,
      manual: { points: (d.manual?.points || []).filter((p) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite)) },
      sys: { ...DEFAULTS.sys, ...(d.sys || {}) },
      saw: { ...DEFAULTS.saw, ...sawFromOld(d.saw || {}) },
      style: d.style ? { ...STYLE_DEFAULTS, ...d.style } : s.style,
      active: false, locked: null, file,
    });
    s.savedKey = file ? this.designKey() : null;
    this.adding = false; this.picking = false;
    this.updateClickMode();
    this.save(); this.sync(); this.drawSaved();
  }

  async confirmLeave(what) {
    const s = this.state;
    if (s.active && !await confirmBox('Replace the active route?', `The current route “${s.name}” is active. Deactivate it and ${what}?`, 'Yes')) return false;
    if (!s.active && this.unsaved() && !await confirmBox('Discard the changes?', `“${s.name}” has changes that aren’t saved. ${what[0].toUpperCase() + what.slice(1)} anyway?`, 'Discard changes', true)) return false;
    return true;
  }

  async openSaved(file) {
    if (file === this.state.file && !this.unsaved()) { this.app.showTab('route'); this.fit(); return; }
    if (!await this.confirmLeave(file === this.state.file ? 'go back to the saved copy' : 'open another route')) return;
    const c = await this.savedRoute(file);
    if (!c) return;
    this.applyDesign({ ...c.design, name: c.design.name || c.name }, file);
    if (!c.exact) { this.state.savedKey = this.designKey(); this.save(); }
    this.app.showTab('route');
    this.render(); this.fit();
    toast(c.exact ? `Opened “${this.state.name}”.` : `Opened ${file} as a manual route (${this.state.manual.points.length} waypoints).`, 'info', 4000);
  }

  // put the route away: the editor is emptied and it's no longer drawn (a saved copy stays in the
  // folder, and on the map if it's ticked under Saved routes)
  async closeRoute() {
    const s = this.state;
    if (s.active && !await confirmBox('Close the active route?', `“${s.name}” is active. Deactivate and close it?`, 'Deactivate and close')) return;
    if (!s.active && this.unsaved() && !await confirmBox('Close without saving?', `“${s.name}” has changes that aren’t saved. Close it anyway?`, 'Close without saving', true)) return;
    const names = new Set((this.saved || []).map((x) => x.name.toLowerCase()));
    let i = 1; while (names.has(`route ${i}`)) i++;
    this.applyDesign({ mode: s.mode, speed: s.speed, start: 'first', name: `Route ${i}`, manual: { points: [] },
      sys: { ...s.sys, start: null }, saw: { ...s.saw }, style: s.style });
    this.render();
  }

  async newRoute() {
    if (!await this.confirmLeave('start a new route')) return;
    const names = new Set((this.saved || []).map((x) => x.name.toLowerCase()));
    let i = 1; while (names.has(`route ${i}`)) i++;
    this.applyDesign({ mode: this.state.mode, speed: this.state.speed, start: 'first', name: `Route ${i}`, manual: { points: [] },
      sys: { ...DEFAULTS.sys }, saw: { ...this.state.saw }, style: this.state.style });
    this.render();
  }

  async saveRoute(asNew = false) {
    const r = this.requireRoute();
    if (!r) return;
    const s = this.state;
    let name = s.name;
    if (asNew) {
      name = (await promptBox('Save as a new route', 'Name', s.file ? `${s.name} (copy)` : s.name, 'Save'))?.trim();
      if (!name) return;
      s.name = name;
    }
    const replace = asNew ? null : s.file;
    let res;
    try { res = await api('/api/routes/save', { name, gpx: this.gpx(r), replace }); } catch { return; }
    if (res.exists) {
      if (!await confirmBox('Replace the saved route?', `There’s already a saved route ${res.exists}. Replace it with this one?`, 'Replace', true)) return;
      try { res = await api('/api/routes/save', { name, gpx: this.gpx(r), replace, overwrite: true }); } catch { return; }
    }
    s.file = res.route.file;
    s.savedKey = this.designKey();
    delete this.savedCache[s.file];
    this.save();
    toast(`Saved “${name}” in the routes folder.`);
    await this.loadSaved();
  }

  async deleteSaved(file) {
    const meta = this.saved?.find((x) => x.file === file);
    if (!await confirmBox('Delete the saved route?', `Delete “${meta?.name || file}”? This removes ${file} from the routes folder.${file === this.state.file ? ' The route stays in the editor, unsaved.' : ''}`, 'Delete', true)) return;
    try { await api('/api/routes/delete', { file }); } catch { return; }
    this.shown.delete(file); this.saveShown();
    delete this.savedCache[file];
    if (file === this.state.file) { this.state.file = null; this.state.savedKey = null; this.save(); }
    await this.loadSaved();
  }

  savedSection() {
    const s = this.state;
    const list = this.saved;
    const sec = el('section', { class: 'settings-sec routes-saved' }, el('h3', {}, 'Saved routes'));
    if (!list) { sec.append(el('p', { class: 'hint' }, 'Loading…')); return sec; }
    const fmtDate = (iso) => { const t = timeParts(new Date(iso), this.app.clock()); return `${t.date} ${t.time.slice(0, 5)}`; };
    const body = list.length ? el('div', { class: 'table-scroll' }, el('table', { class: 'summary routes-table' },
      el('thead', {}, el('tr', {}, ['Show', 'Route', ''].map((h) => el('th', {}, h)))),
      el('tbody', {}, list.map((r) => {
        const editing = r.file === s.file;
        const mode = { ...MODE_LABELS, imported: 'GPX file' }[r.mode] || '';
        const bits = [mode, r.points ? `${r.points} waypoints` : '', r.nm ? `${r.nm.toFixed(2)} nm` : '', `saved ${fmtDate(r.modified)}`].filter(Boolean);
        return el('tr', { class: editing ? 'editing' : '', 'data-file': r.file },
          el('td', {}, el('input', { type: 'checkbox', checked: this.shown.has(r.file), disabled: !!r.error,
            title: 'Show this route on the map, on every tab', onchange: (e) => this.setShown(r.file, e.target.checked) })),
          el('td', { class: 'route-name' }, el('span', { class: 'route-swatch', style: { background: r.color || STYLE_DEFAULTS.color } }), ' ', el('b', {}, r.name),
            editing ? el('span', { class: 'pill route-editing' }, this.unsaved() ? 'editing · changed' : 'editing') : null,
            r.error ? el('div', { class: 'warn-text' }, r.error)
              : el('div', { class: 'hint' }, bits.join(' · '), r.name + '.gpx' !== r.file ? ` · ${r.file}` : '')),
          el('td', { class: 'route-actions' },
            editing ? el('button', { class: 'route-close', onclick: () => this.closeRoute() }, 'Close')
              : el('button', { disabled: !!r.error, onclick: () => this.openSaved(r.file) }, 'Open'),
            editing && this.unsaved() ? el('button', { onclick: () => this.openSaved(r.file) }, 'Revert') : null,
            el('button', { disabled: !!r.error, onclick: () => this.zoomSaved(r.file) }, 'Zoom to'),
            el('button', { class: 'danger-outline', onclick: () => this.deleteSaved(r.file) }, 'Delete')));
      }))))
      : el('p', { class: 'hint' }, 'No saved routes yet. Design one below and press Save route.');
    sec.append(body,
      el('div', { class: 'btnrow' },
        el('button', { onclick: () => this.newRoute() }, 'New route'),
        el('button', { onclick: () => this.importGpx() }, 'Import GPX…'),
        list.length ? el('button', { onclick: () => { list.forEach((r) => { if (!r.error) this.shown.add(r.file); }); this.saveShown(); this.setShown(list[0].file, true); } }, 'Show all') : null,
        this.shown.size ? el('button', { onclick: () => { this.shown.clear(); this.saveShown(); this.drawSaved(); this.render(); } }, 'Hide all') : null,
        el('button', { onclick: () => this.app.open('routes') }, 'Open the routes folder'),
        el('button', { onclick: () => this.loadSaved() }, 'Refresh')),
      el('p', { class: 'hint' }, 'Each route is a GPX file in the routes folder in Spyhop’s folder, so it can also go straight to a chart plotter or OpenCPN. Show puts a route on the map on every tab (Routes in the layers menu switches all routes on or off). Open loads it below to edit or activate. GPX files copied into the folder are listed after Refresh.'));
    return sec;
  }

  // ------------------------------------------------------------------ tab
  render() {
    const pane = document.getElementById('pane-route');
    if (!pane) return;
    if (this.saved === null && !this._loadingSaved) { this._loadingSaved = true; this.loadSaved().finally(() => { this._loadingSaved = false; }); }
    const s = this.state;
    const fmt = this.app.S.config.settings.latlon_format;
    const sec = (title, ...kids) => el('section', { class: 'settings-sec' }, el('h3', {}, title), ...kids);
    const radio = (name, value, label, cur, onchange) => el('label', { class: 'inline' },
      el('input', { type: 'radio', name, value, checked: cur === value, onchange: () => onchange(value) }), label);
    const num = (label, get, set, attrs = {}) => el('label', { class: 'row' }, el('span', { class: 'lbl' }, label),
      el('input', { type: 'number', value: get(), step: attrs.step || 'any', min: attrs.min ?? 0, max: attrs.max, style: 'width:7em',
        onchange: (e) => { set(e.target.value); this.changed(true); } }), attrs.unit ? el('span', { class: 'hint' }, attrs.unit) : null);

    const design = sec('Design',
      el('div', { class: 'btnrow' }, el('b', {}, 'Mode:'),
        ...[['manual', 'Manual — click points on the map'], ['systematic', 'Systematic — parallel legs'], ['sawtooth', 'Systematic — sawtooth (zig-zag)']]
          .map(([v, l]) => radio('plan-mode', v, l, s.mode, (m) => { s.mode = m; this.adding = false; this.picking = false; this.updateClickMode(); this.changed(true); }))),
      el('div', { class: 'grid2' },
        num('Survey speed', () => s.speed, (v) => { s.speed = Math.max(0.1, +v || 10); }, { step: 0.5, min: 0.1, unit: 'kn' })));

    // where the route starts: the vessel (the route follows it until activated) or a fixed point
    const startRow = (fixedLabel) => el('div', { class: 'route-start' }, el('b', {}, 'Start position: '),
      radio('plan-start', 'vessel', 'The vessel’s current position', s.start === 'vessel' ? 'vessel' : 'first', () => { s.start = 'vessel'; this.picking = false; this.updateClickMode(); this.changed(true); }),
      radio('plan-start', 'first', fixedLabel, s.start === 'vessel' ? 'vessel' : 'first', () => { s.start = 'first'; this.changed(true); }));

    let modeBox;
    if (s.mode === 'manual') {
      const toggle = el('button', { class: this.adding ? 'primary' : '', onclick: () => { this.adding = !this.adding; this.updateClickMode(); this.render(); } },
        this.adding ? 'Stop adding points' : 'Add points on the map');
      modeBox = sec('Manual trackline',
        startRow('The first point I click'),
        el('p', { class: 'hint' }, s.start === 'vessel' ? 'The route runs from the vessel to the points you click, and moves with the vessel until you activate it. ' : '',
          this.adding ? 'Click the map to add waypoints in order. Drag a waypoint to move it.' : 'Press Add points, then click the map where each waypoint should go. Drag a waypoint to move it.'),
        el('div', { class: 'btnrow' }, toggle,
          el('button', { disabled: !s.manual.points.length, onclick: () => { s.manual.points.pop(); this.changed(true); } }, 'Undo last point')));
    } else {
      const latIn = el('input', { type: 'text', style: 'width:9em', placeholder: 'latitude', value: s.sys.start ? fmtCoord(s.sys.start[0], true, fmt) : '' });
      const lonIn = el('input', { type: 'text', style: 'width:10em', placeholder: 'longitude', value: s.sys.start ? fmtCoord(s.sys.start[1], false, fmt) : '' });
      const setTyped = () => {
        const a = parseCoord(latIn.value, true), b = parseCoord(lonIn.value, false);
        if (a === null || b === null) { toast('Type the start as e.g. 41 54.0 N and 70 20.0 W, or 41.9 and -70.33', 'warn'); return; }
        s.sys.start = [a, b]; s.start = 'first'; this.changed(true);
      };
      latIn.onchange = lonIn.onchange = () => { if (latIn.value && lonIn.value) setTyped(); };
      const fixed = s.start !== 'vessel';
      if (!fixed) { latIn.disabled = true; lonIn.disabled = true; }
      const startBox = el('div', { class: `route-fixed${fixed ? '' : ' off'}` },
        el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Start point'), latIn, lonIn),
        el('div', { class: 'btnrow' },
          el('button', { disabled: !fixed, class: this.picking ? 'primary' : '', onclick: () => { this.picking = !this.picking; this.updateClickMode(); this.render(); } }, this.picking ? 'Click the map…' : 'Pick on the map'),
          el('button', { disabled: !fixed || !this.vesselLL(), onclick: () => { const v = this.vesselLL(); if (v) { s.sys.start = v.map((x) => +x.toFixed(6)); s.start = 'first'; this.changed(true); } } }, 'Use the vessel position now')));
      const startHint = el('p', { class: 'hint' }, s.start === 'vessel' ? 'Starting from the vessel’s current position; the route moves with the vessel until you choose a fixed start or activate it.'
        : s.sys.start ? 'Drag the first waypoint on the map to move the whole pattern.' : 'Choose a start point: pick it on the map, type it, or use the vessel position.');
      if (s.mode === 'sawtooth') {
        const w = s.saw;
        const n3 = (v) => Math.round((((+v || 0) % 360) + 360) % 360).toString().padStart(3, '0');
        const th = (180 - (+w.angle || 90)) / 2, sg = w.side === 'port' ? -1 : 1;
        const width = Math.sin(th * Math.PI / 180) * (+w.legNm || 0);
        const along = Math.cos(th * Math.PI / 180) * (+w.legNm || 0) * Math.max(1, Math.round(+w.legs || 1));
        modeBox = sec('Sawtooth trackline',
          startRow('A fixed point'), startBox,
          el('div', { class: 'grid2' },
            num('Survey direction', () => w.direction, (v) => { w.direction = ((+v || 0) % 360 + 360) % 360; }, { step: 1, min: -360, max: 360, unit: '°T (the way the pattern advances)' }),
            num('Leg length', () => w.legNm, (v) => { w.legNm = Math.max(0, +v || 0); }, { step: 0.5, unit: 'nm' }),
            num('Angle between legs', () => w.angle, (v) => { w.angle = Math.max(1, Math.min(179, +v || 90)); }, { step: 1, min: 1, max: 179, unit: '° where one leg meets the next' }),
            el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'First leg to'),
              el('select', { onchange: (e) => { w.side = e.target.value; this.changed(true); } },
                el('option', { value: 'starboard', selected: w.side !== 'port' }, 'Starboard (right)'),
                el('option', { value: 'port', selected: w.side === 'port' }, 'Port (left)'))),
            num('Number of legs', () => w.legs, (v) => { w.legs = Math.max(1, Math.min(200, Math.round(+v || 1))); }, { step: 1, min: 1, max: 200, unit: w.ret ? 'each way' : '' }),
            el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Pattern'),
              el('select', { class: 'saw-ret', onchange: (e) => { w.ret = e.target.value === 'return'; this.changed(true); } },
                el('option', { value: 'oneway', selected: !w.ret }, 'One way'),
                el('option', { value: 'return', selected: !!w.ret }, 'Return: a reciprocal sawtooth back through it')))),
          el('p', { class: 'hint saw-summary' }, `The legs alternate between ${n3((+w.direction || 0) + sg * th)}°T and ${n3((+w.direction || 0) - sg * th)}°T, `,
            `advancing toward ${n3(w.direction)}°T: ${along.toFixed(1)} nm along that line and ${width.toFixed(1)} nm wide.`,
            w.ret ? ` At the far end a crossover leg straight across (${n3((+w.direction || 0) + sg * 90 * (Math.max(1, Math.round(+w.legs || 1)) % 2 ? -1 : 1))}°T, ${width.toFixed(1)} nm) leads onto the reciprocal sawtooth, which comes back through the outbound one, crossing each of its legs in the middle.` : ''),
          startHint);
      } else {
      modeBox = sec('Systematic trackline',
        startRow('A fixed point'), startBox,
        el('div', { class: 'grid2' },
          num('Survey direction', () => s.sys.bearing, (v) => { s.sys.bearing = ((+v || 0) % 360 + 360) % 360; }, { step: 1, min: -360, max: 360, unit: '°T (bearing of leg 1)' }),
          num('Number of legs', () => s.sys.legs, (v) => { s.sys.legs = Math.max(1, Math.min(200, Math.round(+v || 1))); }, { step: 1, min: 1, max: 200 }),
          num('Leg length', () => s.sys.legNm, (v) => { s.sys.legNm = Math.max(0, +v || 0); }, { step: 0.5, unit: 'nm' }),
          num('Leg spacing', () => s.sys.spacingNm, (v) => { s.sys.spacingNm = Math.max(0, +v || 0); }, { step: 0.25, unit: 'nm' }),
          el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Next leg is to'),
            el('select', { onchange: (e) => { s.sys.side = e.target.value; this.changed(true); } },
              el('option', { value: 'starboard', selected: s.sys.side !== 'port' }, 'Starboard (right) of leg 1'),
              el('option', { value: 'port', selected: s.sys.side === 'port' }, 'Port (left) of leg 1')))),
        startHint);
      }
    }

    const nameIn = el('input', { type: 'text', value: s.name, style: 'width:16em', onchange: (e) => { s.name = e.target.value.trim() || 'Route'; this.save(); this.render(); } });
    const n = this.route().length;
    const unsaved = this.unsaved();
    const status = sec(`Current route: ${s.name}`,
      el('p', { class: 'hint' }, s.file ? (unsaved ? `Opened from ${s.file}; changed since it was saved.` : `Saved as ${s.file}.`)
        : n ? 'Not saved yet.' : 'Empty: design one below, or open a saved route.'),
      s.active
        ? el('p', {}, el('b', { class: 'route-active' }, '● Active. '), 'The waypoints are locked and the route is drawn on the map from every tab',
          s.layerOn ? '' : ' (it is hidden now: tick “Routes” in the map’s layers menu)', '. Deactivate it to change it.')
        : el('p', { class: 'hint' }, 'Draft: drawn on the map only while this tab is open. Activate it to lock the waypoints and keep it on the map.'),
      el('div', { class: 'btnrow' },
        s.active
          ? el('button', { onclick: () => this.deactivate() }, 'Deactivate (edit the route)')
          : el('button', { class: 'primary', disabled: n < 2, title: n < 2 ? 'The route needs at least two waypoints' : '', onclick: () => this.activate() }, 'Activate route'),
        el('button', { class: 'route-close', disabled: !n && !s.active && !s.file, title: 'Close this route: empty the editor and take it off the map', onclick: () => this.closeRoute() }, 'Close route'),
        el('button', { disabled: !n && !s.active, onclick: () => this.clearRoute() }, 'Clear waypoints'),
        el('button', { disabled: !n, onclick: () => this.fit() }, 'Zoom to route')));

    const st = s.style;
    const setStyle = (k, v) => { st[k] = v; this.save(); this.draw(); };
    const looks = sec('Appearance',
      el('div', { class: 'grid2' },
        el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Colour'),
          el('input', { type: 'color', value: st.color, oninput: (e) => setStyle('color', e.target.value) })),
        el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Line style'),
          el('select', { onchange: (e) => setStyle('line', e.target.value) },
            LINE_STYLES.map(([v, l]) => el('option', { value: v, selected: st.line === v }, l)))),
        el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Line width'),
          el('input', { type: 'number', min: 1, max: 12, step: 1, value: st.width, style: 'width:5em',
            oninput: (e) => { const v = Math.max(1, Math.min(12, +e.target.value || 3)); setStyle('width', v); } }), el('span', { class: 'hint' }, 'px')),
        el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Waypoint size'),
          el('input', { type: 'number', min: 4, max: 48, step: 2, value: st.point, style: 'width:5em',
            oninput: (e) => { const v = Math.max(4, Math.min(48, +e.target.value || 22)); setStyle('point', v); } }), el('span', { class: 'hint' }, 'px (numbers show from 14)'))),
      el('div', { class: 'btnrow' }, el('button', { onclick: () => { s.style = { ...STYLE_DEFAULTS }; this.save(); this.draw(); this.render(); } }, 'Reset appearance')),
      el('p', { class: 'hint' }, 'Used on the map and in the saved GPX file.'));
    const out = sec('Save',
      el('div', { class: 'btnrow' }, el('label', { class: 'inline' }, 'Name ', nameIn),
        el('button', { class: 'primary', disabled: n < 2 || (!!s.file && !unsaved && s.file === `${s.name}.gpx`), onclick: () => this.saveRoute(false) }, s.file ? 'Save route' : 'Save route…'),
        s.file ? el('button', { disabled: n < 2, onclick: () => this.saveRoute(true) }, 'Save as new…') : null,
        el('button', { disabled: n < 2, onclick: () => this.exportGpx() }, 'Export GPX…')),
      el('p', { class: 'hint' }, 'Save route keeps it in the routes folder (listed under Saved routes); renaming it and saving renames the file. Export GPX… downloads a copy and keeps one in the exports folder, for a chart plotter or OpenCPN. A route saved or exported by Spyhop opens again exactly as designed (mode, legs, speed and appearance); any other GPX file opens as a manual route of its route points (or else its waypoints, or its track).'));

    if (s.active) {
      for (const box of [design, modeBox]) {
        box.classList.add('locked');
        box.querySelectorAll('input, select, button').forEach((x) => { x.disabled = true; });
      }
    }
    pane.replaceChildren(this.savedSection(), status, out, design, modeBox, el('section', { class: 'settings-sec', id: 'plan-tables' }), looks);
    this.renderTables();
  }

  // ------------------------------------------------------------------ activate / clear / start here
  activate() {
    const r = this.route();
    if (r.length < 2) { toast('The route needs at least two waypoints.', 'warn'); return; }
    this.adding = false; this.picking = false;
    this.state.locked = r.map(({ ll, name, fixed, leg, survey }) => ({ ll: [+ll[0].toFixed(6), +ll[1].toFixed(6)], name,
      ...(fixed ? { fixed: true } : {}), ...(leg ? { leg, survey } : {}) }));
    this.state.active = true;
    this.state.activated = new Date().toISOString();
    this.state.layerOn = true;
    this.updateClickMode();
    this.save(); this.sync(); this.render();
    toast('Route activated: it stays on the map from every tab.');
  }

  deactivate() {
    this.state.active = false;
    this.state.locked = null;
    this.save(); this.sync(); this.render();
  }

  async clearRoute() {
    if (!await confirmBox('Clear the route?', 'Remove all the waypoints of this route' + (this.state.active ? ' and deactivate it' : '') + '? Saved routes and GPX files are not affected.', 'Clear', true)) return;
    const s = this.state;
    s.active = false; s.locked = null;
    s.manual.points = []; s.sys.start = null;
    if (s.start === 'vessel') s.start = 'first';
    this.adding = false; this.picking = false;
    this.updateClickMode();
    this.save(); this.sync();
    if (this.inTab) this.render();
  }

  // the map's right-click "Start route here": open the Route tab with that point as the start
  async startHere(ll) {
    const s = this.state;
    if (s.active) {
      if (!await confirmBox('Change the active route?', 'The route is active (locked). Deactivate it and start it from this point?', 'Deactivate and change')) return;
      s.active = false; s.locked = null;
    }
    const p = [+ll.lat.toFixed(6), +ll.lng.toFixed(6)];
    s.start = 'first';
    if (s.mode === 'systematic') {
      s.sys.start = p;
    } else {
      s.manual.points.unshift(p);
      this.adding = true;     // carry on clicking the rest of the route
    }
    this.save();
    this.app.showTab('route');
    this.updateClickMode();
    this.render();
    toast(s.mode === 'systematic' ? 'Start point set; adjust the legs in the Routes tab.'
      : s.manual.points.length > 1 ? 'Added as the route’s first waypoint.' : 'Route started here: click the map to add the next waypoints.', 'info', 5000);
  }

  renderTables() {
    const box = document.getElementById('plan-tables');
    if (!box) return;
    const fmt = this.app.S.config.settings.latlon_format;
    const r = this.route();
    const legs = this.legs(r);
    const clock = this.app.clock();
    const eta = (sec) => { const t = timeParts(new Date(Date.now() + sec * 1000), clock); return `${t.time.slice(0, 5)} ${t.abbr}`; };
    const nm = (m) => (m / M_PER_NM).toFixed(2);
    const dur = (s) => fmtDuration(s);
    if (!r.length) {
      box.replaceChildren(el('h3', {}, 'Legs'), el('p', { class: 'hint' }, this.state.mode === 'manual'
        ? 'No waypoints yet. Press Add points on the map, then click the map.' : 'Choose a start point to see the legs.'));
      return;
    }
    const last = legs[legs.length - 1];
    const surveyM = legs.filter((l) => l.survey).reduce((a, l) => a + l.m, 0);
    const totals = last ? el('div', { class: 'cards' },
      el('div', { class: 'card' }, el('div', { class: 'card-v' }, nm(last.total)), el('div', { class: 'card-l' }, 'nm in total')),
      surveyM !== last.total ? el('div', { class: 'card' }, el('div', { class: 'card-v' }, nm(surveyM)), el('div', { class: 'card-l' }, 'nm on the legs')) : null,
      el('div', { class: 'card' }, el('div', { class: 'card-v' }, dur(last.totalS)), el('div', { class: 'card-l' }, `at ${this.state.speed} kn`)),
      el('div', { class: 'card' }, el('div', { class: 'card-v' }, eta(last.totalS)), el('div', { class: 'card-l' }, 'finish, if you start now'))) : null;
    const legTable = el('table', { class: 'summary plan-table' },
      el('thead', {}, el('tr', {}, ['', 'From', 'To', 'Course', 'Distance', 'Time', 'Total', 'Total time', 'ETA'].map((h) => el('th', {}, h)))),
      el('tbody', {}, legs.map((l) => el('tr', { class: l.survey ? '' : 'crossing' },
        el('td', {}, l.kind), el('td', {}, l.from), el('td', {}, l.to), el('td', { class: 'num' }, `${Math.round(l.course).toString().padStart(3, '0')}°T`),
        el('td', { class: 'num' }, `${nm(l.m)} nm`), el('td', { class: 'num' }, dur(l.sec)),
        el('td', { class: 'num' }, `${nm(l.total)} nm`), el('td', { class: 'num' }, dur(l.totalS)), el('td', { class: 'num' }, eta(l.totalS))))));
    const manual = this.state.mode === 'manual';
    const wpTable = el('table', { class: 'summary plan-table' },
      el('thead', {}, el('tr', {}, ['#', 'Waypoint', 'Latitude', 'Longitude', ''].map((h) => el('th', {}, h)))),
      el('tbody', {}, r.map((p, i) => el('tr', {},
        el('td', {}, p.fixed ? '' : String(i + (r[0]?.fixed ? 0 : 1))), el('td', {}, p.name),
        el('td', { class: 'mono' }, fmtCoord(p.ll[0], true, fmt)), el('td', { class: 'mono' }, fmtCoord(p.ll[1], false, fmt)),
        el('td', {}, manual && !p.fixed && !this.state.active ? el('button', { class: 'icon', title: 'Remove this waypoint', onclick: () => { this.state.manual.points.splice(p.index, 1); this.changed(true); } }, '✕') : null)))));
    box.replaceChildren(el('h3', {}, 'Legs'), totals || el('p', { class: 'hint' }, 'Add a second point to make a leg.'),
      legs.length ? el('div', { class: 'table-scroll' }, legTable) : null,
      legs.length ? el('p', { class: 'hint' }, `Times at ${this.state.speed} kn, with no time for turns. ETA is the arrival time at the end of each leg if you start now.`) : null,
      el('h4', {}, 'Waypoints'), el('div', { class: 'table-scroll' }, wpTable));
  }

  // ------------------------------------------------------------------ output
  requireRoute() {
    const r = this.route();
    if (r.length < 2) { toast('The route needs at least two waypoints.', 'warn'); return null; }
    return r;
  }

  gpx(r) {
    const x = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const s = this.state;
    const legs = this.legs(r);
    const pt = (tag, p, i) => `  <${tag} lat="${p.ll[0].toFixed(6)}" lon="${p.ll[1].toFixed(6)}"><name>${x(p.name)}</name>`
      + (i ? `<desc>${x(`${legs[i - 1].kind}: ${(legs[i - 1].m / M_PER_NM).toFixed(2)} nm, ${fmtDuration(legs[i - 1].sec)} at ${s.speed} kn`)}</desc>` : '')
      + `<sym>Waypoint</sym></${tag}>`;
    const last = legs[legs.length - 1];
    return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Spyhop ${x(this.app.S.about?.spyhop || '')}" xmlns="http://www.topografix.com/GPX/1/1" xmlns:spyhop="https://github.com/spyhop/route/1">
  <metadata><name>${x(s.name)}</name><desc>${x(`Planned trackline: ${(last.total / M_PER_NM).toFixed(2)} nm, ${fmtDuration(last.totalS)} at ${s.speed} kn`)}</desc><time>${new Date().toISOString()}</time>
    <extensions><spyhop:route>${x(JSON.stringify(this.design()))}</spyhop:route></extensions></metadata>
${r.map((p, i) => pt('wpt', p, i)).join('\n')}
  <rte><name>${x(s.name)}</name>
${r.map((p, i) => '  ' + pt('rtept', p, i)).join('\n')}
  </rte>
</gpx>
`;
  }

  // the design, as saved in a GPX file so Import GPX… can bring it back exactly
  design() {
    const s = this.state;
    const d = { spyhop: 1, mode: s.mode, speed: s.speed, start: s.start, name: s.name, manual: s.manual, sys: s.sys, style: s.style };
    if (s.mode === 'sawtooth') d.saw = s.saw;
    // an activated route that started at the vessel is saved where it was frozen
    if (s.active && Array.isArray(s.locked) && s.start === 'vessel') {
      if (s.mode === 'manual') d.manual = { points: s.locked.map((p) => p.ll) };
      else d.sys = { ...s.sys, start: s.locked[0].ll };
      d.start = 'first';
    }
    return JSON.parse(JSON.stringify(d));
  }

  async importGpx() {
    const input = el('input', { type: 'file', accept: '.gpx,application/gpx+xml' });
    input.onchange = async () => {
      const f = input.files[0];
      if (!f) return;
      let txt;
      try { txt = await f.text(); } catch (e) { toast(`Couldn’t read ${f.name}: ${e.message}`, 'error'); return; }
      const res = parseRouteGpx(txt, f.name);
      if (res.error) { toast(res.error, 'error', 8000); return; }
      if (!await this.confirmLeave(`load “${res.design.name}” from ${f.name}`)) return;
      this.applyDesign(res.design, null);
      this.render(); this.fit();
      toast(`${res.exact ? `Loaded the route “${this.state.name}” as it was designed` : `Loaded ${this.state.manual.points.length} waypoints from ${f.name} as a manual route`}. Press Save route to keep it in the routes folder.`, 'info', 7000);
    };
    input.click();
  }

  async exportGpx() {
    const r = this.requireRoute();
    if (!r) return;
    let res;
    try { res = await api('/api/plan/gpx', { name: this.state.name, gpx: this.gpx(r) }); } catch { return; }
    const a = el('a', { href: res.url, download: res.name });
    document.body.append(a); a.click(); a.remove();
    toast(`GPX saved: ${res.path}`, 'info', 8000);
  }
}

// Read a route from GPX text. A file exported by Spyhop carries the whole design in
// <metadata><extensions><spyhop:route>; otherwise the first <rte>, else the <wpt>s, else a <trk>.
export function parseRouteGpx(txt, fileName = '') {
  const doc = new DOMParser().parseFromString(txt, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length || !doc.getElementsByTagName('gpx').length) return { error: `${fileName || 'That file'} isn’t a GPX file.` };
  const name = (n, tag) => n.getElementsByTagName(tag)[0]?.textContent?.trim() || '';
  const pts = (list) => [...list].map((p) => [+(+p.getAttribute('lat')).toFixed(6), +(+p.getAttribute('lon')).toFixed(6)])
    .filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a) <= 90 && Math.abs(b) <= 180);
  let points = [], title = '';
  const rte = doc.getElementsByTagName('rte')[0];
  const ext = doc.getElementsByTagName('spyhop:route')[0];
  if (ext) {
    try {
      const d = JSON.parse(ext.textContent);
      // the route as drawn when saved (a route from the vessel is saved where the vessel was)
      const drawn = rte ? pts(rte.getElementsByTagName('rtept')) : pts(doc.getElementsByTagName('wpt'));
      if (d && MODE_LABELS[d.mode]) return { design: d, exact: true, points: drawn };
    } catch { /* fall back to the points */ }
  }
  if (rte) { points = pts(rte.getElementsByTagName('rtept')); title = name(rte, 'name'); }
  if (points.length < 2) { points = pts(doc.getElementsByTagName('wpt')); }
  if (points.length < 2) { const trk = doc.getElementsByTagName('trk')[0]; if (trk) { points = pts(trk.getElementsByTagName('trkpt')); title = title || name(trk, 'name'); } }
  if (points.length < 2) return { error: `${fileName || 'The file'} has no route, waypoints or track with at least two points.` };
  if (points.length > 500) return { error: `${fileName || 'The file'} has ${points.length} points; a route can have up to 500.` };
  const meta = doc.getElementsByTagName('metadata')[0];
  title = title || (meta && name(meta, 'name')) || fileName.replace(/\.gpx$/i, '') || 'Imported route';
  return { design: { mode: 'manual', start: 'first', name: title, manual: { points } }, exact: false, points };
}
