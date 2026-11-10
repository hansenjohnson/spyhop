// Tools → Resights: for each sighting with resights, the swim speed between resights and the dive times
// (from a resight with a dive behavior to the next resight with the first-surfacing behavior).
import { el, api, fmtDist, fmtDuration, distM, timeParts, toast } from './util.js';
import { Resights } from './resights.js';

const KN = 1.943844, KMH = 3.6;          // m/s → knots, km/h

// the animals' position (SigLat/SigLon, from the bearing and distance), else the platform's
function pos(r) {
  const a = [+r.SigLat, +r.SigLon];
  if (r.SigLat !== '' && r.SigLat != null && Number.isFinite(a[0]) && Number.isFinite(a[1])) return a;
  const b = [+r.Lat, +r.Lon];
  return r.Lat !== '' && r.Lat != null && Number.isFinite(b[0]) && Number.isFinite(b[1]) ? b : null;
}
const behaviors = (r) => String(r.Behaviors || '').split(';').map((s) => s.trim()).filter(Boolean);
// the FieldIDs used (in order, once each; blank if none)
const fieldIds = (rows) => [...new Set(rows.map((r) => String(r.FieldID || '').trim()).filter(Boolean))].join(', ');
const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

// one sighting and its resights (in time order): legs between them, speeds and dives
export function analyse(group, dive, surface) {
  const seen = [...group].filter((r) => r.DateTime && !isNaN(new Date(r.DateTime)))
    .sort((a, b) => new Date(a.DateTime) - new Date(b.DateTime));
  const legs = [];
  for (let i = 1; i < seen.length; i++) {
    const a = seen[i - 1], b = seen[i], pa = pos(a), pb = pos(b);
    const dt = (new Date(b.DateTime) - new Date(a.DateTime)) / 1000;
    const d = pa && pb ? distM(pa, pb) : null;
    legs.push({ from: a, to: b, dt, d, speed: d != null && dt > 0 ? d / dt : null });
  }
  const timed = legs.filter((l) => l.speed != null);
  const tDist = timed.reduce((s, l) => s + l.d, 0), tTime = timed.reduce((s, l) => s + l.dt, 0);
  const p0 = pos(seen[0] || {}), p1 = pos(seen.at(-1) || {});
  const span = seen.length > 1 ? (new Date(seen.at(-1).DateTime) - new Date(seen[0].DateTime)) / 1000 : 0;
  // dives: the latest resight with a dive behavior, then the next one with the surfacing behavior
  const dives = [];
  let down = null;
  for (const r of seen) {
    const bs = behaviors(r);
    if (down && bs.includes(surface)) { dives.push({ from: down, to: r, dt: (new Date(r.DateTime) - new Date(down.DateTime)) / 1000 }); down = null; }
    if (bs.some((b) => dive.includes(b))) down = r;
  }
  return {
    first: group[0], seen, legs, dives,
    distance: tDist, time: tTime,
    speed: tTime > 0 ? tDist / tTime : null,                                   // along the resights
    net: p0 && p1 && span > 0 ? distM(p0, p1) / span : null,                   // first → last, straight
    diveMean: mean(dives.map((x) => x.dt)),
  };
}

export class ResightTool {
  constructor(app) { this.app = app; this.open = new Set(); }

  settings() {
    const d = this.app.S.config.display;
    return { dive: String(d.resight_dive_behaviors ?? 'Fluke-up dive|Fluke-down dive').split('|').map((s) => s.trim()).filter(Boolean),
      surface: d.resight_surface_behavior ?? 'First surfacing' };
  }

  results() {
    const { dive, surface } = this.settings();
    const rows = this.app.S.tables.sightings?.rows || [];
    return new Resights(rows).groups().filter((g) => g.length > 1).map((g) => analyse(g, dive, surface));
  }

