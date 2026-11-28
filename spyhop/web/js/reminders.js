// Tools → Reminders (0.63): Weather (the conditions check: a new Effort row resets it) and the team's own
// reminders (watch change, visual scan…), each every so many minutes, counted from the last one or on the
// clock (:00, :15, :30…). Due ones show in the status bar, with a message and a chime. Also the warning
// when this computer's battery runs low (battery.py).
import { $, el, toast, fmtDuration, timeParts, clockOffsetMin, isOn } from './util.js';

const WHEN = [['survey', 'In a survey'], ['effort', 'On effort'], ['always', 'Always']];
const SUGGEST = ['Watch change', 'Visual scan', 'Photo check', 'Instrument check', 'Break'];
const DAY = 86400000;

// the next time on the clock after t that is a whole number of intervals from midnight (in the survey clock)
export function nextSlot(t, everyMin, clock = 'local') {
  const P = everyMin * 60000;
  const off = clockOffsetMin(new Date(t), clock) * 60000;
  const local = t + off;
  const midnight = Math.floor(local / DAY) * DAY;
  let next = midnight + (Math.floor((local - midnight) / P) + 1) * P;
  if (next > midnight + DAY) next = midnight + DAY;      // intervals that don't divide the day start again at midnight
  return next - off;
}

export class Reminders {
  constructor(app) {
    this.app = app;
    this.opened = Date.now();
    this.alerted = {};        // id -> the due time already announced
    this.battery = { low: null, plugged: null };
  }

  get S() { return this.app.S; }
  list() { return this.S.config.settings.reminders || []; }
  doneAt(id) { const t = Date.parse(this.S.config.settings.reminder_done?.[id] || ''); return isNaN(t) ? 0 : t; }

  effortRows() {
    return [...(this.S.tables.effort?.rows || [])].filter((r) => r.DateTime).sort((a, b) => (a.DateTime < b.DateTime ? -1 : 1));
  }

  // when this reminder's count starts (null: not running now)
  start(r) {
    const active = !!this.S.survey?.active;
    if (r.on === false) return null;
    if (r.when === 'always') return this.opened;
    if (!active) return null;
    const rows = this.effortRows();
    if (!rows.length) return null;
    if (r.id === 'weather') return Date.parse(rows[rows.length - 1].DateTime);    // the last Effort row
    if (r.when === 'effort') {
      if (!isOn(rows[rows.length - 1].Effort)) return null;
      let i = rows.length - 1;
      while (i > 0 && isOn(rows[i - 1].Effort)) i--;
      return Date.parse(rows[i].DateTime);                     // since effort went on
    }
    return Date.parse(rows[0].DateTime);                       // since the survey's start
  }

  // when it's next due (ms), or null
  due(r) {
    const s = this.start(r);
    if (s === null || isNaN(s)) return null;
    const base = Math.max(s, this.doneAt(r.id));
    const every = Math.max(1, +r.every || 30);
    // on the clock: the next slot at least half an interval after the last one, so an Effort row made at
    // 10:28 counts for 10:30 (the next is 11:00)
    return r.sync ? nextSlot(base + every * 30000, every, this.app.clock()) : base + every * 60000;
  }

  // every second (app.updateStatus): the status bar, the Effort tab's warning and the alerts
  tick() {
    const box = $('#sf-remind');
    if (!box || !this.S) return;
    const now = Date.now();
    const parts = [];
    let weatherLate = false, anyLate = false;
    for (const r of this.list()) {
      const due = this.due(r);
      if (due === null) continue;
      const left = (due - now) / 1000, late = left <= 0;
      if (late) {
        anyLate = true;
        if (r.id === 'weather') weatherLate = true;
        if (this.alerted[r.id] !== due) { this.alerted[r.id] = due; this.announce(r); }
      }
      parts.push(el('span', { class: `rem${late ? ' late' : ''}`, 'data-id': r.id,
        title: r.id === 'weather' ? 'Weather (conditions) check: a new Effort row resets it — click to open the Effort table'
          : late ? `${r.name} is due — click when done` : `${r.name}: next ${this.at(due)} — click for Tools → Reminders` },
        late ? `${r.name} DUE ${fmtDuration(-left)}` : `${r.name} ${fmtDuration(left)}`));
    }
    const key = parts.map((p) => p.textContent + p.className).join('|');
    if (key !== this._key) { this._key = key; box.replaceChildren(...parts.flatMap((p, i) => (i ? [' · ', p] : [p]))); }
    box.classList.toggle('alert', anyLate);
    $('#pane-effort')?.classList.toggle('overdue', weatherLate);
    $('#tabs [data-tab="effort"]')?.classList.toggle('overdue', weatherLate);
    if (this.app.shown('reminders')) this.updateNext();
  }

  at(t, zone = true) { const p = timeParts(new Date(t), this.app.clock()); return p ? `${p.time.slice(0, 5)}${zone ? ` ${p.abbr}` : ''}` : ''; }

  announce(r) {
    toast(r.id === 'weather' ? 'Weather check due: add an Effort row with the conditions.' : `${r.name} is due.`, 'warn', 15000);
    this.chime();
  }

