// 0.57: navigation to a waypoint or along a route — how long until we get there, not steering.
// The server keeps the target (settings nav_active) and works out the numbers once a second (nav.py); this draws
// the route being navigated (highlighted, the leg ahead brightest), the arrival circle, a line from the vessel to
// the waypoint, and a small box on the map with the distance, bearing, VMG, time to go and ETAs.
// Started from a waypoint's popup, the map's right-click menu, the Waypoints tab and Tools → Routes.
import { el, api, toast, confirmBox, fmtDist, fmtBrg, timeParts } from './util.js';
import { fmtDuration } from './planning.js';

const NAV_COLOR = '#00b4d8';

export class Navigation {
  constructor(app) {
    this.app = app;
    const map = app.map.map;
    map.createPane('nav').style.zIndex = 415;          // under the tracks (420) and markers, over the routes' overlay pane
    this.layer = L.layerGroup().addTo(map);
    this.toLines = null;
    this.last = null;
    this._drawnKey = null;
    const Box = L.Control.extend({ options: { position: 'topright' }, onAdd: () => this.makeBox() });
    this.control = new Box();
    this.control.addTo(map);
    this.box.hidden = true;
  }

  get target() { return this.app.S.config.settings.nav_active || null; }
  get viewer() { return !!this.app.S.viewer; }

  // ---------------------------------------------------------------- starting and stopping
  async start(target) {
    if (this.viewer) return;
    const cur = this.target;
    if (cur && !await confirmBox('Navigate somewhere else?', `Spyhop is navigating ${cur.kind === 'route' ? 'along' : 'to'} “${cur.name}”. Stop that and navigate ${target.kind === 'route' ? 'along' : 'to'} “${target.name}” instead?`, 'Yes')) return;
    try {
      const r = await api('/api/nav/start', target);
      this.app.S.config.settings.nav_active = r.target;
      this.update(r.nav); this.redraw();
      toast(target.kind === 'route' ? `Navigating along “${r.target.name}”, to waypoint ${r.target.index + 1} of ${r.target.points.length}.` : `Navigating to ${r.target.name}.`);
    } catch (e) { toast(e.message, 'error'); }
  }

  toWaypoint(name, lat, lon) { return this.start({ kind: 'waypoint', name: name || 'Waypoint', points: [{ name: name || 'Waypoint', lat, lon }] }); }

  // a route's waypoints [{name, ll: [lat, lon]}]; index: a number, or 'ahead' (the waypoint ahead of the vessel)
  alongRoute(name, pts, index = 'ahead') {
    // 0.58: a route's waypoints are known by their number
    return this.start({ kind: 'route', name, index, points: pts.map((p, i) => ({ name: String(i + 1), lat: p.ll[0], lon: p.ll[1] })) });
  }

  async stop() {
    try { await api('/api/nav/stop', {}); } catch (e) { toast(e.message, 'error'); return; }
    this.app.S.config.settings.nav_active = null;
    this.update(null); this.redraw();
  }

  async step(by) {
    try {
      const r = await api('/api/nav/step', { by });
      this.app.S.config.settings.nav_active = r.target;
      this.update(r.nav); this.redraw();
    } catch (e) { toast(e.message, 'error'); }
  }

  // ---------------------------------------------------------------- drawing
  // the route (or waypoint) being navigated; called when the target or the settings change
  redraw() {
    const t = this.target, st = this.app.S.config.settings;
    const key = t ? JSON.stringify([t.points, t.index, st.nav_arrival_nm]) : null;
    if (key === this._drawnKey) return;
    this._drawnKey = key;
    this.layer.clearLayers();
    this.toLines = null;
    if (!t) { this.box.hidden = true; return; }
    const lls = t.points.map((p) => [p.lat, p.lon]), i = t.index;
    const pane = 'nav';
    if (lls.length > 1) {
      // done legs faint, the leg ahead brightest, the rest highlighted
      if (i > 1) L.polyline(lls.slice(0, i), { pane, color: NAV_COLOR, weight: 4, opacity: 0.35, dashArray: '6 6', interactive: false }).addTo(this.layer);
      L.polyline(lls.slice(Math.max(0, i - 1)), { pane, color: '#fff', weight: 9, opacity: 0.7, interactive: false }).addTo(this.layer);
      L.polyline(lls.slice(Math.max(0, i - 1)), { pane, color: NAV_COLOR, weight: 5, opacity: 0.9, interactive: false, className: 'nav-route' }).addTo(this.layer);
      if (i > 0) L.polyline([lls[i - 1], lls[i]], { pane, color: '#ffd400', weight: 3, opacity: 1, interactive: false, className: 'nav-leg' }).addTo(this.layer);
    }
    t.points.forEach((p, k) => {
      L.circleMarker([p.lat, p.lon], { pane, radius: k === i ? 7 : 5, color: '#fff', weight: 2, fillColor: k < i ? '#7aa' : k === i ? '#ffd400' : NAV_COLOR,
        fillOpacity: 1, className: k === i ? 'nav-target' : 'nav-wp' })
        .bindTooltip(`${t.kind === 'route' ? `Waypoint ${k + 1}` : p.name}${k === i ? ' (next)' : k < i ? ' (passed)' : ''}`, { direction: 'top' }).addTo(this.layer);
    });
    const tp = t.points[i];
    L.circle([tp.lat, tp.lon], { pane, radius: (+st.nav_arrival_nm || 0.1) * 1852, color: '#ffd400', weight: 1.5, dashArray: '4 4',
      fill: false, interactive: false, className: 'nav-arrival' }).addTo(this.layer);
    if (t.kind === 'route') {
      this.toLines = [L.polyline([], { pane, color: '#ffd400', weight: 2, dashArray: '2 6', interactive: false, className: 'nav-to' }).addTo(this.layer)];
    } else {
      // 0.58: to a single point, the line from the vessel looks like the leg ahead on a route
      this.toLines = [L.polyline([], { pane, color: '#fff', weight: 9, opacity: 0.7, interactive: false }),
        L.polyline([], { pane, color: NAV_COLOR, weight: 5, opacity: 0.9, interactive: false }),
        L.polyline([], { pane, color: '#ffd400', weight: 3, opacity: 1, interactive: false, className: 'nav-leg nav-to' })].map((l) => l.addTo(this.layer));
    }
    this.placeToLine();
  }

