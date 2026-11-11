// Tools → Reports: pick rows of Sightings, Events or Effort and some of their columns, see the
// result as you go, and save it (CSV, HTML, PDF). Reports are saved by name in the current template
// (templates/current/spyhop-config.json; the server's reports.py runs them).
// Run Reports saves several saved reports at once.
import { $, el, api, toast, confirmBox, promptBox, modal } from './util.js';

const TABLES = [['sightings', 'Sightings'], ['events', 'Events'], ['effort', 'Effort']];
const NOUN = { sightings: ['sighting', 'sightings'], events: ['event', 'events'], effort: ['effort row', 'effort rows'] };
const STARTING_COLUMNS = { sightings: ['time', 'position', 'Species', 'Count', 'Notes'], events: ['time', 'position', 'EventType', 'Notes'],
  effort: ['time', 'position', 'Effort', 'SeaState', 'Visibility', 'Notes'] };
const LISTS = { sightings: ['species', 'species_code'], events: ['event_types', 'event_code'] };
const blank = (table = 'sightings') => ({ name: '', table, codes: [], columns: [...STARTING_COLUMNS[table]], on_effort: false, time_from: '', time_to: '', rules: [] });
const same = (a, b) => JSON.stringify(strip(a)) === JSON.stringify(strip(b));
function strip(f) {
  const { name, table, codes, columns, on_effort, time_from, time_to, rules } = f || {};
  return { name, table, codes, columns, on_effort: !!on_effort, time_from: time_from || '', time_to: time_to || '', rules: rules || [] };
}

export class ReportsTool {
  constructor(app) {
    this.app = app;
    this.defs = null;          // {reports, errors, columns, ops, folder, exports, last_folder, pdf}
    this.res = null;           // the last result
    this.counts = [];
    this.seq = 0;
    try {
      const saved = JSON.parse(localStorage.getItem('wsr.report') || localStorage.getItem('wsr.filter') || 'null');
      if (saved?.spec?.table) { this.spec = saved.spec; this.file = saved.file || null; }
    } catch {}
    if (!this.spec) { this.spec = null; this.file = null; }
  }

  async loadDefs(force = false) {
    if (!this.defs || force) {
      try { this.defs = await api('/api/reports'); } catch { return this.defs?.reports || []; }
    }
    return this.defs.reports;
  }

  describe(f) {
    const what = { sightings: 'Sightings', events: 'Events', effort: 'Effort rows' }[f.table];
    const bits = [];
    if (f.codes?.length) bits.push(f.codes.join(', '));
    if (f.on_effort) bits.push('on effort');
    if (f.time_from || f.time_to) bits.push('in a time range');
    if (f.rules?.length) bits.push(`${f.rules.length} more condition${f.rules.length === 1 ? '' : 's'}`);
    return `${what}${bits.length ? `: ${bits.join('; ')}` : ' (all)'}.`;
  }

  // the saved report that's open, if any
  savedOne() { return this.file ? this.defs?.reports.find((f) => f.file === this.file) : null; }
  changed() { const s = this.savedOne(); return !s || !same(s, this.spec); }

  remember() { try { localStorage.setItem('wsr.report', JSON.stringify({ spec: this.spec, file: this.file })); } catch {} }

  set(patch) {
    this.spec = { ...this.spec, ...patch };
    this.remember();
    this.render();
  }

  open(f) {
    this.spec = f ? strip(f) : blank(this.spec?.table);
    this.file = f ? f.file : null;
    this.remember();
    this.render();
  }

  onDefsChanged() {
    this.loadDefs(true).then(() => { if (this.app.shown('reports')) this.render(); });
  }

  onData(tab) {
    if (this.app.shown('reports') && (tab === this.spec?.table || (this.spec?.on_effort && tab === 'effort'))) this.run();
  }