  chime(low = false) {
    if (this.S.config.settings.reminder_sound === false) return;
    try {
      this.audio ||= new (window.AudioContext || window.webkitAudioContext)();
      const a = this.audio, t = a.currentTime;
      (low ? [440, 330, 440, 330] : [880, 660]).forEach((f, i) => {
        const o = a.createOscillator(), g = a.createGain();
        o.frequency.value = f; o.connect(g); g.connect(a.destination);
        g.gain.setValueAtTime(0.0001, t + i * 0.22);
        g.gain.exponentialRampToValueAtTime(0.25, t + i * 0.22 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.22 + 0.2);
        o.start(t + i * 0.22); o.stop(t + i * 0.22 + 0.21);
      });
    } catch { /* no sound here */ }
  }

  // a click on the status bar: Weather opens the Effort table; a due reminder is marked done; else this tab
  onStatusClick(e) {
    const s = e.target.closest('.rem');
    if (!s) return;
    if (s.dataset.id === 'weather') { this.app.showTab('effort'); return; }
    if (s.classList.contains('late') && !this.S.viewer) this.done(s.dataset.id);
    else this.app.showTab('reminders');
  }

  async done(id) {
    const d = { ...(this.S.config.settings.reminder_done || {}), [id]: new Date().toISOString() };
    await this.app.saveSettings({ reminder_done: d }, true);
  }

  async saveList(list) { await this.app.saveSettings({ reminders: list }); }

  // ------------------------------------------------------------ Tools → Reminders
  render() {
    const pane = $('#pane-reminders');
    if (!pane) return;
    const st = this.S.config.settings, view = !!this.S.viewer;
    const list = this.list().map((r) => ({ ...r }));
    const edit = (i, k, v) => { list[i][k] = v; this.saveList(list); };
    const rows = list.map((r, i) => {
      const w = r.id === 'weather';
      return el('tr', { 'data-id': r.id },
        el('td', {}, el('input', { type: 'checkbox', checked: r.on !== false, 'aria-label': `${r.name} on`, disabled: view, onchange: (e) => edit(i, 'on', e.target.checked) })),
        el('td', {}, w ? el('b', {}, 'Weather') : el('input', { type: 'text', value: r.name, list: 'reminder-names', style: 'width:8.8em', 'aria-label': 'Name', disabled: view,
          onchange: (e) => { const v = e.target.value.trim(); if (v) edit(i, 'name', v); else { toast('A reminder needs a name.', 'warn'); e.target.value = r.name; } } })),
        el('td', {}, el('input', { type: 'number', min: 1, max: 1440, step: 1, value: r.every, style: 'width:3.8em', 'aria-label': `${r.name}: every (min)`, disabled: view,
          onchange: (e) => { const v = +e.target.value; if (v >= 1 && v <= 1440) edit(i, 'every', v); else { toast('Every 1–1440 minutes', 'warn'); e.target.value = r.every; } } })),
        el('td', {}, el('input', { type: 'checkbox', checked: !!r.sync, 'aria-label': `${r.name}: on the clock`, disabled: view, onchange: (e) => edit(i, 'sync', e.target.checked) })),
        el('td', {}, w ? el('span', { class: 'hint' }, 'In a survey')
          : el('select', { 'aria-label': `${r.name}: when`, disabled: view, onchange: (e) => edit(i, 'when', e.target.value) },
            WHEN.map(([v, l]) => el('option', { value: v, selected: r.when === v }, l)))),
        el('td', { class: 'rem-next' }),
        el('td', {}, view ? null : el('span', { class: 'inline' },
          el('button', { class: 'rem-done', title: w ? 'Done without an Effort row (the count starts again now)' : 'Done: the count starts again now', onclick: () => this.done(r.id) }, 'Done'),
          w ? null : el('button', { class: 'danger', title: 'Delete this reminder', onclick: () => { list.splice(i, 1); this.saveList(list); } }, '✕'))));
    });
    const add = el('button', { id: 'btn-add-reminder', onclick: () => {
      const used = new Set(list.map((r) => r.name));
      list.push({ name: SUGGEST.find((n) => !used.has(n)) || 'Reminder', every: 30, sync: false, when: 'survey', on: true });
      this.saveList(list);
    } }, '+ Add a reminder');
    const bat = this.S.battery;
    const chk = (key, label, id) => el('label', { class: 'check' }, el('input', { type: 'checkbox', id, checked: st[key] !== false, disabled: view,
      onchange: (e) => this.app.saveSettings({ [key]: e.target.checked }) }), el('span', {}, label));
    pane.replaceChildren(
      el('section', { class: 'settings-sec', id: 'reminders-section' }, el('h3', {}, 'Reminders'),
        el('div', { class: 'table-scroll' }, el('table', { class: 'track-style', id: 'reminder-table' },
          el('thead', {}, el('tr', {}, [['On'], ['Reminder'], ['Every (min)'], ['Clock', 'On the clock: due at :00, :15, :30… rather than counted from the last one'], ['When'], ['Next due'], ['']]
            .map(([h, t]) => el('th', { title: t || '' }, h)))),
          el('tbody', {}, rows))),
        el('datalist', { id: 'reminder-names' }, SUGGEST.map((n) => el('option', { value: n }))),
        view ? null : el('div', { class: 'btnrow' }, add),
        el('div', { class: 'grid2 checks' }, chk('reminder_sound', 'Chime when a reminder is due', 'reminder-sound')),
        el('p', { class: 'hint help' }, 'Weather is the conditions check: a new Effort row (with the weather and sightability) starts its count again, and the Error check flags long gaps without one. Your own reminders start counting at the survey’s start (“In a survey”), when effort goes on (“On effort”, paused off effort) or when Spyhop opens (“Always”); Done, here or on the reminder in the status bar, starts the count again. “On the clock” makes one due at whole intervals from midnight, e.g. every 30 min at :00 and :30, and every 15 min at :00, :15, :30 and :45 — one done or an Effort row made shortly before a slot counts for that slot. Due reminders show in the status bar, with a message and a chime. Reminders are part of the template’s preferences, so the whole team gets the same ones.')),
      el('section', { class: 'settings-sec', id: 'battery-section' }, el('h3', {}, 'Battery'),
        el('p', { id: 'battery-now' }, this.batteryText()),
        el('div', { class: 'grid2 checks' },
          chk('battery_warn', 'Warn when the battery runs low', 'battery-warn'),
          chk('battery_warn_unplug', 'Warn when the computer is unplugged (starts running on battery)', 'battery-unplug')),
        el('div', { class: 'grid2' }, el('label', { class: 'row' }, 'Warn below (%)', el('input', { type: 'number', id: 'battery-pct', min: 1, max: 95, value: st.battery_warn_pct ?? 20, style: 'width:5em', disabled: view,
          onchange: (e) => { const v = +e.target.value; if (v >= 1 && v <= 95) this.app.saveSettings({ battery_warn_pct: v }); else { toast('1–95 %', 'warn'); e.target.value = st.battery_warn_pct; } } }))),
        el('p', { class: 'hint help' }, 'The battery of the computer running Spyhop, checked every 30 s. Below this level on battery the status bar shows it in red, with a message and a chime, again every 5 % lower. Spyhop keeps working on a flat battery only as long as the computer does: plug it in, and see Settings → General → Sleep for keeping it awake.')));
    this.updateNext();
  }