  placeToLine() {
    const t = this.target, v = this.app.S.vessel;
    if (!this.toLines || !t) return;
    const p = t.points[t.index];
    for (const l of this.toLines) l.setLatLngs(v && v.lat != null ? [[v.lat, v.lon], [p.lat, p.lon]] : []);
  }

  // ---------------------------------------------------------------- the box
  makeBox() {
    this.box = el('div', { class: 'nav-box leaflet-bar', id: 'nav-box' });
    L.DomEvent.disableClickPropagation(this.box);
    L.DomEvent.disableScrollPropagation(this.box);
    return this.box;
  }

  // every vessel message (m.nav), and after a start/step/stop
  update(n, events) {
    this.last = n || null;
    for (const e of events || []) {
      const what = e.kind === 'route' ? `waypoint ${(e.index ?? 0) + 1} of ${e.count}` : e.arrived;
      if (e.last) toast(`Arrived at ${what}${e.kind === 'route' ? ', the end of the route' : ''}. Navigation stopped.`, 'info', 8000);
      else toast(`Reached ${what}.${this.app.S.config.settings.nav_auto_advance === false ? ' Press Next for the next waypoint.' : ''}`, 'info', 6000);
    }
    this.redraw();
    this.placeToLine();
    this.renderBox();
  }

  renderBox() {
    const box = this.box, t = this.target, n = this.last, st = this.app.S.config.settings;
    if (!box) return;
    if (!t || st.nav_show_box === false) { box.hidden = true; return; }
    box.hidden = false;
    const unit = this.app.unit(), clock = this.app.clock();
    const eta = (s) => { if (!s) return '—'; const p = timeParts(new Date(s * 1000).toISOString(), clock); return `${p.time.slice(0, 5)} ${p.abbr}`; };
    const dur = (s) => (s === null || s === undefined ? '—' : fmtDuration(s));
    const kn = (v) => (v === null || v === undefined ? '—' : `${(+v).toFixed(1)} kn`);
    const route = t.kind === 'route';
    // 0.58: the whole title folds and unfolds the box
    const head = el('div', { class: 'nav-head', title: this.folded ? 'Show the details' : 'Fold the box', onclick: () => { this.folded = !this.folded; this.renderBox(); } },
      el('span', { class: 'nav-fold' }, this.folded ? '▸' : '▾'),
      el('b', {}, route ? `${t.name}` : `To ${t.name}`),
      route ? el('span', { class: 'hint' }, ` ${t.index + 1}/${t.points.length}`) : null,
      this.viewer ? null : el('button', { class: 'nav-stop', title: 'Stop navigating', onclick: (e) => { e.stopPropagation(); this.stop(); } }, '✕'));
    const rows = [];
    const row = (k, v, cls) => rows.push(el('tr', { class: cls || '' }, el('th', {}, k), el('td', {}, v)));
    if (!n || n.no_fix) row('', 'Waiting for a GPS position');
    else {
      if (route) row('Next waypoint', `${t.index + 1} of ${t.points.length}`, 'nav-next');
      row('Distance', fmtDist(n.dist_m, unit), 'nav-dist');
      row('Bearing', `${fmtBrg(n.brg_t)}T${n.brg_m != null ? ` (${fmtBrg(n.brg_m)}M)` : ''}`);
      row('VMG', kn(n.vmg_kn), 'nav-vmg');
      row('Time to go', n.fixed_speed ? `${dur(n.ttg_s)} at ${(+st.nav_eta_speed_kn).toFixed(1)} kn` : dur(n.ttg_s), 'nav-ttg');
      row('ETA', eta(n.eta), 'nav-eta');
      if (route) {
        row('To the end', `${fmtDist(n.remaining_m, unit)} · ${dur(n.ttg_end_s)}`, 'nav-rest');
        row('ETA at end', eta(n.eta_end), 'nav-eta-end');
      }
      if (n.arrived && !n.finished) row('', el('b', {}, 'Reached — press Next ▸'));
    }
    const btns = this.viewer || !route ? null : el('div', { class: 'nav-btns' },
      el('button', { disabled: t.index === 0, onclick: () => this.step(-1) }, '◂ Previous'),
      el('button', { disabled: t.index >= t.points.length - 1, onclick: () => this.step(1) }, 'Next ▸'));
    box.replaceChildren(head, ...(this.folded ? [] : [el('table', { class: 'nav-table' }, el('tbody', {}, rows)), btns]));
    box.title = n && !n.fixed_speed && n.window_s != null ? `VMG averaged over the last ${n.window_s} s` : '';
  }
}