  render() {
    const pane = document.querySelector('#pane-resights');
    if (!pane) return;
    const app = this.app, S = app.S, unit = app.unit();
    if (!S.survey) { pane.replaceChildren(el('p', { class: 'hint' }, 'No survey open: open one in the Survey tab.')); return; }
    const { dive, surface } = this.settings();
    const beh = (S.config.lists.behaviors || []).map((b) => b.name);
    const fmtT = (iso) => (timeParts(iso, app.clock()) || {}).time || '';
    const spd = (v) => (v == null ? '—' : `${(v * KN).toFixed(1)} kn · ${(v * KMH).toFixed(1)} km/h`);
    const res = this.results();
    const allDives = res.flatMap((r) => r.dives.map((x) => x.dt));
    const sec = (title, ...kids) => el('section', { class: 'settings-sec' }, el('h3', {}, title), ...kids);

    const setup = sec('Dive and surfacing behaviors',
      el('p', { class: 'hint' }, 'A dive time runs from a resight with a dive behavior to the next resight with the first-surfacing behavior (the latest dive, if several come first). The behaviors come from Settings → Dropdowns → Behaviors.'),
      el('div', { class: 'grid2' },
        el('label', { class: 'row' }, 'First surfacing behavior', el('select', { id: 'rs-surface', onchange: (e) => app.saveDisplay({ resight_surface_behavior: e.target.value }) },
          ['', ...beh].map((b) => el('option', { value: b, selected: b === surface }, b || '—'))))),
      el('h4', {}, 'Behaviors that count as a dive'),
      el('div', { class: 'rs-dives', id: 'rs-dives' }, beh.filter((b) => b !== surface).map((b) => el('label', { class: 'check' },
        el('input', { type: 'checkbox', value: b, checked: dive.includes(b), onchange: () => {
          const v = [...pane.querySelectorAll('#rs-dives input:checked')].map((x) => x.value).join('|');
          app.saveDisplay({ resight_dive_behaviors: v });
        } }), el('span', {}, b)))),
      !beh.includes(surface) && surface ? el('p', { class: 'warnbox' }, `“${surface}” isn’t in the behaviors list, so no dive times can be found. `,
        el('button', { id: 'rs-add-surface', onclick: () => this.addSurfacing(surface) }, `Add “${surface}” to the behaviors list`),
        ' or choose another.') : null);

    const head = ['Sighting', 'Species', 'FieldID', 'Resights', 'Time span', 'Distance (along the resights)', 'Average swim speed', 'Net speed (first → last)', 'Dives', 'Mean dive time', ''];
    const body = [];
    for (const r of res) {
      const id = r.first.RowID, open = this.open.has(id);
      body.push(el('tr', { 'data-sighting': r.first.SightNo },
        el('td', {}, r.first.SightNo), el('td', {}, r.first.Species || ''), el('td', { class: 'rs-fieldid' }, fieldIds(r.seen)),
        el('td', { class: 'num' }, r.seen.length - 1),
        el('td', {}, r.seen.length > 1 ? `${fmtT(r.seen[0].DateTime)}–${fmtT(r.seen.at(-1).DateTime)}` : '—'),
        el('td', { class: 'num' }, r.time > 0 ? fmtDist(r.distance, unit) : '—'),
        el('td', { class: 'rs-speed' }, spd(r.speed)), el('td', {}, spd(r.net)),
        el('td', { class: 'num' }, r.dives.length || ''),
        el('td', { class: 'rs-dive' }, r.diveMean == null ? '—' : fmtDuration(r.diveMean)),
        el('td', {}, el('button', { class: 'rs-toggle', onclick: () => { if (open) this.open.delete(id); else this.open.add(id); this.render(); } }, open ? 'Hide resights' : 'Resights…'))));
      if (open) {
        const legRows = r.legs.map((l) => el('tr', {},
          el('td', {}, `${l.from.SightNo} → ${l.to.SightNo}`), el('td', {}, fieldIds([l.from, l.to])), el('td', {}, `${fmtT(l.from.DateTime)} → ${fmtT(l.to.DateTime)}`),
          el('td', {}, fmtDuration(l.dt)), el('td', {}, l.d == null ? 'no position' : fmtDist(l.d, unit)), el('td', {}, spd(l.speed)),
          el('td', {}, behaviors(l.to).join(', '))));
        const diveRows = r.dives.map((x) => el('tr', {}, el('td', {}, `Dive ${x.from.SightNo} → surfacing ${x.to.SightNo}`),
          el('td', {}, `${fmtT(x.from.DateTime)} → ${fmtT(x.to.DateTime)}`), el('td', {}, fmtDuration(x.dt))));
        body.push(el('tr', { class: 'rs-detail' }, el('td', { colspan: head.length },
          el('table', { class: 'summary' }, el('thead', {}, el('tr', {}, ['Sightings', 'FieldID', 'Times', 'Interval', 'Distance', 'Swim speed', 'Behaviors (later one)'].map((h) => el('th', {}, h)))),
            el('tbody', {}, legRows)),
          diveRows.length ? el('table', { class: 'summary' }, el('thead', {}, el('tr', {}, ['Dive', 'Times', 'Dive time'].map((h) => el('th', {}, h)))), el('tbody', {}, diveRows)) : null)));
      }
    }
    pane.replaceChildren(
      el('div', { class: 'summary-head' }, el('h2', {}, 'Resights: swim speed and dive times'),
        el('div', { class: 'summary-actions' },
          el('button', { id: 'rs-csv', disabled: !res.length, onclick: () => this.saveCsv(res) }, 'Save as CSV…'))),
      res.length ? el('div', { class: 'table-scroll' }, el('table', { class: 'summary', id: 'rs-table' },
        el('thead', {}, el('tr', {}, head.map((h) => el('th', {}, h)))), el('tbody', {}, body)))
        : el('p', { class: 'hint' }, 'No sightings with resights yet. Select a sighting in the Sightings tab and use Add resight each time the same animals are seen again.'),
      res.length ? el('p', { class: 'hint', id: 'rs-overall' },
        `${res.length} sighting${res.length === 1 ? '' : 's'} with resights. `,
        allDives.length ? `${allDives.length} dive${allDives.length === 1 ? '' : 's'}, mean ${fmtDuration(mean(allDives))} (${fmtDuration(Math.min(...allDives))}–${fmtDuration(Math.max(...allDives))}). ` : 'No dives found yet. ',
        'Speeds use the animals’ positions (SigLat/SigLon, worked out from the bearing and distance; the platform’s position when there was none), so errors in the distance estimates show up as speed, most of all over short intervals. Average swim speed follows the resights in turn; net speed is the straight line from the first sighting to the last resight.') : null,
      setup);
  }

