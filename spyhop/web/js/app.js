// Main controller: layout, status bar, tabs, shortcuts, settings, summary, live updates.
import { $, $$, el, esc, api, toast, modal, confirmBox, promptBox, fmtPos, fmtDuration, timeParts, distM, fmtBrg, isModalOpen, renderMarkdown, isTrackBreak, trackStates, isPlaceholderObs, LINE_STYLES, isOn, ON_EFFORT, setEffortList, effortInfo, effortColor, EFFORT_REQUIRED, watchHelp } from './util.js';
import { Grid } from './grid.js';
import { Resights, groupCounts } from './resights.js';
import { ResightTool } from './resight_tool.js';

// what each Effort value means (the Effort column's help, the Summary)
import { MapView, SHAPES } from './map.js';
import { buildSummaryHtml } from './summary_html.js';
import { openInstrumentPlot } from './plot.js';
import { Planner } from './planning.js';
import { ReportsTool } from './reports.js';
import { OnlineOverlays } from './online.js';

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform);
const MOD = IS_MAC ? '⌘' : 'Ctrl';

class App {
  constructor() {
    this.S = null;
    this.grids = {};
    this.tab = 'sightings';       // the tab used last, in either pane (shortcuts that add rows go there)
    this.dataTab = 'sightings';   // the data pane's tab: Sightings, Effort or Events
    this.utilTab = 'survey';      // the Survey/Tools/Settings pane's tab
    this.wsOk = false;
  }

  async start() {
    await this.load();
    this.buildLayout();
    this.map = new MapView(this, $('#map'));
    this.planner = new Planner(this);
    this.reportsTool = new ReportsTool(this);
    this.resightTool = new ResightTool(this);
    this.online = new OnlineOverlays(this);
    this.applyDisplay();
    this.renderAll();
    this.applyLayout();
    // the sub-tab last used in each group (Tools, Settings)
    this.lastSub = { tools: 'marks', config: 'settings' };
    try {
      const saved = JSON.parse(localStorage.getItem('wsr.subtabs') || 'null');
      if (saved) Object.assign(this.lastSub, saved);
    } catch {}
    this.connect();
    setInterval(() => {
      this.updateStatus();
      if (this.shown('summary') && !window.getSelection()?.toString()) this.renderSummary();   // live counters
    }, 1000);
    document.addEventListener('keydown', (e) => this.onShortcut(e), true);
    this.watchSlowness();
    watchHelp();
    this.watchErrors();
    const ab = this.S.about || {};
    if (ab.updated_from) toast(`Spyhop has been updated from ${ab.updated_from} to ${ab.spyhop}. See what's new in Settings → About.`, 'info', 12000);
    window.addEventListener('resize', () => this.map.invalidate());
    (this.S.notices || []).forEach((n) => toast(n, 'warn', 15000));
    // each pane opens on the tab it had last; with no survey open, on Survey
    let saved = {};
    try { saved = { data: localStorage.getItem('wsr.datatab'), util: localStorage.getItem('wsr.utiltab') }; } catch {}
    this.showTab(this.allTabs().includes(saved.util) && !this.topTabs().includes(saved.util) ? saved.util : 'survey', { reveal: false });
    this.showTab(this.topTabs().includes(saved.data) ? saved.data : 'sightings', { reveal: false });
    if (!this.S.survey) this.showTab('survey', { reveal: false });
    // a survey open at startup (active or ended): show all of it, once the panes have their sizes
    if (this.S.survey) setTimeout(() => { this.map.map.invalidateSize(); this.map.fitSurvey(); }, 300);
    if (this.S.resume_prompt) this.askResume();
  }

  // Send errors in this window to Spyhop's diagnostic log, plus a performance note every 5 minutes.
  watchErrors() {
    const pending = [];
    const add = (message, stack) => { if (pending.length < 20) pending.push({ message: `${message} [${this.tab} tab]`, stack }); };
    window.addEventListener('error', (e) => add(e.message || 'error', e.error?.stack || `${e.filename}:${e.lineno}`));
    window.addEventListener('unhandledrejection', (e) => add(`unhandled: ${e.reason?.message || e.reason}`, e.reason?.stack));
    let longTasks = 0, longMs = 0;
    try { new PerformanceObserver((l) => l.getEntries().forEach((e) => { longTasks++; longMs += e.duration; })).observe({ entryTypes: ['longtask'] }); } catch {}
    let n = 0;
    setInterval(() => {
      n++;
      const body = {};
      if (pending.length) body.errors = pending.splice(0);
      if (n % 30 === 0) {      // every 5 minutes
        const mem = performance.memory ? `${Math.round(performance.memory.usedJSHeapSize / 1e6)} MB used` : 'memory n/a';
        body.perf = `${mem}, ${longTasks} long tasks (${Math.round(longMs)} ms) in 5 min, ${document.querySelectorAll('*').length} page elements, tabs ${this.dataTab} + ${this.utilTab}`;
        longTasks = 0; longMs = 0;
      }
      if (body.errors || body.perf) fetch('/api/client-log', { method: 'POST', body: JSON.stringify(body) }).catch(() => {});
    }, 10000);
  }