  updateNext() {
    const now = Date.now();
    for (const tr of document.querySelectorAll('#reminder-table tbody tr')) {
      const r = this.list().find((x) => x.id === tr.dataset.id), td = tr.querySelector('.rem-next');
      if (!r || !td) continue;
      const due = this.due(r);
      const txt = due === null ? (r.on === false ? 'Off' : r.when === 'effort' ? 'Waits for effort' : 'Waits for a survey')
        : due <= now ? `DUE ${fmtDuration((now - due) / 1000)}` : `${this.at(due, false)} (${fmtDuration((due - now) / 1000)})`;
      if (td.textContent !== txt) td.textContent = txt;
      td.classList.toggle('late', due !== null && due <= now);
    }
  }

  // ------------------------------------------------------------ battery
  batteryText() {
    const b = this.S.battery;
    if (!b) return 'No battery found on this computer (a desktop, or it can’t be read): nothing to warn about.';
    return `${this.S.viewer ? 'The Spyhop laptop’s' : 'This computer’s'} battery: ${b.percent}%, ${b.plugged ? 'plugged in' : 'on battery'}.`;
  }

  // a new reading (bootstrap or the server's "battery" message)
  onBattery(b) {
    const prev = this.S.battery;
    this.S.battery = b;
    const st = this.S.config.settings, who = this.S.viewer ? 'The Spyhop laptop' : 'This computer';
    const sf = $('#sf-battery');
    if (sf) {
      const low = b && !b.plugged && b.percent <= (st.battery_warn_pct ?? 20);
      sf.hidden = !b || b.plugged;
      sf.textContent = b ? `Battery ${b.percent}%` : '';
      sf.classList.toggle('alert', !!low && st.battery_warn !== false);
    }
    const p = $('#battery-now'); if (p) p.textContent = this.batteryText();
    if (!b) return;
    if (b.plugged) { this.battery.low = null; }
    else if (st.battery_warn !== false) {
      const pct = st.battery_warn_pct ?? 20;
      // warn at the level, then every 5 % lower
      if (b.percent <= pct) {
        const step = Math.ceil((pct - b.percent) / 5);
        if (this.battery.low === null || step > this.battery.low) {
          this.battery.low = step;
          toast(`${who}’s battery is low: ${b.percent}%. Plug it in.`, 'error', 20000);
          this.chime(true);
        }
      }
    }
    if (prev && prev.plugged && !b.plugged && st.battery_warn_unplug !== false) {
      toast(`${who} is unplugged: running on battery (${b.percent}%).`, 'warn', 10000);
      this.chime(true);
    }
  }
}