  // ---------------------------------------------------------------- drawing
  async render() {
    const pane = $('#pane-reports');
    if (!pane) return;
    if (!this.defs) {
      pane.replaceChildren(el('p', { class: 'hint' }, 'Loading…'));
      await this.loadDefs();
      if (!this.defs) return;
      if (!this.spec) { const first = this.defs.reports[0]; this.spec = first ? strip(first) : blank(); this.file = first?.file || null; }
    }
    if (!this.spec) this.spec = blank();
    // saved reports are part of the data template, and reports read a finished survey: locked while one
    // is under way (0.40)
    if (this.app.S.survey?.active) {
      const names = (this.defs.reports || []).map((f) => f.name);
      pane.replaceChildren(el('section', { class: 'settings-sec', id: 'reports-locked' }, el('h3', {}, 'Reports'),
        el('p', { class: 'warnbox' }, el('b', {}, 'Reports are ready when the survey ends. '),
          'During a survey they can’t be run or changed: the saved reports are part of the survey’s template, like the drop-down lists. End the survey in the Survey tab to run them.'),
        names.length ? el('p', {}, `Saved reports: ${names.join(', ')}.`) : el('p', { class: 'hint' }, 'No saved reports.')));
      return;
    }
    if (!this.$result) {
      this.$side = el('div', { class: 'flt-side' });
      this.$result = el('div', { class: 'flt-result' });
      this.$top = el('div', { class: 'btnrow flt-top no-print' },
        el('button', { type: 'button', class: 'primary', onclick: () => this.runReports(),
          title: 'Save several saved reports at once, in the formats and folder you choose' }, 'Run Reports…'));
      pane.replaceChildren(this.$top, el('div', { class: 'flt' }, this.$side, this.$result));
    } else if (!pane.contains(this.$result)) {
      pane.replaceChildren(this.$top, el('div', { class: 'flt' }, this.$side, this.$result));
    }
    this.drawSide();
    this.drawResult();
    this.run();
  }

