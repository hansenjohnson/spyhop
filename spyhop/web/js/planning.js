// Tools → Route: design a trackline (manual clicks or a systematic parallel-leg
// pattern), see each leg's distance and time, activate it (locked and shown on the map
// from every tab), style it, save it as a map overlay and/or export GPX.
import { el, esc, api, toast, confirmBox, fmtCoord, fmtPos, fmtDist, fmtBrg, distM, bearing, destination, timeParts, dashFor, LINE_STYLES } from './util.js';

// "45 min", "1 h 42 min" — clearer for passage times than 0:45:00
export function fmtDuration(sec) {
  const m = Math.round(Math.max(0, sec) / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${String(m % 60).padStart(2, '0')} min` : ''}`;
}

const M_PER_NM = 1852;
const STORE = 'wsr.plan';
export const STYLE_DEFAULTS = { color: '#6b6b6b', point: 18, width: 3, line: 'dotted' };
const OLD_DEFAULT_STYLE = { color: '#d35400', point: 22, width: 3, line: 'dashed' };   // before 0.8.0
const DEFAULTS = {
  mode: 'manual', speed: 10, start: 'first', name: 'Route 1',
  manual: { points: [] },
  sys: { start: null, bearing: 0, legs: 4, legNm: 10, spacingNm: 2, side: 'starboard' },
  active: false, locked: null,      // an activated route: its waypoints, frozen
  layerOn: true,                    // the "Route" entry in the map's layers menu
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

export class Planner {
  constructor(app) {
    this.app = app;
    this.state = this.load();
    this.layer = L.layerGroup();
    this.adding = false;          // manual: clicks on the map add points
    this.picking = false;         // systematic: the next click sets the start
    this.inTab = false;           // the Route tab is open
    const m = app.map;
    m.layerControl.addOverlay(this.layer, 'Route');
    // the user ticking / unticking "Route" in the layers menu (not our own add/remove)
    m.map.on('overlayadd overlayremove', (e) => {
      if (e.layer !== this.layer || this._syncing) return;
      this.state.layerOn = e.type === 'overlayadd';
      this.save();
      if (this.state.layerOn) this.draw();
      if (this.inTab) this.render();
    });
    this.sync();
  }

  // The route is on the map while the Route tab is open, and from every tab once activated
  // (unless "Route" is unticked in the layers menu).
  sync() {
    const want = this.state.layerOn && (this.inTab || this.state.active);
    const map = this.app.map.map;
    this._syncing = true;
    try {
      if (want && !map.hasLayer(this.layer)) this.layer.addTo(map);
      else if (!want && map.hasLayer(this.layer)) this.layer.remove();
    } finally { this._syncing = false; }
    this.draw();
  }

  load() {
    try {
      const s = JSON.parse(localStorage.getItem(STORE) || 'null');
      if (s) {
        // a style never changed from the old orange default takes the new grey dotted one
        const st = s.style && Object.keys(OLD_DEFAULT_STYLE).every((k) => s.style[k] === OLD_DEFAULT_STYLE[k]) ? null : s.style;
        return { ...DEFAULTS, ...s, manual: { ...DEFAULTS.manual, ...s.manual }, sys: { ...DEFAULTS.sys, ...s.sys }, style: { ...STYLE_DEFAULTS, ...st } };
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
      const kind = this.state.mode === 'systematic' ? (i % 2 ? 'Crossing' : `Leg ${i / 2 + 1}`) : `Leg ${i + 1}`;
      out.push({ kind, from: a.name, to: b.name, course: bearing(a.ll, b.ll), m, sec, total, totalS, survey: this.state.mode !== 'systematic' || i % 2 === 0 });
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
    if (!this.app.map.map.hasLayer(this.layer)) return;
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
    this.render();      // the whole tab: the Route status buttons depend on the number of waypoints
  }

  // ------------------------------------------------------------------ tab
  render() {
    const pane = document.getElementById('pane-route');
    if (!pane) return;
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
        radio('plan-mode', 'manual', 'Manual — click points on the map', s.mode, (v) => { s.mode = v; this.adding = false; this.picking = false; this.updateClickMode(); this.changed(true); }),
        radio('plan-mode', 'systematic', 'Systematic — parallel legs', s.mode, (v) => { s.mode = v; this.adding = false; this.picking = false; this.updateClickMode(); this.changed(true); })),
      el('div', { class: 'grid2' },
        num('Survey speed', () => s.speed, (v) => { s.speed = Math.max(0.1, +v || 10); }, { step: 0.5, min: 0.1, unit: 'kn' }),
        el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Start position'),
          el('select', { onchange: (e) => { s.start = e.target.value; this.changed(true); } },
            el('option', { value: 'vessel', selected: s.start === 'vessel' }, 'Current vessel position'),
            el('option', { value: 'first', selected: s.start !== 'vessel' }, s.mode === 'manual' ? 'First point clicked' : 'A chosen point')))));

    let modeBox;
    if (s.mode === 'manual') {
      const toggle = el('button', { class: this.adding ? 'primary' : '', onclick: () => { this.adding = !this.adding; this.updateClickMode(); this.render(); } },
        this.adding ? 'Stop adding points' : 'Add points on the map');
      modeBox = sec('Manual trackline',
        el('p', { class: 'hint' }, this.adding ? 'Click the map to add waypoints in order. Drag a waypoint to move it.' : 'Press Add points, then click the map where each waypoint should go. Drag a waypoint to move it.'),
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
      modeBox = sec('Systematic trackline',
        el('div', { class: 'grid2' },
          el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Start point'), latIn, lonIn),
          el('div', { class: 'btnrow' },
            el('button', { class: this.picking ? 'primary' : '', onclick: () => { this.picking = !this.picking; this.updateClickMode(); this.render(); } }, this.picking ? 'Click the map…' : 'Pick on the map'),
            el('button', { disabled: !this.vesselLL(), onclick: () => { const v = this.vesselLL(); if (v) { s.sys.start = v.map((x) => +x.toFixed(6)); s.start = 'first'; this.changed(true); } } }, 'Use the vessel position now')),
          num('Survey direction', () => s.sys.bearing, (v) => { s.sys.bearing = ((+v || 0) % 360 + 360) % 360; }, { step: 1, min: -360, max: 360, unit: '°T (bearing of leg 1)' }),
          num('Number of legs', () => s.sys.legs, (v) => { s.sys.legs = Math.max(1, Math.min(200, Math.round(+v || 1))); }, { step: 1, min: 1, max: 200 }),
          num('Leg length', () => s.sys.legNm, (v) => { s.sys.legNm = Math.max(0, +v || 0); }, { step: 0.5, unit: 'nm' }),
          num('Leg spacing', () => s.sys.spacingNm, (v) => { s.sys.spacingNm = Math.max(0, +v || 0); }, { step: 0.25, unit: 'nm' }),
          el('label', { class: 'row' }, el('span', { class: 'lbl' }, 'Next leg is to'),
            el('select', { onchange: (e) => { s.sys.side = e.target.value; this.changed(true); } },
              el('option', { value: 'starboard', selected: s.sys.side !== 'port' }, 'Starboard (right) of leg 1'),
              el('option', { value: 'port', selected: s.sys.side === 'port' }, 'Port (left) of leg 1')))),
        el('p', { class: 'hint' }, s.start === 'vessel' ? 'Starting from the vessel’s current position; the route moves with the vessel until you choose a fixed start or activate it.'
          : s.sys.start ? 'Drag the first waypoint on the map to move the whole pattern.' : 'Choose a start point: pick it on the map, type it, or use the vessel position.'));
    }

    const nameIn = el('input', { type: 'text', value: s.name, style: 'width:16em', onchange: (e) => { s.name = e.target.value.trim() || 'Route'; this.save(); } });
    const n = this.route().length;
    const status = sec('Route',
      s.active
        ? el('p', {}, el('b', { class: 'route-active' }, '● Active. '), 'The waypoints are locked and the route is drawn on the map from every tab',
          s.layerOn ? '' : ' (it is hidden now: tick “Route” in the map’s layers menu)', '. Deactivate it to change it.')
        : el('p', { class: 'hint' }, 'Draft: drawn on the map only while this tab is open. Activate it to lock the waypoints and keep it on the map.'),
      el('div', { class: 'btnrow' },
        s.active
          ? el('button', { onclick: () => this.deactivate() }, 'Deactivate (edit the route)')
          : el('button', { class: 'primary', disabled: n < 2, title: n < 2 ? 'The route needs at least two waypoints' : '', onclick: () => this.activate() }, 'Activate route'),
        el('button', { disabled: !n && !s.active, onclick: () => this.clearRoute() }, 'Clear route'),
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
      el('p', { class: 'hint' }, 'Used on the map and in a saved overlay.'));
    const out = sec('Save the design',
      el('div', { class: 'btnrow' }, el('label', { class: 'inline' }, 'Name ', nameIn),
        el('button', { class: 'primary', onclick: () => this.saveOverlay() }, 'Save as map overlay'),
        el('button', { onclick: () => this.exportGpx() }, 'Export GPX…'),
        el('button', { onclick: () => this.importGpx() }, 'Import GPX…')),
      el('p', { class: 'hint' }, 'A saved overlay is drawn under “Imported overlays” in the map’s layers menu and listed in Tools → Waypoints (remove it there). The GPX file holds the waypoints and the route, for a chart plotter or OpenCPN; it is also kept in the exports folder. Import GPX… loads a route back: one exported by Spyhop comes back exactly as designed (mode, legs, speed and appearance); from any other GPX file, the route (or else the waypoints, or a track) becomes a manual route.'));

    if (s.active) {
      for (const box of [design, modeBox]) {
        box.classList.add('locked');
        box.querySelectorAll('input, select, button').forEach((x) => { x.disabled = true; });
      }
    }
    pane.replaceChildren(status, design, modeBox, el('section', { class: 'settings-sec', id: 'plan-tables' }), looks, out);
    this.renderTables();
  }

  // ------------------------------------------------------------------ activate / clear / start here
  activate() {
    const r = this.route();
    if (r.length < 2) { toast('The route needs at least two waypoints.', 'warn'); return; }
    this.adding = false; this.picking = false;
    this.state.locked = r.map(({ ll, name, fixed }) => ({ ll: [+ll[0].toFixed(6), +ll[1].toFixed(6)], name, ...(fixed ? { fixed: true } : {}) }));
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
    if (!await confirmBox('Clear the route?', 'Remove all the waypoints of this route' + (this.state.active ? ' and deactivate it' : '') + '? Saved overlays and GPX files are not affected.', 'Clear', true)) return;
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
    toast(s.mode === 'systematic' ? 'Start point set; adjust the legs in the Route tab.'
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
      this.state.mode === 'systematic' ? el('div', { class: 'card' }, el('div', { class: 'card-v' }, nm(surveyM)), el('div', { class: 'card-l' }, 'nm on the legs')) : null,
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

  geojson(r) {
    const legs = this.legs(r);
    const last = legs[legs.length - 1];
    const s = this.state;
    const created = new Date().toISOString();
    const lonlat = (ll) => [+ll[1].toFixed(6), +ll[0].toFixed(6)];
    return {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', geometry: { type: 'LineString', coordinates: r.map((p) => lonlat(p.ll)) },
          properties: { name: s.name, kind: 'Planned trackline', mode: s.mode, speed_kn: s.speed,
            total_nm: +(last.total / M_PER_NM).toFixed(2), duration: fmtDuration(last.totalS), created,
            stroke: s.style.color, 'stroke-width': +s.style.width || 3, dash: dashFor(s.style.line, s.style.width) } },
        ...r.map((p, i) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: lonlat(p.ll) },
          properties: { name: `${s.name} ${p.name}`, waypoint: i + 1, 'marker-color': s.style.color, 'marker-radius': Math.max(2, Math.round((+s.style.point || 22) / 4)),
            ...(i ? { leg_nm: +(legs[i - 1].m / M_PER_NM).toFixed(2), total_nm: +(legs[i - 1].total / M_PER_NM).toFixed(2) } : {}) } })),
      ],
    };
  }

  async saveOverlay() {
    const r = this.requireRoute();
    if (!r) return;
    const file = `${this.state.name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_')}.geojson`;
    if ((this.app.S.overlays || []).includes(file)
      && !await confirmBox('Replace the overlay?', `An overlay called ${file} already exists. Replace it with this route?`, 'Replace')) return;
    const fd = new FormData();
    fd.append('file', new Blob([JSON.stringify(this.geojson(r), null, 1)], { type: 'application/geo+json' }), file);
    const res = await fetch('/api/overlays', { method: 'POST', body: fd }).then((x) => x.json()).catch(() => ({ ok: false, error: 'Couldn’t reach Spyhop' }));
    if (!res.ok) { toast(res.error, 'error'); return; }
    // make sure imported overlays are visible so the user sees it
    const m = this.app.map;
    if (!m.map.hasLayer(m.layers.imported)) m.layers.imported.addTo(m.map);
    toast(`Saved the route as the overlay ${file}`);
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
      const s = this.state;
      const hasRoute = s.active || this.route().length;
      if (hasRoute && !await confirmBox('Replace the route?', `Replace the current route${s.active ? ' (it is active)' : ''} with “${res.design.name}” from ${f.name}?`, 'Replace')) return;
      const d = res.design;
      Object.assign(s, {
        mode: d.mode === 'systematic' ? 'systematic' : 'manual', speed: +d.speed > 0 ? +d.speed : s.speed,
        start: d.start === 'vessel' ? 'vessel' : 'first', name: d.name || s.name,
        manual: { points: (d.manual?.points || []).filter((p) => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite)) },
        sys: { ...s.sys, ...(d.sys || {}) },
        style: d.style ? { ...STYLE_DEFAULTS, ...d.style } : s.style,
        active: false, locked: null,
      });
      this.adding = false; this.picking = false;
      this.updateClickMode();
      this.save(); this.sync(); this.render(); this.fit();
      toast(res.exact ? `Loaded the route “${s.name}” as it was designed.` : `Loaded ${s.manual.points.length} waypoints from ${f.name} as a manual route.`, 'info', 6000);
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
  const ext = doc.getElementsByTagName('spyhop:route')[0];
  if (ext) {
    try {
      const d = JSON.parse(ext.textContent);
      if (d && (d.mode === 'manual' || d.mode === 'systematic')) return { design: d, exact: true };
    } catch { /* fall back to the points */ }
  }
  const name = (n, tag) => n.getElementsByTagName(tag)[0]?.textContent?.trim() || '';
  const pts = (list) => [...list].map((p) => [+(+p.getAttribute('lat')).toFixed(6), +(+p.getAttribute('lon')).toFixed(6)])
    .filter(([a, b]) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a) <= 90 && Math.abs(b) <= 180);
  let points = [], title = '';
  const rte = doc.getElementsByTagName('rte')[0];
  if (rte) { points = pts(rte.getElementsByTagName('rtept')); title = name(rte, 'name'); }
  if (points.length < 2) { points = pts(doc.getElementsByTagName('wpt')); }
  if (points.length < 2) { const trk = doc.getElementsByTagName('trk')[0]; if (trk) { points = pts(trk.getElementsByTagName('trkpt')); title = title || name(trk, 'name'); } }
  if (points.length < 2) return { error: `${fileName || 'The file'} has no route, waypoints or track with at least two points.` };
  if (points.length > 500) return { error: `${fileName || 'The file'} has ${points.length} points; a route can have up to 500.` };
  const meta = doc.getElementsByTagName('metadata')[0];
  title = title || (meta && name(meta, 'name')) || fileName.replace(/\.gpx$/i, '') || 'Imported route';
  return { design: { mode: 'manual', start: 'first', name: title, manual: { points } }, exact: false };
}