  // Report moments when this window is busy (shown in Spyhop's Terminal window), to find slowness.
  watchSlowness() {
    const pending = [];
    let mapBusyUntil = 0;
    try {
      for (const ev of ['movestart', 'zoomstart', 'move', 'zoom']) this.map.map.on(ev, () => { mapBusyUntil = performance.now() + 1000; });
    } catch {}
    try {
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          if (e.duration < 200) continue;
          const onMap = e.startTime < mapBusyUntil;
          pending.push({ ms: Math.round(e.duration), what: `${onMap ? 'moving/zooming the map, ' : ''}${this.tab} tab` });
        }
      }).observe({ entryTypes: ['longtask'] });
    } catch { return; }     // not supported by this browser
    setInterval(() => {
      if (!pending.length) return;
      const events = pending.splice(0);
      fetch('/api/client-log', { method: 'POST', body: JSON.stringify({ events }) }).catch(() => {});
    }, 5000);
  }

  async load() {
    this.S = await api('/api/bootstrap');
    setEffortList(this.S.config.lists.effort);
  }

  // the Refresh buttons of the survey list and the overlays: read those folders again
  async refreshFolders() {
    try {
      const d = await api('/api/bootstrap');
      this.S.overlays = d.overlays; this.S.surveys = d.surveys;
      this.map.loadOverlays(d.overlays);
      this.renderOverlays();
      if (this.shown('survey')) this.renderSurvey();
    } catch { /* toast shown */ }
  }

  async reload() {
    const before = this.S?.about?.spyhop;
    await this.load();
    // Spyhop was updated and restarted: load the new version's page
    if (before && this.S.about?.spyhop && this.S.about.spyhop !== before) { location.reload(); return; }
    // a survey action can ask for a tab to show once the new data is in (e.g. Effort after Start)
    const tab = this.pendingTab || this.tab, dataTab = this.dataTab, utilTab = this.utilTab;
    this.pendingTab = null;
    this.rebuildTabs();
    this.applyDisplay();
    this.renderAll();
    this.map.drawTrack();
    this.map.loadOverlays(this.S.overlays);
    this.online?.applyPackDisplay();
    this.showTab(utilTab, { reveal: false });
    this.showTab(dataTab, { reveal: false });
    this.showTab(this.allTabs().includes(tab) ? tab : 'sightings', { reveal: tab !== dataTab && tab !== utilTab });
    if (this.pendingFit) { this.pendingFit = false; this.map.fitSurvey(); }
  }

  // distances on the map, in popups, routes and the Summary (Settings → General: never reticles)
  unit() { const u = this.S.config.settings.map_distance_unit || 'nm'; return u === 'reticle' ? 'nm' : u; }
  // the platform of the open survey (else of the last survey details): Shipboard, Aerial, Stationary, Other or ''
  platformType() { return this.S.survey?.meta?.platform_type || this.S.config.settings.last_meta?.platform_type || ''; }
  // an optional column (schema optional=…) is shown or not: Settings → General → Altitude column
  columnShown(c) {
    if (!c.optional) return true;
    if (c.optional === 'segment') return (this.S.config.settings.segment_column || 'show') !== 'hide';
    if (c.optional === 'altitude') {
      const m = this.S.config.settings.altitude_column || 'auto';
      return m === 'show' || (m === 'auto' && this.platformType() === 'Aerial');
    }
    return true;
  }
  // the survey clock for timeParts(): 'local', 'UTC', a fixed 'UTC±hh:mm', or (from the platform's
  // position) the IANA zone the server found
  clock() {
    const v = this.S.config.settings.timezone || 'local';
    if (v === 'auto') return this.S.clock?.zone || 'local';
    return v === 'UTC' || /^UTC[+-]/.test(v) ? v : 'local';
  }
  variation() {
    const v = this.S.vessel?.mag_var;
    return v === null || v === undefined ? null : v;
  }
  dataTabs() {
    return ['sightings', 'effort', 'events', 'marks'];
  }
  // Top row: the data tabs, Survey (the pane called 'survey'), then two groups with a second row of tabs.
  // Pane keys stay as they were (so tab: shortcuts and saved tabs keep working): 'settings' is General,
  // 'nmea' is Instruments, 'marks' is the Waypoints table.
  topTabs() { return ['sightings', 'effort', 'events']; }
  tabGroups() {
    return [
      ['tools', 'Tools', [['marks', 'Waypoints'], ['overlays', 'Overlays'], ['route', 'Routes'], ['nmea', 'Instruments'], ['resights', 'Resights'], ['qc', 'Error check'], ['summary', 'Summary'], ['reports', 'Reports']]],
      ['config', 'Settings', [['settings', 'General'], ['basemap', 'Basemap'], ['inputs', 'Inputs'], ['shortcuts', 'Shortcuts'], ['dropdowns', 'Dropdowns'],
        ['templates', 'Templates'], ['guide', 'Guide'], ['about', 'About']]]];
  }
  groupTabs() { return this.tabGroups().flatMap(([g, , tabs]) => tabs.map(([k, l]) => [k, l, g])); }
  groupOf(tab) { return this.groupTabs().find(([k]) => k === tab)?.[2] || null; }
  // "Settings → General", "Tools → Instruments", "Survey"
  tabPath(tab) {
    const t = this.groupTabs().find(([k]) => k === tab);
    if (!t) return tab === 'survey' ? 'Survey' : (this.S.schema.tabs[tab]?.title || tab);
    return `${this.tabGroups().find(([g]) => g === t[2])[1]} → ${t[1]}`;
  }
  allTabs() { return [...this.topTabs(), 'survey', ...this.groupTabs().map(([k]) => k)]; }

  // ---------------------------------------------------------------- layout
  // Three panes: the map and Survey/Tools/Settings ("utilities") share the top; the data tables
  // (Sightings, Effort, Events) span the full width below. Each can be resized, minimized to a strip
  // or maximized; the sizes and states are kept on this computer (settings.pane_layout).
  buildLayout() {
    const root = $('#app');
    const winBtns = (k, label) => [
      el('button', { class: 'pane-btn pane-min', 'data-pane': k, 'aria-label': `Minimize ${label}`, title: `Minimize ${label}`, onclick: () => this.setPaneMin(k, !this.paneLayout().min[k]) },
        el('span', { 'aria-hidden': 'true' }, '▁')),
      el('button', { class: 'pane-btn pane-max', 'data-pane': k, onclick: () => this.setPaneMax(k) })];
    root.replaceChildren(
      el('header', { id: 'status' }),
      el('main', { id: 'main' },
        el('section', { id: 'map-pane', class: 'pane', 'aria-label': 'Map' },
          el('div', { class: 'pane-head map-head' }, el('b', { class: 'pane-title' }, 'Map'), el('span', { class: 'tabs-spacer' }), ...winBtns('map', 'the map')),
          el('div', { class: 'pane-body' }, el('div', { id: 'map' })),
          el('button', { class: 'strip-btn', 'data-pane': 'map', title: 'Show the map', onclick: () => this.setPaneMin('map', false) }, 'Map ▸')),
        el('section', { id: 'util-pane', class: 'pane', 'aria-label': 'Survey, Tools and Settings' },
          el('div', { class: 'pane-head' }, el('nav', { id: 'util-tabs', class: 'pane-tabs', role: 'tablist' }), el('span', { class: 'tabs-spacer' }), ...winBtns('util', 'Survey, Tools and Settings')),
          el('nav', { id: 'subtabs', role: 'tablist' }),
          el('div', { class: 'pane-body', id: 'util-body' }),
          el('button', { class: 'strip-btn', 'data-pane': 'util', title: 'Show Survey, Tools and Settings', onclick: () => this.setPaneMin('util', false) }, '◂ Survey · Tools · Settings')),
        el('section', { id: 'data-pane', class: 'pane', 'aria-label': 'Data tables' },
          el('div', { class: 'pane-head' }, el('nav', { id: 'tabs', class: 'pane-tabs', role: 'tablist' }), el('span', { class: 'tabs-spacer' }), ...winBtns('data', 'the data tables')),
          el('div', { class: 'pane-body', id: 'data-body' }),
          el('footer', { id: 'bottom' })),
        el('button', { id: 'split-v', class: 'pane-split', 'aria-label': 'Resize the map and Survey/Tools/Settings (drag, or use ← →)', title: 'Drag to resize · double-click to share equally' }),
        el('button', { id: 'split-h', class: 'pane-split', 'aria-label': 'Resize the top and the data tables (drag, or use ↑ ↓)', title: 'Drag to resize · double-click for the default' })));
    this.buildStatus();
    this.rebuildTabs();
    this.buildBottom();
    this.initSplitters();
    // the pane last clicked or typed in: its tab is the one "the current tab" shortcuts act on
    $('#data-body').addEventListener('pointerdown', () => { this.tab = this.dataTab; }, true);
    $('#data-body').addEventListener('focusin', () => { this.tab = this.dataTab; });
    $('#util-body').addEventListener('pointerdown', () => { this.tab = this.utilTab; }, true);
    $('#util-body').addEventListener('focusin', () => { this.tab = this.utilTab; });
  }

  buildStatus() {
    const s = $('#status');
    const f = (id, title, ...kids) => el('div', { class: 'sf', id, title }, ...kids);
    s.replaceChildren(
      f('sf-clock', 'Survey clock (local or UTC — set in Settings)'),
      f('sf-pos', 'Vessel position from GPS', el('span', { id: 'pos-text' }), el('span', { id: 'pos-flag' })),
      f('sf-nav', 'Speed / course / heading'),
      f('sf-remind', 'Time until the next Effort/conditions check — click to open the Effort table (the interval is in Settings → General)'),
      f('sf-survey', 'Current survey'),
      f('sf-track', 'Internal trackline (switch on/off in Settings)'),
      f('sf-effort', 'Latest effort state'),
      el('div', { class: 'sf grow' }),
      f('sf-version', 'Spyhop version — click for details (Settings → About)', `Spyhop ${this.S.about?.spyhop || ''}`));
    $('#sf-version').addEventListener('click', () => this.showTab('about'));
    $('#sf-remind').addEventListener('click', () => this.showTab('effort'));
    $('#sf-survey').addEventListener('click', () => this.showTab('survey'));
  }

  rebuildTabs() {
    const combo = (t) => (this.S.config.shortcuts.find((x) => x.action === `tab:${t}`)?.combo || '').replace('Mod', MOD);
    // the data pane: Sightings, Effort, Events
    $('#tabs').replaceChildren(...this.topTabs().map((t) => el('button', {
      role: 'tab', 'data-tab': t, onclick: () => this.showTab(t), title: combo(t) },
      this.S.schema.tabs[t].title, el('span', { class: 'count', id: `count-${t}` }))));
    // Survey, then Tools and Settings, which open the tab of theirs used last
    $('#util-tabs').replaceChildren(
      el('button', { role: 'tab', 'data-tab': 'survey', title: 'Start, end, open and export surveys' + (combo('survey') ? ` (${combo('survey')})` : ''),
        onclick: () => this.showTab('survey') }, 'Survey'),
      ...this.tabGroups().map(([g, label, tabs]) => el('button', { role: 'tab', 'data-group': g, class: 'group-tab', title: tabs.map(([, l]) => l).join(', '),
        onclick: () => { const last = this.lastSub[g]; this.showTab(tabs.some(([k]) => k === last) ? last : tabs[0][0]); } }, label)));
    $('#subtabs').replaceChildren(...this.groupTabs().map(([k, label, g]) => el('button', {
      role: 'tab', 'data-tab': k, 'data-group': g, title: combo(k), onclick: () => this.showTab(k) }, label,
      this.S.schema.tabs[k] ? el('span', { class: 'count', id: `count-${k}` }) : null)));
    const dataBody = $('#data-body'), utilBody = $('#util-body');
    dataBody.replaceChildren(); utilBody.replaceChildren();
    this.grids = {};
    for (const t of this.dataTabs()) {        // Waypoints is a table too, in Tools
      const pane = el('div', { class: 'tab-pane', id: `pane-${t}` }, this.toolbar(t));
      (this.topTabs().includes(t) ? dataBody : utilBody).append(pane);
      this.grids[t] = new Grid(this, t, pane);
    }
    utilBody.append(...['survey', ...this.groupTabs().map(([k]) => k)].filter((k) => !this.grids[k]).map((k) => el('div', { class: 'tab-pane scroll', id: `pane-${k}` })));
    this.updatePaneButtons();
  }

  toolbar(tab) {
    const sc = (action) => {
      const s = this.S.config.shortcuts.find((x) => x.action === action && !x.prefill);
      return s ? ` (${s.combo.replace('Mod', MOD)})` : '';
    };
    const bar = el('div', { class: 'toolbar' },
      el('button', { class: 'primary', onclick: () => this.addRow(tab), title: `Add a row${sc(`add:${tab}`)}` },
        'Add row'),
      el('button', { id: `insert-${tab}`, onclick: () => this.insertRow(tab), title: 'Insert a row before or after the selected row, with its time and position averaged from the rows either side or copied from one of them' }, 'Insert row…'),
      el('button', { onclick: () => this.deleteRow(tab), title: 'Delete the selected row' }, 'Delete row'),
      el('button', { id: `undo-${tab}`, onclick: () => this.undo(tab), title: `Undo${sc('undo')}` }, '↶ Undo'),
      el('button', { id: `redo-${tab}`, onclick: () => this.redo(tab), title: `Redo${sc('redo')}` }, '↷ Redo'));
    if (tab === 'sightings') {
      bar.insertBefore(el('button', { id: 'btn-add-resight', disabled: true, onclick: () => this.addResight(),
        title: `Add a resight of the animals of the selected sighting: a new row linked to their first sighting, with the species, numbers and FieldID filled in${sc('add-resight')}` },
        'Add resight'), bar.children[1]);
    }
    return bar;
  }

  buildBottom() {
    $('#bottom').replaceChildren(el('div', { id: 'col-help', 'aria-live': 'polite' }));
  }

  // ---- the panes' sizes and states
  paneLayout() {
    const d = { fx: 0.62, fy: 0.5, min: { map: false, util: false, data: false }, max: null };
    const p = this.S.config.settings.pane_layout || {};
    return { fx: +p.fx || d.fx, fy: +p.fy || d.fy, min: { ...d.min, ...(p.min || {}) }, max: ['map', 'util', 'data'].includes(p.max) ? p.max : null };
  }

  savePaneLayout(lay, now = false) {
    this.S.config.settings.pane_layout = lay;
    this.applyLayout();
    clearTimeout(this._paneSave);
    const send = () => api('/api/settings', { updates: { pane_layout: this.S.config.settings.pane_layout } }).catch(() => {});
    if (now) send(); else this._paneSave = setTimeout(send, 400);
  }

  setPaneMin(k, on) {
    const L = this.paneLayout();
    L.min[k] = on; L.max = null;
    this.savePaneLayout(L, true);
    if (!on && k === 'data') this.grids[this.dataTab]?.wrap.focus({ preventScroll: true });
    if (!on) this.renderPane(k === 'util' ? this.utilTab : k === 'data' ? this.dataTab : null);
  }

  setPaneMax(k) {
    const L = this.paneLayout();
    L.max = L.max === k ? null : k;
    L.min[k] = false;
    this.savePaneLayout(L, true);
  }

  resetPanes() { this.savePaneLayout({}, true); toast('Panes back to their starting sizes', 'info', 2000); }

  // show the pane a tab lives in (out of a strip, or back from another pane filling the window)
  revealPaneOf(tab) {
    const k = this.topTabs().includes(tab) ? 'data' : 'util';
    const L = this.paneLayout();
    if (!L.min[k] && (!L.max || L.max === k)) return;
    L.min[k] = false;
    if (L.max && L.max !== k) L.max = null;
    this.savePaneLayout(L, true);
  }

  applyLayout() {
    const L = this.paneLayout(), m = L.min, S = 34, G = 6;
    const pct = (v) => `${(v * 100).toFixed(3)}%`;
    const set = (id, mode, l, t, w, h) => {
      const p = $(id);
      p.dataset.mode = mode;
      Object.assign(p.style, mode === 'hidden' ? { display: 'none' } : { display: '', left: l, top: t, width: w, height: h });
    };
    const sv = $('#split-v'), sh = $('#split-h');
    sv.hidden = true; sh.hidden = true;
    if (L.max) {
      for (const k of ['map', 'util', 'data']) set(`#${k}-pane`, k === L.max ? 'full' : 'hidden', '0', '0', '100%', '100%');
    } else {
      const topBoth = m.map && m.util;
      let topH, dataTop, dataH;
      if (m.data && topBoth) { topH = `${S}px`; dataTop = `${S + G}px`; dataH = `${S}px`; }
      else if (m.data) { topH = `calc(100% - ${S + G}px)`; dataTop = `calc(100% - ${S}px)`; dataH = `${S}px`; }
      else if (topBoth) { topH = `${S}px`; dataTop = `${S + G}px`; dataH = `calc(100% - ${S + G}px)`; }
      else { topH = `calc(${pct(L.fy)} - ${G / 2}px)`; dataTop = `calc(${pct(L.fy)} + ${G / 2}px)`; dataH = `calc(${pct(1 - L.fy)} - ${G / 2}px)`; }
      set('#data-pane', m.data ? 'head' : 'full', '0', dataTop, '100%', dataH);
      if (topBoth) {
        set('#map-pane', 'hstrip', '0', '0', `calc(50% - ${G / 2}px)`, topH);
        set('#util-pane', 'hstrip', `calc(50% + ${G / 2}px)`, '0', `calc(50% - ${G / 2}px)`, topH);
      } else if (m.map) {
        set('#map-pane', 'vstrip', '0', '0', `${S}px`, topH);
        set('#util-pane', 'full', `${S + G}px`, '0', `calc(100% - ${S + G}px)`, topH);
      } else if (m.util) {
        set('#map-pane', 'full', '0', '0', `calc(100% - ${S + G}px)`, topH);
        set('#util-pane', 'vstrip', `calc(100% - ${S}px)`, '0', `${S}px`, topH);
      } else {
        set('#map-pane', 'full', '0', '0', `calc(${pct(L.fx)} - ${G / 2}px)`, topH);
        set('#util-pane', 'full', `calc(${pct(L.fx)} + ${G / 2}px)`, '0', `calc(${pct(1 - L.fx)} - ${G / 2}px)`, topH);
        sv.hidden = false;
        Object.assign(sv.style, { left: `calc(${pct(L.fx)} - 5px)`, top: '0', width: '10px', height: topH });
      }
      if (!m.data && !topBoth) {
        sh.hidden = false;
        Object.assign(sh.style, { top: `calc(${pct(L.fy)} - 5px)`, left: '0', height: '10px', width: '100%' });
      }
    }
    this.updatePaneButtons();
    this.map?.invalidate();
  }

  updatePaneButtons() {
    const L = this.paneLayout();
    for (const b of $$('.pane-max')) {
      const on = L.max === b.dataset.pane, name = { map: 'the map', util: 'Survey, Tools and Settings', data: 'the data tables' }[b.dataset.pane];
      b.replaceChildren(el('span', { 'aria-hidden': 'true' }, on ? '❐' : '□'));
      b.title = on ? 'Restore (back to three panes)' : `Maximize ${name}`;
      b.setAttribute('aria-label', b.title);
    }
    for (const b of $$('.pane-min')) b.hidden = !!L.max;
    const dm = $('.pane-min[data-pane="data"]');
    if (dm && L.min.data) { dm.hidden = false; dm.replaceChildren(el('span', { 'aria-hidden': 'true' }, '▴')); dm.title = `Show the data tables (${MOD}+Shift+M)`; }
    else if (dm) { dm.replaceChildren(el('span', { 'aria-hidden': 'true' }, '▁')); dm.title = `Minimize the data tables (${MOD}+Shift+M)`; }
    if (dm) dm.setAttribute('aria-label', dm.title);
  }

  initSplitters() {
    const main = $('#main');
    const wire = (btn, key) => {
      const set = (v, now) => { const L = this.paneLayout(); L[key] = Math.max(0.15, Math.min(0.85, v)); this.savePaneLayout(L, now); };
      btn.addEventListener('pointerdown', (e) => {
        e.preventDefault();
        btn.setPointerCapture(e.pointerId);
        document.body.classList.add('pane-resizing');
        const r = main.getBoundingClientRect();
        const move = (ev) => {
          const v = key === 'fx' ? (ev.clientX - r.left) / r.width : (ev.clientY - r.top) / r.height;
          const L = this.paneLayout(); L[key] = Math.max(0.15, Math.min(0.85, v));
          this.S.config.settings.pane_layout = L; this.applyLayout();
        };
        const up = () => {
          btn.removeEventListener('pointermove', move); btn.removeEventListener('pointerup', up);
          document.body.classList.remove('pane-resizing');
          this.savePaneLayout(this.paneLayout(), true);
        };
        btn.addEventListener('pointermove', move); btn.addEventListener('pointerup', up);
      });
      btn.addEventListener('dblclick', () => set(key === 'fx' ? 0.62 : 0.5, true));
      btn.addEventListener('keydown', (e) => {
        const d = key === 'fx' ? { ArrowLeft: -0.02, ArrowRight: 0.02 }[e.key] : { ArrowUp: -0.02, ArrowDown: 0.02 }[e.key];
        if (d === undefined) return;
        e.preventDefault(); e.stopPropagation();
        set(this.paneLayout()[key] + d, false);
      });
    };
    wire($('#split-v'), 'fx');
    wire($('#split-h'), 'fy');
  }

  applyDisplay() {
    const d = this.S.config.display;
    document.documentElement.style.setProperty('--grid-font', `${+d.grid_font_size || 13}px`);
    document.documentElement.style.setProperty('--ui-font', `${+d.ui_font_size || 13}px`);
    document.documentElement.style.setProperty('--status-font', `${+d.status_font_size || +d.ui_font_size || 13}px`);
  }

  // ---------------------------------------------------------------- render
  renderAll() {
    for (const t of Object.keys(this.grids)) this.renderTab(t);
    for (const t of ['sightings', 'events', 'marks']) this.map.drawMarkers(t);
    this.map.drawTrack();
    this.map.loadOverlays(this.S.overlays);
    this.rendered = { fmt: this.S.config.settings.latlon_format, clock: this.clock() };
    this.map.updateVessel(this.S.vessel);
    this.updateStatus();
    this.renderPane(this.dataTab);
    this.renderPane(this.utilTab);
  }

  // draw one of the panes that aren't data tables
  renderPane(tab) {
    const f = { survey: this.renderSurvey, settings: this.renderSettings, shortcuts: this.renderShortcuts, dropdowns: this.renderDropdowns, nmea: this.renderNmea,
      inputs: this.renderInputs, templates: this.renderTemplates, overlays: this.renderOverlays, basemap: this.renderBasemap,
      qc: this.renderQc, summary: this.renderSummaryPane, resights: () => this.resightTool.render(), reports: () => this.reportsTool.render(), guide: this.renderGuide, about: this.renderAbout,
      route: () => this.planner.render() }[tab];
    if (f) f.call(this);
  }

  renderTab(tab) {
    const g = this.grids[tab];
    if (g) g.render();
    const t = this.S.tables[tab];
    const c = $(`#count-${tab}`);
    if (c) c.textContent = t.rows.length ? t.rows.length : '';
    const u = $(`#undo-${tab}`), r = $(`#redo-${tab}`);
    if (u) u.disabled = !t.can_undo;
    if (r) r.disabled = !t.can_redo;
    if (tab === 'sightings') this.updateResightButton();
  }

  // Add resight: only with a sighting selected
  selectedSighting() {
    const g = this.grids.sightings, id = g?.sel?.id;
    return id ? this.S.tables.sightings.rows.find((r) => r.RowID === id) || null : null;
  }

  updateResightButton() {
    const b = $('#btn-add-resight');
    if (!b) return;
    const r = this.selectedSighting();
    b.disabled = !r || !this.S.survey;
    b.textContent = r ? `Add resight of ${new Resights(this.S.tables.sightings.rows).original(r).SightNo}` : 'Add resight';
  }

  toastReadonly(col) { toast(`${col.label} is filled in by Spyhop and can’t be typed.`, 'info', 3000); }

  // Insert row…: before or after the selected row; time and position averaged or copied, with a note
  async insertRow(tab) {
    const g = this.grids[tab], id = g?.sel?.id;
    const rows = this.S.tables[tab].rows;
    if (!id || !rows.some((r) => r.RowID === id)) { toast('Select the row to insert next to first.', 'warn'); return; }
    const i = rows.findIndex((r) => r.RowID === id);
    const radio = (name, value, label, checked) => el('label', { class: 'check' },
      el('input', { type: 'radio', name, value, checked: !!checked }), el('span', {}, label));
    const label = (r) => r ? `${r.SightNo ? `sighting ${r.SightNo}` : r.EventNo ? `event ${r.EventNo}` : r.Effort ? r.Effort : r.Name || 'row'} at ${(timeParts(r.DateTime, this.clock()) || {}).time || '?'}` : 'none';
    const body = el('div', { id: 'insert-dialog' },
      el('p', {}, `Selected: ${label(rows[i])}.`),
      el('h4', {}, 'Where'),
      radio('ins-where', 'after', 'After the selected row', true), radio('ins-where', 'before', 'Before the selected row'),
      el('h4', {}, 'Time and position'),
      radio('ins-method', 'average', 'Average of the rows before and after', true),
      radio('ins-method', 'previous', 'Copied from the row before'),
      radio('ins-method', 'next', 'Copied from the row after'),
      radio('ins-method', 'time', 'Use this time and the nearest vessel position'),
      el('label', { class: 'row', id: 'ins-time-row' }, 'Time ', el('input', { type: 'text', id: 'ins-time', placeholder: 'e.g. 14:05 or 14:05:30', size: 14,
        onfocus: () => { body.querySelector('input[name=ins-method][value=time]').checked = true; between(); } })),
      el('p', { class: 'hint', id: 'ins-between' }),
      el('p', { class: 'hint' }, 'A note in Notes says how the time and position were filled in. Correct them afterwards if you know better.'));
    const between = () => {
      const where = body.querySelector('input[name=ins-where]:checked').value;
      const timed = body.querySelector('input[name=ins-method]:checked').value === 'time';
      const at = where === 'after' ? i + 1 : i;
      body.querySelectorAll('input[name=ins-where]').forEach((x) => { x.disabled = timed; });
      body.querySelector('#ins-between').textContent = timed ? 'A row at a typed time goes in time order (Where doesn’t apply); the day is the selected row’s.'
        : `Between ${label(rows[at - 1])} and ${label(rows[at])}.`;
    };
    body.addEventListener('change', between);
    between();
    const got = await modal({ title: `Insert a row: ${this.S.schema.tabs[tab].title}`, body,
      buttons: [{ label: 'Cancel', value: null }, { label: 'Insert', primary: true,
        value: () => ({ where: body.querySelector('input[name=ins-where]:checked').value, method: body.querySelector('input[name=ins-method]:checked').value,
          time: body.querySelector('#ins-time').value }) }] });
    if (!got) return;
    let res;
    try { res = await api(`/api/tab/${tab}/insert`, { id, ...got }); } catch { return; }
    (res.warnings || []).forEach((w) => toast(w, 'warn'));
    const t = this.S.tables[tab];
    if (!t.rows.some((x) => x.RowID === res.row.RowID)) {
      let at = got.where === 'after' ? i + 1 : i;
      if (got.method === 'time') { at = t.rows.findIndex((x) => new Date(x.DateTime) > new Date(res.row.DateTime)); if (at < 0) at = t.rows.length; }
      t.rows.splice(at, 0, res.row); t.can_undo = true; this.renderTab(tab); this.map.drawMarkers?.(tab);
    }
    this.grids[tab].select(res.row.RowID, 'DateTime');
  }

  async addResight() {
    const r = this.selectedSighting();
    if (!r) { toast('Select a sighting first: the resight is linked to it.', 'warn'); this.showTab('sightings'); return; }
    const key = this.grids.sightings.sel?.key || 'DateTime';
    let res;
    try { res = await api('/api/sightings/resight', { id: r.RowID }); } catch { return; }
    const t = this.S.tables.sightings;
    if (!t.rows.some((x) => x.RowID === res.row.RowID)) { t.rows.push(res.row); t.can_undo = true; this.renderTab('sightings'); this.map.drawMarkers('sightings'); }
    this.showTab('sightings');
    // the new row, in the column that was selected (the cursor doesn't jump to another column)
    const g = this.grids.sightings;
    g.select(res.row.RowID, key);
  }

  // is this tab the one showing in its pane? (Sightings/Effort/Events in the data pane, the others in
  // the Survey/Tools/Settings pane: one of each is showing at a time)
  shown(tab) { return tab === this.dataTab || tab === this.utilTab; }

  showTab(tab, { reveal = true } = {}) {
    if (!this.allTabs().includes(tab)) tab = 'sightings';
    const inData = this.topTabs().includes(tab);
    if (!inData && this.utilTab === 'route' && tab !== 'route') this.planner.hide();
    this.tab = tab;
    if (inData) this.dataTab = tab; else this.utilTab = tab;
    if (reveal) this.revealPaneOf(tab);
    const group = this.groupOf(tab);
    if (group) this.lastSub[group] = tab;
    try {
      localStorage.setItem(inData ? 'wsr.datatab' : 'wsr.utiltab', tab);
      if (group) localStorage.setItem('wsr.subtabs', JSON.stringify(this.lastSub));
    } catch {}
    if (inData) {
      $$('#tabs button[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
      $$('#data-body > .tab-pane').forEach((p) => p.classList.toggle('active', p.id === `pane-${tab}`));
    } else {
      $$('#util-tabs button').forEach((b) => b.classList.toggle('active', group ? b.dataset.group === group : b.dataset.tab === tab));
      $$('#subtabs button').forEach((b) => { b.classList.toggle('active', b.dataset.tab === tab); b.hidden = b.dataset.group !== group; });
      $('#util-pane')?.classList.toggle('survey-group', !!group);
      $$('#util-body > .tab-pane').forEach((p) => p.classList.toggle('active', p.id === `pane-${tab}`));
    }
    this.renderPane(tab);
    if (tab === 'route') this.planner.show();
    if (this.grids[tab]) {
      const g = this.grids[tab];
      if (g.pendingRender) g.render();
      g.wrap.focus({ preventScroll: true });
    }
    if (this.grids[tab]) this.showHelp(tab, this.grids[tab].sel?.key);
  }

  onRowSelected(tab, id) { this.map?.focusRow(tab, id); if (tab === 'sightings') this.updateResightButton(); }

  // Description of the selected column, shown in the bottom bar.
  showHelp(tab, key) {
    const box = $('#col-help');
    if (!box) return;
    const c = key && this.S.schema.tabs[tab]?.columns.find((x) => x.key === key);
    if (c && c.help) box.replaceChildren(el('b', {}, c.label), ` — ${c.help}`);
    else if (this.grids[tab]) box.replaceChildren(el('span', { class: 'hint' }, 'Click a cell to see what its column is for.'));
    else box.replaceChildren();
  }

  // select a row (and a column) in a data table, bringing its pane into view; flash: make it obvious (Error check → Show)
  selectRow(tab, id, key, { flash = false } = {}) {
    this.showTab(tab);
    const g = this.grids[tab];
    if (!g) return;
    if (!g.wrap.querySelector(`tr[data-id="${CSS.escape(id)}"]`)) g.render();       // drawn while hidden: draw it now
    // the column if it's shown (an optional column may be hidden), else the one already selected, else the first
    const shown = (k) => k && g.cols.some((c) => c.key === k);
    const col = shown(key) ? key : shown(g.sel?.key) ? g.sel.key : g.cols[0]?.key;
    g.select(id, col, { center: flash });
    if (flash) {
      const tr = g.wrap.querySelector(`tr[data-id="${CSS.escape(id)}"]`);
      tr?.classList.remove('flash'); void tr?.offsetWidth; tr?.classList.add('flash');
      // a redraw just after (a live update) mustn't lose the selection or the scroll
      requestAnimationFrame(() => { if (g.sel?.id === id && !g.td(id, col)?.classList.contains('sel')) g.select(id, col, { center: true, focus: false }); });
    }
  }

  // ---------------------------------------------------------------- live updates
  connect() {
    const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onopen = () => { if (this.wsOk === null) this.reload(); this.wsOk = true; this.updateStatus(); };
    ws.onclose = () => { this.wsOk = null; this.updateStatus(); if (!this.noReconnect) setTimeout(() => this.connect(), 2000); };
    ws.onmessage = (ev) => this.onMessage(JSON.parse(ev.data));
  }

  onMessage(m) {
    switch (m.type) {
      case 'vessel':
        this.S.vessel = m.vessel;
        if (m.vessel?.clock) {
          const before = this.clock();
          this.S.clock = m.vessel.clock;
          if (this.clock() !== before) this.onClockChanged();
        }
        this.map.updateVessel(m.vessel);
        if (m.nmea) { this.S.nmea = { ...this.S.nmea, ...m.nmea }; this.updateNmeaStatus(); this.updateRawLog(); }
        if (m.inst) { this.S.inst = m.inst; if (this.shown('nmea')) this.updateInstruments(); }
        this.planner.onVessel();
        if (m.prefetch) this.updatePrefetch(m.prefetch);
        break;
      case 'tab':
        this.S.tables[m.tab] = { rows: m.rows, can_undo: m.can_undo, can_redo: m.can_redo };
        if (this.qcReport && !this.qcStale) { this.qcStale = true; if (this.shown('qc')) this.renderQc(); }
        this.renderTab(m.tab);
        this.map.drawMarkers(m.tab);
        if (m.tab === 'effort') this.map.drawTrack();        // ERROR rows break the line
        if (this.shown('summary')) this.renderSummary();
        if (this.shown('resights') && m.tab === 'sightings') this.resightTool.render();
        this.reportsTool.onData(m.tab);
        this.updateStatus();
        break;
      case 'track':
        this.S.track.push(m.point);
        this.map.appendTrack(m.point);
        break;
      case 'settings': {
        const prev = this.S.config.settings;
        if (this._layoutPending) m.settings.column_layout = prev.column_layout;   // a newer layout is being saved
        this.S.config.settings = m.settings;
        if (this.S.survey) this.S.survey.tracking = !!m.settings.tracking_enabled;
        this.refreshFormats();
        for (const g of Object.values(this.grids)) g.refreshColumns?.();
        this.updateStatus();
        if (this.shown('survey') && !document.activeElement?.closest('#pane-survey input[type=text], #pane-survey textarea')) this.renderSurvey();
        if (this.shown('settings') && !document.activeElement?.closest('#pane-settings')) this.renderSettings();
        if (this.shown('nmea') && !document.activeElement?.closest('#pane-nmea')) this.renderNmea();
        if (this.shown('inputs') && !document.activeElement?.closest('#pane-inputs input[type=text], #pane-inputs input[type=number], #pane-inputs select')) this.renderInputs();
        if (this.shown('basemap') && !document.activeElement?.closest('#pane-basemap input, #pane-basemap select')) this.renderBasemap();
        if (this.shown('overlays')) this.renderOverlays();
        if (this.shown('templates') && !document.activeElement?.closest('#pane-templates input[type=text], #pane-templates textarea')) this.renderTemplates();
        if (this.shown('shortcuts')) this.renderShortcuts();
        break;
      }
      case 'display':
        this.S.config.display = m.display;
        this.applyDisplay();
        this.map.restyleOverlays();
        this.map.redrawData();
        this.map.updateVessel(this.S.vessel);
        this.grids.sightings?.render();          // resights nested or in time order
        if (this.shown('settings')) this.renderSettings();
        if (this.shown('resights')) this.resightTool.render();
        break;
      case 'notice': toast(m.text, m.level || 'info', m.level === 'error' ? 12000 : 5000); break;
      case 'awake':
        this.S.awake = m.awake;
        { const p = document.getElementById('awake-status'); if (p) p.textContent = this.awakeText(); }
        break;
      case 'update':
        this.updateInfo = m.info;
        toast(`Spyhop ${m.info.latest} is available: see Settings → About → Updates.`, 'info', 10000);
        if (this.shown('about')) this.renderAbout();
        break;
      case 'charts':
        this.S.mbtiles = m.mbtiles;
        this.map.syncCharts(m.mbtiles);
        this.renderChartList();
        break;
      case 'overlays': api('/api/bootstrap').then((d) => { this.S.overlays = d.overlays; this.S.surveys = d.surveys; this.map.loadOverlays(d.overlays); this.renderOverlays(); }); break;
      case 'reload': this.reload(); break;
      case 'closing': this.showClosing(m.message); break;
      case 'reports': this.reportsTool.onDefsChanged(); break;
      case 'routes': this.planner.loadSaved(); break;
      case 'feeds': this.online.loadFeeds(); break;
      default: break;
    }
  }

  // ---------------------------------------------------------------- status bar
  lastEffortRow() {
    const rows = this.S.tables.effort?.rows || [];
    let best = null;
    for (const r of rows) if (!best || r.DateTime > best.DateTime) best = r;
    return best;
  }

  updateStatus() {
    if (!this.S) return;
    const st = this.S.config.settings, v = this.S.vessel || {};
    const fmt = st.latlon_format;
    const now = timeParts(new Date(), this.clock());
    $('#sf-clock').textContent = `${now.time} ${now.abbr}`;
    $('#pos-text').textContent = v.lat !== null && v.lat !== undefined ? fmtPos(v.lat, v.lon, fmt) : 'No position';
    const flag = $('#pos-flag');
    flag.textContent = v.lost ? (v.lat === null ? ' NO GPS' : ' GPS LOST') : v.frozen ? ' NOT MOVING' : '';
    $('#sf-pos').classList.toggle('alert', !!(v.lost || v.frozen));
    $('#sf-nav').textContent = `${v.sog !== null && v.sog !== undefined ? v.sog.toFixed(1) : '—'} kn · COG ${fmtBrg(v.cog)} · HDG ${fmtBrg(v.best_heading)}`;
    // effort reminder
    const last = this.lastEffortRow();
    const rem = $('#sf-remind');
    const mins = +st.effort_reminder_min || 30;
    let overdue = false;
    if (!this.S.survey?.active) {
      rem.textContent = '';
    } else if (last && last.DateTime) {
      const due = new Date(last.DateTime).getTime() + mins * 60000;
      const left = (due - Date.now()) / 1000;
      overdue = left < 0;
      rem.textContent = overdue ? `Conditions check OVERDUE ${fmtDuration(-left)}` : `Next check ${fmtDuration(left)}`;
    } else rem.textContent = `Check every ${mins} min`;
    rem.classList.toggle('alert', overdue);
    $('#pane-effort')?.classList.toggle('overdue', overdue);
    $('#tabs [data-tab="effort"]')?.classList.toggle('overdue', overdue);
    const sv = this.S.survey;
    $('#sf-survey').textContent = !sv ? 'No survey open' : `Survey: ${sv.name}${sv.ended ? ' (ended)' : ''}`;
    const title = `Spyhop ${this.S.about?.spyhop || ''}${sv ? ` — ${sv.name}` : ''}`;
    if (document.title !== title) document.title = title;
    $('#sf-survey').classList.toggle('alert', !sv);
    const tr = $('#sf-track');
    const still = this.platformType() === 'Stationary';          // a stationary platform records no trackline
    tr.textContent = still && st.tracking_enabled ? '◆ Stationary (no trackline)' : st.tracking_enabled ? `● Tracking ${st.tracking_interval}s` : '○ Tracking off';
    tr.title = still ? 'A stationary platform doesn’t move, so Spyhop records only its Start and End positions, not a trackline.' : '';
    tr.classList.toggle('on', !!st.tracking_enabled);
    const eff = last?.Effort || '—';
    $('#sf-effort').replaceChildren('Effort ', el('span', { class: `pill ${isOn(eff) ? 'on' : 'off'}`, style: eff !== '—' ? { background: effortColor(eff), color: '#fff' } : null }, eff));
  }

  // Re-draw tables, popups and summary when the lat/lon format or clock (local/UTC) changes.
  refreshFormats() {
    const r = this.rendered || {};
    if (r.fmt !== this.S.config.settings.latlon_format || r.clock !== this.clock()) this.renderAll();
  }

  async saveSettings(updates, quiet = false) {
    Object.assign(this.S.config.settings, updates);
    if ('track_break_kn' in updates || 'track_break_gap_s' in updates) this.map.drawTrack();
    this.refreshFormats();
    this.updateStatus();
    try { await api('/api/settings', { updates }); } catch { if (!quiet) this.reload(); }
  }

  // column order and widths: saved one after another, and while a save is on its way a settings
  // broadcast from an earlier one doesn't put the old layout back
  saveColumnLayout(all) {
    this.S.config.settings.column_layout = all;
    this._layoutPending = (this._layoutPending || 0) + 1;
    this._layoutChain = (this._layoutChain || Promise.resolve())
      .then(() => api('/api/settings', { updates: { column_layout: all } })).catch(() => {})
      .finally(() => { this._layoutPending--; });
    return this._layoutChain;
  }

  async saveDisplay(updates) {
    try { await api('/api/display', { updates }); } catch {}
  }

  // ---------------------------------------------------------------- data actions
  async addRow(tab, prefill = {}, latlng = null) {
    if (!this.grids[tab]) return;
    if (tab !== 'marks' && !this.S.survey) {
      toast('No survey is open — start or open one in the Survey tab.', 'warn');
      this.showTab('survey');
      return;
    }
    const body = { prefill };
    if (latlng) {
      if (tab === 'sightings') { body.prefill = { ...prefill, SigLat: latlng.lat.toFixed(6), SigLon: latlng.lng.toFixed(6) }; }
      else { body.lat = latlng.lat; body.lon = latlng.lng; }
    }
    let res;
    try { res = await api(`/api/tab/${tab}/add`, body); } catch { return; }
    // make sure the grid has the new row even if the websocket update is still on its way
    const t = this.S.tables[tab];
    if (!t.rows.some((r) => r.RowID === res.row.RowID)) { t.rows.push(res.row); t.can_undo = true; this.renderTab(tab); this.map.drawMarkers(tab); }
    this.showTab(tab);
    const g = this.grids[tab];
    g.select(res.row.RowID, g.firstEmptyEditable(res.row));
  }

  async toggleEffort() {
    if (!this.S.survey) { toast('No survey is open — start or open one in the Survey tab.', 'warn'); this.showTab('survey'); return; }
    let res;
    try { res = await api('/api/toggle-effort', {}); } catch { return; }
    toast(`Effort ${res.row.Effort}`, 'info', 2500);
    const t = this.S.tables.effort;
    if (!t.rows.some((r) => r.RowID === res.row.RowID)) { t.rows.push(res.row); this.renderTab('effort'); }
    this.showTab('effort');
    this.grids.effort.select(res.row.RowID, 'Visibility');
  }



  async deleteRow(tab) {
    const g = this.grids[tab];
    const r = g?.sel && this.S.tables[tab].rows.find((x) => x.RowID === g.sel.id);
    if (!r) { toast('Select a row first (click a cell).', 'warn'); return; }
    const n = this.S.tables[tab].rows.indexOf(r) + 1;
    const what = r.SightNo ? `sighting ${r.SightNo}` : r.EventNo ? `event ${r.EventNo}` : `row ${n}`;
    if (!await confirmBox('Delete row?', `Delete ${what}? You can undo this.`, 'Delete', true)) return;
    try { await api(`/api/tab/${tab}/delete`, { id: r.RowID }); } catch {}
    const rows = this.S.tables[tab].rows;
    const next = rows[Math.min(n - 1, rows.length - 1)];
    if (next && next.RowID !== r.RowID) g.select(next.RowID, g.sel.key);
  }

  async undo(tab) {
    tab = tab || this.tab;
    if (!this.grids[tab]) return;
    try { const r = await api(`/api/tab/${tab}/undo`, {}); if (!r.done) toast('Nothing to undo', 'info', 1500); } catch {}
  }

  async redo(tab) {
    tab = tab || this.tab;
    if (!this.grids[tab]) return;
    try { const r = await api(`/api/tab/${tab}/redo`, {}); if (!r.done) toast('Nothing to redo', 'info', 1500); } catch {}
  }

  async newSurvey() {
    const cur = this.S.survey;
    if (cur?.active) {
      const how = await modal({ title: 'Current survey is still active',
        body: el('p', {}, `“${cur.prefix}” hasn’t ended yet. End it now (adds an End row), or just close it so it can be continued later?`),
        buttons: [{ label: 'Cancel', value: null }, { label: 'Close it (keep active)', value: 'close' },
          { label: 'End it', value: 'end', primary: true }] });
      if (!how) return;
      try { await api(`/api/survey/${how}`, {}); } catch { return; }
    }
    if (!await this.offerTemplateSave()) return;
    const last = this.S.config.settings.last_meta || {};
    const nameBox = el('input', { type: 'text', style: { width: '100%' } });
    const fields = {};
    const form = el('div', { class: 'meta-form' }, this.S.schema.survey_meta.filter(([k]) => k !== 'survey_notes').map(([k, label, hint]) => {
      const inp = k === 'platform_type'
        ? el('select', {}, ['', ...this.S.schema.fixed_lists.platform_type].map((o) => el('option', { value: o, selected: (last[k] || '') === o }, o || '—')))
        : el('input', { type: k.endsWith('email') ? 'email' : 'text', value: last[k] || '', placeholder: hint });
      fields[k] = inp;
      return el('label', {}, label, inp);
    }));
    const got = await modal({ title: 'Start new survey', width: 'min(640px, 94vw)',
      body: el('div', {},
        el('label', { class: 'stack' }, 'Survey name, in your team’s own naming convention (it becomes the start of the file names)', nameBox),
        el('h4', {}, 'Survey details'), form,
        el('p', { class: 'hint' }, 'Details are filled in from your last survey; you can change them later in the Survey tab. A Start row is added to the Effort tab and the trackline begins recording.')),
      buttons: [{ label: 'Cancel', value: null },
        { label: 'Start', primary: true, value: () => ({ name: nameBox.value, meta: Object.fromEntries(Object.entries(fields).map(([k, i]) => [k, i.value])) }) }],
      onOpen: () => { setTimeout(() => nameBox.focus(), 0); return true; } });
    if (!got) return;
    const name = got.name;
    this.pendingTab = 'effort';
    try {
      await api('/api/survey/start', { name, meta: got.meta });
      toast(`Started survey “${name}” — tracking is on`);
    } catch { this.pendingTab = null; }
  }

  async endSurvey() {
    const sv = this.S.survey;
    if (!sv) return;
    if (!await confirmBox('End survey?', `End “${sv.prefix}” now? An End row is added to the Effort tab and the trackline stops. You can still correct its data afterwards.`, 'End survey')) return;
    try { await api('/api/survey/end', {}); toast(`Survey “${sv.prefix}” ended`); } catch {}
  }

  async closeSurvey() {
    const sv = this.S.survey;
    if (!sv) return;
    const text = `Close “${sv.prefix}”? Everything is already saved. The tabs are cleared, and you can reopen it any time from the list below.` +
      (sv.active ? ' It stays active (it has no End row), so you can continue it later.' : '');
    if (!await confirmBox('Close survey?', text, 'Close survey')) return;
    try { await api('/api/survey/close', {}); toast(`Closed “${sv.prefix}”`); } catch {}
  }

  async openSurvey(sv) {
    let resume = false;
    const cur = this.S.survey;
    const closing = cur && !cur.current ? '' : '';
    const note = cur ? el('p', { class: 'hint' }, `“${cur.prefix}” will be closed first (its data is saved${cur.active ? ' and it stays active' : ''}).`) : null;
    if (sv.active) {
      const how = await modal({ title: 'Continue this survey?',
        body: el('div', {}, el('p', {}, `“${sv.prefix}” has no End record — it is still active. Continue it (tracking resumes), or just open it to look at or correct it?`), note),
        buttons: [{ label: 'Cancel', value: null }, { label: 'Just open it', value: 'open' },
          { label: 'Continue survey', value: 'continue', primary: true }] });
      if (!how) return;
      resume = how === 'continue';
    } else if (cur) {
      if (!await confirmBox('Open survey?', `Open “${sv.prefix}” (ended)? “${cur.prefix}” will be closed first (its data is saved${cur.active ? ' and it stays active' : ''}).`, 'Open')) return;
    }
    this.pendingFit = !resume;      // looking at an old survey: show all of it once it's loaded
    try {
      await api('/api/survey/open', { prefix: sv.prefix, resume });
      toast(resume ? `Continuing “${sv.prefix}” — tracking is on` : `Opened “${sv.prefix}”`);
    } catch { this.pendingFit = false; }
  }

  async askResume() {
    const p = this.S.resume_prompt;
    const how = await modal({ title: 'Continue the active survey?',
      body: el('div', {}, el('p', {}, `“${p}” was still active when Spyhop last closed (it has no End row).`),
        el('p', {}, 'Continue it now? Tracking resumes from here.')),
      buttons: [{ label: 'Close survey', value: 'close' }, { label: 'Not now', value: 'later' },
        { label: 'Continue survey', value: 'continue', primary: true }] });
    try { await api('/api/survey/resume', { action: how || 'later' }); } catch {}
    if (how === 'continue') toast(`Continuing “${p}” — tracking is on`);
  }

  async clearSurvey() {
    const sv = this.S.survey;
    if (!sv) return;
    const name = sv.prefix;
    if (!await confirmBox('Delete survey data?',
      `This permanently deletes the survey “${name}” from disk: its folder, with every sighting, effort, event and track record, its template copy, raw NMEA logs and exports. It is closed first. Save a survey package or export first if you need a copy.`, 'Continue…', true)) return;
    const typed = await promptBox('Really delete?', `Type the survey name “${name}” to confirm.`, '', 'Delete everything');
    if (typed === null) return;
    if (typed.trim() !== name) { toast('Name did not match — nothing was deleted.', 'warn'); return; }
    try { await api('/api/survey/clear', { confirm: typed.trim() }); toast('Survey data deleted'); } catch {}
  }

  async chooseDataFolder(path) {
    if (this.S.survey && !await confirmBox('Change data folder?',
      `Switching folders closes “${this.S.survey.prefix}” (its data is saved${this.S.survey.active ? ' and it stays active' : ''}). Surveys in the new folder are listed afterwards.`, 'Switch folder')) return;
    try {
      const r = await api('/api/data-dir', { path });
      this.dataDirDraft = null;
      toast(`Data folder: ${r.data_dir}`);
    } catch {}
  }

  async pickDataFolder() {
    let r;
    try { r = await api('/api/pick-folder', {}); } catch { return; }
    if (r.path) this.chooseDataFolder(r.path);
  }

  // Survey details (platform, organization, chief scientist), saved as you change them.
  metaForm(sv) {
    this.metaDraft = this.metaDraft || {};
    const meta = sv.meta || {};
    const save = (k, v) => api('/api/survey/meta', { updates: { [k]: v } })
      .then(() => { delete this.metaDraft[k]; }).catch(() => {});
    const notesVal = this.metaDraft.survey_notes ?? meta.survey_notes ?? '';
    const notesHint = (this.S.schema.survey_meta.find((m) => m[0] === 'survey_notes') || [])[2] || '';
    return el('div', {}, el('h4', {}, 'Survey details'),
      el('div', { class: 'meta-form' }, this.S.schema.survey_meta.filter(([k]) => k !== 'survey_notes').map(([k, label, hint]) => {
        const val = this.metaDraft[k] ?? meta[k] ?? '';
        const inp = k === 'platform_type'
          ? el('select', { onchange: (e) => save(k, e.target.value) },
            ['', ...this.S.schema.fixed_lists.platform_type].map((o) => el('option', { value: o, selected: val === o }, o || '—')))
          : el('input', { type: k.endsWith('email') ? 'email' : 'text', value: val, placeholder: hint,
            oninput: (e) => { this.metaDraft[k] = e.target.value; },
            onchange: (e) => save(k, e.target.value),
            onkeydown: (e) => { if (e.key === 'Enter') e.target.blur(); } });
        return el('label', {}, label, inp);
      })),
      // general notes or a summary of the survey: in the Summary and its HTML and PDF files
      el('label', { class: 'stack', for: 'survey-notes' }, 'Survey notes'),
      el('textarea', { id: 'survey-notes', class: 'meta-notes', placeholder: notesHint, value: notesVal,
        oninput: (e) => { this.metaDraft.survey_notes = e.target.value; },
        onchange: (e) => save('survey_notes', e.target.value) }),
      el('p', { class: 'hint help' }, 'Saved when you click away. Shown in the Summary and its HTML and PDF files.'));
  }

  // ---------------------------------------------------------------- survey tab
  renderSurvey() {
    const pane = $('#pane-survey');
    if (!pane) return;
    const S = this.S, sv = S.survey;
    const sec = (title, ...kids) => el('section', { class: 'settings-sec' }, el('h3', {}, title), ...kids);
    const when = (iso) => { const t = iso && timeParts(iso, this.clock()); return t ? `${t.date} ${t.time.slice(0, 5)} ${t.abbr}` : ''; };
    let current;
    if (!sv) {
      current = sec('Current survey',
        el('p', {}, el('b', {}, 'No survey open.'), ' Start a new survey, or open one from the list below.'),
        el('div', { class: 'btnrow' }, el('button', { class: 'primary', onclick: () => this.newSurvey() }, 'Start New Survey…')));
    } else {
      const status = sv.ended ? el('span', { class: 'pill off' }, 'Ended') : el('span', { class: 'pill on' }, 'Active');
      current = sec('Current survey',
        el('p', {}, el('b', { class: 'big' }, sv.prefix), ' ', status),
        el('table', { class: 'summary kv' }, el('tbody', {},
          el('tr', {}, el('th', {}, 'Started'), el('td', {}, when(sv.start_time) || '—')),
          sv.ended ? el('tr', {}, el('th', {}, 'Ended'), el('td', {}, when(sv.end_time))) : null,
          el('tr', {}, el('th', {}, 'Trackline'), el('td', {}, sv.active ? (S.config.settings.tracking_enabled ? '● recording' : '○ not recording ') : 'stopped',
            sv.active && !S.config.settings.tracking_enabled
              ? el('button', { onclick: () => this.saveSettings({ tracking_enabled: true }).then(() => toast('Tracking resumed')) }, 'Resume tracking') : null)),
          el('tr', {}, el('th', {}, 'Folder'), el('td', {}, el('span', { class: 'mono' }, sv.prefix), ' in the data folder · ',
            el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.open('survey'); } }, 'Open folder'))),
          el('tr', { id: 'survey-template-row' }, el('th', {}, 'Template'), el('td', {}, this.surveyTemplateLine(sv))))),
        this.surveyTemplateNote(sv),
        this.metaForm(sv),
        el('div', { class: 'btnrow' },
          sv.active ? el('button', { class: 'primary', onclick: () => this.endSurvey() }, 'End Survey…') : null,
          el('button', { onclick: () => this.closeSurvey() }, 'Close Survey…'),
          el('button', { onclick: () => this.newSurvey() }, 'Start New Survey…'),
          el('button', { onclick: () => this.exportData() }, 'Export Data…'),
          el('button', { id: 'btn-save-package', title: 'Save this survey and the template it was recorded with in one file, to open it in Spyhop on another computer', onclick: () => this.savePackage() }, 'Save Survey Package…'),
          el('button', { class: 'danger-outline', onclick: () => this.clearSurvey() }, 'Delete Survey Data…')),
        sv.ended ? el('p', { class: 'hint' }, 'This survey has ended, so no new rows can be added. You can still correct its data. To continue it, delete its End row in the Effort tab.') : null);
    }
    const rows = S.surveys || [];
    const list = sec('Surveys in this folder',
      rows.length ? el('table', { class: 'summary survey-list' },
        el('thead', {}, el('tr', {}, ['Survey', 'Status', 'Started', 'Ended', 'Sightings', ''].map((h) => el('th', {}, h)))),
        el('tbody', {}, rows.map((r) => el('tr', { class: r.current ? 'current' : null },
          el('td', {}, r.prefix),
          el('td', {}, el('span', { class: `pill ${r.active ? 'on' : 'off'}` }, r.active ? 'Active' : 'Ended')),
          el('td', {}, when(r.start_time)), el('td', {}, when(r.end_time)), el('td', {}, String(r.sightings)),
          el('td', {}, r.current ? el('b', {}, 'open now') : el('button', { onclick: () => this.openSurvey(r) }, 'Open'))))))
        : el('p', { class: 'hint' }, 'No surveys in this folder yet.'),
      el('div', { class: 'btnrow' },
        el('button', { id: 'btn-open-package', title: 'Open a survey saved with Save Survey Package (a .spyhop-survey.zip file): it is added to this data folder with its template', onclick: () => this.openPackage() }, 'Open Survey Package…'),
        el('button', { id: 'btn-surveys-refresh', title: 'Read the survey data folder again (e.g. after copying survey folders into it)',
          onclick: () => this.refreshFolders() }, 'Refresh')),
      el('p', { class: 'hint help' }, 'Each survey is a folder in the data folder, holding its tables, survey details, instrument readings, a copy of the template it was started with, its raw NMEA logs and its exports.'));
    const folder = sec('Folders',
      el('p', { id: 'survey-folder-link' }, 'Surveys are saved in ', el('span', { class: 'mono' }, S.config.data_dir), '. ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.open('datafolder'); } }, 'Open folder'), ' · ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.showTab('settings'); setTimeout(() => $('#settings-folders')?.scrollIntoView({ block: 'start' }), 50); } },
          'Change it in Settings → General → Folders')));
    pane.replaceChildren(...[current, folder, list].filter(Boolean));
  }

  // Settings → General → Folders: the survey data folder (can be changed) and Spyhop's own folder
  foldersSection() {
    const S = this.S;
    const dd = S.config.data_dir, isDefault = dd === S.config.default_data_dir;
    const pathBox = el('input', { type: 'text', value: this.dataDirDraft ?? dd, style: { flex: '1', minWidth: '18em' },
      oninput: (e) => { this.dataDirDraft = e.target.value; },
      onkeydown: (e) => { if (e.key === 'Enter') this.chooseDataFolder(e.target.value); } });
    return el('section', { class: 'settings-sec', id: 'settings-folders' }, el('h3', {}, 'Folders'),
      el('h4', {}, 'Survey data folder'),
      el('p', {}, 'Surveys (a folder each, with their exports and raw NMEA logs) and waypoints are saved in ', el('span', { class: 'mono' }, dd),
        isDefault ? el('span', { class: 'hint' }, ' (the default, inside Spyhop’s own folder)') : null, '. ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.open('datafolder'); } }, 'Open folder')),
      el('div', { class: 'btnrow' }, el('button', { onclick: () => this.pickDataFolder() }, 'Choose folder…'),
        isDefault ? null : el('button', { onclick: () => this.chooseDataFolder('') }, 'Use the default')),
      el('div', { class: 'btnrow' }, el('label', { class: 'inline', style: { flex: '1' } }, 'Or type a path:', pathBox),
        el('button', { onclick: () => this.chooseDataFolder(pathBox.value) }, 'Use this folder')),
      el('p', { class: 'hint help' }, 'Pick a backed-up folder if you like. Spyhop remembers it between sessions. Your lists (species, observers…), settings and templates stay in Spyhop’s own folder.'),
      el('h4', {}, 'Spyhop folder'),
      el('p', {}, 'Spyhop’s own files are in ', el('span', { class: 'mono' }, S.config.root), '. ',
        el('a', { href: '#', id: 'open-app-folder', onclick: (e) => { e.preventDefault(); this.open('app'); } }, 'Open folder')),
      el('p', { class: 'hint help' }, 'It holds templates/ (current: the current template, i.e. the lists, shortcuts and spyhop-config.json with the shared settings, map display and saved reports; saved: your saved templates; backups), spyhop-local.json (this computer’s own settings), offline charts, map overlays, routes, map feeds, the tile cache and logs. Spyhop always uses this folder.'));
  }

  // the template a survey was recorded with (a copy is kept in its folder since 0.36)
  surveyTemplateLine(sv) {
    const t = sv.template || {};
    if (!t.saved) return el('span', { class: 'hint' }, 'No copy kept (the survey was started before Spyhop 0.36)', t.name ? `; it was started with “${t.name}”` : '', '.');
    return el('span', {}, t.name ? `“${t.name}”` : 'unnamed (not saved as a template)', el('span', { class: 'hint' }, ' — a copy is kept with the survey. '),
      t.differs?.length ? el('span', { class: 'warn-text' }, 'Differs from the current template.') : el('span', { class: 'ok' }, 'Same as the current template.'));
  }

  surveyTemplateNote(sv) {
    const t = sv.template || {};
    if (!t.saved || !t.differs?.length) return null;
    return el('div', { class: 'warnbox', id: 'survey-template-note' },
      el('p', {}, el('b', {}, 'This survey was recorded with a different template. '),
        `Its data part (the lists and data settings) differs from the current template in: ${t.differs.join(', ')}. The data aren’t changed either way, but the drop-downs and the Error check use the current template, so values that aren’t in its lists are flagged.`),
      el('div', { class: 'btnrow' },
        el('button', { id: 'btn-use-survey-template', onclick: () => this.useSurveyTemplate(sv) }, 'Compare and use the survey’s template…')));
  }

  async useSurveyTemplate(sv) {
    this.showTab('templates');
    await this.loadTemplates?.();
    await this.checkTemplate({ survey: sv.prefix });
  }

  async savePackage() {
    const sv = this.S.survey;
    if (!sv) return;
    const logs = el('input', { type: 'checkbox', id: 'pkg-logs' });
    const ok = await modal({ title: 'Save survey package', body: el('div', {},
      el('p', {}, `Saves “${sv.prefix}” as `, el('span', { class: 'mono' }, `${sv.prefix}.spyhop-survey.zip`),
        ': its tables, survey details, instrument readings and the template it was recorded with, ready to open in Spyhop on another computer (Survey → Open Survey Package…). ',
        sv.active ? 'The survey is still active: the package holds it as it is now.' : ''),
      el('label', { class: 'check' }, logs, el('span', {}, 'Include the raw NMEA logs (they can be large)')),
      el('p', { class: 'hint help' }, 'Exports aren’t included. For analysis, use Export Data instead.')),
    buttons: [{ label: 'Cancel', value: false }, { label: 'Save', value: true, primary: true }] });
    if (!ok) return;
    let r;
    try { r = await api('/api/survey/package/save', { logs: logs.checked }); } catch { return; }
    const a = el('a', { href: r.url, download: r.name }); document.body.append(a); a.click(); a.remove();
    const mb = r.size > 1e6 ? `${(r.size / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(r.size / 1024))} KB`;
    await modal({ title: 'Survey package saved', body: el('p', {}, `Saved ${r.name} (${mb}) in the survey’s exports folder, and downloaded a copy.`),
      buttons: [{ label: 'Open exports folder', value: () => this.open('exports') }, { label: 'Done', primary: true, value: true }] });
  }

  openPackage() {
    const input = el('input', { type: 'file', accept: '.zip' });
    input.onchange = async () => {
      const f = input.files[0];
      if (!f) return;
      const cur = this.S.survey;
      if (cur && !await confirmBox('Open survey package?', `Open the survey in ${f.name}? “${cur.prefix}” will be closed first (its data is saved${cur.active ? ' and it stays active' : ''}).`, 'Open')) return;
      let name = '';
      for (;;) {
        const fd = new FormData();
        fd.append('file', f, f.name);
        if (name) fd.append('name', name);
        let r;
        try { r = await fetch('/api/survey/package/open', { method: 'POST', body: fd }).then((x) => x.json()); } catch { toast('Couldn’t reach Spyhop', 'error'); return; }
        if (!r.ok) { toast(r.error, 'error', 8000); return; }
        if (r.exists) {
          const v = await promptBox('That name is taken', `There’s already a survey called “${r.survey}” in this data folder, and it isn’t overwritten. Open the package under another name:`, r.suggest, 'Open');
          if (v === null || !v.trim()) return;
          name = v.trim();
          continue;
        }
        this.pendingFit = true;
        const m = r.manifest || {};
        toast(`Opened “${r.opened}”${r.renamed_from ? ` (saved as “${r.renamed_from}” in the package)` : ''}${m.made_with ? ` — packaged with Spyhop ${m.made_with}` : ''}`, 'info', 6000);
        this.showTab('survey');
        return;
      }
    };
    input.click();
  }

  async exportData() {
    const sv = this.S.survey;
    if (!sv) { toast('Open a survey to export it.', 'warn'); return; }
    const FORMATS = [
      ['csv', 'Separate CSV files', 'Sightings, effort, events, track, instrument readings, survey details and waypoints — one file each, as Spyhop records them.'],
      ['merged', 'Merged CSV file', 'Sightings, effort, events and track points in one file in time order, with the survey details and the effort and conditions at the time on every row.'],
      ['gpx', 'GPX file', 'Track and waypoints for GPS units, plotters and mapping apps.'],
      ['geojson', 'GeoJSON file', 'Track (split by effort) and points with all their columns, for QGIS or ArcGIS.'],
      ['html', 'Summary report', 'Tools → Summary, with an interactive map (in the HTML file).'],
    ];
    const REPORTS = (await this.reportsTool.loadDefs(true))
      .map((f) => [`report:${f.file}`, `Report: ${f.name}`, `${this.reportsTool.describe(f)} Saved as CSV.`]);
    const pdfOk = !!this.reportsTool.defs?.pdf;
    let reportAs;
    try { reportAs = localStorage.getItem('wsr.exportReportAs') || 'html'; } catch { reportAs = 'html'; }
    if (!pdfOk) reportAs = 'html';
    const asSel = el('select', { onchange: () => update() },
      [['html', 'HTML'], ['pdf', 'PDF'], ['both', 'HTML and PDF']].map(([v, l]) => el('option', { value: v, selected: v === reportAs, disabled: v !== 'html' && !pdfOk }, l)));
    let chosen;
    try { chosen = JSON.parse(localStorage.getItem('wsr.exportFormats') || 'null'); } catch {}
    if (!Array.isArray(chosen)) chosen = ['csv', 'merged', 'gpx', 'geojson', 'html'];
    const boxes = {};
    const note = el('p', { class: 'hint' });
    const okBtn = () => document.querySelector('.modal-buttons button.primary');
    const update = () => {
      const n = Object.values(boxes).filter((b) => b.checked).length;
      const both = asSel.value === 'both' && boxes.html.checked;
      note.textContent = !n ? 'Choose at least one format.'
        : n > 1 || boxes.csv.checked || both ? 'The files are saved together in one zip file.' : 'Saved as a single file.';
      const b = okBtn(); if (b) b.disabled = !n;
    };
    const body = el('div', { class: 'export-choices' },
      el('p', {}, `Export “${sv.prefix}” as:`),
      ...FORMATS.map(([k, label, hint]) => {
        boxes[k] = el('input', { type: 'checkbox', checked: chosen.includes(k), onchange: update });
        return el('label', { class: 'check' }, boxes[k], el('span', {}, el('b', {}, label), el('br'), el('span', { class: 'hint' }, hint)));
      }),
      REPORTS.length ? el('h4', {}, 'Saved reports (Tools → Reports)') : null,
      REPORTS.length && sv.active ? el('p', { class: 'hint', id: 'export-reports-locked' }, 'Saved reports can be exported once the survey ends.') : null,
      ...REPORTS.map(([k, label, hint]) => {
        boxes[k] = el('input', { type: 'checkbox', checked: chosen.includes(k) && !sv.active, disabled: !!sv.active, onchange: update });
        return el('label', { class: 'check' }, boxes[k], el('span', {}, el('b', {}, label), el('br'), el('span', { class: 'hint' }, hint)));
      }),
      el('label', { class: 'row' }, 'Save the summary as ', asSel,
        pdfOk ? null : el('span', { class: 'hint' }, ' (PDF needs Google Chrome or Microsoft Edge)')),
      note);
    const ok = await modal({ title: 'Export data', body, width: '34em',
      onOpen: () => { setTimeout(update, 0); return false; },
      buttons: [{ label: 'Cancel', value: false }, { label: 'Export', primary: true, value: true }] });
    if (!ok) return;
    const formats = [...FORMATS, ...REPORTS].map(([k]) => k).filter((k) => boxes[k].checked);
    if (!formats.length) return;
    const report_as = asSel.value === 'both' ? ['html', 'pdf'] : [asSel.value];
    try { localStorage.setItem('wsr.exportFormats', JSON.stringify(formats)); localStorage.setItem('wsr.exportReportAs', asSel.value); } catch {}
    if (report_as.includes('pdf') && formats.includes('html')) toast('Making the PDF (a few seconds)…', 'info', 4000);
    let html, html_pdf;
    if (formats.includes('html')) {
      this.renderSummaryPane();
      try {
        html = await buildSummaryHtml(this);
        if (report_as.includes('pdf')) html_pdf = await buildSummaryHtml(this, { pdf: true });   // the printed version
      } catch (e) { toast(`Couldn't build the HTML summary: ${e.message}`, 'error'); return; }
    }
    let r;
    try { r = await api('/api/export', { formats, html, html_pdf, report_as }); } catch { return; }
    const a = el('a', { href: r.url, download: r.name });
    document.body.append(a); a.click(); a.remove();
    await modal({ title: 'Export complete', body: el('div', {},
      el('p', {}, r.zip ? 'Saved as one zip file:' : 'Saved:'),
      el('p', { class: 'mono' }, r.path),
      el('p', {}, 'A copy is downloading now.')),
      buttons: [{ label: 'Open exports folder', value: () => this.open('exports') }, { label: 'Done', primary: true, value: true }] });
  }

  // ---------------------------------------------------------------- quality control
  renderQc() {
    const pane = $('#pane-qc');
    if (!pane) return;
    const sv = this.S.survey;
    pane.replaceChildren(sv ? this.qcSection(sv) : el('section', { class: 'settings-sec' }, el('h3', {}, 'Error check'),
      el('p', {}, 'Open a survey (in Survey) to check it.')));
  }

  qcSection(sv) {
    if (!sv) return null;
    const rep = this.qcReport?.survey === sv.prefix ? this.qcReport : null;
    const f = this.qcFilter || (this.qcFilter = { error: true, warning: true, info: true });
    const LEVEL = { error: 'Error', warning: 'Warning', info: 'Note' };
    const kids = [el('p', { class: 'hint help' }, 'Checks this survey for missing survey details, blank required fields and values that look wrong. It doesn’t change anything — click Show to go to a row and fix it there.'),
      el('div', { class: 'btnrow' }, el('button', { class: 'primary', onclick: () => this.runQc() }, rep ? 'Run the check again' : 'Run error check'),
        rep ? el('button', { onclick: () => this.saveQcReport() }, 'Save report…') : null)];
    if (rep) {
      const t = timeParts(rep.generated, this.clock());
      const c = rep.counts;
      kids.push(el('p', {}, `Checked ${t.time.slice(0, 5)} ${t.abbr}: ${rep.checked.sightings} sightings, ${rep.checked.effort} effort rows, ${rep.checked.events} events, ${rep.checked.track} track points. `,
        el('span', { class: 'qc-pill error' }, `${c.error} error${c.error === 1 ? '' : 's'}`), ' ',
        el('span', { class: 'qc-pill warning' }, `${c.warning} warning${c.warning === 1 ? '' : 's'}`), ' ',
        el('span', { class: 'qc-pill info' }, `${c.info} note${c.info === 1 ? '' : 's'}`),
        this.qcStale ? el('span', { class: 'hint' }, ' · the data has changed since — run it again to update.') : null));
      if (!rep.issues.length) kids.push(el('p', { class: 'qc-ok' }, '✓ No problems found.'));
      else {
        kids.push(el('div', { class: 'btnrow' }, el('span', { class: 'hint' }, 'Show:'),
          ...['error', 'warning', 'info'].map((k) => el('label', { class: 'inline' }, el('input', { type: 'checkbox', checked: f[k],
            onchange: (e) => { f[k] = e.target.checked; this.renderQc(); } }), `${LEVEL[k]}s (${c[k]})`))));
        const shown = rep.issues.filter((x) => f[x.level]);
        const when = (iso) => { const p = iso && timeParts(iso, this.clock()); return p ? `${p.time.slice(0, 5)} ${p.abbr}` : ''; };
        kids.push(el('table', { class: 'summary qc-table' },
          el('thead', {}, el('tr', {}, ['', 'Where', 'Time', 'Problem', ''].map((h) => el('th', {}, h)))),
          el('tbody', {}, shown.map((x) => el('tr', { class: `qc-${x.level}` },
            el('td', {}, el('span', { class: `qc-pill ${x.level}` }, LEVEL[x.level])),
            el('td', {}, x.label || x.tab),
            el('td', { class: 'mono' }, when(x.time)),
            el('td', { title: `Check: ${x.check}` }, x.message),
            el('td', { class: 'nowrap' }, x.row_id || x.tab === 'survey' ? el('button', { onclick: () => this.showQcIssue(x) }, 'Show') : null,
              x.fix ? el('button', { class: 'primary', title: 'Add an ERROR row to the Effort table for this stretch, so it is left out of the trackline and the effort time and distance',
                onclick: () => this.fixQcIssue(x) }, 'Fix') : null))))));
        if (shown.length < rep.issues.length) kids.push(el('p', { class: 'hint' }, `${rep.issues.length - shown.length} hidden by the Show filter.`));
      }
      kids.push(el('details', {}, el('summary', {}, 'What is checked'),
        el('ul', { class: 'qc-checks' }, rep.checks.map(([name, what]) => el('li', {}, el('b', {}, name), ' — ', what)))));
    }
    return el('section', { class: 'settings-sec', id: 'qc-section' }, el('h3', {}, 'Error check'), ...kids);
  }

  async fixQcIssue(x) {
    let r;
    try { r = await api('/api/qc/fix', { fix: x.fix }); } catch { return; }
    toast(`Added ${r.added === 1 ? 'an ERROR row' : 'an ERROR row and a row putting the effort back'} to the Effort table.`, 'info', 6000);
    await this.runQc();
  }

  async runQc() {
    let r;
    try { r = await api('/api/qc', {}); } catch { return; }
    this.qcReport = r.report;
    this.qcStale = false;
    this.renderQc();
    const c = r.report.counts;
    const n = (k, w) => `${c[k]} ${w}${c[k] === 1 ? '' : 's'}`;
    toast(c.error + c.warning ? `Error check: ${n('error', 'error')}, ${n('warning', 'warning')}, ${n('info', 'note')}` : 'Error check: no problems found');
  }

  showQcIssue(x) {
    if (x.tab === 'survey') {
      this.showTab('survey');
      const inp = [...$$('#pane-survey .meta-form label')].find((l) => l.querySelector('input,select') && this.S.schema.survey_meta.find((m) => m[0] === x.column && l.textContent.startsWith(m[1])));
      const box = inp?.querySelector('input,select');
      if (box) { box.scrollIntoView({ block: 'center' }); box.focus(); }
      return;
    }
    if (!x.row_id || !this.grids[x.tab]) return;
    if (!this.S.tables[x.tab].rows.some((r) => r.RowID === x.row_id)) { toast('That row no longer exists — run the check again.', 'warn'); return; }
    this.selectRow(x.tab, x.row_id, x.column, { flash: true });
  }

  saveQcReport() {
    const rep = this.qcReport;
    if (!rep) return;
    const q = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const lines = [['Level', 'Check', 'Tab', 'Where', 'Time', 'Column', 'Problem'].join(',')]
      .concat(rep.issues.map((x) => [x.level, x.check, x.tab, x.label, x.time, x.column, x.message].map(q).join(',')));
    const stamp = rep.generated.slice(0, 19).replace(/[-:]/g, '').replace('T', '-');
    const a = el('a', { href: URL.createObjectURL(new Blob([lines.join('\r\n') + '\r\n'], { type: 'text/csv' })), download: `${rep.survey}_QC_${stamp}.csv` });
    document.body.append(a); a.click(); a.remove();
  }

  renderAbout() {
    const pane = $('#pane-about');
    if (!pane) return;
    pane.replaceChildren(this.aboutSection());
  }

  // Settings → Guide: the tutorial (docs/TUTORIAL.md); it doesn't change, so it's drawn once
  renderGuide() {
    const pane = $('#pane-guide');
    if (!pane || pane.querySelector('#tutorial-section .tutorial h3, #tutorial-section .tutorial h4')) return;
    const tut = el('div', { class: 'tutorial' }, el('p', { class: 'hint' }, 'Loading the guide…'));
    pane.replaceChildren(el('section', { class: 'settings-sec', id: 'tutorial-section' }, tut));
    fetch('/api/tutorial').then((r) => r.text()).then((md) => {
      // drop the sentence that points back to this tab
      const nodes = renderMarkdown(md.replace(/ It's also in Spyhop itself, under \*\*Settings → (?:Guide|About)\*\*\./, ''));
      tut.replaceChildren(...(nodes.length ? nodes : [el('p', { class: 'hint' }, 'The guide (docs/TUTORIAL.md) is missing.')]));
      this.guideContents(tut);
    }).catch(() => {});
  }

  // the Guide's contents (0.39): a list of its sections beside it (above it in a narrow pane);
  // the section being read is highlighted
  guideContents(tut) {
    const heads = [...tut.querySelectorAll('h4')];
    if (heads.length < 2) return;
    const links = heads.map((h, i) => {
      h.id = `guide-${i + 1}`;
      return el('a', { href: `#${h.id}`, 'data-sec': h.id, onclick: (e) => {
        e.preventDefault();
        h.scrollIntoView({ behavior: 'smooth', block: 'start' });
        mark(h.id);
      } }, h.textContent);
    });
    const top = el('a', { href: '#', class: 'guide-top', onclick: (e) => { e.preventDefault(); wrap.scrollIntoView({ behavior: 'smooth', block: 'start' }); } }, '↑ Top');
    const nav = el('nav', { class: 'guide-toc', 'aria-label': 'Guide contents' }, el('b', {}, 'Contents'), el('ol', {}, links.map((a) => el('li', {}, a))), top);
    const mark = (id) => links.forEach((a) => a.classList.toggle('active', a.dataset.sec === id));
    const wrap = el('div', { class: 'guide-wrap' }, nav, tut.cloneNode(false));
    const body = wrap.lastChild;
    body.append(...tut.childNodes);
    tut.replaceWith(wrap);
    mark(heads[0].id);
    try {
      const seen = new Map();
      const io = new IntersectionObserver((ents) => {
        ents.forEach((e) => seen.set(e.target.id, e.isIntersecting ? e.boundingClientRect.top : null));
        const vis = heads.filter((h) => seen.get(h.id) != null);
        if (vis.length) mark(vis[0].id);
      }, { rootMargin: '0px 0px -60% 0px' });
      heads.forEach((h) => io.observe(h));
    } catch { /* no IntersectionObserver: no highlight */ }
  }

  aboutSection() {
    const a = this.S.about || {};
    const kv = (k, v) => el('tr', {}, el('th', {}, k), el('td', {}, v));
    const notes = el('div', { class: 'changelog' });
    const det = el('details', { ontoggle: () => {
      if (!det.open || notes.childElementCount) return;
      fetch('/api/changelog').then((r) => r.text()).then((md) => notes.replaceChildren(...renderMarkdown(md))).catch(() => {});
    } }, el('summary', {}, 'What’s new (changelog)'), notes);
    return el('section', { class: 'settings-sec', id: 'about-section' }, el('h3', {}, 'About Spyhop'),
      el('p', {}, el('b', { class: 'big' }, `Spyhop ${a.spyhop || ''}`), el('span', { class: 'hint' }, `  released ${a.spyhop_date || ''}`)),
      el('table', { class: 'summary kv' }, el('tbody', {},
        kv('Python', `${a.python || ''}`), kv('System', a.system || ''),
        kv('Program folder', el('span', { class: 'mono' }, a.program_folder || '')),
        kv('Spyhop’s folder', el('span', { class: 'mono' }, a.spyhop_folder || '')),
        kv('Diagnostic logs', el('span', {}, el('span', { class: 'mono' }, a.log_folder || ''), ' ',
          el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.open('logs'); } }, 'Open folder'))))),
      el('p', { class: 'hint help' }, 'Spyhop keeps diagnostic logs of what it did, how fast it was and any errors, never survey data. If something goes wrong, Save diagnostics… makes a zip of the logs, settings, a listing of Spyhop’s folders and system details (no survey data, team or observer names) to send with a bug report.'),
      el('div', { class: 'btnrow' }, el('button', { onclick: () => this.saveDiagnostics() }, 'Save diagnostics…')),
      det,
      this.updatesSection(),
      this.uninstallSection());
  }

  // ---------------------------------------------------------------- updates (updater.py)
  // ---------------------------------------------------------------- Settings → About → Uninstall or reinstall
  uninstallSection() {
    return el('section', { class: 'settings-sec', id: 'uninstall-section' }, el('h3', {}, 'Uninstall or reinstall'),
      el('p', {}, 'Reinstall replaces the program with a clean copy of the latest version from GitHub (it needs an internet connection) and sets up its Python packages again; your surveys are kept, and so are your settings unless you choose to reset them. Uninstall removes the program and its shortcuts from this computer; your settings and surveys are deleted only if you tick them.'),
      el('div', { class: 'btnrow' },
        el('button', { id: 'btn-reinstall', onclick: () => this.uninstallDialog('reinstall') }, 'Reinstall a clean copy…'),
        el('button', { id: 'btn-uninstall', class: 'danger-outline', onclick: () => this.uninstallDialog('uninstall') }, 'Uninstall Spyhop…')));
  }

  async uninstallDialog(mode) {
    const re = mode === 'reinstall';
    const opts = { mode, delete_settings: false, delete_data: false };
    const size = (n) => (n > 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n > 1e6 ? `${(n / 1e6).toFixed(0)} MB` : n > 1e3 ? `${(n / 1e3).toFixed(0)} KB` : '');
    const planBox = el('div', { class: 'uninstall-plan' });
    const typed = el('input', { type: 'text', id: 'uninstall-confirm', placeholder: 'DELETE', size: 10, disabled: true, autocomplete: 'off',
      oninput: () => check() });
    const setBox = el('input', { type: 'checkbox', id: 'uninstall-settings', onchange: (e) => { opts.delete_settings = e.target.checked; refresh(); } });
    const dataBox = el('input', { type: 'checkbox', id: 'uninstall-data', onchange: (e) => { opts.delete_data = e.target.checked; typed.disabled = !e.target.checked; if (!e.target.checked) typed.value = ''; refresh(); } });
    let plan = null, go = null;
    const check = () => {
      if (!go) return;
      const needType = opts.delete_data && plan?.default_data;
      go.disabled = !plan || plan.problems.length > 0 || plan.survey_active || (needType && typed.value.trim() !== plan.confirm_data);
    };
    const refresh = async () => {
      try { plan = (await api('/api/uninstall/plan', opts)).plan; } catch { return; }
      const row = (x) => el('li', {}, el('b', {}, x.what), size(x.size) ? ` (${size(x.size)})` : '', el('div', { class: 'mono hint' }, x.path));
      planBox.replaceChildren(
        plan.problems.length ? el('div', { class: 'cell-err' }, ...plan.problems.map((t) => el('p', {}, '⚠ ', t))) : null,
        plan.survey_active ? el('p', { class: 'cell-err' }, '⚠ A survey is under way: end it in the Survey tab first.') : null,
        el('p', {}, el('b', {}, re ? 'Deleted and replaced:' : 'Deleted:')), el('ul', {}, plan.delete.map(row)),
        plan.keep.length ? el('p', {}, el('b', {}, 'Kept:')) : null, plan.keep.length ? el('ul', {}, plan.keep.map(row)) : null);
      check();
    };
    const body = el('div', {},
      el('p', {}, re
        ? 'Spyhop closes, downloads a clean copy of the latest version, replaces its program folder with it (Python packages are set up again when it starts) and opens again in a new window.'
        : 'Spyhop closes and removes itself from this computer. This can’t be undone.'),
      el('label', { class: 'check' }, setBox, el('span', {}, re
        ? 'Also reset the settings, templates, offline maps, overlays, routes and feeds (Spyhop’s folder) to a fresh start'
        : 'Also delete the settings, templates, offline maps, overlays, routes and feeds (Spyhop’s folder)')),
      re ? null : el('label', { class: 'check' }, dataBox, el('span', {}, 'Also delete the survey data, waypoints, templates, NMEA logs and exports')),
      re ? null : el('div', { class: 'indent hint' }, 'To delete the survey data, type ', el('b', { class: 'mono' }, 'DELETE'), ': ', typed),
      planBox,
      re ? null : el('p', { class: 'hint' }, 'Export any surveys you need first (Survey tab). A data folder you chose yourself is never deleted, because it may hold other files.'));
    refresh();
    const res = await modal({
      title: re ? 'Reinstall Spyhop' : 'Uninstall Spyhop', body, width: 'min(46em, 94vw)',
      buttons: [{ label: 'Cancel', value: undefined }, { label: re ? 'Reinstall' : 'Uninstall', primary: true, value: () => ({ ...opts, confirm: typed.value }) }],
      onOpen: (box) => {
        go = box.querySelector('.modal-buttons button.primary');
        go.classList.add('danger'); go.classList.remove('primary');
        go.disabled = true;
        go.id = 'uninstall-go';
        return false;
      },
    });
    if (!res) return;
    try {
      const r = await api('/api/uninstall/start', res);
      this.showClosing(r.result.message, r.result.helper_log);
    } catch {}
  }

  // Spyhop is closing for good (uninstall) or to be replaced (reinstall): say so instead of reconnecting
  showClosing(message, logPath = '') {
    if (this.closingShown) return;
    this.closingShown = true;
    this.noReconnect = true;
    document.body.append(el('div', { class: 'modal-back closing' }, el('div', { class: 'modal', id: 'closing-box' },
      el('h3', {}, 'Spyhop is closing'), el('p', {}, message || ''),
      logPath ? el('p', { class: 'hint' }, 'A record of what was done goes to ', el('span', { class: 'mono' }, logPath), '.') : null,
      el('p', { class: 'hint' }, 'You can close this browser window.'))));
  }

  updatesSection() {
    const a = this.S.about || {}, st = this.S.config.settings;
    const box = el('div', { id: 'update-box' });
    const u = this.updateInfo, res = this.updateResult;
    if (res) {
      box.append(el('p', {}, el('b', {}, '✓ '), res.message),
        res.backup ? el('p', { class: 'hint' }, `The previous version is backed up in ${res.backup}. Python packages: ${res.packages}.`) : null,
        res.can_restart
          ? el('div', { class: 'btnrow' }, el('button', { class: 'primary', onclick: () => this.restartForUpdate() }, 'Restart Spyhop now'))
          : el('p', {}, el('b', {}, 'Close Spyhop’s console window and start Spyhop again from its icon to finish.')));
    } else if (u) {
      if (u.newer) {
        box.append(el('p', {}, el('b', {}, `Spyhop ${u.latest} is available`), ` (you have ${u.current}${u.source === 'main' ? '; from the main branch on GitHub' : ''}${u.published ? `; released ${u.published.slice(0, 10)}` : ''}).`));
        if (u.notes) box.append(el('details', { open: true }, el('summary', {}, 'What’s new'), el('div', { class: 'changelog' }, ...renderMarkdown(u.notes))));
        box.append(el('div', { class: 'btnrow' },
          el('button', { class: 'primary', onclick: () => this.installUpdate() }, u.git ? 'Update (git pull)' : `Install Spyhop ${u.latest}`),
          el('a', { href: u.url, target: '_blank', rel: 'noopener' }, 'See it on GitHub')),
          el('p', { class: 'hint' }, 'Installing keeps a backup of this version, never touches your surveys, lists or settings, and needs a restart afterwards. '
            + (this.S.survey && !this.S.survey.ended ? 'A survey is open: it is safest to update between surveys (an open survey is reopened after the restart).' : '')));
      } else {
        box.append(el('p', {}, el('b', {}, '✓ '), `Spyhop ${u.current} is the latest version.`));
      }
    }
    return el('section', { class: 'settings-sec', id: 'updates-section' }, el('h3', {}, 'Updates'),
      el('p', {}, `This is Spyhop ${a.spyhop || ''}. Updates come from `, el('a', { href: 'https://github.com/hansenjohnson/spyhop', target: '_blank', rel: 'noopener' }, 'github.com/hansenjohnson/spyhop'), ' and need an internet connection.'),
      el('div', { class: 'btnrow' },
        el('button', { id: 'btn-check-update', onclick: () => this.checkForUpdate() }, 'Check for updates'),
        el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!st.check_updates_on_start,
          onchange: (e) => this.saveSettings({ check_updates_on_start: e.target.checked }) }), el('span', {}, 'Check when Spyhop starts'))),
      box);
  }

  async checkForUpdate() {
    const b = $('#btn-check-update');
    if (b) { b.disabled = true; b.textContent = 'Checking…'; }
    try { this.updateInfo = (await api('/api/update/check', {})).update; this.updateResult = null; } catch {}
    this.renderAbout();
  }

  async installUpdate() {
    const u = this.updateInfo;
    if (!u) return;
    if (!await confirmBox(`Install Spyhop ${u.latest}?`, 'Spyhop downloads the new version, keeps a backup of this one, and installs it. Your surveys, lists and settings are not changed. You restart Spyhop afterwards.', 'Install')) return;
    const box = $('#update-box');
    if (box) box.replaceChildren(el('p', {}, 'Downloading and installing… (this can take a minute)'));
    try { this.updateResult = (await api('/api/update/install', { update: u })).result; } catch { this.renderAbout(); return; }
    this.renderAbout();
  }

  async restartForUpdate() {
    try { await api('/api/update/restart', {}); } catch { return; }
    const box = $('#update-box');
    if (box) box.replaceChildren(el('p', {}, 'Restarting… the window reloads by itself in a few seconds.'));
  }

  async saveDiagnostics() {
    let r;
    try { r = await api('/api/diagnostics', {}); } catch { return; }
    const a = el('a', { href: r.url, download: r.name });
    document.body.append(a); a.click(); a.remove();
    toast(`Diagnostics saved: ${r.path}`, 'info', 10000);
  }

  async open(what) {
    try { await api('/api/open', { what }); } catch {}
  }

  importOverlay() {
    const input = el('input', { type: 'file', accept: '.geojson,.json,.gpx,.kml', multiple: true });
    input.onchange = async () => {
      const fd = new FormData();
      for (const f of input.files) fd.append('file', f, f.name);
      const r = await fetch('/api/overlays', { method: 'POST', body: fd }).then((x) => x.json());
      if (r.ok) toast(`Imported ${r.saved.join(', ')}`); else toast(r.error, 'error');
    };
    input.click();
  }

  // ---------------------------------------------------------------- shortcuts
  matchCombo(combo, e) {
    const parts = combo.split('+').map((p) => p.trim());
    const key = parts.pop();
    const want = { mod: false, shift: false, alt: false };
    for (const p of parts) {
      const l = p.toLowerCase();
      if (l === 'mod' || l === 'cmd' || l === 'ctrl') want.mod = true;
      else if (l === 'shift') want.shift = true;
      else if (l === 'alt' || l === 'option') want.alt = true;
    }
    const mod = IS_MAC ? e.metaKey : e.ctrlKey;
    if (mod !== want.mod || e.shiftKey !== want.shift || e.altKey !== want.alt) return false;
    if (/^[A-Za-z]$/.test(key)) return e.code === `Key${key.toUpperCase()}`;
    if (/^[0-9]$/.test(key)) return e.code === `Digit${key}` || e.code === `Numpad${key}`;
    return e.key.toLowerCase() === key.toLowerCase();
  }

  onShortcut(e) {
    if (this.comboCapture && this.comboCapture(e) !== false) return;     // Settings → Shortcuts is recording new keys
    if (isModalOpen()) return;
    if (e.key === 'Escape' && this.map?.measure?.active) { this.map.endMeasure(); return; }
    const typing = e.target?.matches?.('input[type=text], input[type=number], input:not([type]), textarea, [contenteditable=true]');
    for (const s of this.S.config.shortcuts) {
      if (!this.matchCombo(s.combo, e)) continue;
      // undo / redo while typing in a box (a cell being edited, a Settings field) undo the typing, as usual
      if (typing && (s.action === 'undo' || s.action === 'redo')) return;
      e.preventDefault();
      e.stopPropagation();
      const g = this.grids[this.tab];
      if (g?.editing) g.commit(g.pendingValue());
      this.runAction(s.action, s.prefill);
      return;
    }
  }

  runAction(action, prefillStr) {
    const prefill = {};
    for (const part of (prefillStr || '').split(';')) {
      const i = part.indexOf('=');
      if (i > 0) prefill[part.slice(0, i).trim()] = part.slice(i + 1).trim();
    }
    const [verb, arg] = action.split(':');
    const tabs = this.allTabs();
    switch (verb) {
      case 'add': this.addRow(arg, prefill); break;
      // the data table in view (Sightings, Effort or Events), whichever pane has the focus; never waypoints
      case 'add-current': this.addRow(this.topTabs().includes(this.dataTab) ? this.dataTab : 'sightings', prefill); break;
      case 'add-resight': this.addResight(); break;
      case 'toggle-effort': this.toggleEffort(); break;
      case 'undo': this.undo(); break;
      case 'redo': this.redo(); break;
      case 'tab': this.showTab(arg); break;
      case 'toggle-log': this.setPaneMin('data', !this.paneLayout().min.data); break;
      case 'max-log': this.setPaneMax('data'); break;
      case 'next-tab': this.showTab(tabs[(tabs.indexOf(this.tab) + 1) % tabs.length]); break;
      case 'prev-tab': this.showTab(tabs[(tabs.indexOf(this.tab) - 1 + tabs.length) % tabs.length]); break;
      case 'center-vessel': this.map.centerVessel(); break;
      case 'measure': this.map.toggleMeasure(); break;
      default: toast(`Unknown shortcut action “${action}” in shortcuts.csv`, 'warn');
    }
  }

  // ---------------------------------------------------------------- summary
  // Tools → Summary. #report-summary is also what Export and Save copy (summary_html.js).
  renderSummaryPane() {
    const pane = $('#pane-summary');
    if (!pane) return;
    if (!$('#report-summary')) pane.replaceChildren(el('div', { id: 'report-summary' }));
    this.renderSummary();
  }

  renderSummary() {
    const pane = $('#report-summary');
    if (!pane) return;
    const S = this.S, st = S.config.settings, sight = S.tables.sightings.rows, ev = S.tables.events.rows;
    if (!S.survey) { pane.replaceChildren(el('p', { class: 'hint' }, 'No survey open — start or open one in the Survey tab.')); return; }
    // resights aren't counted again: one entry per first sighting, with the largest number and
    // calves seen on any look at those animals
    const rsx = new Resights(sight);
    const groups = rsx.groups().map((g) => ({ r: g[0], ...groupCounts(g) }));
    const nResights = sight.length - groups.length;
    const bySp = {};
    for (const g of groups) {
      const k = g.r.Species || '(unidentified)';
      const o = bySp[k] || (bySp[k] = { n: 0, number: 0, calves: 0, re: 0 });
      o.n++; o.number += g.number; o.calves += g.calves; o.re += g.resights;
    }
    const byEv = {};
    for (const r of ev) byEv[r.EventType || '(no type)'] = (byEv[r.EventType || '(no type)'] || 0) + 1;
    // effort time from the Effort table (the current ON stretch counts up to now)
    const eff = [...S.tables.effort.rows].filter((r) => r.DateTime).sort((a, b) => new Date(a.DateTime) - new Date(b.DateTime));
    let onSec = 0;
    const byKind = {};                 // time in each kind of on effort (the on-effort entries of the effort list)
    eff.forEach((r, i) => {
      if (!isOn(r.Effort)) return;
      const t0 = new Date(r.DateTime).getTime();
      const t1 = i + 1 < eff.length ? new Date(eff[i + 1].DateTime).getTime() : Date.now();
      const dt = Math.max(0, (t1 - t0) / 1000);
      onSec += dt;
      byKind[r.Effort] = (byKind[r.Effort] || 0) + dt;
    });
    const effortNow = isOn(eff.at(-1)?.Effort);
    // distances from the internal track, plus the live stretch since the last track point
    // trackline breaks (GPS jumps or losses, Settings → General → Tracking) and ERROR stretches don't count
    let total = 0, onDist = 0;
    const tr = S.track, tst = trackStates(tr, S.tables.effort.rows);
    for (let i = 1; i < tr.length; i++) {
      if (tst[i] === 'ERROR' || tst[i - 1] === 'ERROR' || isTrackBreak(tr[i - 1], tr[i], st)) continue;
      const d = distM([+tr[i - 1].Lat, +tr[i - 1].Lon], [+tr[i].Lat, +tr[i].Lon]);
      if (d > 20000) continue; // skip gaps (e.g. tracking paused)
      total += d;
      if (isOn(tst[i]) && isOn(tst[i - 1])) onDist += d;
    }
    const v = S.vessel, last = tr.at(-1);
    if (st.tracking_enabled && last && v?.has_fix && tst.at(-1) !== 'ERROR') {
      const d = distM([+last.Lat, +last.Lon], [v.lat, v.lon]);
      if (d < 20000) { total += d; if (effortNow && isOn(tst.at(-1))) onDist += d; }
    }
    const unit = this.unit(), div = { nm: 1852, km: 1000, m: 1, mi: 1609.344, yd: 0.9144 }[unit];
    const firstIso = [sight[0]?.DateTime, eff[0]?.DateTime, tr[0]?.DateTime].filter(Boolean).sort((a, b) => new Date(a) - new Date(b))[0];
    const first = firstIso ? timeParts(firstIso, this.clock()) : null;
    const tbl = (head, rows) => el('table', { class: 'summary' }, el('thead', {}, el('tr', {}, head.map((h) => el('th', {}, h)))),
      el('tbody', {}, rows.map((r) => el('tr', {}, r.map((c) => el('td', {}, c))))));
    const spRows = Object.entries(bySp).sort((a, b) => b[1].n - a[1].n).map(([k, o]) => [k, o.n, o.number, o.calves, o.re || '']);

    // range of environmental conditions logged in the Effort tab
    const fixed = S.schema.fixed_lists;
    const cond = [['Visibility', 'visibility', true], ['SeaState', 'seastate', true], ['Weather', 'weather', false], ['Glare', 'glare', true]];
    const labels = { Visibility: 'Visibility', SeaState: 'Sea state', Weather: 'Weather', Glare: 'Glare' };
    const condRows = [];
    for (const [key, list, ordered] of cond) {
      const seen = [...new Set(eff.map((r) => r[key]).filter(Boolean))];
      if (!seen.length) continue;
      const order = fixed[list] || [];
      seen.sort((a, b) => order.indexOf(a) - order.indexOf(b));
      const range = ordered ? (seen.length === 1 ? seen[0] : `${seen[0]} – ${seen.at(-1)}`) : seen.join(', ');
      const onlyOn = [...new Set(eff.filter((r) => isOn(r.Effort)).map((r) => r[key]).filter(Boolean))]
        .sort((a, b) => order.indexOf(a) - order.indexOf(b));
      const rangeOn = !onlyOn.length ? '—' : ordered ? (onlyOn.length === 1 ? onlyOn[0] : `${onlyOn[0]} – ${onlyOn.at(-1)}`) : onlyOn.join(', ');
      condRows.push([labels[key], range, rangeOn]);
    }

    // observers on watch: time in each position while effort was ON
    const fullName = Object.fromEntries((S.config.lists.observers || []).map((o) => [o.name, o.full_name]));
    const posKeys = [['Port', 'Port'], ['Recorder', 'Recorder'], ['Starboard', 'Stbd']];
    const watch = {};
    eff.forEach((r, i) => {
      if (!isOn(r.Effort)) return;
      const t0 = new Date(r.DateTime).getTime();
      const t1 = i + 1 < eff.length ? new Date(eff[i + 1].DateTime).getTime() : Date.now();
      const dt = Math.max(0, (t1 - t0) / 1000);
      for (const [k] of posKeys) {
        if (!r[k] || isPlaceholderObs(r[k], fullName[r[k]])) continue;   // NA (None): an empty position
        const w = watch[r[k]] || (watch[r[k]] = { Port: 0, Recorder: 0, Starboard: 0 });
        w[k] += dt;
      }
    });
    const dur = (sec) => (sec ? fmtDuration(sec) : '—');
    const obsRows = Object.entries(watch)
      .map(([n, w]) => [n, w, w.Port + w.Recorder + w.Starboard])
      .sort((a, b) => b[2] - a[2])
      .map(([n, w, tot]) => [fullName[n] && fullName[n] !== n ? `${n} (${fullName[n]})` : n, dur(w.Port), dur(w.Recorder), dur(w.Starboard), dur(tot)]);

    const sv = S.survey, meta = sv.meta || {};
    const fmtT = (iso) => { const t = iso && timeParts(iso, this.clock()); return t ? `${t.date} ${t.time} ${t.abbr}` : '—'; };
    const t0 = sv.start_time ? new Date(sv.start_time).getTime() : null;
    const t1 = sv.end_time ? new Date(sv.end_time).getTime() : Date.now();
    const platform = [meta.platform_name, meta.platform_type ? `(${meta.platform_type})` : ''].filter(Boolean).join(' ');
    const kv = (pairs) => el('table', { class: 'summary kv' }, el('tbody', {},
      pairs.filter(([, v]) => v !== null).map(([k, v]) => el('tr', {}, el('th', {}, k), el('td', {}, v)))));
    const gen = timeParts(new Date(), this.clock());
    // North Atlantic right whales, one row per sighting (species code RIWH or the species name)
    const riwhNames = new Set((S.config.lists.species || []).filter((x) => String(x.species_code || '').toUpperCase() === 'RIWH').map((x) => x.name));
    const isRiwh = (sp) => riwhNames.has(sp) || /north atlantic right whale|eubalaena glacialis/i.test(sp || '');
    const fmt = st.latlon_format;
    const pos = (r) => {
      const la = r.SigLat !== '' && r.SigLat != null ? r.SigLat : r.Lat, lo = r.SigLon !== '' && r.SigLon != null ? r.SigLon : r.Lon;
      return la !== '' && la != null && lo !== '' && lo != null ? fmtPos(+la, +lo, fmt) : '—';
    };
    const riwh = groups.filter((g) => isRiwh(g.r.Species))
      .sort((a, b) => new Date(a.r.DateTime) - new Date(b.r.DateTime) || (+a.r.SightNo || 0) - (+b.r.SightNo || 0));
    const riwhTable = riwh.length ? el('table', { class: 'summary riwh-table' },
      el('thead', {}, el('tr', {}, ['Sighting', 'Time', 'Position', 'Number', 'Calves', 'Resights', 'Field ID', 'Notes'].map((h) => el('th', {}, h)))),
      el('tbody', {}, riwh.map(({ r, number, calves, resights, fieldIds }) => el('tr', {},
        el('td', {}, r.SightNo || ''), el('td', { class: 'nowrap' }, fmtT(r.DateTime)), el('td', { class: 'mono nowrap' }, pos(r)),
        el('td', { class: 'num' }, number || ''), el('td', { class: 'num' }, calves || ''), el('td', { class: 'num' }, resights || ''),
        el('td', {}, fieldIds.join(', ')), el('td', {}, r.Notes || ''))))) : null;
    const riwhTotals = riwh.length ? `${riwh.length} sighting${riwh.length === 1 ? '' : 's'}, ${riwh.reduce((a, g) => a + g.number, 0)} animals`
      + `, ${riwh.reduce((a, g) => a + g.calves, 0)} calves. Positions are the whales’ at the first sighting (SigLat/SigLon), or the vessel’s if none was worked out; numbers are the largest seen on the sighting or any resight.` : '';
    pane.replaceChildren(
      el('div', { class: 'summary-head' },
        el('h2', {}, `Survey: ${sv.name}`),
        el('div', { class: 'summary-actions no-print' },
          el('button', { onclick: () => this.saveSummaryHtml(), title: 'Save this summary and a map of the survey as one HTML file that opens in any browser, even offline' }, 'Save as HTML…'),
          el('button', { disabled: this.reportsTool.defs && !this.reportsTool.defs.pdf, title: 'Save this summary, with its map, as a PDF (needs Google Chrome or Microsoft Edge)',
            onclick: () => this.saveSummaryHtml('pdf') }, 'Save as PDF…'))),
      el('p', { class: 'print-only hint' }, `Spyhop summary · generated ${gen.date} ${gen.time} ${gen.abbr}`),
      el('div', { class: 'cards' },
        card(nResights ? `Sightings (+${nResights} resight${nResights === 1 ? '' : 's'})` : 'Sightings', groups.length), card('Number', groups.reduce((a, g) => a + g.number, 0)),
        card('Species', Object.keys(bySp).filter((k) => k !== '(unidentified)').length),
        card('Time on effort', fmtDuration(onSec), effortNow), card('On-effort distance', `${(onDist / div).toFixed(2)} ${unit}`, effortNow && st.tracking_enabled),
        card('Track distance', `${(total / div).toFixed(2)} ${unit}`, !!st.tracking_enabled), card('Events', ev.length)),
      el('p', { class: 'hint' }, first ? `First record ${first.date} ${first.time} ${first.abbr}. ` : '',
        effortNow ? 'On effort now — counters marked ● are running. ' : '',
        'Distances come from the internal trackline, so they only count while tracking is on.'),
      el('h3', {}, 'Survey details'),
      el('div', { class: 'summary-details' }, kv([['Started', fmtT(sv.start_time)],
        ['Ended', sv.ended ? fmtT(sv.end_time) : 'still active'],
        ['Duration', t0 ? fmtDuration((t1 - t0) / 1000) : '—'],
        ['Platform', platform || '—'], ['Platform altitude', meta.platform_altitude_ft ? `${meta.platform_altitude_ft} ft` : '—'], ['Organization', meta.organization || '—'], ['Chief scientist', meta.chief_scientist || '—'],
        ['Chief scientist email', meta.chief_scientist_email ? el('a', { href: `mailto:${meta.chief_scientist_email}` }, meta.chief_scientist_email) : '—']])),
      meta.survey_notes ? el('h3', {}, 'Survey notes') : null,
      meta.survey_notes ? el('p', { class: 'survey-notes' }, meta.survey_notes) : null,
      Object.keys(byKind).some((k) => k !== 'ON') ? el('h3', {}, 'Time on effort by type') : null,
      Object.keys(byKind).some((k) => k !== 'ON') ? tbl(['Effort', 'Time'], ON_EFFORT.filter((k) => byKind[k]).map((k) => [effortInfo(k).definition ? `${k} (${effortInfo(k).definition.replace(/\.$/, '')})` : k, fmtDuration(byKind[k])])) : null,
      el('h3', {}, 'Sightings by species'),
      spRows.length ? tbl(['Species', 'Sightings', 'Number', 'Calves', 'Resights'], spRows) : el('p', { class: 'hint' }, 'No sightings yet.'),
      spRows.length && nResights ? el('p', { class: 'hint' }, 'Resights aren’t counted as sightings; Number and Calves are the largest seen on any look at the same animals.') : null,
      el('h3', {}, 'North Atlantic right whale sightings'),
      riwhTable ? el('div', { class: 'table-scroll' }, riwhTable) : el('p', { class: 'hint' }, 'No North Atlantic right whales sighted.'),
      riwhTable ? el('p', { class: 'hint' }, riwhTotals) : null,
      el('h3', {}, 'Observers on watch'),
      obsRows.length ? tbl(['Observer', 'Port', 'Recorder', 'Stbd', 'Total'], obsRows) : el('p', { class: 'hint' }, 'No observers logged on effort yet (Port / Recorder / Stbd in the Effort tab).'),
      obsRows.length ? el('p', { class: 'hint' }, `Time in each position while on effort (${ON_EFFORT.join(', ')}), from the Effort tab.`) : null,
      el('h3', {}, 'Environmental conditions'),
      condRows.length ? tbl(['Condition', 'Whole survey', 'On effort'], condRows) : el('p', { class: 'hint' }, 'No conditions logged yet.'),
      el('h3', {}, 'Events by type'),
      Object.keys(byEv).length ? tbl(['Event', 'Count'], Object.entries(byEv).sort((a, b) => b[1] - a[1])) : el('p', { class: 'hint' }, 'No events yet.'));
  }

  async saveSummaryHtml(format = 'html') {
    if (!this.S.survey) return;
    if (!this.shown('summary')) this.showTab('summary');
    this.renderSummaryPane();
    toast(format === 'pdf' ? 'Making the PDF (a few seconds)…' : 'Building the summary file…', 'info', 3000);
    let html, r;
    try { html = await buildSummaryHtml(this, { pdf: format === 'pdf' }); } catch (e) { toast(`Couldn't build the summary: ${e.message}`, 'error'); return; }
    if (format === 'pdf') {
      try { r = await api('/api/summary/pdf', { html }); } catch { return; }
      const a = el('a', { href: r.url, download: r.name });
      document.body.append(a); a.click(); a.remove();
      toast(`Saved ${r.name} in the exports folder (a copy is downloading).`, 'info', 6000);
      return;
    }
    try { r = await api('/api/summary/save', { html }); } catch { return; }
    const a = el('a', { href: r.url, download: r.name });
    document.body.append(a); a.click(); a.remove();
    await modal({ title: 'Summary saved', body: el('div', {},
      el('p', {}, 'The summary and an interactive map of the survey were saved as one HTML file (it opens in any web browser, even offline):'),
      el('p', { class: 'mono' }, r.path),
      el('p', {}, 'A copy is downloading now too.')),
      buttons: [{ label: 'Open it', value: () => this.open(`export:${r.name}`) }, { label: 'Done', primary: true, value: true }] });
  }

  // ---------------------------------------------------------------- templates (templates.py)
  // Settings → Templates: the current template (templates/current) and the saved templates (templates/saved)
  renderTemplates() {
    const pane = $('#pane-templates');
    if (!pane) return;
    pane.replaceChildren(this.templatesSection());
  }

  templatesSection() {
    const S = this.S, st = S.config.settings, tp = (this.tpl ||= {});
    const sec = (title, ...kids) => el('section', { class: 'settings-sec', id: 'templates' }, el('h3', {}, title), ...kids);
    const when = (iso) => { const p = iso && timeParts(iso, this.clock()); return p ? `${p.date} ${p.time.slice(0, 5)} ${p.abbr}` : ''; };
    if (!tp.list && !tp.loading) this.loadTemplates();
    const L = tp.list;
    const stem = (n) => n.replace(/\.spyhop-template\.zip$|\.zip$/i, '');
    const ext = (n) => n.slice(stem(n).length);
    const cur = L?.current?.name && L.templates.find((p) => p.name === L.current.name);
    const btn = (label, attrs, fn) => el('button', { ...attrs, onclick: fn }, label);

    // ---- the current template and the saved templates
    const kids = [
      el('p', {}, 'A template is your team’s Spyhop settings in one small file, so every computer records the same way: the species, event types, observers and behaviors lists, keyboard shortcuts, map display, saved reports, shared settings (clock, units, tracking, keep awake, raw NMEA log, network GPS / NMEA inputs), the map feeds and which online overlays are on, and, if you choose, waypoints, routes and overlays. Update the template and use it again whenever the team changes something. The current template is the one in use, kept unzipped in templates/current of Spyhop’s folder; saved templates are zip files in templates/saved. Share one by uploading it (or copying it to a USB stick). Offline charts, survey data, serial GPS ports and the data folder are never in a template.'),
    ];
    if (!L) kids.push(el('p', { class: 'hint' }, tp.loading ? 'Reading the templates folder…' : ''));
    else {
      let curText;
      const c = L.current;
      if (c?.name && cur) {
        const how = { saved: 'Saved to', loaded: 'Loaded from', backup: 'Restored from a backup, then' }[c.how] || 'From';
        curText = el('p', { id: 'tpl-current' }, el('b', {}, 'Current template: '), `${how} `, el('span', { class: 'mono' }, cur.name),
          c.when ? ` (${when(c.when)})` : '', cur.matches ? ' — no changes since.'
            : cur.differs?.length ? ` — changed since: ${cur.differs.join(', ')}.` : '.');
      } else if (c?.how === 'backup') curText = el('p', { id: 'tpl-current' }, el('b', {}, 'Current template: '), `restored from a backup${c.when ? ` (${when(c.when)})` : ''}.`);
      else curText = el('p', { id: 'tpl-current' }, el('b', {}, 'Current template: '), c?.name ? `from ${c.name}, which is no longer in the folder.` : 'not saved yet.');
      kids.push(curText);
      kids.push(el('p', { class: 'hint' }, 'Templates in ', el('span', { class: 'mono' }, L.folder)));
      if (!L.templates.length) kids.push(el('p', { class: 'hint', id: 'tpl-none' }, 'No saved templates yet. Save the current template, or get one from a web address below.'));
      else {
        kids.push(el('table', { class: 'summary tpl-list', id: 'tpl-list' },
          el('thead', {}, el('tr', {}, ['Template', 'Latest change', 'Compared with here', ''].map((h) => el('th', {}, h)))),
          el('tbody', {}, L.templates.map((p) => {
            const inUse = cur && p.name === cur.name;
            const status = p.error ? el('span', { class: 'err' }, p.error)
              : p.problems?.length ? el('span', { class: 'err' }, `Has problems: ${p.problems[0]}`)
                : p.matches ? 'Same' : `Differs: ${p.differs.join(', ')}`;
            const latest = p.latest ? el('span', {}, [p.latest.date, p.latest.by].filter(Boolean).join(' · '),
              p.latest.notes ? el('div', { class: 'tpl-note' }, p.latest.notes) : null) : el('span', { class: 'hint' }, 'no record of changes');
            return el('tr', { class: inUse ? 'tpl-inuse' : '', 'data-template': p.name },
              el('td', {}, el('b', {}, stem(p.name)), el('span', { class: 'hint' }, ext(p.name)), inUse ? el('span', { class: 'pill' }, 'in use') : null),
              el('td', {}, latest),
              el('td', {}, status),
              el('td', { class: 'tpl-actions' },
                btn('Use this template…', { class: 'tpl-use', disabled: !!(p.error || p.problems?.length) }, () => this.checkTemplate({ template: p.name })),
                btn('Update…', { class: 'tpl-update', title: 'Replace this saved template with the current template' }, () => this.saveTemplate(p.name)),
                el('a', { class: 'button', href: `/api/templates/file/${encodeURIComponent(p.name)}`, download: p.name }, 'Download')));
          }))));
      }
    }
    kids.push(el('div', { class: 'btnrow' },
      btn('Save as a new template…', { id: 'tpl-save-new', class: 'primary' }, () => this.saveTemplate(null)),
      btn('Open the templates folder', {}, () => this.open('templates')),
      btn('Open the current template', { title: 'templates/current: the lists, shortcuts and spyhop-config.json in use' }, () => this.open('current')),
      btn('Refresh', {}, () => this.loadTemplates())));

    // ---- what a template did / would change (from the list, the web or a backup)
    if (tp.done) {
      const ad = tp.done.added || {}, n = (k, w) => ad[k] ? `${ad[k]} ${w}${ad[k] > 1 ? 's' : ''}` : '';
      const addText = [n('waypoints', 'waypoint'), n('routes', 'route'), n('overlays', 'overlay'), n('feeds', 'map feed')].filter(Boolean).join(', ');
      const repl = tp.done.changed.filter((f) => !/^(Map feed: |routes\/|overlays\/|waypoints\.csv$)/.test(f));
      kids.push(el('p', { class: 'okbox', id: 'tpl-done' }, repl.length || addText || tp.done.removed
        ? ['Done.', repl.length ? ` Updated: ${repl.join(', ')}.` : '', addText ? ` Added ${addText}.` : '',
          tp.done.removed ? ` Removed ${tp.done.removed} waypoint${tp.done.removed > 1 ? 's' : ''} the template had added.` : ''].join('') : 'Done; nothing needed changing.',
        tp.done.kept?.length ? el('span', {}, ` Kept until the survey ends: ${tp.done.kept.join(', ')}.`) : '',
        tp.done.copy ? el('span', {}, ' A copy was kept in the templates folder as ', el('span', { class: 'mono' }, tp.done.copy), '.') : '',
        tp.done.backup ? el('span', {}, ' Backup saved as ', el('span', { class: 'mono' }, tp.done.backup), '. ') : ' ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); tp.done = null; this.renderTemplates(); } }, 'OK')));
    }
    if (tp.result) kids.push(this.templateResult(tp.result));

    // ---- from the web
    const urlBox = el('input', { type: 'text', id: 'tpl-url', placeholder: 'https://drive.google.com/file/d/…', value: tp.url ?? st.template_url ?? '',
      style: { flex: '1', minWidth: '22em' }, oninput: (e) => { tp.url = e.target.value; },
      onkeydown: (e) => { if (e.key === 'Enter') this.checkTemplate(); } });
    const last = st.template_last || {};
    kids.push(el('h4', {}, 'Get a template from the web'),
      el('p', {}, 'Paste the link to the team’s template (Google Drive, Dropbox, GitHub or a website, shared so anyone with the link can open it). Nothing is downloaded until you press Check; a copy is then kept in the templates folder, so it can be used again without internet.'),
      el('div', { class: 'btnrow' }, el('label', { class: 'inline', style: { flex: '1' } }, 'Web address of the template:', urlBox),
        el('button', { id: 'btn-tpl-check', onclick: () => this.checkTemplate() }, tp.busy === 'check' ? 'Checking…' : 'Check')),
      last.pulled ? el('p', { id: 'tpl-last', class: 'hint' }, `Last got from the web ${when(last.pulled)}`,
        last.latest ? ` — the template’s latest change: ${[last.latest.date, last.latest.by, last.latest.notes].filter(Boolean).join(' · ')}` : '',
        last.url && last.url !== (tp.url ?? st.template_url) ? ` (from ${last.url})` : '') : null);

    // ---- backups
    const bk = L?.backups || [];
    kids.push(el('h4', {}, 'Backups'),
      el('p', { class: 'hint help' }, 'Spyhop saves a backup of the current template before using another (unless you untick it), in ',
        el('span', { class: 'mono' }, L?.backups_folder || 'templates/backups'), '. A backup is itself a template.'),
      bk.length ? el('table', { class: 'summary', id: 'tpl-backups' }, el('tbody', {}, bk.slice(0, 5).map((b) => el('tr', {},
        el('td', {}, when(b.modified)), el('td', { class: 'mono' }, b.name),
        el('td', {}, btn('Restore…', {}, () => this.checkTemplate({ backup: b.name }))))))) : null,
      el('div', { class: 'btnrow' },
        btn('Save a backup now', { id: 'btn-tpl-backup' }, () => this.backupTemplate()),
        btn('Open the backups folder', {}, () => this.open('backups'))),
      el('details', { class: 'hint' }, el('summary', {}, 'How to share a template with the team'),
        el('p', {}, 'Save the current template (or Update the team’s saved template with it), giving your name and what you changed: that’s added to the template’s record of changes. Then upload the file in place of the old one, keeping the same link (in Google Drive: Manage versions → Upload new version). Others press Check with that link.'),
        el('p', {}, 'Templates are ordinary zip files named .spyhop-template.zip, so they open in any zip tool: the lists and shortcuts are CSV files, and everything else is in spyhop-config.json. SharePoint and OneDrive links usually need a sign-in, so they don’t work. See docs/TEMPLATES.md.')));
    return sec('Templates', ...kids);
  }

  templateResult(r) {
    const S = this.S, st = S.config.settings, tp = this.tpl;
    const label = { new: 'New — will be added', changed: 'Changed — replaces this computer’s copy', same: 'Same as here',
      removed: r.kind === 'backup' ? 'Will be removed' : 'Not in the template — will be removed', kept: 'Already here — this computer’s is kept' };
    // during a survey the data part (lists, data settings) waits until it ends; colors don't (0.40)
    const waits = (f) => r.survey_active && f.part === 'data' && f.status !== 'same' && f.status !== 'kept' && !f.colors_only;
    const todo = r.files.filter((f) => f.status !== 'same' && f.status !== 'kept' && !waits(f));
    const title = r.kind === 'backup' ? `Restoring the backup ${r.name}` : r.kind === 'folder' ? `Using the template ${r.name}`
      : r.kind === 'survey' ? `The template the survey was recorded with (${r.name})` : 'The template from the web';
    const box = [el('h4', {}, `${title}: what would change`), el('p', { class: 'hint' }, `From ${r.source}`)];
    if (r.survey_active && r.files.some(waits)) box.push(el('p', { class: 'warnbox', id: 'tpl-waits' }, el('b', {}, 'A survey is under way: '),
      'only the preferences (and list colors) can be used now. The data part — the lists and the data settings — stays as it is until the survey ends.'));
    box.push(el('p', { class: 'warnbox' }, el('b', {}, 'The template’s data part and preferences replace this computer’s '),
      '(nothing is merged; its saved reports replace all of this computer’s). Map feeds, waypoints, routes and overlays are only added',
      r.kind === 'backup' ? ', except those the template used after this backup added, which are taken away.' : '.',
      ' Survey data, offline charts, serial GPS ports and the data folder are never changed.'));
    const inf = r.info || {};
    if (inf.min_spyhop || inf.made_with) box.push(el('p', { class: 'hint', id: 'tpl-version' },
      [inf.min_spyhop ? `Needs Spyhop ${inf.min_spyhop} or newer` : '', inf.made_with ? `made with Spyhop ${inf.made_with}` : ''].filter(Boolean).join('; '),
      ` (this computer has ${S.about?.spyhop || ''}).`));
    if (r.online) {
      const d = r.online, names = [d.ais && 'AIS vessels', d.radar_us && 'US radar', d.radar_world && 'worldwide radar',
        ...(d.feed_names || [])].filter(Boolean);
      box.push(el('p', { class: 'hint', id: 'tpl-online' }, `Online overlays it switches on: ${names.length ? names.join(', ') : 'none'} (the others are switched off; each computer can change them afterwards).`));
    }
    if (r.problems.length) {
      box.push(el('div', { class: 'errbox' }, el('b', {}, 'The template has problems, so it can’t be used. Ask whoever looks after it to fix:'),
        el('ul', {}, r.problems.map((p) => el('li', {}, p)))));
    }
    const count = (f, n) => (f.unit === 'rows' || f.unit === 'waypoints') && n != null ? `${n} ${f.unit === 'rows' ? 'row' : 'waypoint'}${n === 1 ? '' : 's'}` : '';
    box.push(el('table', { class: 'summary tpl-parts' },
      el('thead', {}, el('tr', {}, ['What', 'What happens', 'Here', 'In the template'].map((h) => el('th', {}, h)))),
      el('tbody', {}, Object.entries(S.schema.template_parts || { data: 'Data', prefs: 'Preferences', extra: 'Added to this computer' }).flatMap(([part, name]) => {
        const fs = r.files.filter((f) => (f.part || 'prefs') === part);
        return fs.length ? [el('tr', { class: 'tpl-part', 'data-part': part }, el('th', { colspan: 4 }, name)), ...fs.map((f) => el('tr', { class: `tpl-${waits(f) ? 'waits' : f.status}` },
          el('td', { class: ['rows', 'route', 'overlay'].includes(f.unit) ? 'mono' : '' }, f.file),
          el('td', {}, waits(f) ? 'Changed — waits until the survey ends' : f.unit === 'waypoints' && f.status === 'new' ? `${f.add} new — will be added` : label[f.status],
            f.detail ? el('div', { class: 'tpl-note' }, f.detail) : null),
          el('td', {}, count(f, f.here)), el('td', {}, count(f, f.in_template))))] : [];
      }))));
    if (r.history.length) {
      box.push(el('h4', {}, 'Recent changes in the template'), el('table', { class: 'summary' },
        el('thead', {}, el('tr', {}, ['Date', 'Changed by', 'What changed', 'Notes'].map((h) => el('th', {}, h)))),
        el('tbody', {}, r.history.map((m) => el('tr', {}, el('td', {}, m.date), el('td', {}, m.by), el('td', {}, m.changed), el('td', {}, m.notes))))));
    } else box.push(el('p', { class: 'hint' }, 'The template has no record of its changes.'));
    if (r.ignored.length) box.push(el('p', { class: 'hint' }, `Not part of a template, so left alone: ${r.ignored.join(', ')}`));
    const cancel = el('button', { onclick: () => { tp.result = null; this.renderTemplates(); } }, 'Cancel');
    if (!r.problems.length) {
      if (!todo.length) {
        box.push(r.files.some(waits)
          ? el('p', { id: 'tpl-uptodate' }, el('b', {}, 'Only the data part differs, so there is nothing to use until the survey ends.'))
          : el('p', { id: 'tpl-uptodate' }, el('b', {}, 'The current template is already the same as this one.')),
          el('div', { class: 'btnrow' }, el('button', { id: 'btn-tpl-use', onclick: () => this.useTemplate() },
            r.kind === 'web' || r.kind === 'file' ? 'Keep a copy in the templates folder' : 'Mark it as in use'), cancel));
      } else {
        const backup = el('input', { type: 'checkbox', id: 'tpl-backup', checked: tp.backup ?? st.template_backup !== false,
          onchange: (e) => { tp.backup = e.target.checked; } });
        const verb = r.kind === 'backup' ? 'Restore' : r.kind === 'folder' || r.kind === 'survey' ? 'Use it' : 'Pull it';
        box.push(
          el('label', { class: 'check' }, backup, el('span', {}, 'Save a backup of the current template first, in templates/backups (it can be restored to undo)')),
          el('div', { class: 'btnrow' }, el('button', { id: 'btn-tpl-use', class: 'primary', onclick: () => this.useTemplate() },
            tp.busy === 'use' ? 'Working…' : `${verb}: ${todo.length} change${todo.length > 1 ? 's' : ''}`), cancel));
      }
    } else box.push(el('div', { class: 'btnrow' }, cancel));
    return el('div', { id: 'tpl-result', class: 'tpl-result' }, ...box);
  }

  async loadTemplates() {
    const tp = (this.tpl ||= {});
    tp.loading = true;
    try { tp.list = await api('/api/templates'); } catch { tp.list = tp.list || null; }
    tp.loading = false;
    if (this.shown('templates')) this.renderTemplates();
  }

  // name: update that template in the folder; null: save a new one
  async saveTemplate(name) {
    let info;
    try { info = await api('/api/templates/changes' + (name ? `?name=${encodeURIComponent(name)}` : '')); } catch { return; }
    const since = info.since === 'use' ? 'the last time a template was used here' : info.since === 'save' ? 'the last template saved here' : null;
    const by = el('input', { type: 'text', id: 'tpl-by', value: info.by || '', style: { width: '100%' }, placeholder: 'e.g. H. Johnson' });
    const notes = el('textarea', { id: 'tpl-notes', rows: 3, style: { width: '100%' }, placeholder: 'e.g. Added Dead bird; new observer JM' });
    const changed = el('input', { type: 'text', id: 'tpl-changed', value: info.files == null ? 'all' : info.files.join('; '), style: { width: '100%' } });
    const fname = el('input', { type: 'text', id: 'tpl-name', style: { width: '100%' }, placeholder: 'e.g. 2026-NEA-CCB' });
    // the optional parts: the updated template's choice, else the last one made here
    let inc = info.includes;
    if (!Array.isArray(inc)) {
      try { inc = JSON.parse(localStorage.getItem('wsr.templateInclude') || '[]'); } catch { inc = []; }
    }
    const part = (key, label, n) => el('label', { class: 'check' },
      el('input', { type: 'checkbox', class: 'tpl-include', value: key, checked: inc.includes(key) }),
      el('span', {}, `${label} (${n} on this computer)`));
    const online = this.online.displayState();
    const onNames = [online.ais && 'AIS vessels', online.radar_us && 'US radar', online.radar_world && 'worldwide radar',
      ...(this.online.feeds || []).filter((f) => online.feeds.includes(f.url)).map((f) => f.name)].filter(Boolean);
    const withOnline = el('input', { type: 'checkbox', id: 'tpl-online-on', checked: true });
    const minV = el('input', { type: 'text', id: 'tpl-min', value: info.min_spyhop || info.min_default || '', style: { width: '8em' } });
    const changedHint = name ? (info.files?.length ? `Different from ${name}.` : `Nothing differs from ${name}.`)
      : since ? (info.files?.length ? `Changed on this computer since ${since}.` : `Nothing has changed on this computer since ${since}.`)
        : 'Spyhop doesn’t know what changed, so it says all.';
    const body = el('div', { class: 'stack-form' },
      name ? el('p', { class: 'warnbox' }, el('b', {}, `This replaces ${name} `), 'with the current template. If this is the team’s template, check with whoever looks after it first; the change is added to the template’s record of changes.')
        : el('p', {}, 'This saves the current template as a new saved template (templates/saved), with your change added to its record of changes.'),
      name ? null : el('label', { class: 'stack' }, 'Template name', fname, el('span', { class: 'hint' }, 'Saved as <name>.spyhop-template.zip')),
      el('label', { class: 'stack' }, 'Your name', by),
      el('label', { class: 'stack' }, 'What you changed', notes),
      el('label', { class: 'stack' }, 'Parts changed', changed, el('span', { class: 'hint' }, changedHint)),
      el('div', { class: 'stack tpl-parts-choice' }, el('b', {}, 'Also include'),
        el('span', { class: 'hint' }, 'The lists, shortcuts, map display, saved reports, shared settings and map feeds are always in the template. Waypoints, routes and overlays are added on the computers that use it; any they already have are kept.'),
        part('waypoints', 'Waypoints', info.waypoints), part('routes', 'Routes', info.routes), part('overlays', 'Overlays', info.overlays),
        el('label', { class: 'check' }, withOnline, el('span', {}, `Which online overlays are switched on, and the radar settings (now: ${onNames.length ? onNames.join(', ') : 'none'})`))),
      el('div', { class: 'stack tpl-min' }, el('label', { class: 'inline' }, 'Needs Spyhop version ', minV, ' or newer'),
        el('span', { class: 'hint' }, `Computers with an older Spyhop are asked to update before they can use the template. ${info.min_default} is the lowest; this computer has ${info.version}.`)));
    for (;;) {
      const ok = await modal({ title: name ? 'Update a template' : 'Save a new template', body,
        buttons: [{ label: 'Cancel', value: false }, { label: name ? 'Update the template' : 'Save the template', value: true, primary: true }],
        onOpen: () => { setTimeout(() => (!name ? fname : by.value ? notes : by).focus(), 0); return true; } });
      if (!ok) return false;
      if (!name && !fname.value.trim()) { toast('Please give the template a name.', 'warn'); continue; }
      if (by.value.trim() && notes.value.trim()) break;
      toast('Please give your name and what you changed.', 'warn');
    }
    try {
      const include = [...body.querySelectorAll('.tpl-include')].filter((x) => x.checked).map((x) => x.value);
      try { localStorage.setItem('wsr.templateInclude', JSON.stringify(include)); } catch {}
      const r = await api('/api/templates/save', { name: name || fname.value, overwrite: !!name, by: by.value, notes: notes.value, changed: changed.value,
        include, min_spyhop: minV.value.trim(), online: withOnline.checked ? online : null });
      toast(`${name ? 'Template updated' : 'Template saved'}: ${r.name}`, 'info', 6000);
    } catch { return false; }
    await this.loadTemplates();
    return true;
  }

  // Before a survey starts: if the current template isn't saved, offer to save it, so the
  // survey's details can say which template it was recorded with. Returns false to stop.
  async offerTemplateSave() {
    let st;
    try { st = (await api('/api/templates/status')).status; } catch { return true; }
    if (!st || st.saved) return true;
    const known = st.name && st.changed?.length;
    const choice = await modal({ title: 'Save the current template first?', width: 'min(560px, 94vw)',
      body: el('div', { id: 'tpl-start-prompt' },
        el('p', {}, known
          ? ['The current template has changed since it was saved as ', el('span', { class: 'mono' }, st.name), ` (${st.changed.join(', ')}).`]
          : 'The current template (lists, shortcuts, map display, saved reports and settings) hasn’t been saved.'),
        el('p', {}, 'A copy of the current template is kept with the survey either way, so its data always go with the lists they were recorded with. Saving it as a template first also gives it a name the survey records, and the team can use the same one.')),
      buttons: [{ label: 'Cancel', value: null }, { label: 'Start without saving', value: 'skip' },
        ...(known ? [{ label: `Update ${st.name.replace(/\.spyhop-template\.zip$|\.zip$/i, '')}…`, value: 'update' }] : []),
        { label: 'Save as a new template…', value: 'save', primary: true }] });
    if (!choice) return false;
    if (choice === 'skip') return true;
    return await this.saveTemplate(choice === 'update' ? st.name : null);
  }

  async pickFolder() {
    try { return (await api('/api/pick-folder', {})).path || null; } catch { return null; }
  }

  // from = {template: name} or {backup: name}; else the web address box
  async checkTemplate(from = null) {
    const tp = (this.tpl ||= {});
    let req = from;
    if (!req) { const url = ($('#tpl-url')?.value ?? tp.url ?? '').trim(); tp.url = url; req = { url }; }
    tp.result = null; tp.done = null; tp.busy = from ? null : 'check';
    this.renderTemplates();
    try { tp.result = await api('/api/templates/check', req); } catch { /* the error is shown as a toast */ }
    tp.busy = null;
    this.renderTemplates();
    $('#tpl-result')?.scrollIntoView({ block: 'nearest' });
  }

  async useTemplate() {
    const tp = this.tpl, r = tp?.result;
    if (!r) return;
    const waits = (f) => r.survey_active && f.part === 'data' && f.status !== 'same' && f.status !== 'kept' && !f.colors_only;
    const todo = r.files.filter((f) => f.status !== 'same' && f.status !== 'kept' && !waits(f));
    const backup = todo.length ? ($('#tpl-backup')?.checked ?? true) : false;
    if (todo.length) {
      const over = todo.filter((f) => f.status !== 'new' || f.unit === 'rows' || f.unit === 'report');
      const adds = todo.filter((f) => !over.includes(f));
      let text = over.length ? `${over.length === 1 ? 'This' : 'These'} will be replaced or removed on this computer: ${over.map((f) => f.file).join(', ')}.` : '';
      if (adds.length) text += `${text ? ' ' : ''}Added: ${adds.map((f) => f.unit === 'waypoints' ? `${f.add} waypoint${f.add > 1 ? 's' : ''}` : f.file).join(', ')}.`;
      text += backup ? ' A backup is saved first.' : ' No backup will be saved, so changes made here to these will be lost.';
      const later = r.files.filter(waits).map((f) => f.file);
      if (later.length) text += `\n\nA survey is under way, so these stay as they are until it ends: ${later.join(', ')}.`;
      if (!await confirmBox('Use this template?', text, r.kind === 'backup' ? 'Restore' : 'Use it', true)) return;
    }
    tp.busy = 'use'; this.renderTemplates();
    try {
      const res = await api('/api/templates/use', { token: r.token, backup });
      tp.done = { changed: res.changed, backup: res.backup, copy: res.copy, added: res.added, removed: res.removed_waypoints, kept: res.data_kept || [] }; tp.result = null;
      toast(r.kind === 'backup' ? 'Backup restored' : 'Template used');
    } catch { /* toast shown */ }
    tp.busy = null;
    await this.loadTemplates();
  }

  async backupTemplate() {
    const tp = (this.tpl ||= {});
    try {
      const r = await api('/api/templates/backup', {});
      toast(`Backup saved: ${r.path}`);
    } catch { return; }
    await this.loadTemplates();
  }

  // Settings → General → Altitude and reticles: the Sightings Alt column, and how Unit = reticle
  // readings become distances (spyhop/reticle.py)
  // Settings → General: the Alt column (the reticles themselves are a list: Settings → Dropdowns → Reticles)
  altitudeSection(sec, sel) {
    return sec('Altitude and reticles',
      el('div', { class: 'grid2' },
        el('label', { class: 'row' }, 'Altitude column in Sightings', sel('altitude_column', [['auto', 'Automatic'], ['show', 'Always shown'], ['hide', 'Hidden']]))),
      el('p', { class: 'hint help' }, 'Automatic shows the Alt column for aerial surveys and hides it for shipboard and stationary ones (Survey tab → Platform type). It is always kept in the file. How reticle readings become distances (binoculars, calibrated marks, an inclinometer) is set up in Settings → Dropdowns → Reticles: each entry becomes a Unit, reticles-<name>, in Sightings.'),
      el('p', {}, 'Reticles: ', el('a', { href: '#', id: 'link-reticles', onclick: (e) => { e.preventDefault(); this.ddTab = 'reticles'; this.showTab('dropdowns'); } }, 'Settings → Dropdowns → Reticles')));
  }


  // Settings → General → Tables: Sightings row colors, the effort segment column, column layout
  tablesSection(sec, sel) {
    const d = this.S.config.display;
    const lay = this.S.config.settings.column_layout || {};
    return sec('Tables',
      el('div', { class: 'grid2' },
        el('label', { class: 'row' }, 'Sightings row colors', el('select', { id: 'row-colors', onchange: (e) => this.saveDisplay({ sightings_row_colors: e.target.value }) },
          [['none', 'None'], ['alternate', 'Alternating'], ['resights', 'Highlight resights'], ['groups', 'Group resights']]
            .map(([v, l]) => el('option', { value: v, selected: (d.sightings_row_colors || 'resights') === v }, l)))),
        el('label', { class: 'row' }, 'Effort segment column', sel('segment_column', [['show', 'Shown'], ['hide', 'Hidden']]))),
      el('p', { class: 'hint help' }, 'Group resights gives each sighting that has resights, and its resights, a color of their own. The effort segment (Seg) is numbered by Spyhop: a new number each time the effort status changes. ',
        'Drag a column header to move it, or the edge of a header to change its width; the order and widths are kept on this computer only. Double-click the bar between two panes to put it back where it started.'),
      el('div', { class: 'btnrow' },
        Object.keys(lay).length ? el('button', { id: 'cols-reset-all', onclick: async () => { await this.saveColumnLayout({}); for (const g of Object.values(this.grids)) g.refreshColumns?.(); this.renderSettings(); } }, 'Reset all column orders and widths') : null,
        ' ', el('button', { id: 'btn-reset-panes', title: 'Put the map, Survey/Tools/Settings and the data tables back to their starting sizes', onclick: () => this.resetPanes() }, 'Reset the pane sizes')));
  }

  // Settings → General → Resights: the Sightings table's order, and resights on the map
  resightSection(sec, dnum, dchk) {
    const d = this.S.config.display;
    const dsel = (key, opts, id) => el('select', { id, onchange: (e) => this.saveDisplay({ [key]: e.target.value }) },
      opts.map(([v, l]) => el('option', { value: v, selected: (d[key] || '') === v }, l)));
    return sec('Resights',
      el('p', { class: 'hint help' }, 'A resight is a later sighting of animals already recorded, e.g. on the approach for photos or during a focal follow. Select the sighting and use Add resight: the new row’s ResNo holds the first sighting’s SigNo, and its species, numbers, confidence and FieldID are filled in. Resights aren’t counted again in the Summary, which uses the largest number and calves seen on any resight. Time order lists rows as recorded; Resights nested puts each sighting’s resights straight under it. The marker size is a percentage of the sightings’ marker size.'),
      el('div', { class: 'grid2' },
        el('label', { class: 'row' }, 'Sightings table', dsel('resight_order', [['time', 'Time order'], ['nested', 'Resights nested']], 'resight-order')),
        el('label', { class: 'row' }, 'Resight marker', dsel('resight_marker_shape', [['same', 'Same shape'], ...SHAPES.map((x) => [x, x]), ['hidden', 'Not shown']], 'resight-shape')),
        el('label', { class: 'row' }, 'Resight marker fill', dsel('resight_marker_fill', [['hollow', 'Outline'], ['filled', 'Filled'], ['faded', 'Faded']], 'resight-fill')),
        dnum('resight_marker_size', 'Resight marker size (%)', 30, 150, 5)),
      el('div', { class: 'grid2 checks' },
        dchk('resight_labels', 'Label resight markers on the map')));
  }

  // ---------------------------------------------------------------- settings
  awakeText() {
    const a = this.S.awake || {}, st = this.S.config.settings;
    if (a.error) return `Couldn’t keep the computer awake: ${a.error}`;
    if (a.supported === false) return 'Keeping the computer awake isn’t available on this system.';
    if (a.mode === 'display') return 'Now: keeping the computer awake, with the screen on.';
    if (a.mode === 'system') return 'Now: keeping the computer awake (the screen may still turn off).';
    if (st.keep_awake === 'survey') return 'Now: normal sleep (no survey is active).';
    return 'Now: normal sleep.';
  }

  renderSettings() {
    const pane = $('#pane-settings');
    if (!pane) return;
    const S = this.S, st = S.config.settings, d = S.config.display;
    const num = (key, min, max, step = 1) => el('input', { type: 'number', min, max, step, value: st[key],
      onchange: (e) => { const v = +e.target.value; if (v >= min && v <= max) this.saveSettings({ [key]: v }); else { toast(`Must be ${min}–${max}`, 'warn'); e.target.value = st[key]; } } });
    const sel = (key, opts) => el('select', { onchange: (e) => this.saveSettings({ [key]: e.target.value }) },
      opts.map(([v, l]) => el('option', { value: v, selected: String(st[key]) === v }, l)));
    const chk = (key, label) => el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!st[key],
      onchange: (e) => this.saveSettings({ [key]: e.target.checked }) }), el('span', {}, label));
    const dnum = (key, label, min, max, step = 1) => el('label', { class: 'row' }, label, el('input', { type: 'number', min, max, step, value: d[key],
      onchange: (e) => { const v = +e.target.value; if (v >= min && v <= max) this.saveDisplay({ [key]: e.target.value }); else { toast(`Must be ${min}–${max}`, 'warn'); e.target.value = d[key]; } } }));
    const dchk = (key, label) => el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: d[key] !== '0',
      onchange: (e) => this.saveDisplay({ [key]: e.target.checked ? '1' : '0' }) }), el('span', {}, label));
    const sec = (title, ...kids) => el('section', { class: 'settings-sec' }, el('h3', {}, title), ...kids);

    // settings that change how the data are recorded or worked out can't change during an active survey
    const lockedNow = !!this.S.survey?.active;
    const lockNum = (k, a, b) => { const x = num(k, a, b); if (lockedNow) { x.disabled = true; x.title = 'Locked while a survey is active'; } return x; };
    const lockNote = lockedNow ? el('p', { class: 'hint locked-note' }, '🔒 Settings that change how the data are recorded or worked out (track point interval, trackline breaks, magnetic variation) are locked while a survey is active, like the drop-down lists.') : null;
    const variation = el('input', { type: 'text', value: st.mag_variation, size: 8, disabled: lockedNow, title: lockedNow ? 'Locked while a survey is active' : '',
      onchange: (e) => { const v = e.target.value.trim(); if (v === '' || v === 'auto' || !isNaN(+v)) this.saveSettings({ mag_variation: v || 'auto' }); else toast('Use “auto” or a number of degrees (east +, west −)', 'warn'); } });
    pane.replaceChildren(
      sec('Tracking and reminders',
        el('div', { class: 'grid2' },
          chk('tracking_enabled', 'Record internal trackline (switches on at Start, off at End)'),
          el('label', { class: 'row' }, 'Track point every (s)', lockNum('tracking_interval', 1, 300)),
          el('label', { class: 'row' }, 'Conditions reminder (min)', num('effort_reminder_min', 1, 600)),
          el('label', { class: 'row' }, 'Break the trackline above (kn)', lockNum('track_break_kn', 0, 2000)),
          el('label', { class: 'row' }, '… or after no GPS for (s)', lockNum('track_break_gap_s', 0, 86400))),
        lockNote,
        el('p', { class: 'hint help' }, 'The trackline on the map, and the distances in the summary, are broken where the platform would have moved faster than this between two points (a GPS jump; 30 kn suits a vessel, use about 200 for aerial surveys), or where no position came in for that long. 0 turns either off. Tools → Error check lists each jump or gap, and its Fix button marks it in the Effort table with an ERROR row.')),
      sec('Sleep',
        el('div', { class: 'grid2' },
          el('label', { class: 'row' }, 'Keep the computer awake', sel('keep_awake', [['survey', 'During a survey'], ['always', 'Always'], ['off', 'Never']]))),
        el('div', { class: 'grid2 checks' }, chk('keep_screen_on', 'Keep the screen on too')),
        el('p', { class: 'hint', id: 'awake-status' }, this.awakeText()),
        el('p', { class: 'hint help' }, '“During a survey” means from Start until End (or until the survey is closed); “Always” means whenever Spyhop is open. A computer that sleeps stops recording the trackline and NMEA data. This stops it sleeping when it is left alone; closing a laptop’s lid still puts most laptops to sleep, and a laptop on battery runs down faster. When Spyhop quits, the computer’s own sleep settings apply again.')),
      sec('Bearings, distances and time',
        el('div', { class: 'grid2' },
          el('label', { class: 'row' }, 'Default bearing reference', sel('bearing_reference', [['M', 'Magnetic (compass)'], ['T', 'True'], ['R', 'Relative to bow'], ['C', 'Clock (1–12, relative to bow)']])),
          el('label', { class: 'row' }, 'Default distance unit (Sightings)', sel('distance_unit', [['nm', 'Nautical miles'], ['km', 'Kilometers'], ['m', 'Meters'], ['mi', 'Statute miles'], ['yd', 'Yards'],
            ...(this.S.config.lists.reticles || []).map((r) => [`reticles-${r.name}`, `reticles-${r.name} (a reading: Dropdowns → Reticles)`])])),
          el('label', { class: 'row' }, 'Map distance unit', sel('map_distance_unit', [['nm', 'Nautical miles'], ['km', 'Kilometers'], ['m', 'Meters'], ['mi', 'Statute miles'], ['yd', 'Yards']])),
          el('label', { class: 'row' }, 'Magnetic variation (° E+/W−, or auto)', variation,
            el('span', { class: 'hint' }, ` now ${this.variation() === null ? '—' : this.variation().toFixed(1) + '°'}`)),
          el('label', { class: 'row' }, 'Lat/lon format', sel('latlon_format', [['DDM', 'Deg + decimal min'], ['DD', 'Decimal degrees'], ['DMS', 'Deg min sec']])),
          el('label', { class: 'row' }, 'Clock', sel('timezone', this.clockOptions()), this.clockHint())),
        el('p', { class: 'hint help' }, 'The map distance unit is used for the measuring tool, popups, routes and the Summary’s distances; the Sightings default is the Unit of new sightings. A clock bearing (Ref C) is picked from 1 to 12 o’clock, each hour 30° from the bow (3 = starboard beam). Each sighting row stores its own bearing reference and distance unit, so changing these defaults never changes old rows. “auto” variation uses the World Magnetic Model if installed, otherwise the GPS. The clock setting changes how all times are shown; the files always store the UTC offset with each time.')),
      this.altitudeSection(sec, sel),
      sec('GPS / NMEA inputs', el('p', {}, 'GPS and instrument inputs are in ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.showTab('inputs'); } }, 'Settings → Inputs'),
        '; live readings and raw NMEA logging in ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.showTab('nmea'); } }, 'Tools → Instruments'), '.')),
      sec('Text size',
        el('div', { class: 'grid2' },
          dnum('grid_font_size', 'Table font size', 9, 28), dnum('ui_font_size', 'Interface font size', 9, 24),
          dnum('status_font_size', 'Status bar font size', 9, 36))),
      sec('Map display',
        el('h4', {}, 'Markers'),
        el('div', { class: 'grid2' },
          ...['sightings', 'events'].map((t) => el('label', { class: 'row' },
            `${t === 'sightings' ? 'Sightings' : 'Events'} marker (default)`,
            el('span', { class: 'inline' },
              el('select', { title: 'Marker shape', onchange: (e) => this.saveDisplay({ [`${t}_marker_shape`]: e.target.value }) },
                SHAPES.map((s) => el('option', { value: s, selected: d[`${t}_marker_shape`] === s }, s))),
              el('input', { type: 'color', title: `Used when ${t === 'sightings' ? 'a species' : 'an event type'} has no color in ${t === 'sightings' ? 'species' : 'event_types'}.csv (or color-by-${t === 'sightings' ? 'species' : 'event'} is off)`,
                value: toHex(d[`${t}_marker_color`] || 'orange'), onchange: (e) => this.saveDisplay({ [`${t}_marker_color`]: e.target.value }) })))),
          dnum('marker_radius', 'Marker size', 3, 24), dnum('label_size', 'Marker label size', 8, 24)),
        el('div', { class: 'grid2 checks' }, dchk('use_species_colors', 'Color markers by species/event')),
        el('h4', {}, 'Trackline'),
        el('p', { class: 'hint help' }, 'The track is drawn in the color of each Effort value (Settings → Dropdowns → Effort); here, whether it shows and how wide it is, on and off effort.'),
        el('table', { class: 'track-style' },
          el('thead', {}, el('tr', {}, ['', 'Show', 'Width (px)', 'Line'].map((h) => el('th', {}, h)))),
          el('tbody', {}, [['on', 'On effort', 'show_track_on', 'track_width', 'track_on_style', 3],
            ['off', 'Off effort', 'show_track_off', 'track_off_width', 'track_off_style', 1.5]].map(([, label, show, width, style, dw]) =>
            el('tr', {},
              el('th', {}, label),
              el('td', {}, el('input', { type: 'checkbox', checked: d[show] !== '0', title: `Show the ${label.toLowerCase()} track`, onchange: (e) => this.saveDisplay({ [show]: e.target.checked ? '1' : '0' }) })),
              el('td', {}, el('input', { type: 'number', min: 0.5, max: 10, step: 0.5, value: d[width] || dw, style: 'width:4.5em',
                onchange: (e) => { const v = +e.target.value; if (v >= 0.5 && v <= 10) this.saveDisplay({ [width]: String(v) }); else { toast('Must be 0.5–10', 'warn'); e.target.value = d[width] || dw; } } })),
              el('td', {}, el('select', { onchange: (e) => this.saveDisplay({ [style]: e.target.value }) },
                LINE_STYLES.map(([v, l]) => el('option', { value: v, selected: (d[style] || 'solid') === v }, l)))))))),
        el('h4', {}, 'Lines and vectors'),
        // the lines' show / width / line style; their color is the sighting's
        el('table', { class: 'track-style', id: 'line-styles' },
          el('thead', {}, el('tr', {}, ['', 'Show', 'Width (px)', 'Line'].map((h) => el('th', {}, h)))),
          el('tbody', {}, [['Vessel to each sighting', 'sighting_lines', '1', 1.5, 'dashed'],
            ['Joining sightings with the same FieldID (oldest → newest)', 'fieldid_lines', '0', 2.5, 'dotted'],
            ['From each sighting through its resights (oldest → newest)', 'resight_lines', '1', 2.5, 'dotted']].map(([label, key, on, dw, ds]) =>
            el('tr', { 'data-line': key },
              el('th', {}, label),
              el('td', {}, el('input', { type: 'checkbox', checked: (d[key] ?? on) === '1', 'aria-label': `Show lines: ${label}`, onchange: (e) => this.saveDisplay({ [key]: e.target.checked ? '1' : '0' }) })),
              el('td', {}, el('input', { type: 'number', min: 0.5, max: 10, step: 0.5, value: d[`${key}_width`] || dw, style: 'width:4.5em', 'aria-label': `Width: ${label}`,
                onchange: (e) => { const v = +e.target.value; if (v >= 0.5 && v <= 10) this.saveDisplay({ [`${key}_width`]: String(v) }); else { toast('Must be 0.5–10', 'warn'); e.target.value = d[`${key}_width`] || dw; } } })),
              el('td', {}, el('select', { 'aria-label': `Line: ${label}`, onchange: (e) => this.saveDisplay({ [`${key}_style`]: e.target.value }) },
                LINE_STYLES.map(([v, l]) => el('option', { value: v, selected: (d[`${key}_style`] || ds) === v }, l)))))))),
        el('div', { class: 'grid2' }, dnum('heading_vector_min', 'Heading vector (minutes ahead)', 1, 120)),
        el('div', { class: 'grid2 checks' },
          dchk('heading_vector', 'Vessel heading vector'),
          el('label', { class: 'check', title: 'Only the drawing is smoothed: recorded positions are never changed. Kept on this computer only.' },
            el('input', { type: 'checkbox', id: 'smooth-vessel', checked: st.smooth_vessel !== false, onchange: (e) => this.saveSettings({ smooth_vessel: e.target.checked }) }),
            el('span', {}, 'Smooth vessel movement: glide the vessel between GPS fixes (on the map only, this computer only)')),
          dchk('focus_selected', 'Move the map to a sighting, event or waypoint selected in its table')),
        el('h4', {}, 'Fading'),
        el('div', { class: 'grid2' }, dnum('fade_min', 'Fade after (minutes)', 1, 1440, 1)),
        el('div', { class: 'grid2 checks' }, dchk('fade_enabled', 'Fade the trackline, sightings and events older than this (waypoints never fade)'))),
      this.tablesSection(sec, sel),
      this.resightSection(sec, dnum, dchk),
      sec('Basemap and offline charts', el('p', {}, 'The map’s layers, downloads for offline use and the charts folder are in ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.showTab('basemap'); } }, 'Settings → Basemap'), '.')),
      this.foldersSection(),
      );
    for (const row of pane.querySelectorAll('label.row')) {
      const first = row.firstChild;
      if (first && first.nodeType === 3) row.replaceChild(el('span', { class: 'lbl' }, first.textContent), first);
    }  }

  // Settings → Basemap: map layers, downloads for offline use and the charts folder
  renderBasemap() {
    const pane = $('#pane-basemap');
    if (!pane) return;
    pane.replaceChildren(this.mapSection());
    this.renderChartList();
  }

  // ---------------------------------------------------------------- shortcuts tab
  // Settings → Shortcuts: an editable table of keyboard shortcuts (shortcuts.csv)
  shortcutActions() {
    const tabName = Object.fromEntries([...this.dataTabs().map((t) => [t, this.S.schema.tabs[t].title]),
      ['survey', 'Survey'], ...this.groupTabs().map(([k]) => [k, this.tabPath(k)])]);
    return [
      ['add:sightings', 'Add a sighting'], ['add:effort', 'Add a conditions (effort) row'], ['add:events', 'Add an event'],
      ['add:marks', 'Add a waypoint'], ['add-current', 'Add a row to the data table in view'], ['add-resight', 'Add a resight of the selected sighting'],
      ['toggle-effort', 'Add an effort row that switches effort ON↔OFF'],
      ['undo', 'Undo in the current table'], ['redo', 'Redo in the current table'],
      ['next-tab', 'Next tab'], ['prev-tab', 'Previous tab'],
      ...this.allTabs().map((k) => [`tab:${k}`, `Show ${tabName[k] || k}`]),
      ['center-vessel', 'Center the map on the vessel'], ['measure', 'Start or stop measuring on the map'],
      ['toggle-log', 'Minimize / restore the data tables'], ['max-log', 'Maximize / restore the data tables'],
    ];
  }

  // a key press → a combo in shortcuts.csv's form (Mod+Shift+R), or null for a lone modifier
  comboFromEvent(e) {
    if (['Shift', 'Control', 'Meta', 'Alt', 'CapsLock', 'OS'].includes(e.key)) return null;
    let key = e.key;
    if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3);
    else if (/^Digit[0-9]$/.test(e.code)) key = e.code.slice(5);
    else if (key.length === 1) key = key.toUpperCase();
    const mods = [(IS_MAC ? e.metaKey : e.ctrlKey) && 'Mod', e.shiftKey && 'Shift', e.altKey && 'Alt'].filter(Boolean);
    return [...mods, key].join('+');
  }

  renderShortcuts() {
    const pane = $('#pane-shortcuts');
    if (!pane) return;
    const saved = this.S.config.shortcuts.map((s) => ({ combo: s.combo || '', action: s.action || '', prefill: s.prefill || '' }));
    const rows = this.scDraft || saved;
    const dirty = !!this.scDraft && JSON.stringify(this.scDraft) !== JSON.stringify(saved);
    const actions = this.shortcutActions();
    const label = Object.fromEntries(actions);
    const edit = () => { if (!this.scDraft) this.scDraft = rows.map((r) => ({ ...r })); return this.scDraft; };
    const markDirty = () => { const b = $('#btn-sc-save'); if (b) { b.classList.add('dirty'); b.textContent = 'Save — unsaved changes'; } };
    const norm = (c) => (c || '').toLowerCase().split('+').sort().join('+');
    const count = {};
    rows.forEach((r) => { if (r.combo) count[norm(r.combo)] = (count[norm(r.combo)] || 0) + 1; });
    const RESERVED = IS_MAC ? ['Mod+W', 'Mod+Q', 'Mod+T', 'Mod+N', 'Mod+H', 'Mod+M', 'Mod+Tab', 'Mod+Shift+T']
      : ['Mod+W', 'Mod+T', 'Mod+N', 'Mod+Tab', 'Mod+Shift+T', 'Mod+Shift+N', 'Alt+F4'];
    const shown = (c) => (c || '').replace(/^Mod(?=\+)|(?<=\+)Mod(?=\+)/g, MOD);
    const keyCell = (r, i) => {
      const b = el('button', { class: 'combo mono', title: 'Click, then press the keys' }, r.combo ? shown(r.combo) : 'Set keys…');
      b.onclick = () => {
        b.textContent = 'Press the keys… (Esc cancels)'; b.classList.add('capturing');
        const handler = (e) => {
          if (!b.isConnected) { this.comboCapture = null; return false; }   // the table was redrawn or left
          if (e.type !== 'keydown') return;
          e.preventDefault(); e.stopPropagation();
          if (e.key === 'Escape') { this.comboCapture = null; this.renderShortcuts(); return; }
          const c = this.comboFromEvent(e);
          if (!c) return;
          if (!/(^|\+)(Mod|Alt)\+/.test(c) && !/^(Shift\+)?F([1-9]|1[0-9]|2[0-4])$/.test(c)) {
            toast('A shortcut needs Mod or Alt (or use F1–F12), so it doesn’t get in the way of typing.', 'warn');
            return;
          }
          if (c.endsWith('+ ') || c === ' ') { toast('The space bar can’t be a shortcut key.', 'warn'); return; }
          this.comboCapture = null;
          edit()[i].combo = c;
          this.renderShortcuts();
        };
        this.comboCapture = handler;
        b.onblur = () => { if (this.comboCapture === handler) { this.comboCapture = null; this.renderShortcuts(); } };
      };
      return b;
    };
    const preWidth = Math.min(90, Math.max(32, ...rows.map((r) => (r.prefill || '').length + 3)));
    const body = rows.map((r, i) => {
      const verb = r.action.split(':')[0];
      const canPrefill = verb === 'add' || r.action === 'add-current';
      const dup = r.combo && count[norm(r.combo)] > 1;
      const warn = RESERVED.includes(r.combo);
      const sel = el('select', { onchange: (e) => { edit()[i].action = e.target.value; if (!/^add/.test(e.target.value)) edit()[i].prefill = ''; this.renderShortcuts(); } },
        (label[r.action] ? [] : [el('option', { value: r.action, selected: true }, r.action ? `${r.action} (unknown)` : 'Choose…')]),
        actions.map(([v, l]) => el('option', { value: v, selected: v === r.action }, l)));
      // wide enough for the longest pre-fill in the table (and it grows as you type)
      const pre = el('input', { type: 'text', value: r.prefill, disabled: !canPrefill, placeholder: canPrefill ? 'e.g. Species=Fin whale;Obs=OBS1' : '',
        style: { minWidth: `${preWidth}ch` },
        oninput: (e) => { edit()[i].prefill = e.target.value; e.target.style.minWidth = `${Math.max(preWidth, e.target.value.length + 3)}ch`; markDirty(); } });
      return el('tr', { class: dup ? 'bad' : null },
        el('td', {}, keyCell(r, i), dup ? el('div', { class: 'cell-err' }, 'Used twice') : null,
          warn ? el('div', { class: 'cell-warn', title: 'The browser or the computer may use these keys itself' }, '⚠ may be taken by the browser') : null),
        el('td', {}, sel), el('td', {}, pre),
        el('td', { class: 'rowbtns' },
          el('button', { title: 'Move up', disabled: i === 0, onclick: () => { const d = edit(); [d[i - 1], d[i]] = [d[i], d[i - 1]]; this.renderShortcuts(); } }, '↑'),
          el('button', { title: 'Move down', disabled: i === rows.length - 1, onclick: () => { const d = edit(); [d[i + 1], d[i]] = [d[i], d[i + 1]]; this.renderShortcuts(); } }, '↓'),
          el('button', { title: 'Delete', class: 'danger-outline', onclick: () => { edit().splice(i, 1); this.renderShortcuts(); } }, '✕')));
    });
    pane.replaceChildren(el('section', { class: 'settings-sec' }, el('h3', {}, 'Keyboard shortcuts'),
      el('p', {}, `Click a shortcut’s keys to change them, choose what it does, and press Save. “Mod” is ${MOD} on this computer. Shortcuts that add a row can pre-fill columns, e.g. `,
        el('span', { class: 'mono' }, 'Species=Fin whale;Obs=OBS1'), ' (the column names are listed below the table).'),
      el('table', { class: 'summary edit-table shortcut-edit' },
        el('thead', {}, el('tr', {}, ['Keys', 'What it does', 'Pre-fill', ''].map((h) => el('th', {}, h)))),
        el('tbody', {}, body)),
      el('div', { class: 'btnrow' },
        el('button', { onclick: () => { edit().push({ combo: '', action: 'add:sightings', prefill: '' }); this.renderShortcuts(); } }, 'Add shortcut'),
        el('button', { onclick: () => { this.scDraft = this.S.config.default_shortcuts.map((s) => ({ combo: s.combo, action: s.action, prefill: s.prefill || '' })); this.renderShortcuts(); } }, 'Restore the default shortcuts')),
      el('details', { class: 'hint', id: 'sc-columns' }, el('summary', {}, 'Column names for pre-fills'),
        ...this.dataTabs().map((tb) => el('p', {}, el('b', {}, `${this.S.schema.tabs[tb].title}: `),
          el('span', { class: 'mono' }, this.S.schema.tabs[tb].columns.filter((c) => !['RowID', 'Map'].includes(c.key)).map((c) => c.key).join(', '))))),
      el('div', { id: 'sc-errors' }),
      el('div', { class: 'btnrow' },
        el('button', { id: 'btn-sc-save', class: `primary${dirty ? ' dirty' : ''}`, onclick: () => this.saveShortcuts() }, dirty ? 'Save — unsaved changes' : 'Save'),
        el('button', { onclick: () => { this.scDraft = null; this.renderShortcuts(); } }, 'Revert')),
      el('p', { class: 'hint help' }, `Some ${MOD}+key combinations are taken by web browsers; the app window (the default launch) avoids most of them.`),
      this.fileBox('shortcuts.csv', 'config:shortcuts', () => { this.scDraft = null; })));
  }

  // the "edit the file in a spreadsheet" box under the Shortcuts and Dropdowns editors
  fileBox(file, what, dropDraft, locked = false) {
    return el('div', { class: 'filebox' },
      el('div', {}, el('b', {}, 'Many changes at once? '), 'Edit ', el('span', { class: 'mono' }, file),
        ' in a spreadsheet or text editor, save it, then press Reload. Keep the first (header) row as it is.',
        el('div', { class: 'hint mono' }, (() => { const d = this.S.config.current_dir || this.S.config.root; return `${d}${d.includes('\\') ? '\\' : '/'}${file}`; })())),
      el('div', { class: 'btnrow' },
        el('button', { onclick: () => this.open(what) }, `Open ${file}`),
        el('button', { disabled: locked, onclick: async () => {
          dropDraft();
          try { await api('/api/config/reload', {}); } catch { return; }
          toast(`${file} reloaded`);
        } }, 'Reload from the file')));
  }

  async saveShortcuts() {
    const rows = this.scDraft;
    if (!rows) { toast('No changes to save.', 'info', 2000); return; }
    const box = $('#sc-errors');
    try {
      await api('/api/config/shortcuts', { rows });
    } catch (e) {
      if (box) box.replaceChildren(el('div', { class: 'errbox' }, el('b', {}, 'Not saved:'), el('ul', {}, String(e.message || '').split('\n').map((l) => el('li', {}, l)))));
      return;
    }
    this.scDraft = null;
    toast('Shortcuts saved');
  }

  // ---------------------------------------------------------------- Settings → Dropdowns: the drop-down lists
  dropdownLists() { return [['species', 'Species'], ['event_types', 'Events'], ['behaviors', 'Behaviors'], ['observers', 'Observers'],
    ['effort', 'Effort'], ['visibility', 'Visibility'], ['weather', 'Weather'], ['reticles', 'Reticles']]; }

  renderDropdowns() {
    const pane = $('#pane-dropdowns');
    if (!pane) return;
    const S = this.S, lists = this.dropdownLists();
    let cur = this.ddTab;
    if (!cur) { try { cur = localStorage.getItem('wsr.ddtab'); } catch {} }
    if (!lists.some(([k]) => k === cur)) cur = 'species';
    this.ddTab = cur;
    this.ddDrafts ||= {};
    const locked = !!S.survey?.active;
    const labels = S.config.list_labels[cur] || {};
    const fileCols = S.config.list_columns[cur] || ['name'];
    const cols = [...Object.keys(labels).filter((c) => fileCols.includes(c)), ...fileCols.filter((c) => !(c in labels))];
    const saved = (S.config.lists[cur] || []).map((r) => Object.fromEntries(cols.map((c) => [c, r[c] ?? ''])));
    const rows = this.ddDrafts[cur] || saved;
    const dirty = !!this.ddDrafts[cur] && JSON.stringify(this.ddDrafts[cur]) !== JSON.stringify(saved);
    const edit = () => { if (!this.ddDrafts[cur]) this.ddDrafts[cur] = rows.map((r) => ({ ...r })); return this.ddDrafts[cur]; };
    const markDirty = () => { const b = $('#btn-dd-save'); if (b) { b.classList.add('dirty'); b.textContent = 'Save — unsaved changes'; } };
    const uniq = cols.filter((c) => c === 'name' || /_code$/.test(c));
    const counts = Object.fromEntries(uniq.map((c) => [c, {}]));
    rows.forEach((r) => uniq.forEach((c) => { const v = (r[c] || '').trim().toLowerCase(); if (v) counts[c][v] = (counts[c][v] || 0) + 1; }));
    const okColor = (v) => !v || (typeof CSS !== 'undefined' && CSS.supports ? CSS.supports('color', v) : true);
    const toHex = (v) => { const c = document.createElement('canvas').getContext('2d'); c.fillStyle = '#000'; c.fillStyle = v || '#000'; return c.fillStyle.startsWith('#') ? c.fillStyle : '#000000'; };
    const R = S.schema.reticle || { methods: {}, presets: {} };
    const required = (r) => cur === 'effort' && EFFORT_REQUIRED.includes(r.name);   // Start, End, ERROR: always there
    const fixedName = (r) => required(r) || r.name === 'Other';     // Other: in every list (0.40), the placeholder
    const cell = (r, i, c) => {
      if (cur === 'effort' && c === 'status') {
        return el('td', {}, el('select', { disabled: locked || required(r), 'data-col': c,
          title: required(r) ? `${r.name} always counts as off effort` : 'On effort: drawn and counted as on effort (Summary, reports, Error check)',
          onchange: (e) => { edit()[i].status = e.target.value; markDirty(); } },
          el('option', { value: '', selected: !r.status }, '—'),
          [['on', 'on effort'], ['off', 'off effort']].map(([v, l]) => el('option', { value: v, selected: r.status === v }, l))));
      }
      if (c === 'name' && fixedName(r)) {
        return el('td', {}, el('input', { type: 'text', value: r.name, disabled: true, 'data-col': c, size: 26,
          title: r.name === 'Other' ? 'The placeholder for anything missing from this list: can’t be renamed or removed' : 'Needed by Spyhop: can’t be renamed or removed' }));
      }
      if (cur === 'reticles' && c === 'method') {
        return el('td', {}, el('select', { disabled: locked, 'data-col': c, onchange: (e) => { edit()[i].method = e.target.value; this.renderDropdowns(); } },
          el('option', { value: '', selected: !r.method }, '—'),
          Object.entries(R.methods).map(([v, l]) => el('option', { value: v, selected: r.method === v }, l))));
      }
      if (cur === 'reticles' && c === 'magnification') {
        return el('td', {}, el('select', { disabled: locked || r.method !== 'binoculars', 'data-col': c, onchange: (e) => {
          const d = edit()[i], p = R.presets[e.target.value];
          d.magnification = e.target.value;
          if (p && p[1]) d.deg_per_division = String(p[1]);
          this.renderDropdowns();
        } }, el('option', { value: '', selected: !r.magnification }, '—'),
        Object.entries(R.presets).map(([k, [label]]) => el('option', { value: k, selected: String(r.magnification) === k }, label))));
      }
      if (cur === 'reticles' && c === 'deg_per_division') {
        const on = r.method === 'binoculars' || r.method === 'marks';
        return el('td', {}, el('input', { type: 'text', value: on ? r[c] ?? '' : '', disabled: locked || !on, 'data-col': c, size: 8,
          placeholder: r.method === 'marks' ? '5' : r.method === 'binoculars' ? '0.573' : '',
          title: r.method === 'marks' ? 'Degrees between one mark and the next' : r.method === 'binoculars' ? 'Degrees per reticle division' : 'Not used: the reading is the angle itself',
          oninput: (e) => { edit()[i][c] = e.target.value; markDirty(); } }));
      }
      if (c === 'color') {
        const sw = el('span', { class: 'swatch', style: { background: okColor(r.color) ? r.color || 'transparent' : 'transparent' } });
        const txt = el('input', { type: 'text', value: r.color, class: okColor(r.color) ? null : 'invalid', size: 12,
          oninput: (e) => { edit()[i].color = e.target.value.trim(); const ok = okColor(e.target.value.trim()); e.target.classList.toggle('invalid', !ok); sw.style.background = ok ? e.target.value : 'transparent'; markDirty(); } });
        const pick = el('input', { type: 'color', value: toHex(r.color), title: 'Pick a color',
          oninput: (e) => { edit()[i].color = e.target.value; txt.value = e.target.value; txt.classList.remove('invalid'); sw.style.background = e.target.value; markDirty(); } });
        return el('td', { class: 'color-cell' }, sw, txt, pick);
      }
      const v = r[c] ?? '';
      const dup = uniq.includes(c) && v.trim() && counts[c][v.trim().toLowerCase()] > 1;
      return el('td', {}, el('input', { type: 'text', value: v, disabled: locked, class: dup || (c === 'name' && !v.trim() && Object.values(r).some((x) => x)) ? 'invalid' : null,
        size: c === 'definition' ? 60 : c === 'name' || c === 'full_name' ? 26 : 10, 'data-col': c,
        title: dup ? 'Used more than once' : '',
        oninput: (e) => { edit()[i][c] = e.target.value; markDirty(); } }));
    };
    const body = rows.map((r, i) => el('tr', {}, ...cols.map((c) => cell(r, i, c)),
      el('td', { class: 'rowbtns' },
        el('button', { title: 'Move up', disabled: locked || i === 0, onclick: () => { const d = edit(); [d[i - 1], d[i]] = [d[i], d[i - 1]]; this.renderDropdowns(); } }, '↑'),
        el('button', { title: 'Move down', disabled: locked || i === rows.length - 1, onclick: () => { const d = edit(); [d[i + 1], d[i]] = [d[i], d[i + 1]]; this.renderDropdowns(); } }, '↓'),
        el('button', { title: fixedName(r) ? 'Always in the list: can’t be removed' : 'Delete', class: 'danger-outline', disabled: locked || fixedName(r), onclick: () => { edit().splice(i, 1); this.renderDropdowns(); } }, '✕'))));
    const pills = el('div', { class: 'report-tabs', id: 'dd-tabs' }, lists.map(([k, l]) => el('button', {
      class: `report-tab${k === cur ? ' active' : ''}${this.ddDrafts[k] ? ' has-draft' : ''}`, 'data-list': k,
      onclick: () => { this.ddTab = k; try { localStorage.setItem('wsr.ddtab', k); } catch {} this.renderDropdowns(); } },
    l, el('span', { class: 'count' }, String((this.ddDrafts[k] || S.config.lists[k] || []).length)))));
    const what = { species: 'The Species drop-down in Sightings. The code labels sightings on the map and is used by reports; the color is the marker color when “color by species” is on.',
      event_types: 'The Event drop-down in Events. The code labels events on the map and is used by reports.',
      behaviors: 'The Behaviors drop-down in Sightings (several can be chosen).',
      observers: 'The observer drop-downs (Obs in Sightings; Port, Recorder and Stbd in Effort). The initials are what’s recorded; NA means nobody in that position.',
      visibility: 'The Vis drop-down in Effort. The Error check reads distances from the names (e.g. “1-2 nm” is at most 2 nm, “<0.5 nm” at most 0.5; km, m and mi are understood) to flag sightings beyond the visibility.',
      weather: 'The Weather drop-down in Effort.',
      effort: 'The Effort drop-down in Effort. Status decides whether a value counts as on or off effort: for the track on the map (drawn in the value’s color, with the on- or off-effort width and line from Settings → General → Map display), the Summary’s time on effort and distances, reports and the Error check. Start, End and ERROR are needed by Spyhop and can’t be renamed or removed: Start and End are the first and last rows (Start / End survey in the Survey tab), and Error check → Fix adds ERROR rows to mark a trackline break.',
      reticles: 'How reticle readings are turned into distances. Each entry is a Unit in Sightings, reticles-<name> (e.g. reticles-binos): type the reading in Dist and the animals’ position comes from the bearing, the reading and the platform altitude (the row’s Alt), allowing for the curvature of the earth (Lerczak & Hobbs 1998). Binocular reticles: divisions counted down from the horizon, each a fixed angle (the magnification suggests one, but check the binoculars’ manual or calibrate them: many 7×50 and 10× marine binoculars have a 10-mil scale, 0.573° per division; Fujinon 25×150 big-eyes are 0.0771°, Kinzey & Gerrodette 2001). Calibrated marks: evenly spaced marks (e.g. on an aircraft’s window or strut), counted down from the horizontal (mark 0); Degrees per division is the angle between one mark and the next, so mark n is n × that angle below the horizontal (no magnification). Inclinometer degrees: the reading is the angle below the horizontal (90 = straight down). Other (reticles-Other) is the placeholder: the reading is kept, but no distance is worked out until the right reticle is put in after the survey. Names may use letters, digits, - _ and . (no spaces).' }[cur];
    pane.replaceChildren(pills, el('section', { class: `settings-sec dd-sec${locked ? ' dd-locked' : ''}` },
      el('h3', {}, Object.fromEntries(lists)[cur]),
      locked ? el('p', { class: 'warnbox', id: 'dd-locked' }, el('b', {}, cols.includes('color') ? 'A survey is under way, so only the colors can be changed. ' : 'A survey is under way, so this list can’t be changed. '),
        'Use Other for anything missing from a list, and fill in the right entry after the survey (the Error check lists the rows). End the survey (in Survey) to edit the lists.') : null,
      el('p', { class: 'hint help' }, what),
      el('table', { class: 'summary edit-table dd-edit', 'data-list': cur },
        el('thead', {}, el('tr', {}, ...cols.map((c) => el('th', {}, labels[c] || c)), el('th', {}, ''))),
        el('tbody', {}, body)),
      el('div', { class: 'btnrow' },
        el('button', { disabled: locked, onclick: () => { edit().push({ ...Object.fromEntries(cols.map((c) => [c, ''])), ...(cur === 'reticles' ? { method: 'binoculars' } : cur === 'effort' ? { status: 'on' } : {}) }); this.renderDropdowns();
          const ins = $$('#pane-dropdowns tbody tr:last-child input[type=text]'); ins[0]?.focus(); } }, 'Add entry'),
        el('button', { disabled: locked, onclick: () => { edit().sort((a, b) => (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' })); this.renderDropdowns(); } }, 'Sort A–Z')),
      el('div', { id: 'dd-errors' }),
      el('div', { class: 'btnrow' },
        el('button', { id: 'btn-dd-save', class: `primary${dirty ? ' dirty' : ''}`, disabled: locked && !cols.includes('color'), onclick: () => this.saveDropdown(cur) }, dirty ? 'Save — unsaved changes' : 'Save'),
        el('button', { disabled: !this.ddDrafts[cur] || (locked && !cols.includes('color')), onclick: () => { delete this.ddDrafts[cur]; this.renderDropdowns(); } }, 'Revert')),
      el('p', { class: 'hint help' }, 'The order here is the order in the drop-down. Renaming or removing an entry doesn’t change rows already recorded; the Error check flags values that are no longer in the list. Every list has Other, a placeholder for anything missing from it: lists can’t change during a survey (only their colors can), so record it as Other and fill in the right entry afterwards — the Error check lists the rows that use Other.'),
      this.fileBox(`${cur}.csv`, `config:${cur}`, () => { delete this.ddDrafts[cur]; }, locked)));
  }

  async saveDropdown(list) {
    const rows = this.ddDrafts?.[list];
    if (!rows) { toast('No changes to save.', 'info', 2000); return; }
    const box = $('#dd-errors');
    try {
      await api('/api/config/list', { list, rows });
    } catch (e) {
      if (box) box.replaceChildren(el('div', { class: 'errbox' }, el('b', {}, 'Not saved:'), el('ul', {}, String(e.message || '').split('\n').map((l) => el('li', {}, l)))));
      return;
    }
    delete this.ddDrafts[list];
    toast(`${Object.fromEntries(this.dropdownLists())[list]} list saved`);
  }

  // Settings → General → Clock choices: the computer's zone, the platform's position, UTC, and every UTC offset
  clockOptions() {
    const hrs = [-12, -11, -10, -9.5, -9, -8, -7, -6, -5, -4, -3.5, -3, -2, -1, 1, 2, 3, 3.5, 4, 4.5, 5, 5.5,
      5.75, 6, 6.5, 7, 8, 8.75, 9, 9.5, 10, 10.5, 11, 12, 12.75, 13, 14];
    const name = (h) => { const m = Math.round(Math.abs(h) * 60); return `UTC${h < 0 ? '-' : '+'}${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`; };
    const c = this.S.clock || {};
    const here = c.setting === 'auto' && c.zone ? ` — now ${c.zone.replace(/_/g, ' ')}, ${timeParts(new Date(), c.zone)?.abbr || ''}` : '';
    return [['auto', `From the platform’s position${here}`], ['local', `This computer’s time zone (${timeParts(new Date(), 'local').abbr})`],
      ['UTC', 'UTC'], ...hrs.map((h) => [name(h), name(h).replace('-', '−')])];
  }

  clockHint() {
    const c = this.S.clock || {};
    if ((this.S.config.settings.timezone || 'local') !== 'auto') return null;
    const how = { position: 'the zone at the platform’s position', 'nearest coast': 'the nearest coast’s zone (at sea)',
      'nautical zone': 'the nautical zone (far from any coast)', longitude: 'the nautical zone for the longitude (zone map not installed)' }[c.how] || c.how || '';
    return el('span', { class: 'hint', id: 'clock-hint' }, c.zone ? ` ${c.zone.replace(/_/g, ' ')}: ${how}` : ' no position yet: using this computer’s zone');
  }

  // the zone from the position changed (or was found): redraw every time on screen
  onClockChanged() {
    this.refreshFormats();
    this.updateStatus();
    if (this.shown('settings')) this.renderSettings();
  }

  nmeaSection() {
    const st = this.S.config.settings;
    // Edits are kept in a draft until Apply, so redrawing Settings never loses them.
    if (!this.nmeaDraft) {
      const base = this.S.nmea?.all_sources || st.nmea_sources || [];
      this.nmeaDraft = { sources: JSON.parse(JSON.stringify(base)), dirty: false };
    }
    const draft = this.nmeaDraft, sources = draft.sources;
    const list = el('div', { class: 'nmea-list' });
    const fields = { serial: [['port', 'Port', 'text'], ['baud', 'Baud', 'number']], udp: [['port', 'UDP port', 'number']],
      tcp: [['host', 'Host', 'text'], ['port', 'Port', 'number']], gpsd: [['host', 'Host', 'text'], ['port', 'Port', 'number']],
      file: [['path', 'File path', 'text'], ['speed', 'Speed ×', 'number']],
      sim: [['heading', 'Heading °T', 'number'], ['speed_kn', 'Speed kn', 'number'], ['lat', 'Start lat', 'number'], ['lon', 'Start lon', 'number']] };
    const defaults = { serial: { port: '', baud: 4800 }, udp: { port: 10110 }, tcp: { host: '192.168.1.1', port: 10110 }, gpsd: { host: '127.0.0.1', port: 2947 }, file: { path: '', speed: 1 }, sim: { lat: 41.9, lon: -70.33, speed_kn: 10, heading: 0 } };
    const applyBtn = el('button', { class: 'primary', onclick: () => apply() }, 'Apply');
    const markDirty = () => {
      draft.dirty = true;
      applyBtn.classList.add('dirty');
      applyBtn.textContent = 'Apply — unsaved changes';
    };
    const apply = async () => {
      try {
        const r = await api('/api/nmea/sources', { sources });
        this.S.nmea = { ...(this.S.nmea || {}), all_sources: r.sources };
        this.nmeaDraft = null;
        toast('GPS inputs applied');
        this.renderInputs();
      } catch {}
    };
    const draw = () => {
      list.replaceChildren(...sources.map((s, i) => el('div', { class: `nmea-src${s.session ? ' session' : ''}` },
        el('input', { type: 'checkbox', checked: s.enabled !== false, title: 'Enabled', onchange: (e) => { s.enabled = e.target.checked; markDirty(); } }),
        el('select', { onchange: (e) => { sources[i] = { type: e.target.value, enabled: true, ...defaults[e.target.value], ...(s.session ? { session: true } : {}) }; markDirty(); draw(); } },
          Object.keys(fields).map((t) => el('option', { value: t, selected: t === s.type }, t === 'sim' ? 'SIMULATOR' : t.toUpperCase()))),
        ...(fields[s.type] || []).flatMap(([k, label, type]) => [el('label', { class: 'inline' }, label,
          el('input', { type, value: s[k] ?? '', size: k === 'path' ? 30 : (k === 'heading' || k === 'speed_kn' ? 5 : 10),
            style: type === 'number' ? { width: k === 'heading' || k === 'speed_kn' ? '5em' : '7em' } : null,
            min: k === 'heading' ? 0 : null, max: k === 'heading' ? 359 : null,
            list: k === 'port' && s.type === 'serial' ? 'serial-ports' : null,
            oninput: () => markDirty(),
            onchange: (e) => { s[k] = type === 'number' ? +e.target.value : e.target.value; markDirty(); },
            onkeydown: (e) => { if (e.key === 'Enter') { s[k] = type === 'number' ? +e.target.value : e.target.value; apply(); } } })),
          k === 'path' ? el('button', { title: 'Find the NMEA log on this computer', onclick: async () => {
            let r;
            try { r = await api('/api/pick-file', { current: s.path || '' }); } catch { return; }
            if (r.path) { s.path = r.path; markDirty(); draw(); }
          } }, 'Choose…') : null]),
        s.session ? el('span', { class: 'hint', title: 'Started from the command line (e.g. --sim). Changes apply until Spyhop is closed.' }, 'this session only') : null,
        el('button', { class: 'icon', title: 'Remove', onclick: () => { sources.splice(i, 1); markDirty(); draw(); } }, '✕'))));
    };
    draw();
    if (draft.dirty) markDirty();
    const ports = el('datalist', { id: 'serial-ports' });
    api('/api/nmea').then((r) => {
      ports.replaceChildren(...r.ports.map((p) => el('option', { value: p.device }, p.description)));
      this.S.nmea = r;
      this.updateNmeaStatus();
      // first look at the real list (it includes --sim inputs) if nothing has been edited yet
      if (!draft.dirty && JSON.stringify(r.all_sources) !== JSON.stringify(sources)) {
        draft.sources.splice(0, draft.sources.length, ...JSON.parse(JSON.stringify(r.all_sources)));
        draw();
      }
    }).catch(() => {});
    return el('section', { class: 'settings-sec' }, el('h3', {}, 'GPS / NMEA inputs'),
      el('p', { class: 'hint help' }, 'Position, course and speed come from RMC, GGA, GLL and VTG; heading from HDT, HDG, HDM or THS; the readings in Tools → Instruments from the other sentences, from any talker. Use UDP to share OpenCPN’s, a multiplexer’s or a plotter’s output; Serial for a USB GPS puck. Changes take effect when you press Apply (or Enter in a box). The simulator keeps its position when you change its heading or speed.'),
      list, ports,
      el('div', { class: 'btnrow' },
        el('button', { onclick: () => { sources.push({ type: 'serial', enabled: true, ...defaults.serial }); markDirty(); draw(); } }, '+ Add input'),
        applyBtn,
        el('button', { onclick: () => { this.nmeaDraft = null; this.renderInputs(); }, title: 'Discard unapplied changes' }, 'Revert')),
      el('div', { id: 'nmea-status', class: 'nmea-status' }),
      el('details', {}, el('summary', {}, 'Raw NMEA monitor'), el('pre', { id: 'nmea-raw', class: 'raw' }),
        el('button', { onclick: () => api('/api/nmea').then((r) => { this.S.nmea = r; this.updateNmeaStatus(true); }) }, 'Refresh')));
  }

  // ---------------------------------------------------------------- Tools → Instruments
  renderNmea() {
    const pane = $('#pane-nmea');
    if (!pane) return;
    const st = this.S.config.settings;
    const sec = (title, ...kids) => el('section', { class: 'settings-sec' }, el('h3', {}, title), ...kids);
    const inst = sec('Instruments',
      el('p', { class: 'hint help' }, 'Latest readings from every NMEA input: speed, depth, wind, weather, engines and other transducers. A reading turns gray when it hasn’t been updated for 15 seconds. Click a reading to plot it since the start of the survey (readings are saved every 5 seconds while a survey is active).'),
      el('p', { id: 'inst-inputs-link' }, 'The GPS / NMEA inputs (serial, UDP, TCP, gpsd, file replay, simulator) are set up in ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.showTab('inputs'); } }, 'Settings → Inputs'), '.'),
      el('div', { id: 'inst-grid' }));
    const logChk = el('input', { type: 'checkbox', checked: !!st.nmea_log_enabled,
      onchange: (e) => api('/api/nmea/log', { enabled: e.target.checked }).then((r) => { this.S.nmea = { ...this.S.nmea, log: r.log }; this.updateRawLog();
        toast(e.target.checked ? 'Recording raw NMEA' : 'Raw NMEA recording stopped'); }).catch(() => {}) });
    const tsChk = el('input', { type: 'checkbox', checked: st.nmea_log_timestamps !== false,
      onchange: (e) => api('/api/nmea/log', { timestamps: e.target.checked }).catch(() => {}) });
    const raw = sec('Raw NMEA log',
      el('div', { class: 'grid2 checks' },
        el('label', { class: 'check' }, logChk, el('span', {}, el('b', {}, 'Record raw NMEA to a file'), ' — every sentence from every input, as received')),
        el('label', { class: 'check' }, tsChk, el('span', {}, 'Start each line with the UTC time and the input name (untick for plain NMEA)'))),
      el('p', { id: 'rawlog-status', class: 'hint' }),
      el('p', { class: 'hint help' }, 'Logs are saved in the open survey’s folder (nmea_logs), or in the data folder’s nmea_logs when no survey is open; a new file starts when you start, open or close a survey. Recording carries on after a restart until you switch it off. A log can be played back as a “file” input (Settings → Inputs). ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.open('nmealogs'); } }, 'Open the log folder')));
    pane.replaceChildren(inst, raw);
    this.updateInstruments();
    this.updateRawLog();
  }

  // Settings → Inputs: the GPS / NMEA inputs
  renderInputs() {
    const pane = $('#pane-inputs');
    if (!pane) return;
    pane.replaceChildren(this.nmeaSection(), el('p', { class: 'hint' }, 'Live readings from these inputs and the raw NMEA log are in ',
      el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.showTab('nmea'); } }, 'Tools → Instruments'), '. The online overlays (AIS, weather radar, map feeds) are in ',
      el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.showTab('overlays'); } }, 'Tools → Overlays'), '.'));
    this.updateNmeaStatus();
  }

  // an online overlay loaded or changed: redraw its part of Tools → Overlays (not while typing in it)
  onlineChanged(force = false) {
    if (!this.shown('overlays')) return;
    const box = $('#online-overlays');
    if (!box || !force && box.contains(document.activeElement) && document.activeElement.matches('input[type=text], select')) return;
    box.replaceWith(this.online.section());
  }

  updateInstruments() {
    const box = $('#inst-grid');
    if (!box) return;
    const inst = this.S.inst || {};
    const groups = ['Navigation', 'Depth', 'Wind', 'Weather', 'Engine', 'Other transducers'];
    const keys = Object.keys(inst).sort((a, b) => inst[a].order - inst[b].order);
    if (!keys.length) { box.replaceChildren(el('p', { class: 'hint' }, 'No instrument data yet. Add or check the inputs in Settings → Inputs.')); return; }
    const digits = (u) => (u.startsWith('°') && u !== '°C' ? 0 : u === 'rpm' || u === '%' ? 0 : u === '' ? 1 : 1);
    box.replaceChildren(...groups.filter((g) => keys.some((k) => inst[k].group === g)).map((g) => el('div', { class: 'inst-group' },
      el('h4', {}, g),
      el('div', { class: 'inst-tiles' }, keys.filter((k) => inst[k].group === g).map((k) => {
        const r = inst[k];
        const val = typeof r.value === 'number' ? (Number.isInteger(r.value) && r.unit === '' ? String(r.value) : r.value.toFixed(digits(r.unit))) : String(r.value);
        const age = r.age < 2 ? 'now' : r.age < 90 ? `${Math.round(r.age)} s ago` : `${Math.round(r.age / 60)} min ago`;
        const plottable = typeof r.value === 'number';
        return el('div', { class: `inst${r.age > 15 ? ' stale' : ''}${plottable ? ' plottable' : ''}`, 'data-key': k,
          title: `${r.sentence} from ${r.source || 'input'}${plottable ? ' — click to plot since the start of the survey' : ''}`,
          onclick: plottable ? () => openInstrumentPlot(this, k) : null },
          el('div', { class: 'inst-l' }, r.label),
          el('div', { class: 'inst-v' }, val, el('span', { class: 'inst-u' }, r.unit ? ` ${r.unit}` : '')),
          el('div', { class: 'inst-s' }, `${r.sentence} · ${age}`));
      })))));
  }

  updateRawLog() {
    const box = $('#rawlog-status');
    const lg = this.S.nmea?.log;
    if (!box || !lg) return;
    const size = lg.bytes > 1e6 ? `${(lg.bytes / 1e6).toFixed(1)} MB` : `${Math.round((lg.bytes || 0) / 1024)} KB`;
    box.replaceChildren(lg.on
      ? el('span', {}, el('span', { class: 'rec-dot' }, '● '), 'Recording to ', el('span', { class: 'mono' }, lg.path), ` — ${lg.lines} lines, ${size}`)
      : el('span', {}, 'Not recording.'));
  }

  updateNmeaStatus(withRaw = false) {
    const box = $('#nmea-status');
    if (!box || !this.S.nmea) return;
    const n = this.S.nmea;
    const pos = n.position_source || '';
    box.replaceChildren(...(n.sources || []).map((s) => {
      const live = s.state === 'receiving' || s.state === 'replaying';
      // an input with a position but outranked by one above it in the list (lower in the list = used only as a backup)
      const outranked = live && pos && pos !== s.name && (n.counts?.RMC || n.counts?.GGA || n.counts?.GLL);
      const prog = s.total ? ` · line ${s.at || 0} of ${s.total}${s.loops ? ` (replay ${s.loops + 1})` : ''}` : (s.lines ? ` · ${s.lines} lines` : '');
      return el('div', { class: `src-st ${s.state}` },
        el('b', {}, s.name), ` — ${s.state}`, prog,
        pos === s.name ? el('span', { class: 'ok' }, ' · position from here') : null,
        outranked ? el('span', { class: 'hint', title: 'Inputs higher in the list are preferred; one lower down supplies the position only when those above go quiet for 5 s.' }, ` · position from “${pos}” (higher in the list)`) : null,
        s.error ? el('span', { class: 'err' }, ` · ${s.error}`) : '');
    }),
    el('div', { class: 'hint' }, `Sentences: ${Object.entries(n.counts || {}).map(([k, v]) => `${k} ${v}`).join(', ') || 'none yet'}${n.errors ? ` · ${n.errors} unreadable` : ''}`));
    if (withRaw && n.raw) $('#nmea-raw').textContent = n.raw.join('\n');
  }

  // Tools → Overlays: imported GeoJSON/GPX/KML files and past surveys, each shown or hidden
  renderOverlays() {
    const pane = $('#pane-overlays');
    if (!pane) return;
    const list = this.S.overlays || [];
    const m = this.map;
    const allOn = m.map.hasLayer(m.layers.imported);
    const remove = async (n) => { if (await confirmBox('Remove overlay?', `Remove ${n} from Spyhop’s overlays folder? It can be imported again.`, 'Remove', true)) api(`/api/overlays/${encodeURIComponent(n)}`, undefined, 'DELETE').catch(() => {}); };
    const panel = el('div', { id: 'overlay-panel' }, el('section', { class: 'settings-sec' }, el('h3', {}, 'Offline overlays'),
      el('p', { class: 'hint help' }, 'GeoJSON, GPX or KML files: planned transects, management areas, other surveys. They are kept in Spyhop’s overlays folder. Click an overlay’s color to change it (↺ goes back to its own colors); the colors are kept with the map display, so they travel in templates too.'),
      el('div', { class: 'btnrow' }, el('button', { class: 'primary', onclick: () => this.importOverlay() }, 'Import…'),
        list.length ? el('button', { onclick: () => { list.forEach((n) => m.setOverlayVisible(n, true)); this.renderOverlays(); } }, 'Show all') : null,
        list.length ? el('button', { onclick: () => { list.forEach((n) => m.setOverlayVisible(n, false)); this.renderOverlays(); } }, 'Hide all') : null,
        el('button', { id: 'btn-overlays-refresh', title: 'Read the overlays folder again (e.g. after copying files into it)', onclick: () => this.refreshFolders() }, 'Refresh')),
      !allOn && list.length ? el('p', { class: 'warnbox' }, 'Overlays are switched off in the map’s layers menu (“Imported overlays”), so none are drawn. ',
        el('button', { onclick: () => { m.layers.imported.addTo(m.map); m.saveOverlayState(); this.renderOverlays(); } }, 'Switch them on')) : null,
      list.length ? el('table', { class: 'summary overlay-table', id: 'overlay-table' },
        el('thead', {}, el('tr', {}, ['Show', 'Overlay', ''].map((h) => el('th', {}, h)))),
        el('tbody', {}, list.map((n) => el('tr', { 'data-overlay': n },
          el('td', {}, el('input', { type: 'checkbox', class: 'ov-show', checked: m.overlayVisible(n), 'aria-label': `Show ${n}`,
            onchange: (e) => { m.setOverlayVisible(n, e.target.checked); } })),
          el('td', { class: 'ov-name' }, el('input', { type: 'color', class: 'ov-color', value: m.overlayColor(n), title: 'Color on the map',
            'aria-label': `Color of ${n}`, onchange: async (e) => { await m.setOverlayColor(n, e.target.value); this.renderOverlays(); } }),
          m.customOverlayColor(n) ? el('button', { class: 'icon ov-color-reset', title: 'Back to its own colors',
            onclick: async () => { await m.setOverlayColor(n, null); this.renderOverlays(); } }, '↺') : null, ' ', n),
          el('td', { class: 'nowrap' },
            el('button', { title: 'Zoom the map to this overlay', onclick: () => { m.setOverlayVisible(n, true); m.zoomToOverlay(n); this.renderOverlays(); } }, 'Zoom to'),
            el('button', { class: 'ov-remove', title: 'Remove this overlay', onclick: () => remove(n) }, 'Remove'))))))
        : el('p', { class: 'hint', id: 'overlay-none' }, 'No overlays yet.')),
      el('section', { class: 'settings-sec' }, this.pastSurveyOverlays()));
    // the online overlays (AIS, radar, map feeds) follow; they redraw themselves (onlineChanged), so keep them while typing in them
    const old = $('#overlay-panel'), box = $('#online-overlays');
    if (old && box && pane.contains(old) && pane.contains(box)) old.replaceWith(panel);
    else pane.replaceChildren(panel, this.online.section());
  }

  // Other surveys in the data folder, each of which can be drawn as an overlay
  pastSurveyOverlays() {
    const cur = this.S.survey?.prefix;
    const surveys = (this.S.surveys || []).filter((x) => x.prefix !== cur);
    const have = new Set(this.S.overlays || []);
    const fileOf = (p) => `Survey - ${p}.geojson`;
    const fmtT = (iso) => { if (!iso) return ''; const t = timeParts(iso, this.clock()); return `${t.date} ${t.time.slice(0, 5)}`; };
    const add = async (sv) => {
      try {
        const r = await api('/api/overlays/survey', { prefix: sv.prefix });
        const m = this.map;
        if (!m.map.hasLayer(m.layers.imported)) { m.layers.imported.addTo(m.map); m.saveOverlayState(); }
        toast(`“${sv.prefix}” added as the overlay ${r.name}`);
      } catch {}
    };
    return el('div', { class: 'overlay-surveys' },
      el('h4', {}, 'Past surveys in this data folder'),
      surveys.length ? el('table', { class: 'summary survey-overlays' },
        el('thead', {}, el('tr', {}, ['Survey', 'Started', 'Sightings', ''].map((h) => el('th', {}, h)))),
        el('tbody', {}, surveys.map((sv) => {
          const on = have.has(fileOf(sv.prefix));
          return el('tr', {}, el('td', {}, sv.prefix), el('td', { class: 'nowrap' }, fmtT(sv.start_time)), el('td', { class: 'num' }, String(sv.sightings ?? '')),
            el('td', { class: 'nowrap' }, on
              ? [el('span', { class: 'hint' }, 'overlay ✓ '),
                el('button', { title: 'Redraw it from the survey’s files (after edits)', onclick: () => add(sv) }, 'Update'),
                el('button', { class: 'icon', title: 'Remove this overlay', onclick: () => api(`/api/overlays/${encodeURIComponent(fileOf(sv.prefix))}`, undefined, 'DELETE').catch(() => {}) }, '✕')]
              : el('button', { onclick: () => add(sv) }, 'Add as overlay')));
        })))
        : el('p', { class: 'hint' }, 'No other surveys in this data folder.'),
      surveys.length ? el('p', { class: 'hint help' }, 'Draws the survey’s trackline (solid on effort, dashed off effort), sightings and events. The overlay is a snapshot: press Update after changing that survey.') : null);
  }

  mapSection() {
    const S = this.S, srcs = S.config.tile_sources;
    const dl = (this.dl ||= {});
    const z = Math.round(this.map.map.getZoom());
    const pick = srcs.findIndex((t) => t.name === dl.source) >= 0 ? srcs.findIndex((t) => t.name === dl.source)
      : Math.max(0, srcs.findIndex((t) => t.kind === 'style'));
    const prefetchSrc = el('select', { id: 'dl-source', onchange: () => { dl.source = srcs[+prefetchSrc.value].name; estimate(); } },
      srcs.map((t, i) => el('option', { value: i, selected: i === pick, disabled: /openstreetmap\.org/.test(t.url) && t.kind !== 'style' },
        t.name + (/openstreetmap\.org/.test(t.url) && t.kind !== 'style' ? ' (not allowed)' : ''))));
    const zmin = el('input', { type: 'number', id: 'dl-zmin', min: 0, max: 18, value: dl.zmin ?? Math.max(0, z - 2), size: 3, onchange: () => { dl.zmin = +zmin.value; estimate(); } });
    const zmax = el('input', { type: 'number', id: 'dl-zmax', min: 0, max: 18, value: dl.zmax ?? Math.min(14, z + 2), size: 3, onchange: () => { dl.zmax = +zmax.value; estimate(); } });
    const est = el('span', { class: 'hint', id: 'dl-estimate' });
    const cacheInfo = el('span', { class: 'hint', id: 'cache-info' });
    const today = new Date().toISOString().slice(0, 10);
    const defName = () => `${srcs[+prefetchSrc.value]?.name || 'Map'} ${today}`;
    const nameBox = el('input', { type: 'text', id: 'dl-name', value: dl.name || defName(), style: { minWidth: '18em' },
      oninput: () => { dl.name = nameBox.value; } });
    prefetchSrc.addEventListener('change', () => { if (!dl.name) nameBox.value = defName(); });
    api('/api/tiles').then((r) => {
      cacheInfo.textContent = `Also kept as you view the map (the browsing cache): ${r.cache.tiles.toLocaleString()} tiles, ${r.cache.mb} MB.`;
      if (r.prefetch) this.updatePrefetch(r.prefetch);
    }).catch(() => {});
    const body = () => {
      const b = this.map.map.getBounds();
      return { source: +prefetchSrc.value, bounds: [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()], zmin: +zmin.value, zmax: +zmax.value,
        name: nameBox.value.trim() || defName() };
    };
    // one estimate at a time across redraws (the pane redraws as chart files come and go), and only the latest is shown
    const estimate = () => {
      clearTimeout(this._estTimer);
      this._estTimer = setTimeout(async () => {
        const seq = (this._estSeq = (this._estSeq || 0) + 1);
        est.textContent = 'Counting tiles…';
        try {
          const r = await fetch('/api/tiles/prefetch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body(), dry_run: true }) }).then((x) => x.json());
          if (seq !== this._estSeq) return;
          if (r.ok === false || r.error) { est.textContent = r.error || 'Can’t count the tiles.'; return; }
          est.textContent = `About ${r.total.toLocaleString()} tiles${r.note ? ` · ${r.note}` : ''}${r.skipped?.length ? ` · not downloaded: ${r.skipped.join(', ')}` : ''}`;
        } catch { est.textContent = ''; }
      }, 400);
    };
    if (!this._dlMoveHook) { this._dlMoveHook = true; this.map.map.on('moveend', () => { if (this.shown('basemap') && $('#dl-estimate')) this.renderSettingsMapEstimate?.(); }); }
    this.renderSettingsMapEstimate = estimate;
    estimate();
    return el('section', { class: 'settings-sec', id: 'map-offline' }, el('h3', {}, 'Download an area for offline use'),
      el('p', {}, 'To get ready for a survey, move the map to cover the survey area, then download it here while you have internet. ',
        'Each download is saved as one file in the charts folder (below), so you can preview it, keep several areas, and copy one to another computer’s charts folder.'),
      el('div', { class: 'btnrow' }, el('label', { class: 'inline' }, 'Download the area on the map of', prefetchSrc),
        el('label', { class: 'inline' }, 'from zoom', zmin), el('label', { class: 'inline' }, 'to', zmax)),
      el('div', { class: 'btnrow' }, el('label', { class: 'inline' }, 'Save it as', nameBox),
        el('span', { class: 'hint' }, 'A file of that name in the charts folder; the same name again adds to it.')),
      el('div', { class: 'btnrow' },
        el('button', { id: 'btn-dl', class: 'primary', onclick: async () => {
          try {
            const r = await api('/api/tiles/prefetch', body());
            toast(`Downloading ${r.total.toLocaleString()} tiles of ${srcs[+prefetchSrc.value].name} to ${r.file}…`);
            this.updatePrefetch({ running: true, done: 0, total: r.total, failed: 0, source: srcs[+prefetchSrc.value].name, file: r.file });
            dl.name = '';
          } catch { /* shown */ }
        } }, 'Download'),
        el('button', { onclick: () => api('/api/tiles/prefetch', { cancel: true }).catch(() => {}) }, 'Stop'), est),
      el('div', { id: 'prefetch-status' }),
      el('p', { class: 'hint help' }, 'Each zoom level has four times the tiles of the one before, so keep the highest zoom modest for a big area (12–13 suits a day’s survey area; 14–15 a harbor). ',
        'Zooming in past what was downloaded shows the nearest saved tiles enlarged. OpenStreetMap doesn’t allow bulk downloads (for Seascape, its land background isn’t saved).'),
      el('h4', {}, 'In the charts folder'),
      el('div', { id: 'chart-list' }),
      el('div', { class: 'btnrow' },
        el('button', { onclick: () => this.open('charts') }, 'Open the charts folder'),
        el('button', { title: 'Look again for .mbtiles files copied into the charts folder', onclick: () => api('/api/tiles/rescan', {}).then((r) => {
          this.S.mbtiles = r.mbtiles; this.map.syncCharts(r.mbtiles); this.renderChartList(); toast('Charts folder checked');
        }).catch(() => {}) }, 'Refresh')),
      el('p', { class: 'hint help' }, 'Spyhop uses a downloaded area automatically when the map layer it came from is chosen, before going online. Each file is also listed under “Offline map tiles” in the map’s layers menu; Select puts it on the map on its own, so you can see what you’ll have at sea. NOAA ENC charts (.mbtiles from charts.noaa.gov) can be put in the folder too.'),
      el('p', {}, cacheInfo),
      el('p', { class: 'hint help' }, 'Map overlays (transects, management areas…) are in Tools → ',
        el('a', { href: '#', onclick: (e) => { e.preventDefault(); this.showTab('overlays'); } }, 'Overlays'), '.'));
  }

  async deleteChart(m) {
    const what = m.kind === 'chart' ? 'chart' : 'downloaded area';
    if (!await confirmBox('Delete this chart?', `Delete ${m.file} (${m.tiles?.toLocaleString() ?? '?'} tiles) from the charts folder? The ${what} can’t be used offline after this, and this can’t be undone.`, 'Delete', true)) return;
    try {
      const r = await api('/api/tiles/delete', { file: m.file });
      this.S.mbtiles = r.mbtiles; this.map.syncCharts(r.mbtiles); this.renderChartList();
      toast(`Deleted ${m.file}`);
    } catch { /* shown */ }
  }

  // Settings → Basemap: the files in the charts folder
  renderChartList() {
    const box = $('#chart-list');
    if (!box) return;
    const list = this.S.mbtiles || [];
    if (!list.length) { box.replaceChildren(el('p', { class: 'hint', id: 'chart-none' }, 'No charts yet. Downloads appear here.')); return; }
    const when = (iso) => { const t = iso && timeParts(iso, this.clock()); return t ? t.date : ''; };
    const zooms = (m) => (m.minzoom === m.maxzoom ? `${m.minzoom}` : `${m.minzoom}–${m.maxzoom}`);
    const tot = list.reduce((a, m) => [a[0] + (m.tiles || 0), a[1] + (m.bytes || 0)], [0, 0]);
    const size = (b) => (b == null ? '' : b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`);
    box.replaceChildren(el('table', { class: 'summary charts-table', id: 'charts-table' },
      el('thead', {}, el('tr', {}, ['Chart', 'Made from', 'Zooms', 'Tiles', 'Size', 'Saved', ''].map((h) => el('th', {}, h)))),
      el('tbody', {}, list.map((m) => el('tr', { 'data-file': m.file },
        el('td', {}, el('b', {}, m.name), m.name !== m.file.replace(/\.mbtiles$/, '') ? el('div', { class: 'hint mono' }, m.file) : null,
          m.error ? el('div', { class: 'err' }, m.error) : null),
        el('td', {}, m.kind === 'chart' ? 'MBTiles chart' : `Download of ${m.source}`),
        el('td', { class: 'num' }, zooms(m)),
        el('td', { class: 'num' }, m.tiles != null ? m.tiles.toLocaleString() : ''),
        el('td', { class: 'num nowrap' }, size(m.bytes)),
        el('td', { class: 'nowrap' }, when(m.created)),
        el('td', { class: 'nowrap' }, this.map.chartLayers?.[m.file] && this.map.baseLayer === this.map.chartLayers[m.file]
          ? el('span', { class: 'pill on chart-current' }, 'On the map')
          : el('button', { class: 'chart-select', disabled: !!m.error, title: 'Show this chart on the map (only what is saved in it), zoomed to its area',
            onclick: () => { if (this.map.previewChart(m)) { this.renderChartList(); toast(`The map now shows ${m.name}: only what is saved in the file.`, 'info', 5000); } } }, 'Select'),
          el('button', { class: 'chart-delete', title: 'Delete this file from the charts folder', onclick: () => this.deleteChart(m) }, 'Delete'))))),
      el('tfoot', {}, el('tr', {}, el('td', {}, `${list.length} file${list.length === 1 ? '' : 's'}`), el('td', {}), el('td', {}),
        el('td', { class: 'num' }, tot[0].toLocaleString()), el('td', { class: 'num nowrap' }, size(tot[1])), el('td', {}), el('td', {})))));
  }

  updatePrefetch(p) {
    const box = $('#prefetch-status');
    if (!box) return;
    const was = this._dlRunning;
    this._dlRunning = !!p.running;
    if (p.running) {
      const pct = p.total ? Math.round((100 * p.done) / p.total) : 0;
      box.replaceChildren(el('div', { class: 'progress' }, el('div', { class: 'bar', style: { width: `${pct}%` } })),
        el('span', { class: 'hint' }, `Downloading ${p.source}: ${p.done.toLocaleString()} of ${p.total.toLocaleString()} (${pct}%)${p.failed ? `, ${p.failed} failed` : ''}`));
    } else if (p.total) {
      const ok = p.done - p.failed - (p.empty || 0);
      box.replaceChildren(el('p', { class: p.failed ? (ok > 0 ? 'warnbox' : 'errbox') : 'okbox' },
        `${p.source}: ${ok.toLocaleString()} of ${p.total.toLocaleString()} tiles saved${p.file ? ` in ${p.file} (charts folder)` : ' for offline use'}`,
        p.cached ? ` (${p.cached.toLocaleString()} were already saved)` : '',
        p.empty ? `; ${p.empty.toLocaleString()} had no map data (open ocean or land), which is normal` : '', '. ',
        p.failed ? `${p.failed.toLocaleString()} failed${p.error ? ` — last problem: ${p.error}` : ''}. ${ok > 0 ? 'Press Download again to retry them.' : 'Check the internet connection.'}` : '',
        p.skipped ? ` Not downloaded (the server doesn’t allow it): ${p.skipped}.` : ''));
      if (was) api('/api/tiles').then((r) => { this.S.mbtiles = r.mbtiles; this.renderChartList(); }).catch(() => {});
    }
  }
}

function card(label, value, live = false) {
  return el('div', { class: `card${live ? ' live' : ''}` }, el('div', { class: 'card-v' }, String(value)),
    el('div', { class: 'card-l' }, live ? '● ' : '', label));
}

function toHex(color) {
  const c = document.createElement('canvas').getContext('2d');
  c.fillStyle = '#000';
  c.fillStyle = color || '#000';
  const v = c.fillStyle;
  return v.startsWith('#') ? v : '#000000';
}

const app = new App();
window.wsr = app;
app.start().catch((e) => {
  console.error(e);
  document.getElementById('app').innerHTML = `<div class="fatal">Couldn't start: ${esc(e.message)}. Is Spyhop running?</div>`;
});
