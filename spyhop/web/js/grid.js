// Spreadsheet-style editable grid for one data tab.
import { el, fmtCoord, timeParts, api, modal, confirmBox, isModalOpen, isOn, effortInfo } from './util.js';
import { shapeSvg } from './map.js';
import { Resights } from './resights.js';

const PRINTABLE = /^.$/u;
// clock bearings (Ref C): each hour is 30° from the bow
const CLOCK_ITEMS = Array.from({ length: 12 }, (_, i) => i + 1).map((h) => ({ name: String(h),
  extra: `${h} o’clock · ${h * 30 % 360}° ${h === 12 ? '(dead ahead)' : h === 3 ? '(starboard beam)' : h === 6 ? '(astern)' : h === 9 ? '(port beam)' : h < 6 ? 'to starboard' : 'to port'}` }));

export class Grid {
  constructor(app, tab, container) {
    this.app = app;
    this.tab = tab;
    this.spec = app.S.schema.tabs[tab];
    this.cols = this.visibleCols();
    this.container = container;
    this.sel = null;          // {id, key}
    this.editing = null;      // {td, input, col, row, original}
    this.pendingRender = false;
    this.dropdown = null;
    this.wrap = el('div', { class: 'grid-wrap', tabindex: '0' });
    this.container.append(this.wrap);
    this.wrap.addEventListener('keydown', (e) => this.onKey(e));
    this.wrap.addEventListener('mousedown', (e) => this.onMouse(e));
    this.wrap.addEventListener('dblclick', (e) => this.onDbl(e));
  }

  // columns shown: not hidden, and optional ones (e.g. Altitude) only when Settings → General says so;
  // in this computer's order (dragged headers or Columns…), a column not in that order after the
  // column it follows in the schema
  visibleCols() {
    const hide = new Set(this.layout().hidden || []);           // 0.51: hidden with Columns… (still in the data)
    const out = this.orderedCols().filter((c) => !hide.has(c.key));
    return out.length ? out : this.orderedCols();
  }
  // every column that can be shown, in this computer's order, hidden ones (Columns…) included
  orderedCols() {
    const cols = this.spec.columns.filter((c) => !c.hidden && this.app.columnShown(c));
    const order = this.layout().order || [];
    if (!order.length) return cols;
    const out = order.map((k) => cols.find((c) => c.key === k)).filter(Boolean);
    cols.forEach((c, i) => {
      if (out.includes(c)) return;
      const before = cols.slice(0, i).reverse().find((x) => out.includes(x));
      out.splice(before ? out.indexOf(before) + 1 : 0, 0, c);
    });
    return out;
  }
  layout() { return (this.app.S.config.settings.column_layout || {})[this.tab] || {}; }
  widthOf(c) { return +(this.layout().widths || {})[c.key] || 0; }
  layoutSig() { return JSON.stringify([this.visibleCols().map((c) => c.key), this.layout().widths || {}]); }
  refreshColumns() {
    if (this.layoutSig() === this._sig) return;
    this.cols = this.visibleCols();
    this.render();
  }

  // save this table's column order and widths (spyhop-local.json: this computer only)
  async saveLayout(lay) {
    const all = { ...(this.app.S.config.settings.column_layout || {}) };
    if (lay) all[this.tab] = lay; else delete all[this.tab];
    this.app.S.config.settings.column_layout = all;
    this.cols = this.visibleCols();
    this.render();
    await this.app.saveColumnLayout(all);
  }

  moveColumn(key, toIndex) {
    const keys = this.cols.map((c) => c.key);
    const from = keys.indexOf(key);
    if (from < 0) return;
    keys.splice(from, 1);
    toIndex = Math.max(0, Math.min(keys.length, toIndex));
    // hidden columns (0.51) keep their places in the full order: put the column before the shown one it lands on
    const full = this.orderedCols().map((c) => c.key).filter((k) => k !== key);
    const at = toIndex < keys.length ? full.indexOf(keys[toIndex]) : full.length;
    full.splice(at, 0, key);
    return this.saveLayout({ ...this.layout(), order: full });
  }