  drawSide() {
    const f = this.spec, cols = this.defs.columns[f.table] || [];
    const chip = (label, on, onclick, title) => el('button', { type: 'button', class: `flt-chip${on ? ' on' : ''}`, onclick, title }, label);
    const saved = this.defs.reports.map((x) => chip(x.file === this.file && this.changed() ? `${x.name} •` : x.name, x.file === this.file,
      () => this.open(x), `${this.describe(x)}${x.file === this.file && this.changed() ? ' Changed, not saved.' : ''}`));
    saved.push(chip('+ New', !this.file, () => this.open(null), 'Start a new report'));

    const tables = el('div', { class: 'seg', role: 'group', 'aria-label': 'Table' }, TABLES.map(([k, l]) => el('button', {
      type: 'button', class: k === f.table ? 'on' : '', 'aria-pressed': String(k === f.table),
      onclick: () => { if (k !== f.table) this.set({ table: k, codes: [], columns: [...STARTING_COLUMNS[k]], rules: [], on_effort: k === 'effort' ? false : f.on_effort }); } }, l)));

    // codes: the ones in this survey (with how many), then any picked that aren't
    let codeSec = null;
    if (LISTS[f.table]) {
      const [list, field] = LISTS[f.table];
      const want = new Set(f.codes.map((c) => c.toUpperCase()));
      const here = this.counts.map((c) => c.code.toUpperCase());
      const toggle = (code) => this.set({ codes: want.has(code.toUpperCase()) ? f.codes.filter((c) => c.toUpperCase() !== code.toUpperCase()) : [...f.codes, code] });
      const chips = [
        ...this.counts.map((c) => chip(el('span', {}, c.code, el('span', { class: 'n' }, ` ${c.n}`)), want.has(c.code.toUpperCase()), () => toggle(c.code), c.name)),
        ...f.codes.filter((c) => !here.includes(c.toUpperCase())).map((c) => chip(el('span', {}, c, el('span', { class: 'n' }, ' 0')), true, () => toggle(c), 'None in this survey yet')),
      ];
      const entries = (this.app.S.config.lists[list] || []).filter((x) => x.name);
      const dl = el('datalist', { id: 'flt-codes' }, entries.map((x) => el('option', { value: x[field] || x.name }, x.name)));
      const add = el('input', { type: 'text', list: 'flt-codes', placeholder: f.table === 'sightings' ? 'Add a species…' : 'Add an event type…', class: 'flt-add',
        onchange: (e) => {
          const v = e.target.value.trim(); if (!v) return;
          const hit = entries.find((x) => (x[field] || '').toUpperCase() === v.toUpperCase() || x.name.toLowerCase() === v.toLowerCase());
          const code = hit ? (hit[field] || hit.name) : v;
          if (!want.has(code.toUpperCase())) this.set({ codes: [...f.codes, code] }); else e.target.value = '';
        } });
      codeSec = el('div', { class: 'flt-sec' },
        el('h4', {}, f.table === 'sightings' ? 'Species' : 'Event types'),
        el('div', { class: 'flt-chips' }, chips.length ? chips : el('span', { class: 'hint' }, `No ${NOUN[f.table][1]} yet.`)),
        el('div', {}, add, dl),
        el('p', { class: 'hint' }, f.codes.length ? el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.set({ codes: [] }); } }, 'Clear (show all)') : `None picked: all ${NOUN[f.table][1]}.`));
    }

    // columns: the chosen ones first, in order (with ▲ ▼), then the rest in table order
    const chosen = f.columns.map((k) => cols.find((c) => c.key === k)).filter(Boolean);
    const rest = cols.filter((c) => !f.columns.includes(c.key));
    const move = (i, d) => { const a = [...f.columns]; const j = i + d; if (j < 0 || j >= a.length) return; [a[i], a[j]] = [a[j], a[i]]; this.set({ columns: a }); };
    const colRow = (c, i) => el('div', { class: `flt-col${i >= 0 ? ' on' : ''}` },
      el('label', {}, el('input', { type: 'checkbox', checked: i >= 0,
        onchange: () => this.set({ columns: i >= 0 ? f.columns.filter((k) => k !== c.key) : [...f.columns, c.key] }) }), ' ', c.label,
        c.computed ? el('span', { class: 'hint' }, c.key === 'position' ? ' (formatted)' : '') : null),
      i >= 0 ? el('span', { class: 'flt-move' },
        el('button', { type: 'button', class: 'icon', title: 'Move up', disabled: i === 0, onclick: () => move(i, -1) }, '▲'),
        el('button', { type: 'button', class: 'icon', title: 'Move down', disabled: i === chosen.length - 1, onclick: () => move(i, 1) }, '▼')) : null);
    const colSec = el('details', { class: 'flt-sec flt-colsec', open: !!this.colsOpen, ontoggle: (e) => { this.colsOpen = e.target.open; } },
      el('summary', {}, el('b', {}, 'Columns'), ` (${chosen.length})`,
        el('span', { class: 'flt-colnames' }, chosen.length ? chosen.map((c) => c.label).join(' · ') : 'none')),
      el('div', { class: 'flt-cols' }, chosen.map((c, i) => colRow(c, i)), rest.length && chosen.length ? el('hr') : null, rest.map((c) => colRow(c, -1))),
      el('p', { class: 'hint help' }, 'Time, Position, Latitude and Longitude use the clock and lat/lon format in Settings → General. Position is the animals’ (SigLat/SigLon) for sightings, or the vessel’s if there is none.'));

    // more conditions
    const tableCols = (this.app.S.schema.tabs[f.table]?.columns || []).filter((c) => !c.hidden && !['RowID', 'Map'].includes(c.key));
    const ops = this.defs.ops;
    const setRule = (i, patch) => { const r = f.rules.map((x, j) => (j === i ? { ...x, ...patch } : x)); this.set({ rules: r }); };
    const rules = f.rules.map((r, i) => el('div', { class: 'flt-rule' },
      el('select', { onchange: (e) => setRule(i, { column: e.target.value }), 'aria-label': 'Column' },
        tableCols.map((c) => el('option', { value: c.key, selected: c.key === r.column }, c.label))),
      el('select', { onchange: (e) => setRule(i, { op: e.target.value }), 'aria-label': 'Condition' },
        Object.entries(ops).map(([k, l]) => el('option', { value: k, selected: k === r.op }, l))),
      ['blank', 'not_blank'].includes(r.op) ? null
        : el('input', { type: 'text', value: r.value, size: 8, 'aria-label': 'Value', onchange: (e) => setRule(i, { value: e.target.value }) }),
      el('button', { type: 'button', class: 'icon', title: 'Remove this condition', onclick: () => this.set({ rules: f.rules.filter((_, j) => j !== i) }) }, '✕')));
    const nMore = (f.on_effort ? 1 : 0) + (f.time_from || f.time_to ? 1 : 0) + f.rules.length;
    const more = el('details', { class: 'flt-sec flt-more', open: this.moreOpen || nMore > 0,
      ontoggle: (e) => { this.moreOpen = e.target.open; } },
      el('summary', {}, el('b', {}, 'More conditions'), nMore ? ` (${nMore})` : ''),
      f.table !== 'effort' ? el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!f.on_effort, onchange: (e) => this.set({ on_effort: e.target.checked }) }),
        ' On effort only (effort was ON at the time)') : null,
      el('div', { class: 'flt-time' },
        el('label', {}, 'From ', el('input', { type: 'datetime-local', value: f.time_from, onchange: (e) => this.set({ time_from: e.target.value }) })),
        el('label', {}, 'to ', el('input', { type: 'datetime-local', value: f.time_to, onchange: (e) => this.set({ time_to: e.target.value }) }))),
      el('p', { class: 'hint help' }, 'Times in the survey clock. Leave blank for the whole survey.'),
      rules,
      el('button', { type: 'button', onclick: () => { this.moreOpen = true; this.set({ rules: [...f.rules, { column: tableCols.find((c) => c.key === 'Notes')?.key || tableCols[0].key, op: 'contains', value: '' }] }); } }, '+ Add a condition'));

    const errs = this.defs.errors || [];
    this.$side.replaceChildren(
      el('div', { class: 'flt-sec' }, el('h4', {}, 'Saved reports'), el('div', { class: 'flt-chips' }, saved)),
      el('div', { class: 'flt-sec' }, el('h4', {}, 'Table'), tables),
      codeSec, colSec, more,
      errs.length ? el('p', { class: 'warn-text' }, `Skipped: ${errs.join('; ')}`) : null);
  }

  drawResult() {
    const f = this.spec, r = this.res, s = this.savedOne();
    const pdf = !!this.defs.pdf, survey = !!this.app.S.survey;
    const title = s ? s.name : (f.name || 'New report');
    const btn = (label, onclick, attrs = {}) => el('button', { type: 'button', onclick, ...attrs }, label);
    const head = el('div', { class: 'summary-head' },
      el('h2', {}, title, s && this.changed() ? el('span', { class: 'hint' }, ' (changed)') : null),
      el('div', { class: 'btnrow no-print' },
        btn('Export CSV…', () => this.export('csv'), { class: 'primary', disabled: !survey, title: 'For R, Excel or a database' }),
        btn('HTML…', () => this.export('html'), { disabled: !survey, title: 'A page with the survey details, the table and its totals' }),
        btn('PDF…', () => this.export('pdf'), { disabled: !survey || !pdf, title: pdf ? 'The same page as a PDF' : 'Needs Google Chrome or Microsoft Edge' })));
    const saveRow = el('div', { class: 'btnrow no-print' },
      s ? btn('Save changes', () => this.save(false), { disabled: !this.changed() }) : null,
      btn(s ? 'Save as new…' : 'Save report…', () => this.save(true)),
      s ? btn('Rename…', () => this.rename()) : null,
      s ? btn('Delete…', () => this.remove(), { class: 'danger-outline' }) : null,
      s && this.changed() ? btn('Undo changes', () => this.open(s)) : null);
    let body;
    if (!survey) body = el('p', { class: 'hint' }, 'Open a survey (in Survey) to see the rows this report picks.');
    else if (!f.columns.length) body = el('p', { class: 'hint' }, 'Tick at least one column.');
    else if (!r || r.table !== f.table) body = el('p', { class: 'hint' }, 'Working…');
    else if (!r.rows.length) body = el('p', { class: 'hint' }, `No ${NOUN[f.table][1]} match.`);
    else {
      const right = (i) => (r.columns[i].align === 'right' ? 'num' : '');
      const nowrap = (i) => (['time', 'date', 'clock', 'position', 'lat', 'lon'].includes(r.columns[i].key) ? ' nowrap' : '');
      body = el('div', { class: 'table-scroll' }, el('table', { class: 'summary report-table flt-table' },
        el('thead', {}, el('tr', {}, r.columns.map((c, i) => el('th', { class: right(i) }, c.label)))),
        el('tbody', {}, r.rows.map((row, n) => el('tr', { title: 'Click to show this row in its table', onclick: () => this.app.selectRow(f.table, r.row_ids[n]) },
          row.map((v, i) => el('td', { class: right(i) + nowrap(i) }, v))))),
        r.totals ? el('tfoot', {}, el('tr', {}, r.totals.map((v, i) => el('td', { class: right(i) }, i === 0 && !v ? `Total (${r.count})` : v)))) : null));
    }
    this.$result.replaceChildren(head, body, saveRow,
      el('p', { class: 'hint' }, survey && r?.rows?.length ? 'Click a row to show it in its table. Number columns get a total. Exports are saved in the exports folder. ' : '',
        'Saved reports are part of the current template, so they travel with it (Settings → Templates).'));
  }

  // ---------------------------------------------------------------- server
  async run() {
    const n = ++this.seq;
    if (!this.app.S.survey || this.app.S.survey.active || !this.spec?.columns.length) { this.counts = []; this.res = null; this.drawResult(); return; }
    let r;
    try { r = await api('/api/reports/run', { spec: this.spec }); } catch { return; }
    if (n !== this.seq) return;           // a newer change is on its way
    const before = JSON.stringify(this.counts);
    this.res = r.result; this.counts = r.counts;
    if (JSON.stringify(this.counts) !== before && this.app.shown('reports')) this.drawSide();
    if (this.app.shown('reports')) this.drawResult();
  }

  async export(format) {
    if (format === 'pdf') toast('Making the PDF (a few seconds)…', 'info', 3000);
    const name = this.savedOne()?.name || this.spec.name || 'report';
    let r;
    try { r = await api('/api/reports/export', { spec: { ...this.spec, name }, format }); } catch { return; }
    const a = el('a', { href: r.url, download: r.name });
    document.body.append(a); a.click(); a.remove();
    toast(`Saved ${r.name} (${r.count} row${r.count === 1 ? '' : 's'}) in the exports folder (a copy is downloading).`, 'info', 6000);
  }

  async save(asNew) {
    const s = this.savedOne();
    let name = s && !asNew ? s.name : await promptBox(asNew && s ? 'Save as a new report' : 'Save this report', 'Name', asNew && s ? `${s.name} (copy)` : (this.spec.name || ''), 'Save');
    if (name === null) return;
    name = name.trim();
    if (!name) { toast('Give the report a name.', 'warn'); return; }
    const clash = this.defs.reports.find((x) => x.name.toLowerCase() === name.toLowerCase() && x.file !== (asNew ? null : s?.file));
    if (clash && !(await confirmBox('Replace the saved report?', `There's already a report called “${clash.name}”. Replace it with this one?`, 'Replace', true))) return;
    let r;
    try { r = await api('/api/reports/save', { spec: { ...this.spec, name }, replace: !asNew && s ? s.file : (clash?.file || null) }); } catch { return; }
    this.file = r.report.file;
    this.spec = strip(r.report);
    this.remember();
    await this.loadDefs(true);
    toast(`Saved “${name}”.`);
    this.render();
  }

  async rename() {
    const s = this.savedOne();
    if (!s) return;
    const name = (await promptBox('Rename the report', 'Name', s.name, 'Rename'))?.trim();
    if (!name || name === s.name) return;
    let r;
    try { r = await api('/api/reports/save', { spec: { ...s, name }, replace: s.file }); } catch { return; }
    this.file = r.report.file;
    this.spec = { ...this.spec, name };
    this.remember();
    await this.loadDefs(true);
    this.render();
  }

  async remove() {
    const s = this.savedOne();
    if (!s || !(await confirmBox('Delete the saved report?', `Delete the saved report “${s.name}”?`, 'Delete', true))) return;
    try { await api('/api/reports/delete', { file: s.file }); } catch { return; }
    this.file = null;
    this.spec = { ...this.spec, name: '' };
    this.remember();
    await this.loadDefs(true);
    this.render();
  }

  // ---------------------------------------------------------------- Run Reports
  // Save several saved reports at once: which ones, in which formats, and where.
  async runReports() {
    await this.loadDefs(true);
    const list = this.defs?.reports || [];
    if (!this.app.S.survey) { toast('Open a survey first (in Survey).', 'warn'); return; }
    if (!list.length) { toast('There are no saved reports yet: make one and press Save report…', 'warn'); return; }
    let last = {};
    try { last = JSON.parse(localStorage.getItem('wsr.runReports') || '{}') || {}; } catch {}
    const pdf = !!this.defs.pdf;
    const known = new Set(list.map((x) => x.file));
    const picked = Array.isArray(last.files) && last.files.some((f) => known.has(f)) ? new Set(last.files) : new Set(known);
    const boxes = {};
    const fmts = {};
    const note = el('p', { class: 'hint' });
    const folderIn = el('input', { type: 'text', value: last.folder || this.defs.last_folder || '', placeholder: 'Full path of a folder', style: { flex: '1', minWidth: '14em' },
      oninput: () => { whereOther.checked = true; update(); } });
    const whereExports = el('input', { type: 'radio', name: 'rr-where', checked: last.where !== 'folder', onchange: () => update() });
    const whereOther = el('input', { type: 'radio', name: 'rr-where', checked: last.where === 'folder', onchange: () => update() });
    const okBtn = () => document.querySelector('.modal-buttons button.primary');
    const update = () => {
      const n = Object.values(boxes).filter((b) => b.checked).length;
      const k = Object.values(fmts).filter((b) => b.checked).length;
      const noFolder = whereOther.checked && !folderIn.value.trim();
      note.textContent = !n ? 'Choose at least one report.' : !k ? 'Choose at least one format.'
        : noFolder ? 'Choose the folder to save them in.' : `${n * k} file${n * k === 1 ? '' : 's'} will be saved.`;
      const b = okBtn(); if (b) b.disabled = !n || !k || noFolder;
    };
    const setAll = (on) => { Object.values(boxes).forEach((b) => { b.checked = on; }); update(); };
    const body = el('div', { class: 'export-choices run-reports' },
      el('h4', {}, 'Reports ', el('span', { class: 'hint' },
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); setAll(true); } }, 'all'), ' · ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); setAll(false); } }, 'none'))),
      ...list.map((x) => {
        boxes[x.file] = el('input', { type: 'checkbox', checked: picked.has(x.file), onchange: update });
        return el('label', { class: 'check' }, boxes[x.file], el('span', {}, el('b', {}, x.name), el('br'), el('span', { class: 'hint' }, this.describe(x))));
      }),
      el('h4', {}, 'Formats'),
      el('div', { class: 'rr-formats' }, [['csv', 'CSV'], ['html', 'HTML'], ['pdf', 'PDF']].map(([k, l]) => {
        fmts[k] = el('input', { type: 'checkbox', checked: (last.formats || ['csv']).includes(k) && (k !== 'pdf' || pdf), disabled: k === 'pdf' && !pdf, onchange: update });
        return el('label', { class: 'check', title: k === 'pdf' && !pdf ? 'Needs Google Chrome or Microsoft Edge' : '' }, fmts[k], ` ${l}`);
      })),
      el('h4', {}, 'Save them in'),
      el('label', { class: 'check' }, whereExports, el('span', {}, 'The exports folder', el('br'), el('span', { class: 'hint' }, this.defs.exports))),
      el('label', { class: 'check' }, whereOther, el('span', { style: { flex: '1' } }, 'This folder:',
        el('span', { class: 'rr-folder' }, folderIn,
          el('button', { type: 'button', onclick: async (e) => {
            e.preventDefault();
            let r; try { r = await api('/api/pick-folder', {}); } catch { return; }
            if (r.path) { folderIn.value = r.path; whereOther.checked = true; update(); }
          } }, 'Choose…')))),
      note);
    const ok = await modal({ title: 'Run Reports', body, width: '36em',
      onOpen: () => { setTimeout(update, 0); return false; },
      buttons: [{ label: 'Cancel', value: false }, { label: 'Save reports', primary: true, value: true }] });
    if (!ok) return;
    const files = list.map((x) => x.file).filter((f) => boxes[f].checked);
    const formats = Object.keys(fmts).filter((k) => fmts[k].checked);
    const where = whereOther.checked ? 'folder' : 'exports';
    const folder = where === 'folder' ? folderIn.value.trim() : '';
    try { localStorage.setItem('wsr.runReports', JSON.stringify({ files, formats, where, folder: folderIn.value.trim() })); } catch {}
    if (formats.includes('pdf')) toast('Making the PDFs (a few seconds each)…', 'info', 4000);
    let r;
    try { r = await api('/api/reports/batch', { files, formats, folder }); } catch { return; }
    this.defs.last_folder = r.folder;
    await modal({ title: 'Reports saved', width: '34em', body: el('div', {},
      el('p', {}, `${r.files.length} file${r.files.length === 1 ? '' : 's'} saved in `, el('b', {}, r.folder), ':'),
      el('ul', { class: 'rr-done' }, r.files.map((x) => el('li', {}, x.name, el('span', { class: 'hint' }, ` · ${x.count} row${x.count === 1 ? '' : 's'}`))))),
      buttons: [{ label: 'Open the folder', value: () => { this.app.open('reportsout'); return true; } }, { label: 'OK', primary: true, value: true }] });
  }
}
