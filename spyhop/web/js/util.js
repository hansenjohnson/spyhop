// Shared helpers: formatting, geodesy, small UI primitives (toasts, modals).

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// Leave out null / undefined / false when adding children, as el() does, so an optional part written
// `x ? el(...) : null` never shows up as the text "null" (it did in the summary and reports).
for (const m of ['append', 'prepend', 'replaceChildren']) {
  for (const proto of [Element.prototype, DocumentFragment.prototype]) {
    const orig = proto[m];
    if (orig.__skipsNull) continue;
    const wrapped = function (...kids) { return orig.apply(this, kids.filter((k) => k !== null && k !== undefined && k !== false)); };
    wrapped.__skipsNull = true;
    proto[m] = wrapped;
  }
}

export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else if (k === 'html') e.innerHTML = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ------------------------------------------------------------------ coords
export function fmtCoord(v, isLat, fmt = 'DDM') {
  if (v === '' || v === null || v === undefined || isNaN(+v)) return '';
  v = +v;
  const hemi = isLat ? (v >= 0 ? 'N' : 'S') : (v >= 0 ? 'E' : 'W');
  let a = Math.abs(v);
  if (fmt === 'DD') return v.toFixed(5);
  let d = Math.floor(a);
  let m = (a - d) * 60;
  if (fmt === 'DMS') {
    let mi = Math.floor(m);
    let s = (m - mi) * 60;
    if (+s.toFixed(1) >= 60) { s = 0; mi += 1; }
    if (mi >= 60) { mi = 0; d += 1; }
    return `${d}°${String(mi).padStart(2, '0')}'${s.toFixed(1).padStart(4, '0')}"${hemi}`;
  }
  if (+m.toFixed(3) >= 60) { m = 0; d += 1; }
  return `${String(d).padStart(isLat ? 2 : 3, '0')}°${m.toFixed(3).padStart(6, '0')}'${hemi}`;
}

export function fmtPos(lat, lon, fmt) {
  if (lat === null || lat === undefined || lat === '') return '—';
  return `${fmtCoord(lat, true, fmt)}  ${fmtCoord(lon, false, fmt)}`;
}