  // an existing behaviors list (made before 0.32) has no First surfacing: add it with one click
  async addSurfacing(name) {
    const rows = [...(this.app.S.config.lists.behaviors || [])];
    if (rows.some((b) => b.name === name)) return;
    rows.push({ name, behavior_code: name === 'First surfacing' ? 'SU' : '',
      definition: name === 'First surfacing' ? 'The first time the animals are seen at the surface after a dive (the start of a surfacing). With a dive, it gives the dive time in Tools → Resights.' : '' });
    try { await api('/api/config/list', { list: 'behaviors', rows }); toast(`Added “${name}” to the behaviors list`); } catch { /* the server says why */ }
  }

  saveCsv(res) {
    const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const n = (v, k = 1) => (v == null ? '' : (v * k).toFixed(3));
    const lines = [['Sighting', 'Species', 'FieldID', 'Record', 'FromSightNo', 'ToSightNo', 'FromTime', 'ToTime', 'Seconds', 'Meters', 'Knots', 'KmPerHour', 'Behaviors'].join(',')];
    for (const r of res) {
      for (const l of r.legs) lines.push([r.first.SightNo, r.first.Species, fieldIds([l.from, l.to]), 'leg', l.from.SightNo, l.to.SightNo, l.from.DateTime, l.to.DateTime, l.dt, n(l.d), n(l.speed, KN), n(l.speed, KMH), behaviors(l.to).join('; ')].map(q).join(','));
      for (const x of r.dives) lines.push([r.first.SightNo, r.first.Species, fieldIds([x.from, x.to]), 'dive', x.from.SightNo, x.to.SightNo, x.from.DateTime, x.to.DateTime, x.dt, '', '', '', ''].map(q).join(','));
      lines.push([r.first.SightNo, r.first.Species, fieldIds(r.seen), 'sighting', r.seen[0]?.SightNo, r.seen.at(-1)?.SightNo, r.seen[0]?.DateTime, r.seen.at(-1)?.DateTime, r.time, n(r.distance), n(r.speed, KN), n(r.speed, KMH), r.diveMean == null ? '' : `mean dive ${r.diveMean.toFixed(0)} s`].map(q).join(','));
    }
    const sv = this.app.S.survey?.prefix || 'survey';
    const a = el('a', { href: URL.createObjectURL(new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/csv' })), download: `${sv}_resights.csv` });
    document.body.append(a); a.click(); a.remove();
    toast('Saved the resights table', 'info', 2500);
  }
}
