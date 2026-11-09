// Build a self-contained HTML summary: the Summary tab's contents plus an interactive
// Leaflet map (offline coastline by default). Everything is inlined, so the file opens
// anywhere, without internet and without Spyhop.
//
// { pdf: true } builds the page that is printed to PDF instead: a fixed-size map fitted to
// the survey, on Esri Ocean when its tiles load (else the offline coastline), with no point
// labels or map buttons, and a legend of the point symbols under the map.
/* global topojson */
import { esc, timeParts, isTrackBreak, trackStates, dashFor } from './util.js';
import { shapeSvg } from './map.js';

const ONLINE = {
  'OpenStreetMap (online)': ['https://tile.openstreetmap.org/{z}/{x}/{y}.png', '© OpenStreetMap contributors', 19],
  'Esri Ocean (online)': ['https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}',
    'Esri, GEBCO, NOAA, Garmin, HERE', 13],
};

// Sutherland–Hodgman clip of one ring ([[lon,lat],…]) to a lon/lat box.
function clipRing(ring, [w, s, e, n]) {
  const edges = [
    [(p) => p[0] >= w, (a, b) => [w, a[1] + (b[1] - a[1]) * (w - a[0]) / (b[0] - a[0])]],
    [(p) => p[0] <= e, (a, b) => [e, a[1] + (b[1] - a[1]) * (e - a[0]) / (b[0] - a[0])]],
    [(p) => p[1] >= s, (a, b) => [a[0] + (b[0] - a[0]) * (s - a[1]) / (b[1] - a[1]), s]],
    [(p) => p[1] <= n, (a, b) => [a[0] + (b[0] - a[0]) * (n - a[1]) / (b[1] - a[1]), n]],
  ];
  let out = ring;
  for (const [inside, cross] of edges) {
    const input = out;
    out = [];
    if (!input.length) break;
    let prev = input[input.length - 1];
    for (const cur of input) {
      if (inside(cur)) {
        if (!inside(prev)) out.push(cross(prev, cur));
        out.push(cur);
      } else if (inside(prev)) out.push(cross(prev, cur));
      prev = cur;
    }
  }
  const r = out.map((p) => [+p[0].toFixed(4), +p[1].toFixed(4)]);
  if (r.length >= 3) r.push(r[0]);
  return r.length >= 4 ? r : null;
}

function clipLand(gj, box) {
  const polys = [];
  for (const f of gj.features) {
    const g = f.geometry;
    const list = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
    for (const poly of list) {
      const rings = poly.map((ring) => clipRing(ring, box)).filter(Boolean);
      if (rings.length) polys.push(rings);
    }
  }
  return { type: 'Feature', properties: {}, geometry: { type: 'MultiPolygon', coordinates: polys } };
}

const noScriptClose = (txt) => txt.replace(/<\/script/gi, '<\\/script');