  setWidth(key, w) {
    const widths = { ...(this.layout().widths || {}) };
    if (w) widths[key] = Math.round(Math.max(30, Math.min(800, w))); else delete widths[key];
    return this.saveLayout({ ...this.layout(), widths });
  }

  // drag a header's right edge to resize it, or the header itself to move the column
  wireHeader(th, c) {
    const grip = el('span', { class: 'col-grip', title: 'Drag to resize · double-click for the default width' });
    th.append(grip);
    grip.addEventListener('mousedown', (e) => {
      e.preventDefault(); e.stopPropagation();
      const x0 = e.clientX, w0 = th.getBoundingClientRect().width;
      const set = (w) => { const v = `${Math.round(Math.max(30, Math.min(800, w)))}px`; Object.assign(th.style, { width: v, minWidth: v, maxWidth: v }); };
      const mv = (ev) => set(w0 + ev.clientX - x0);
      const up = (ev) => {
        document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up);
        document.body.classList.remove('col-resizing');
        if (Math.abs(ev.clientX - x0) > 2) this.setWidth(c.key, w0 + ev.clientX - x0);
      };
      document.body.classList.add('col-resizing');
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    });
    grip.addEventListener('dblclick', (e) => { e.stopPropagation(); this.setWidth(c.key, 0); });
    th.draggable = true;
    th.addEventListener('dragstart', (e) => {
      if (document.body.classList.contains('col-resizing')) { e.preventDefault(); return; }
      e.dataTransfer.setData('text/x-spyhop-col', c.key); e.dataTransfer.effectAllowed = 'move';
      th.classList.add('dragging');
    });
    th.addEventListener('dragend', () => { th.classList.remove('dragging'); this.wrap.querySelectorAll('.drop-before,.drop-after').forEach((n) => n.classList.remove('drop-before', 'drop-after')); });
    th.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes('text/x-spyhop-col')) return;
      e.preventDefault();
      const r = th.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
      this.wrap.querySelectorAll('.drop-before,.drop-after').forEach((n) => n.classList.remove('drop-before', 'drop-after'));
      th.classList.add(after ? 'drop-after' : 'drop-before');
    });
    th.addEventListener('drop', (e) => {
      const key = e.dataTransfer.getData('text/x-spyhop-col');
      if (!key || key === c.key) return;
      e.preventDefault();
      const r = th.getBoundingClientRect(), after = e.clientX > r.left + r.width / 2;
      const keys = this.cols.map((x) => x.key).filter((k) => k !== key);
      this.moveColumn(key, keys.indexOf(c.key) + (after ? 1 : 0));
    });
  }

  // Sightings row colors (Settings → General → Tables): none | alternate | resights | groups
  rowTint(r, i, rs) {
    if (this.tab !== 'sightings') return '';
    const mode = this.app.S.config.display.sightings_row_colors || 'resights';
    if (mode === 'alternate') return i % 2 ? 'tint-alt' : '';
    if (mode === 'resights') return rs?.isResight(r) ? 'resight-tint' : '';
    if (mode === 'groups') {
      const g = this._groupTint?.get(rs.original(r).RowID);
      return g === undefined ? '' : `tint-g${g}`;
    }
    return '';
  }

  get rows() { return this.app.S.tables[this.tab].rows; }
  // rows in the order shown: Sightings can nest each sighting's resights under it (Settings → General)
  shownRows() {
    if (this.tab !== 'sightings') return { rows: this.rows, rs: null };
    const rs = new Resights(this.rows);
    return { rows: this.app.S.config.display.resight_order === 'nested' ? rs.nested() : this.rows, rs };
  }
  row(id) { return this.rows.find((r) => r.RowID === id); }

  // ---------------------------------------------------------------- display
  listInfo(name) {
    const S = this.app.S;
    // Unit: the units, then one reticles-<name> for each entry of the reticles list (0.37)
    if (name === 'distunit') {
      const UNITS = { m: 'meters', km: 'kilometers', nm: 'nautical miles', mi: 'statute miles', yd: 'yards' };
      const ret = (r) => {
        const m = (S.schema.reticle?.methods || {})[r.method] || r.method;
        return r.method === 'binoculars' ? `${m}, ${r.deg_per_division}° per division` : r.method === 'marks' ? `${m}, ${r.deg_per_division}° between marks` : m;
      };
      return [...S.schema.fixed_lists.distunit.map((n) => ({ name: n, extra: UNITS[n] || '' })),
        ...(S.config.lists.reticles || []).map((r) => ({ name: `reticles-${r.name}`, extra: ret(r) }))];
    }
    if (name === 'effort') {          // Start and End are set by Start/End survey, ERROR by Error check → Fix
      return (S.config.lists.effort || []).filter((r) => !['Start', 'End', 'ERROR'].includes(r.name))
        .map((r) => ({ name: r.name, extra: `${r.status === 'on' ? 'on' : 'off'} effort${r.definition ? ': ' + r.definition : ''}`, color: r.color }));
    }
    if (S.schema.fixed_lists[name]) return S.schema.fixed_lists[name].map((n) => ({ name: n, color: name === 'colors' ? n : undefined }));
    return (S.config.lists[name] || []).map((r) => ({
      name: r.name, code: r.species_code || r.behavior_code || r.event_code || '', extra: r.full_name || '', color: r.color, definition: r.definition || '' }));
  }

  display(col, v) {
    const fmt = this.app.S.config.settings.latlon_format;
    switch (col.type) {
      case 'datetime': { const p = timeParts(v, this.app.clock()); return p ? `${p.time} ${p.abbr}` : v; }
      case 'lat': return fmtCoord(v, true, fmt);
      case 'lon': return fmtCoord(v, false, fmt);
      case 'bool': return v === '1' ? '☑' : '☐';
      default: return v ?? '';
    }
  }

  editText(col, v) {
    const fmt = this.app.S.config.settings.latlon_format;
    if (col.type === 'datetime') { const p = timeParts(v, this.app.clock()); return p ? `${p.date} ${p.time}` : v; }
    if (col.type === 'lat') return fmtCoord(v, true, fmt);
    if (col.type === 'lon') return fmtCoord(v, false, fmt);
    return v ?? '';
  }

  render() {
    if (this.editing) { this.pendingRender = true; return; }
    this.pendingRender = false;
    const scroll = [this.wrap.scrollLeft, this.wrap.scrollTop];
    const colors = {};
    for (const s of this.app.S.config.lists.species || []) colors[s.name] = s.color;
    const evColors = {};
    for (const s of this.app.S.config.lists.event_types || []) evColors[s.name] = s.color;

    this._sig = this.layoutSig();
    const thead = el('thead', {}, el('tr', {}, el('th', { class: 'rownum' }, '#'),
      this.cols.map((c) => {
        const w = this.widthOf(c);
        const th = el('th', {
          'data-key': c.key, title: `${c.key}${c.auto || c.readonly ? ' (filled in automatically)' : ''} · drag to move, drag the edge to resize`,
          style: w ? { width: `${w}px`, minWidth: `${w}px`, maxWidth: `${w}px` } : c.width ? { minWidth: `${c.width}px` } : null }, c.label);
        this.wireHeader(th, c);
        return th;
      })));
    const tbody = el('tbody');
    const { rows, rs } = this.shownRows();
    const nested = rows !== this.rows;
    if (rs) {          // a tint for each sighting that has resights, in turn (group resights)
      this._groupTint = new Map();
      let n = 0;
      for (const g of rs.groups()) if (g.length > 1) this._groupTint.set(g[0].RowID, n++ % 6);
    }
    const qc = this.app.qcCells?.(this.tab);      // 0.51: Error check → Highlight in the tables
    const LV = { error: 'Error', warning: 'Warning', info: 'Note' };
    const mark = (td, hit) => { td.classList.add(`qc-hl`, `qc-hl-${hit.level}`); td.title = hit.msgs.map((m) => `${LV[hit.level]}: ${m}`).join('\n'); };
    rows.forEach((r, i) => {
      const re = rs?.isResight(r);
      const cls = [this.sel?.id === r.RowID ? 'selrow' : '', re ? 'resight' : '', re && nested ? 'nested' : '', this.rowTint(r, i, rs)].filter(Boolean).join(' ');
      const tr = el('tr', { 'data-id': r.RowID, class: cls || null });
      const num = el('td', { class: 'rownum', title: 'Select row' }, i + 1);
      const rowHit = qc?.get(`${r.RowID}|#`);
      if (rowHit) mark(num, rowHit);
      tr.append(num);
      for (const c of this.cols) {
        const v = r[c.key] ?? '';
        const td = el('td', { 'data-key': c.key, class: `t-${c.type}${c.auto || c.readonly ? ' auto' : ''}` });
        if (c.key === 'DateTime' && v) { const p = timeParts(v, this.app.clock()); td.title = p ? `${p.date} ${p.time} ${p.abbr}` : v; }
        if (c.list === 'species' && v) {
          td.append(el('span', { class: 'swatch', style: { background: colors[v] || 'transparent' } }), this.display(c, v));
        } else if (c.list === 'event_types' && v) {
          td.append(el('span', { class: 'swatch', style: { background: evColors[v] || 'transparent' } }), this.display(c, v));
        } else if (c.list === 'colors' && v) {
          td.append(el('span', { class: 'swatch', style: { background: v } }), v);
        } else if (c.list === 'shapes' && v) {
          td.append(el('span', { class: 'shape-icon', html: shapeSvg(v, r.Color || 'gray', 6) }), v);
        } else if (c.key === 'ResightOf' && v) {
          td.textContent = `↳ ${v}`;
          if (!re) { td.classList.add('dangling'); td.title = `There is no sighting ${v}: this row is counted as a sighting of its own`; }
        } else if (c.key === 'Effort' && v) {
          td.append(el('span', { class: `pill ${isOn(v) ? 'on' : v === 'ERROR' ? 'err' : 'off'}`, style: effortInfo(v).color ? { background: effortInfo(v).color, color: '#fff' } : null }, v));
        } else {
          td.textContent = this.display(c, v);
        }
        const hit = qc?.get(`${r.RowID}|${c.key}`);
        if (hit) mark(td, hit);
        if (this.sel && this.sel.id === r.RowID && this.sel.key === c.key) td.classList.add('sel');
        tr.append(td);
      }
      tbody.append(tr);
    });
    const table = el('table', { class: 'grid' }, thead, tbody);
    this.wrap.replaceChildren(table);
    if (!this.rows.length) {
      const none = !this.app.S.survey && this.tab !== 'marks';
      this.wrap.append(el('div', { class: 'empty' }, none
        ? 'No survey open — start a new survey or open one in the Survey tab.'
        : `No ${this.spec.title.toLowerCase()} yet. Use “Add row” or a keyboard shortcut.`));
    }
    [this.wrap.scrollLeft, this.wrap.scrollTop] = scroll;
    document.getElementById(`showcols-${this.tab}`)?.classList.toggle('hidden', !(this.layout().hidden || []).length);
  }

  td(id, key) {
    return this.wrap.querySelector(`tr[data-id="${CSS.escape(id)}"] td[data-key="${CSS.escape(key)}"]`);
  }

  select(id, key, { scroll = true, focus = true, center = false } = {}) {
    if (!id) return;
    key = key || this.sel?.key || this.cols[0].key;
    this.sel = { id, key };
    this.wrap.querySelectorAll('.sel').forEach((n) => n.classList.remove('sel'));
    this.wrap.querySelectorAll('.selrow').forEach((n) => n.classList.remove('selrow'));
    const td = this.td(id, key);
    if (td) {
      td.classList.add('sel');
      td.parentElement.classList.add('selrow');
      if (scroll) this.scrollTo(td, center);
    }
    if (focus && !this.editing) this.wrap.focus({ preventScroll: true });
    this.app.onRowSelected(this.tab, id);
    this.app.showHelp(this.tab, key);
  }

  // scroll the table (only the table: scrollIntoView would also scroll the panes around it) to show a cell
  scrollTo(td, center = false) {
    const w = this.wrap, r = td.getBoundingClientRect(), b = w.getBoundingClientRect();
    const head = w.querySelector('thead')?.getBoundingClientRect().height || 0;
    const top = b.top + head, bottom = b.top + w.clientHeight;
    if (center && (r.top < top || r.bottom > bottom)) w.scrollTop += r.top - (top + bottom) / 2 + r.height / 2;
    else if (r.top < top) w.scrollTop -= top - r.top;
    else if (r.bottom > bottom) w.scrollTop += r.bottom - bottom;
    const left = b.left + (w.querySelector('td.rownum')?.getBoundingClientRect().width || 0), right = b.left + w.clientWidth;
    if (r.left < left) w.scrollLeft -= left - r.left;
    else if (r.right > right) w.scrollLeft += Math.min(r.right - right, r.left - left);
  }

  firstEmptyEditable(row) {
    const c = this.cols.find((c) => !c.auto && !c.skip && c.type !== 'seq' && c.type !== 'bool' && !row[c.key]);
    return (c || this.cols.find((c) => !c.auto) || this.cols[0]).key;
  }

  move(dRow, dCol) {
    const rows = this.shownRows().rows;
    if (!rows.length) return;
    if (!this.sel || !this.row(this.sel.id)) { this.select(rows.at(-1).RowID, this.cols[0].key); return; }
    let ri = rows.findIndex((r) => r.RowID === this.sel.id);
    let ci = this.cols.findIndex((c) => c.key === this.sel.key);
    ri = Math.max(0, Math.min(rows.length - 1, ri + dRow));
    ci = Math.max(0, Math.min(this.cols.length - 1, ci + dCol));
    this.select(rows[ri].RowID, this.cols[ci].key);
  }

  // ---------------------------------------------------------------- events
  onMouse(e) {
    const td = e.target.closest('td');
    if (!td || this.editing?.td === td) return;
    if (this.editing) this.commit();
    const tr = td.parentElement;
    const id = tr.dataset.id;
    if (td.classList.contains('rownum')) { this.select(id, this.sel?.key); return; }
    const key = td.dataset.key;
    this.select(id, key);
    const col = this.cols.find((c) => c.key === key);
    if (col.type === 'bool') { e.preventDefault(); this.toggleBool(id, col); }
  }

  onDbl(e) {
    const td = e.target.closest('td');
    if (!td || td.classList.contains('rownum')) return;
    const col = this.cols.find((c) => c.key === td.dataset.key);
    if (col && col.type !== 'bool') this.startEdit();
  }

  onKey(e) {
    if (this.editing || isModalOpen() || this.multiOpen) return;   // editor/dialog handles its own keys
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key;
    const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (moves[k]) { e.preventDefault(); this.move(...moves[k]); return; }
    if (k === 'Tab') { e.preventDefault(); this.move(0, e.shiftKey ? -1 : 1); return; }
    if (k === 'Home') { e.preventDefault(); this.move(0, -999); return; }
    if (k === 'End') { e.preventDefault(); this.move(0, 999); return; }
    if (!this.sel) return;
    const col = this.cols.find((c) => c.key === this.sel.key);
    if (k === 'Enter' || k === 'F2') {
      e.preventDefault();
      if (col.type === 'bool') this.toggleBool(this.sel.id, col); else this.startEdit();
      return;
    }
    if (k === ' ' && col.type === 'bool') { e.preventDefault(); this.toggleBool(this.sel.id, col); return; }
    if (k === 'Delete' || k === 'Backspace') {
      e.preventDefault();
      if (col.type === 'seq' || col.readonly) return;
      this.save(this.sel.id, col, '');
      return;
    }
    if (PRINTABLE.test(k) && col.type !== 'bool') {
      e.preventDefault();
      this.startEdit(k);
    }
  }

  // ---------------------------------------------------------------- editing
  async toggleBool(id, col) {
    const r = this.row(id);
    await this.save(id, col, r[col.key] === '1' ? '0' : '1');
  }

  startEdit(initial) {
    if (!this.sel) return;
    const r = this.row(this.sel.id);
    const col = this.cols.find((c) => c.key === this.sel.key);
    if (!r || !col) return;
    if (col.readonly) { this.app.toastReadonly?.(col); return; }
    if (col.type === 'multi') { this.editMulti(r, col, initial); return; }
    const td = this.td(r.RowID, col.key);
    const original = this.editText(col, r[col.key]);
    const input = el('input', { type: 'text', class: 'cell-editor', spellcheck: 'false', autocomplete: 'off' });
    input.value = initial !== undefined ? initial : original;
    td.replaceChildren(input);
    td.classList.add('editing');
    this.editing = { td, input, col, row: r, original };
    input.focus();
    if (initial === undefined) input.select();
    if (col.type === 'choice') this.openDropdown(col, input.value, initial === undefined);
    // a clock bearing (Ref C): pick 1–12 o'clock from a list (or type it)
    else if ((this.tab === 'sightings' && col.key === 'Bearing' && r.BrgRef === 'C')
      || (this.tab === 'effort' && (col.key === 'GlareStart' || col.key === 'GlareEnd') && r.GlareRef === 'C')) this.openDropdown(col, input.value, initial === undefined, CLOCK_ITEMS);
    input.addEventListener('keydown', (e) => this.onEditKey(e));
    input.addEventListener('input', () => { if (this.dropdown) this.filterDropdown(input.value); });
    input.addEventListener('blur', () => setTimeout(() => {
      if (this.editing?.input === input && document.activeElement !== input) this.commit();
    }, 120));
  }

  onEditKey(e) {
    const ed = this.editing;
    if (!ed) return;
    e.stopPropagation();
    const dd = this.dropdown;
    if (e.key === 'Escape') { e.preventDefault(); this.cancel(); return; }
    if (dd && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      this.highlight(dd.hi + (e.key === 'ArrowDown' ? 1 : -1));
      return;
    }
    if (dd && (e.key === 'PageDown' || e.key === 'PageUp')) {
      e.preventDefault();
      this.highlight(dd.hi + (e.key === 'PageDown' ? 8 : -8));
      return;
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      let value = ed.input.value;
      if (dd && dd.hi >= 0 && dd.items[dd.hi]) value = dd.items[dd.hi].name;
      const after = e.key === 'Tab' ? [0, e.shiftKey ? -1 : 1] : null;
      this.commit(value, after);
      return;
    }
    if (!dd && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      this.commit(undefined, [e.key === 'ArrowDown' ? 1 : -1, 0]);
    }
    if (e.ctrlKey || e.metaKey) {
      // allow app shortcuts while editing: commit first
      if (e.shiftKey || /^(Page|Digit)/.test(e.code)) this.commit();
    }
  }

  openDropdown(col, text, showAll, list = null) {
    this.closeDropdown();
    const items = list || this.listInfo(col.list);
    const box = el('div', { class: 'dropdown' });
    box.addEventListener('mousedown', (e) => {
      e.preventDefault();
      const li = e.target.closest('.dd-item');
      if (li) this.commit(li.dataset.name);
    });
    // one highlight only: the mouse moves it (a pointer that was already over the list when it opened
    // by keyboard does nothing until it moves)
    box.addEventListener('mousemove', (e) => {
      const li = e.target.closest('.dd-item');
      if (li && this.dropdown && +li.dataset.i !== this.dropdown.hi) this.highlight(+li.dataset.i, false);
    });
    document.body.append(box);
    this.dropdown = { box, all: items, items: [], hi: -1 };
    this.filterDropdown(showAll ? '' : text, showAll ? text : null);
    this.positionDropdown();
  }

  positionDropdown() {
    if (!this.dropdown || !this.editing) return;
    const r = this.editing.td.getBoundingClientRect();
    const box = this.dropdown.box;
    box.style.minWidth = `${Math.max(r.width, 180)}px`;
    box.style.left = `${Math.min(r.left, window.innerWidth - 260)}px`;
    const below = window.innerHeight - r.bottom;
    if (below < 200 && r.top > below) {
      box.style.top = ''; box.style.bottom = `${window.innerHeight - r.top}px`;
      box.style.maxHeight = `${Math.min(320, r.top - 8)}px`;
    } else {
      box.style.bottom = ''; box.style.top = `${r.bottom}px`;
      box.style.maxHeight = `${Math.min(320, below - 8)}px`;
    }
  }

  filterDropdown(text, current = null) {
    const dd = this.dropdown;
    const q = (text || '').trim().toLowerCase();
    let items = dd.all;
    if (q) {
      const score = (it) => {
        const n = it.name.toLowerCase(), c = (it.code || '').toLowerCase(), x = (it.extra || '').toLowerCase();
        if (c && c === q) return 0;
        if (n.startsWith(q)) return 1;
        if (c.startsWith(q)) return 2;
        if (n.split(/[\s/().-]+/).some((w) => w.startsWith(q))) return 3;
        if (n.includes(q) || x.includes(q)) return 4;
        return 99;
      };
      items = items.map((it) => [score(it), it]).filter(([s]) => s < 99)
        .sort((a, b) => a[0] - b[0]).map(([, it]) => it);
    }
    dd.items = items;
    dd.box.replaceChildren(...items.map((it, i) => el('div', { class: 'dd-item', 'data-name': it.name, 'data-i': i },
      it.color ? el('span', { class: 'swatch', style: { background: it.color } }) : null,
      el('span', {}, it.name), it.code ? el('span', { class: 'dd-code' }, it.code) : null,
      it.extra ? el('span', { class: 'dd-code' }, it.extra) : null)));
    if (!items.length) dd.box.append(el('div', { class: 'dd-none' }, 'No match — Enter saves what you typed'));
    let hi = q ? 0 : -1;
    if (current) hi = items.findIndex((it) => it.name === current);
    this.highlight(items.length ? hi : -1);
  }

  highlight(i, scroll = true) {
    const dd = this.dropdown;
    if (!dd) return;
    if (dd.items.length) i = Math.max(0, Math.min(dd.items.length - 1, i)); else i = -1;
    dd.hi = i;
    dd.box.querySelectorAll('.dd-item').forEach((n) => n.classList.toggle('hi', +n.dataset.i === i));
    if (scroll) dd.box.querySelector('.hi')?.scrollIntoView({ block: 'nearest' });
  }

  closeDropdown() {
    if (this.dropdown) { this.dropdown.box.remove(); this.dropdown = null; }
  }

  // What Enter would save right now: the highlighted dropdown choice, else the typed text.
  pendingValue() {
    const ed = this.editing, dd = this.dropdown;
    if (!ed) return undefined;
    if (dd && dd.hi >= 0 && dd.items[dd.hi]) return dd.items[dd.hi].name;
    return ed.input.value;
  }

  cancel() {
    this.closeDropdown();
    const ed = this.editing;
    this.editing = null;
    this.render();
    if (ed) this.select(ed.row.RowID, ed.col.key);
  }

  async commit(value, after) {
    const ed = this.editing;
    if (!ed) return;
    if (value === undefined) value = ed.input.value;
    this.closeDropdown();
    this.editing = null;
    const changed = value.trim() !== String(ed.original).trim();
    if (changed) await this.save(ed.row.RowID, ed.col, value);
    else this.render();
    this.select(ed.row.RowID, ed.col.key);
    if (after) this.move(...after);
  }

  async save(id, col, value) {
    if (col.type === 'seq') {
      const ok = await confirmBox(`Change ${col.label}?`,
        `${col.label} numbers link sightings to photos and other records. Change it to “${value}”?`, 'Change');
      if (!ok) { this.render(); return; }
    }
    try {
      await api(`/api/tab/${this.tab}/edit`, { id, updates: { [col.key]: value } });
    } catch (e) {
      this.render();
    }
  }

  async editMulti(r, col, initial) {
    if (this.multiOpen) return;
    this.multiOpen = true;
    try { await this._editMulti(r, col, initial); } finally { this.multiOpen = false; }
  }

  async _editMulti(r, col, initial) {
    const items = this.listInfo(col.list);
    const current = new Set((r[col.key] || '').split(';').map((s) => s.trim()).filter(Boolean));
    const extra = [...current].filter((v) => !items.some((it) => it.name === v));
    const all = [...items, ...extra.map((n) => ({ name: n, code: 'not in list', definition: 'Not in the list (Settings → Dropdowns).' }))];
    // a single-column list: ↑/↓ move, Space ticks, Enter saves; typing jumps to the next entry starting with that text
    const rows = all.map((it, i) => el('div', { class: 'ms-item', 'data-i': i, role: 'option' },
      el('input', { type: 'checkbox', value: it.name, checked: current.has(it.name), tabindex: '-1' }),
      el('span', {}, it.name), it.code ? el('span', { class: 'dd-code' }, it.code) : null));
    const list = el('div', { class: 'ms-list', tabindex: '0', role: 'listbox', 'aria-multiselectable': 'true' }, rows);
    const def = el('div', { class: 'ms-def' });
    let hi = -1;
    const show = (i, scroll = true) => {
      if (!rows.length) return;
      hi = Math.max(0, Math.min(rows.length - 1, i));
      rows.forEach((n, j) => n.classList.toggle('hi', j === hi));
      if (scroll) rows[hi].scrollIntoView({ block: 'nearest' });
      const it = all[hi];
      def.replaceChildren(el('b', {}, it.name), it.definition ? ` — ${it.definition}` : el('span', { class: 'hint' }, ' — no definition (add one in Settings → Dropdowns)'));
    };
    const toggle = (i) => { const cb = rows[i].querySelector('input'); cb.checked = !cb.checked; };
    let typed = '', typedAt = 0;
    const jump = (ch) => {
      const now = Date.now();
      typed = (now - typedAt < 800 ? typed : '') + ch.toLowerCase();
      typedAt = now;
      // the same letter again (b, b…) cycles through the entries starting with it; letters typed quickly spell a name
      const same = [...typed].every((c) => c === typed[0]);
      const q = same ? typed[0] : typed;
      const starts = (it) => it.name.toLowerCase().startsWith(q) || (it.code || '').toLowerCase().startsWith(q);
      const from = same ? hi + 1 : Math.max(hi, 0);
      for (let k = 0; k < all.length; k++) {
        const j = (from + k) % all.length;
        if (starts(all[j])) { show(j); return; }
      }
    };
    list.addEventListener('keydown', (e) => {
      const page = Math.max(1, Math.floor(list.clientHeight / (rows[0]?.offsetHeight || 20)) - 1);
      const moves = { ArrowDown: 1, ArrowUp: -1, PageDown: page, PageUp: -page };
      if (moves[e.key] !== undefined) { e.preventDefault(); show(hi < 0 ? 0 : hi + moves[e.key]); }
      else if (e.key === 'Home') { e.preventDefault(); show(0); }
      else if (e.key === 'End') { e.preventDefault(); show(rows.length - 1); }
      else if (e.key === ' ') { e.preventDefault(); if (hi < 0) show(0); else toggle(hi); }
      else if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); jump(e.key); }
    });
    list.addEventListener('mousemove', (e) => { const n = e.target.closest('.ms-item'); if (n && +n.dataset.i !== hi) show(+n.dataset.i, false); });
    list.addEventListener('mousedown', (e) => {
      const n = e.target.closest('.ms-item');
      if (!n) return;
      e.preventDefault();               // keep the focus on the list
      list.focus();
      show(+n.dataset.i, false);
      toggle(+n.dataset.i);
    });
    list.addEventListener('click', (e) => { if (e.target.matches('input')) e.preventDefault(); });   // mousedown already toggled it
    const res = await modal({
      title: `${col.label} — row ${this.rows.indexOf(r) + 1}`,
      width: 'min(34em, 94vw)',
      body: el('div', {}, list, def,
        el('p', { class: 'hint' }, 'Tick all that apply: ↑/↓ move, Space ticks, a letter jumps to it, Enter saves.')),
      buttons: [{ label: 'Clear', value: '' }, { label: 'Cancel', value: undefined },
        { label: 'Save', primary: true, value: () => rows.map((b) => b.querySelector('input')).filter((c) => c.checked).map((c) => c.value).join('; ') }],
      onOpen: () => {
        list.focus();
        const first = rows.findIndex((n) => n.querySelector('input').checked);
        show(first >= 0 ? first : 0);
        if (initial && initial.trim()) { hi = -1; jump(initial); }   // the key that opened it jumps to its entry
        return true;
      },
    });
    if (res !== undefined && res !== r[col.key]) await this.save(r.RowID, col, res);
    this.select(r.RowID, col.key);
  }
}