// ------------------------------------------------------------------ time
// Format an ISO timestamp in the survey clock, with the zone abbreviation. The clock is
// 'local' (the computer's), 'UTC', an IANA zone (from the platform's position) or a fixed
// offset such as 'UTC-03:30'.
export function parseOffsetMin(mode) {
  const m = /^UTC([+-])(\d{1,2}):?(\d{2})?$/.exec(String(mode || ''));
  if (!m) return null;
  const v = +m[2] * 60 + +(m[3] || 0);
  return m[1] === '-' ? -v : v;
}
export function timeParts(iso, mode = 'local') {
  const d = iso instanceof Date ? iso : new Date(iso);
  if (!iso || isNaN(d)) return null;
  const opts = { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    second: '2-digit', hourCycle: 'h23', timeZoneName: 'short' };
  const off = parseOffsetMin(mode);
  let when = d, abbr = null;
  if (off !== null) { when = new Date(d.getTime() + off * 60000); opts.timeZone = 'UTC'; abbr = off ? mode : 'UTC'; }
  else if (mode === 'UTC') opts.timeZone = 'UTC';
  else if (mode && mode !== 'local') {
    try { new Intl.DateTimeFormat('en-US', { timeZone: mode }); opts.timeZone = mode; } catch { /* unknown zone: local */ }
  }
  const p = {};
  for (const x of new Intl.DateTimeFormat('en-US', opts).formatToParts(when)) p[x.type] = x.value;
  return { date: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}:${p.second}`, abbr: abbr ?? (p.timeZoneName || (mode === 'UTC' ? 'UTC' : '')) };
}
// minutes ahead of UTC in that clock at that moment
export function clockOffsetMin(date, mode = 'local') {
  const d = date instanceof Date ? date : new Date(date);
  const off = parseOffsetMin(mode);
  if (off !== null) return off;
  if (mode === 'UTC') return 0;
  if (!mode || mode === 'local') return -d.getTimezoneOffset();
  const t = timeParts(d, mode);
  if (!t) return -d.getTimezoneOffset();
  const asUtc = Date.UTC(+t.date.slice(0, 4), +t.date.slice(5, 7) - 1, +t.date.slice(8, 10), +t.time.slice(0, 2), +t.time.slice(3, 5), +t.time.slice(6, 8));
  return Math.round((asUtc - Math.floor(d.getTime() / 1000) * 1000) / 60000);
}
export function fmtDuration(sec) {
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
           : `${m}:${String(s).padStart(2, '0')}`;
}

// ------------------------------------------------------------------ geodesy
const R = 6371008.8;
const rad = (d) => d * Math.PI / 180, deg = (r) => r * 180 / Math.PI;
export function distM(a, b) {
  const p1 = rad(a[0]), p2 = rad(b[0]), dp = p2 - p1, dl = rad(b[1] - a[1]);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
export function bearing(a, b) {
  const p1 = rad(a[0]), p2 = rad(b[0]), dl = rad(b[1] - a[1]);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (deg(Math.atan2(y, x)) + 360) % 360;
}
export function destination(a, brg, d) {
  const dd = d / R, b = rad(brg), p1 = rad(a[0]), l1 = rad(a[1]);
  const p2 = Math.asin(Math.sin(p1) * Math.cos(dd) + Math.cos(p1) * Math.sin(dd) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(dd) * Math.cos(p1), Math.cos(dd) - Math.sin(p1) * Math.sin(p2));
  return [deg(p2), ((deg(l2) + 540) % 360) - 180];
}
export const UNIT_M = { m: 1, km: 1000, nm: 1852, mi: 1609.344, yd: 0.9144 };
export function fmtDist(m, unit = 'nm') {
  const v = m / (UNIT_M[unit] || 1852);
  const dp = v < 10 ? 2 : v < 100 ? 1 : 0;
  return `${v.toFixed(dp)} ${unit}`;
}
export const fmtBrg = (b) => (b === null || b === undefined || isNaN(b)) ? '—' : `${String(Math.round(b) % 360).padStart(3, '0')}°`;

// ------------------------------------------------------------------ toasts
export function toast(text, level = 'info', ms = 4500) {
  const box = $('#toasts');
  const t = el('div', { class: `toast ${level}` }, text);
  t.addEventListener('click', () => t.remove());
  box.append(t);
  if (ms) setTimeout(() => t.remove(), level === 'error' ? ms * 2 : ms);
}

// ------------------------------------------------------------------ modals
let modalOpen = 0;
export const isModalOpen = () => modalOpen > 0;

// closeOnOutside: a click on the dimmed area around the box closes it (for read-only boxes such as plots)
export function modal({ title, body, buttons = [{ label: 'OK', value: true, primary: true }], onOpen, width, closeOnOutside = false }) {
  return new Promise((resolve) => {
    modalOpen++;
    const back = el('div', { class: 'modal-back' });
    const box = el('div', { class: 'modal', role: 'dialog', 'aria-label': title });
    if (width) box.style.width = width;
    const close = (v) => { modalOpen--; back.remove(); document.removeEventListener('keydown', key, true); resolve(v); };
    const btns = buttons.map((b) => el('button', {
      class: b.primary ? 'primary' : (b.danger ? 'danger' : ''),
      onclick: () => close(typeof b.value === 'function' ? b.value() : b.value) }, b.label));
    box.append(el('h3', {}, title), el('div', { class: 'modal-body' }, body), el('div', { class: 'modal-buttons' }, btns));
    back.append(box);
    if (closeOnOutside) {
      // only a press that starts and ends outside the box, so dragging out of it doesn't close it
      let downOutside = false;
      back.addEventListener('pointerdown', (e) => { downOutside = e.target === back; });
      back.addEventListener('click', (e) => { if (downOutside && e.target === back) close(undefined); downOutside = false; });
    }
    document.body.append(back);
    const key = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(undefined); }
      else if (e.key === 'Enter' && !(e.target instanceof HTMLTextAreaElement)) {
        const p = buttons.findIndex((b) => b.primary);
        if (p >= 0) { e.preventDefault(); e.stopPropagation(); btns[p].click(); }
      }
    };
    document.addEventListener('keydown', key, true);
    (onOpen && onOpen(box, close)) || setTimeout(() => (box.querySelector('input,select,textarea') || btns.at(-1))?.focus(), 0);
  });
}

export async function confirmBox(title, text, okLabel = 'OK', danger = false) {
  const r = await modal({ title, body: el('p', { style: { whiteSpace: 'pre-line' } }, text), buttons: [
    { label: 'Cancel', value: false }, { label: okLabel, value: true, primary: true, danger }] });
  return !!r;
}

export async function promptBox(title, label, value = '', okLabel = 'OK') {
  const input = el('input', { type: 'text', value, style: { width: '100%' } });
  const r = await modal({ title, body: el('label', { class: 'stack' }, label, input),
    buttons: [{ label: 'Cancel', value: null }, { label: okLabel, value: () => input.value, primary: true }],
    onOpen: () => { setTimeout(() => { input.focus(); input.select(); }, 0); return true; } });
  return r === undefined ? null : r;
}

// ------------------------------------------------------------------ api
export async function api(path, body, method) {
  const opts = { method: method || (body !== undefined ? 'POST' : 'GET'), headers: {} };
  if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  let r;
  try { r = await fetch(path, opts); }
  catch (e) { toast('Lost connection to Spyhop. Is it still running?', 'error'); throw e; }
  const data = await r.json().catch(() => ({ ok: false, error: `HTTP ${r.status}` }));
  if (!data.ok) { toast(data.error || 'Request failed', 'error'); const err = new Error(data.error); err.handled = true; throw err; }
  (data.warnings || []).forEach((w) => toast(w, 'warn'));
  return data;
}

// A very small Markdown renderer for the changelog: ## headings, - bullets (one level of
// nesting), paragraphs, **bold** and `code`. Text is escaped first, so it's safe.
// GitHub-style heading anchors ("Clock check" → "clock-check"), so links like [x](#clock-check) work in the Guide too
export function slugify(t) {
  return t.toLowerCase().replace(/<[^>]+>/g, '').replace(/[^\p{L}\p{N}\s_-]/gu, '').trim().replace(/\s/g, '-');
}

// A small Markdown renderer for the Guide, the changelog and update notes: headings (# → h3, ## → h4,
// ### → h5, #### → h6, each with a GitHub-style id), paragraphs, nested - / 1. lists, tables, ``` code
// blocks, **bold**, *italic*, `code` and [links](…). docBase: where relative links (other docs) point.
const DOC_BASE = 'https://github.com/hansenjohnson/spyhop/blob/main/docs/';
export function renderMarkdown(md, docBase = DOC_BASE) {
  const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const href = (u) => {
    if (u.startsWith('#') || /^[a-z]+:/i.test(u)) return u;
    try { return new URL(u, docBase).href; } catch { return u; }
  };
  const inline = (t) => {
    const span = document.createElement('span');
    const codes = [];
    let h = esc(t).replace(/`([^`]+)`/g, (m, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
    h = h.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m, txt, u) => {
      const url = href(u.replace(/&amp;/g, '&'));
      return url.startsWith('#') ? `<a href="${url}" data-anchor="${url.slice(1)}">${txt}</a>`
        : `<a href="${url.replace(/"/g, '%22')}" target="_blank" rel="noopener">${txt}</a>`;
    }).replace(/&lt;(https?:\/\/[^\s&]+)&gt;/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
      .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
      .replace(/(^|[^\w*])\*([^*\s][^*]*?)\*(?!\w)/g, '$1<i>$2</i>')
      .replace(/\u0000(\d+)\u0000/g, (m, i) => `<code>${codes[+i]}</code>`);
    span.innerHTML = h;
    return span;
  };
  const out = [], slugs = new Map();
  let list = null, sub = null, para = [], code = null, table = null;   // list: a <ul>, or an <ol> for "1. " lines
  const flushPara = () => { if (para.length) { const p = document.createElement('p'); p.append(inline(para.join(' '))); out.push(p); para = []; } };
  const cells = (line) => line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
  for (const raw of md.split('\n')) {
    const line = raw.replace(/\s+$/, '');
    if (code) {                                   // inside a ``` block
      if (/^\s*```/.test(line)) { out.push(code); code = null; } else code.firstChild.append(raw + '\n');
      continue;
    }
    if (/^\s*```/.test(line)) { flushPara(); list = sub = table = null; code = document.createElement('pre'); code.append(document.createElement('code')); continue; }
    if (/^\s*\|.*\|\s*$/.test(line)) {           // a table row
      flushPara(); list = sub = null;
      if (/^\s*\|[\s:|-]+\|\s*$/.test(line)) continue;     // the |---|---| line
      if (!table) {
        table = document.createElement('table'); table.className = 'md-table';
        const tr = table.createTHead().insertRow();
        for (const c of cells(line)) { const th = document.createElement('th'); th.append(inline(c)); tr.append(th); }
        table.createTBody(); out.push(table);
      } else {
        const tr = table.tBodies[0].insertRow();
        for (const c of cells(line)) tr.insertCell().append(inline(c));
      }
      continue;
    }
    table = null;
    const m = line.match(/^(\s*)(- |\d+\. )(.*)$/);
    if (m) {
      flushPara();
      const tag = m[2] === '- ' ? 'UL' : 'OL';
      const li = document.createElement('li'); li.append(inline(m[3]));
      if (m[1].length >= 2 && list) {
        if (!sub || sub.tagName !== tag) { sub = document.createElement(tag); list.lastChild?.append(sub); }
        sub.append(li);
      } else {
        if (!list || list.tagName !== tag) { list = document.createElement(tag); out.push(list); }
        sub = null; list.append(li);
      }
      continue;
    }
    if (/^\s+\S/.test(line) && list) { (sub || list).lastChild?.append(' ', inline(line.trim())); continue; }
    list = null; sub = null;
    const h = line.match(/^(#{1,4}) (.*)$/);
    if (h) {
      flushPara();
      const e = document.createElement(`h${h[1].length + 2}`); e.append(inline(h[2]));
      let id = slugify(h[2].replace(/[*`]/g, '')), n = slugs.get(id) || 0;
      slugs.set(id, n + 1); if (n) id = `${id}-${n}`;
      e.dataset.slug = id;
      out.push(e); continue;
    }
    if (!line.trim()) { flushPara(); continue; }
    para.push(line.trim());
  }
  flushPara();
  if (code) out.push(code);
  return out;
}

// The Effort values come from the effort list (Settings → Dropdowns → Effort, 0.39): each has a
// status (on or off effort), a definition and a color (its track color). setEffortList is called when
// the app loads; schema.set_effort_list does the same on the server.
export const EFFORT_REQUIRED = ['Start', 'End', 'ERROR'];
export let ON_EFFORT = ['ON', 'TRANSECT', 'DIRECTED', 'PHOTO-ID', 'FOLLOW'];
let EFFORT = {};
export function setEffortList(rows) {
  rows = (rows || []).filter((r) => r.name);
  if (!rows.length) return;
  EFFORT = Object.fromEntries(rows.map((r) => [r.name, r]));
  ON_EFFORT = rows.filter((r) => (r.status || '').toLowerCase() === 'on' && !EFFORT_REQUIRED.includes(r.name)).map((r) => r.name);
}
export const isOn = (e) => ON_EFFORT.includes(e);
// an Effort value's entry in the list ({name, status, definition, color}), or {} if not in it
export const effortInfo = (e) => EFFORT[e] || {};
// the track / pill color of an Effort value
export const effortColor = (e) => EFFORT[e]?.color || (isOn(e) ? '#00a000' : '#7a7a7a');

// Effort state of each track point from the Effort table as it is now (so an ERROR row added
// later by Error check → Fix applies). A point in the same second as an Effort row keeps the
// state it was recorded with, as in the export.
export function trackStates(points, effortRows) {
  const rows = (effortRows || []).map((r) => [new Date(r.DateTime).getTime(), r.Effort || ''])
    .filter(([t]) => Number.isFinite(t)).sort((x, y) => x[0] - y[0]);
  const times = new Set(rows.map(([t]) => t));
  let k = -1, state = '';
  return points.map((p) => {
    const t = new Date(p.DateTime).getTime();
    while (k + 1 < rows.length && rows[k + 1][0] <= t) { k++; state = rows[k][1]; }
    if (times.has(t) && p.Effort) return p.Effort;
    return state || p.Effort || 'OFF';
  });
}

// 0.46: where the trackline is broken: brk[i] = don't join point i-1 to point i. Broken when the
// Effort row in force at point i-1 (an ERROR row in the same second counts: Error check → Fix puts it at
// the last good point) is ERROR, or an ERROR row falls between the two points. (Point states alone
// missed a gap or a one-way jump, where no point lies inside the ERROR stretch.)
export function trackBreaks(points, effortRows) {
  const rows = (effortRows || []).map((r) => [new Date(r.DateTime).getTime(), r.Effort || ''])
    .filter(([t]) => Number.isFinite(t)).sort((x, y) => x[0] - y[0]);
  const errs = rows.filter(([, e]) => e === 'ERROR').map(([t]) => t);
  let k = -1, state = '', prevT = null, prevState = '';
  return points.map((p) => {
    const t = new Date(p.DateTime).getTime();
    while (k + 1 < rows.length && rows[k + 1][0] <= t) { k++; state = rows[k][1]; }
    const brk = prevT !== null && (prevState === 'ERROR' || errs.some((e) => e > prevT && e < t));
    prevT = t; prevState = state;
    return brk;
  });
}

// 0.46: the Effort row in force at a time (for the track point popup's segment number)
export function effortRowAt(effortRows, when) {
  const t = new Date(when).getTime();
  let best = null, bt = -Infinity;
  for (const r of effortRows || []) {
    const rt = new Date(r.DateTime).getTime();
    if (Number.isFinite(rt) && rt <= t && rt >= bt) { best = r; bt = rt; }
  }
  return best;
}

// 'NA' (None) and the like stand for an empty watch position, not an observer
export function isPlaceholderObs(name, fullName = '') {
  return ['NA', 'N/A', 'NONE', '-', '—'].includes(String(name || '').trim().toUpperCase()) || String(fullName || '').trim().toLowerCase() === 'none';
}

// line styles for the route and the tracks
export const LINE_STYLES = [['solid', 'Solid'], ['dashed', 'Dashed'], ['dotted', 'Dotted'], ['dashdot', 'Dash-dot']];
// Leaflet dashArray for a line style, scaled to the line width
export function dashFor(line, w) {
  w = Math.max(1, +w || 3);
  return { solid: null, dashed: `${w * 3} ${w * 2}`, dotted: `1 ${w * 2}`, dashdot: `${w * 4} ${w * 2} 1 ${w * 2}` }[line] ?? null;
}

// ---------------------------------------------------------------- help behind ? buttons (0.39)
// Explanations in Survey, Tools and Settings are marked class "help". helpify() takes each out of the
// page and puts it behind a small ? button on its section's heading (or where it was, if there is no
// heading): hover to read it, click to keep it open (click again, Esc or click elsewhere to close).
let helpPop = null, helpPinned = null, helpTimer = null;
function helpShow(btn, pin = false) {
  clearTimeout(helpTimer);
  if (!helpPop) {
    helpPop = el('div', { id: 'help-pop', role: 'tooltip' });
    helpPop.addEventListener('mouseenter', () => clearTimeout(helpTimer));
    helpPop.addEventListener('mouseleave', () => { if (!helpPinned) helpHideSoon(); });
    document.body.append(helpPop);
    document.addEventListener('mousedown', (e) => {
      if (helpPinned && !helpPop.contains(e.target) && !e.target.closest?.('.help-btn')) helpHide(true);
    }, true);
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && helpPop.style.display === 'block') helpHide(true); });
  }
  if (helpPinned && helpPinned !== btn && !pin) return;          // another one is pinned open
  if (pin) { helpPinned?.setAttribute('aria-expanded', 'false'); helpPinned = btn; }
  helpPop.replaceChildren(btn._help);
  helpPop.style.display = 'block';
  btn.setAttribute('aria-expanded', 'true');
  const r = btn.getBoundingClientRect(), w = Math.min(460, window.innerWidth - 16);
  helpPop.style.maxWidth = `${w}px`;
  helpPop.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - w - 8))}px`;
  const h = helpPop.offsetHeight, below = window.innerHeight - r.bottom;
  helpPop.style.top = `${below < h + 12 && r.top > below ? Math.max(8, r.top - h - 6) : r.bottom + 6}px`;
}
function helpHide(force = false) {
  if (!helpPop || (helpPinned && !force)) return;
  helpPop.style.display = 'none';
  helpPinned?.setAttribute('aria-expanded', 'false');
  document.querySelectorAll('.help-btn[aria-expanded=true]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
  helpPinned = null;
}
function helpHideSoon() { clearTimeout(helpTimer); helpTimer = setTimeout(() => helpHide(), 250); }

export function helpButton(title = 'Help') {
  const btn = el('button', { type: 'button', class: 'help-btn', 'aria-label': title, 'aria-expanded': 'false', title: '' });   // the ? is drawn by CSS, so it isn't part of the heading's text
  btn._help = el('div', { class: 'help-body' });
  btn.addEventListener('mouseenter', () => helpShow(btn));
  btn.addEventListener('mouseleave', () => { if (helpPinned !== btn) helpHideSoon(); });
  btn.addEventListener('focus', () => helpShow(btn));
  btn.addEventListener('blur', () => { if (helpPinned !== btn) helpHideSoon(); });
  btn.addEventListener('click', (e) => {
    e.preventDefault(); e.stopPropagation();
    if (helpPinned === btn) helpHide(true); else helpShow(btn, true);
  });
  return btn;
}

function helpHeading(p) {
  for (let node = p, up = 0; node && up < 3; node = node.parentElement, up++) {
    for (let s = node.previousElementSibling; s; s = s.previousElementSibling) {
      if (/^H[1-4]$/.test(s.tagName)) return s;
      if (s.matches('section, .settings-sec')) break;           // the end of this section
    }
    if (node.parentElement?.matches('section, .settings-sec, details')) {
      const h = node.parentElement.querySelector(':scope > h2, :scope > h3, :scope > h4');
      if (h) return h;
      break;
    }
  }
  return null;
}

export function helpify(root = document) {
  for (const p of root.querySelectorAll('.help:not(.help-body *)')) {
    if (helpPop?.contains(p)) continue;
    const h = helpHeading(p);
    let btn = h && [...h.children].find((c) => c.classList.contains('help-btn'));
    if (!btn) {
      btn = helpButton(h ? `About ${h.textContent.trim()}` : 'Help');
      if (h) h.append(btn); else p.before(btn);
    }
    const part = el('p', {});
    part.append(...p.childNodes);
    btn._help.append(part);
    p.remove();
    if (helpPinned === btn) helpShow(btn, true);
  }
}

// keep every new help paragraph behind its ? button, whichever part of the app drew it
export function watchHelp() {
  let queued = false;
  helpify(document);
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    queueMicrotask(() => { queued = false; helpify(document); });
  }).observe(document.body, { childList: true, subtree: true });
}