export async function buildSummaryHtml(app, { pdf = false } = {}) {
  const S = app.S, sv = S.survey, disp = S.config.display, fmt = S.config.settings.latlon_format;
  const [leafletCss, leafletJs, appCss, topo] = await Promise.all([
    fetch('/static/vendor/leaflet/leaflet.css').then((r) => r.text()),
    fetch('/static/vendor/leaflet/leaflet.js').then((r) => r.text()),
    fetch('/static/css/app.css').then((r) => r.text()),
    fetch('/static/vendor/land-10m.json').then((r) => r.json()),
  ]);
  const when = (iso) => { const t = iso && timeParts(iso, app.clock()); return t ? `${t.date} ${t.time} ${t.abbr}` : ''; };

  // ---- map data
  const popup = (tab, r) => {        // the same essentials as the app's popups (no live distance here)
    const rows = app.map.popupFields(tab, r).filter(([, v]) => v).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('');
    return `<b>${esc(app.map.popupHeading(tab, r))}</b><table class="pop">${rows}</table>`;
  };
  const rad = +disp.marker_radius || 8;
  const items = (tab) => (S.tables[tab]?.rows || []).filter((r) => r.Map !== '0').map((r) => {
    const pos = app.map.rowPos(tab, r);
    if (!pos) return null;
    const color = app.map.markerColor(tab, r);
    const shape = tab === 'marks' && r.Shape ? r.Shape : disp[`${tab}_marker_shape`] || 'Diamond';
    return { lat: pos[0], lon: pos[1], svg: shapeSvg(shape, color, rad), size: rad * 2 + 4, color,
      kind: tab === 'sightings' ? (r.Species || '') : (r.EventType || ''),
      label: app.map.label(tab, r), popup: popup(tab, r), old: false,
      ves: tab === 'sightings' && r.Lat && r.SigLat && (r.Lat !== r.SigLat || r.Lon !== r.SigLon) ? [+r.Lat, +r.Lon] : null };
  }).filter(Boolean);
  const data = {
    // [lat, lon, on effort?, break before this point?]; ERROR stretches are left out
    track: (() => {
      const st = trackStates(S.track, S.tables.effort.rows), out = [];
      let prev = null, prevSt = null;
      S.track.forEach((p, i) => {
        if (isNaN(+p.Lat)) return;
        if (st[i] === 'ERROR') { prev = p; prevSt = 'ERROR'; return; }
        const brk = !prev || prevSt === 'ERROR' || isTrackBreak(prev, p, S.config.settings);
        out.push([+p.Lat, +p.Lon, st[i] === 'ON' ? 1 : 0, brk ? 1 : 0]);
        prev = p; prevSt = st[i];
      });
      return out;
    })(),
    sightings: items('sightings'), events: items('events'),          // marks belong to no survey: left out
    style: { on: disp.track_on_effort_color, off: disp.track_off_effort_color, width: +disp.track_width || 3,
      offWidth: +disp.track_off_width || 1.5,
      onDash: dashFor(disp.track_on_style || 'solid', +disp.track_width || 3), offDash: dashFor(disp.track_off_style || 'solid', +disp.track_off_width || 1.5),
      showOn: disp.show_track_on !== '0', showOff: disp.show_track_off !== '0', lines: disp.sighting_lines !== '0',
      labelSize: +disp.label_size || 12 },
    online: ONLINE,
    pdf,
  };
  // the PDF's legend: one entry per point symbol, named by its species / event type when the
  // symbol stands for just one (colors by species), else "Sightings" / "Events"
  const legend = [];
  for (const [tab, title] of [['sightings', 'Sightings'], ['events', 'Events']]) {
    const by = new Map();
    for (const m of data[tab]) {
      const g = by.get(m.svg) || { svg: m.svg, kinds: new Set(), n: 0 };
      g.kinds.add(m.kind || `(no ${tab === 'sightings' ? 'species' : 'type'})`); g.n += 1; by.set(m.svg, g);
    }
    const groups = [...by.values()].map((g) => ({ svg: g.svg, n: g.n,
      label: g.kinds.size === 1 ? [...g.kinds][0] : (by.size === 1 ? title : [...g.kinds].sort().join(', ')) }))
      .sort((a, b) => a.label.localeCompare(b.label));
    if (groups.length) legend.push({ title, groups });
  }
  // survey extent (with a generous margin) for the coastline clip and the initial view
  const pts = [...data.track.map((p) => [p[0], p[1]]), ...data.sightings.map((x) => [x.lat, x.lon]),
    ...data.events.map((x) => [x.lat, x.lon])];
  if (!pts.length && S.vessel?.lat != null) pts.push([S.vessel.lat, S.vessel.lon]);
  let box = [-180, -85, 180, 85];
  if (pts.length) {
    const lats = pts.map((p) => p[0]), lons = pts.map((p) => p[1]);
    const s = Math.min(...lats), n = Math.max(...lats), w = Math.min(...lons), e = Math.max(...lons);
    const pad = Math.max(1.5, (n - s) * 1.5, (e - w) * 1.5);
    box = [w - pad, Math.max(-85, s - pad), e + pad, Math.min(85, n + pad)];
    data.bounds = [[s, w], [n, e]];
  }
  data.land = clipLand(topojson.feature(topo, topo.objects.land), box);

  // ---- summary content (as shown in the app, without its buttons)
  const pane = document.querySelector('#report-summary').cloneNode(true);
  pane.querySelectorAll('.no-print, button').forEach((n) => n.remove());
  pane.querySelectorAll('.print-only').forEach((n) => n.remove());
  pane.querySelectorAll('.card.live').forEach((n) => n.classList.remove('live'));
  pane.querySelectorAll('.card-l').forEach((n) => { n.textContent = n.textContent.replace(/^● /, ''); });
  pane.querySelectorAll('p.hint').forEach((n) => {
    n.textContent = n.textContent.replace(/On effort now — counters marked ● are running\. /, '');
  });
  const gen = timeParts(new Date(), app.clock());
  // the map goes at the top, right under the survey title; the rest keeps the Summary tab's order
  const head = pane.querySelector('.summary-head');
  const mapDiv = document.createElement('div');
  mapDiv.id = 'map';
  if (head) head.after(mapDiv); else pane.prepend(mapDiv);
  if (pdf) mapDiv.insertAdjacentHTML('afterend', '<div id="legend-slot"></div>');

  const script = `
(function () {
  var D = ${JSON.stringify(data)};
  var map = L.map('map', { zoomSnap: D.pdf ? 0.25 : 0.5, worldCopyJump: true, zoomControl: !D.pdf });
  map.attributionControl.setPrefix('Spyhop · <a href="https://leafletjs.com">Leaflet</a>');
  var coast = L.geoJSON(D.land, { interactive: false, style: { color: '#6b5b3e', weight: 1, fillColor: '#e8dcb5', fillOpacity: 1 } });
  var bases = { 'Coastline (offline)': L.layerGroup([coast]) };
  Object.keys(D.online).forEach(function (k) {
    var o = D.online[k];
    bases[k] = L.tileLayer(o[0], { attribution: o[1], maxNativeZoom: o[2], maxZoom: 19 });
  });
  if (!D.pdf) bases['Coastline (offline)'].addTo(map);
  var track = L.layerGroup(), lines = L.layerGroup();
  var seg = null;
  D.track.forEach(function (p) {
    var on = p[2] === 1;
    if (p[3] === 1) seg = null;
    if (!seg || seg.on !== on) {
      var start = seg ? [seg.last] : [];
      var show = on ? D.style.showOn : D.style.showOff;
      seg = { on: on, last: [p[0], p[1]], line: show ? L.polyline(start.concat([[p[0], p[1]]]), {
        color: on ? D.style.on : D.style.off, weight: on ? D.style.width : D.style.offWidth, dashArray: on ? D.style.onDash : D.style.offDash }).addTo(track) : null };
    } else { if (seg.line) seg.line.addLatLng([p[0], p[1]]); seg.last = [p[0], p[1]]; }
  });
  function markers(list) {
    var g = L.layerGroup();
    list.forEach(function (m) {
      var label = D.pdf ? '' : '<span class="mlabel" style="font-size:' + D.style.labelSize + 'px;left:' + m.size + 'px">' + m.label.replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }) + '</span>';
      var icon = L.divIcon({ className: 'data-marker', iconSize: [m.size, m.size], iconAnchor: [m.size / 2, m.size / 2], html: m.svg + label });
      var mk = L.marker([m.lat, m.lon], { icon: icon, riseOnHover: true, interactive: !D.pdf });
      if (!D.pdf) mk.bindPopup(m.popup, { maxWidth: 360 });
      mk.addTo(g);
      if (m.ves && D.style.lines) L.polyline([m.ves, [m.lat, m.lon]], { color: m.color, weight: 1.5, dashArray: '4 4', interactive: false }).addTo(lines);
    });
    return g;
  }
  var overlays = { 'Track': track, 'Sightings': markers(D.sightings), 'Sighting lines': lines, 'Events': markers(D.events) };
  Object.keys(overlays).forEach(function (k) { overlays[k].addTo(map); });
  L.control.scale({ imperial: false }).addTo(map);
  if (D.pdf) {
    // fitted to the survey itself; Esri Ocean if its tiles load (needs internet), else the coastline
    var fit = function (maxZoom) {
      if (D.bounds) map.fitBounds(D.bounds, { maxZoom: maxZoom, padding: [24, 24] });
      else map.setView([41.8, -70], 6);
    };
    var o = D.online['Esri Ocean (online)'], done = false;
    var useCoast = function () {
      if (done) return; done = true;
      coast.addTo(map); fit(14);
      document.getElementById('basemap-note').textContent = 'Basemap: offline coastline (Natural Earth 1:10m, approximate). Esri Ocean wasn’t reachable.';
      document.documentElement.setAttribute('data-basemap', 'coastline');
    };
    var probe = new Image();
    probe.onload = function () {
      if (done) return; done = true;
      L.tileLayer(o[0], { attribution: o[1], maxNativeZoom: o[2], maxZoom: o[2] }).addTo(map); fit(o[2]);
      document.getElementById('basemap-note').textContent = 'Basemap: Esri Ocean (' + o[1] + ').';
      document.documentElement.setAttribute('data-basemap', 'esri');
    };
    probe.onerror = useCoast;
    setTimeout(useCoast, 4000);
    probe.src = o[0].replace('{z}', '0').replace('{y}', '0').replace('{x}', '0');
  } else {
    L.control.layers(bases, overlays, { collapsed: true }).addTo(map);
    if (D.bounds) map.fitBounds(L.latLngBounds(D.bounds).pad(0.6), { maxZoom: 11, paddingTopLeft: [50, 50], paddingBottomRight: [60, 40] });
    else map.setView([41.8, -70], 6);
  }
})();`;
  const legendHtml = !pdf ? '' : `<div id="map-legend">${legend.map((sec) => `<div class="lg-sec"><b>${esc(sec.title)}</b>${
    sec.groups.map((g) => `<span class="lg-item">${g.svg}<span>${esc(g.label)} (${g.n})</span></span>`).join('')}</div>`).join('')
    || '<span class="hint">No sightings or events to show.</span>'}<div id="basemap-note" class="hint"></div></div>`;

  const title = `${sv.prefix} — survey summary`;
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="Spyhop ${esc(app.S.about?.spyhop || '')}">
<title>${esc(title)}</title>
<style>${leafletCss}</style>
<style>${appCss}</style>
<style>
  html, body { height: auto; overflow: auto; background: #fff; }
  body { max-width: 1100px; margin: 0 auto; padding: 1.2em 1.5em 3em; }
  #map { position: relative; inset: auto; width: 100%; height: 520px; border: 1px solid #cfd6dd; border-radius: 6px; margin: 1em 0 1.5em; background: #b9d3e6; }
  .leaflet-control-layers { font-size: 12px; }
  /* the layers button icon (Leaflet's own is an image file, not embedded) */
  .leaflet-control-layers-toggle { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26 26'%3E%3Cg fill='none' stroke='%23333' stroke-width='1.6' stroke-linejoin='round'%3E%3Cpath d='M13 4 23 9 13 14 3 9Z' fill='%23fff'/%3E%3Cpath d='M3 13l10 5 10-5'/%3E%3Cpath d='M3 17l10 5 10-5'/%3E%3C/g%3E%3C/svg%3E") !important; background-size: 26px 26px; }
  .generated { color: #5d6d7e; font-size: 0.9em; }
  @media print { #map, #map.leaflet-container { display: block !important; height: 420px; page-break-inside: avoid; } #map .leaflet-control-layers, #map .leaflet-control-zoom { display: none !important; } body { padding: 0; } }
${pdf ? `  /* the PDF: the map keeps one size on screen and on paper, so the fit to the survey holds */
  body { max-width: 700px; }
  #map, #map.leaflet-container { width: 700px !important; height: 540px !important; margin-bottom: 0.4em; }
  #map-legend { display: flex; flex-wrap: wrap; gap: 0.3em 1.6em; font-size: 12px; margin: 0 0 1.4em; page-break-inside: avoid; }
  #map-legend .lg-sec { display: flex; flex-wrap: wrap; align-items: center; gap: 0.3em 1em; }
  #map-legend .lg-item { display: inline-flex; align-items: center; gap: 0.35em; }
  #map-legend svg { width: 14px; height: 14px; flex: none; }
  #map-legend #basemap-note { flex-basis: 100%; font-size: 11px; }
  @media print { #map, #map.leaflet-container { width: 700px !important; height: 540px !important; } }` : ''}
</style>
</head>
<body>
<div id="summary">${pdf ? pane.innerHTML.replace('<div id="legend-slot"></div>', legendHtml) : pane.innerHTML}</div>
<p class="generated">Generated by Spyhop ${esc(app.S.about?.spyhop || '')} on ${esc(`${gen.date} ${gen.time} ${gen.abbr}`)}. ${pdf ? 'Not for navigation.' : 'The offline coastline is approximate (Natural Earth 1:10m) — not for navigation. Online layers need an internet connection.'}</p>
<script>${noScriptClose(leafletJs)}</script>
<script>${noScriptClose(script)}</script>
</body>
</html>
`;
}
