// 0.53: view-only windows (other devices on the vessel's network; Settings → Sharing on the laptop).
// The server decides what a viewer may do (sharing.py); this only makes the page fit: nothing that
// changes data or the laptop's settings is offered, and view preferences (text size, map display,
// columns, lat/lon format…) are kept in this browser instead of being sent to the laptop.
import { $, $$, el, setViewer, viewOnlyToast, VIEW } from './util.js';

const STORE = 'wsr.viewer.prefs';

// Panes whose controls are all turned off for a viewer, and what stays usable in the others.
const LOCKED_PANES = ['survey', 'inputs', 'shortcuts', 'dropdowns', 'templates', 'marks', 'overlays', 'route', 'about'];
const PARTLY = {
  settings: '#data-collection',                                   // General: data collection only (the rest is this browser's view)
  basemap: 'section:not(#basemap-choice)',                        // the map tiles can be chosen; downloads can't
  rules: '.rule-card :is(input, select, textarea), .rule-head button, .rule-cond button, .rule-side > button, #pane-rules > section > .btnrow button, .filebox button',
};
// in a locked pane, these still work (they change nothing)
const KEEP = '.report-tab, details summary, a, .help-btn, .guide-toc button';

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(STORE) || '{}') || {}; } catch { return {}; }
}
function savePrefs(p) { try { localStorage.setItem(STORE, JSON.stringify(p)); } catch {} }

export function isViewer(app) { return !!app.S?.viewer; }

// after every bootstrap: this browser's view preferences on top of the laptop's
export function applyViewerPrefs(app) {
  if (!isViewer(app)) return;
  setViewer(app.S.viewer_allowed);
  const p = loadPrefs();
  Object.assign(app.S.config.settings, p.settings || {});
  Object.assign(app.S.config.display, p.display || {});
}

// once, when the page starts as a viewer
export function setupViewer(app) {
  if (!isViewer(app) || app._viewerSetup) return;
  app._viewerSetup = true;
  app.viewer = true;
  document.body.classList.add('viewer');
  document.title = 'Spyhop — view only';
  const prefs = loadPrefs();
  prefs.settings ||= {}; prefs.display ||= {};
  // view preferences stay in this browser
  app.saveSettings = async (updates) => {
    const { mag_variation: _m, tracking_interval: _t, ...view } = updates || {};      // data collection: the laptop's
    Object.assign(prefs.settings, view); savePrefs(prefs);
    app.onMessage({ type: 'settings', settings: { ...app.S.config.settings, ...view } });
  };
  app.saveColumnLayout = async (all) => {
    app.S.config.settings.column_layout = all;
    prefs.settings.column_layout = all; savePrefs(prefs);
  };
  app.saveDisplay = async (updates) => {
    Object.assign(prefs.display, updates); savePrefs(prefs);
    app.onMessage({ type: 'display', display: { ...app.S.config.display, ...Object.fromEntries(Object.entries(updates).map(([k, v]) => [k, String(v)])) } });
  };
  const onMessage = app.onMessage.bind(app);
  app.onMessage = (m) => {
    if (m.type === 'settings') m = { ...m, settings: { ...m.settings, ...prefs.settings } };
    else if (m.type === 'display') m = { ...m, display: { ...m.display, ...prefs.display } };
    return onMessage(m);
  };
  // anything else that saves settings or the map display (pane sizes, overlays…): kept here too
  VIEW.local = (path, body) => {
    if (path !== '/api/settings' && path !== '/api/display') return null;
    const { mag_variation: _m, tracking_interval: _t, ...view } = body.updates || {};
    Object.assign(path === '/api/settings' ? prefs.settings : prefs.display, view); savePrefs(prefs);
    return { ok: true, settings: app.S.config.settings, display: app.S.config.display };
  };
  app.resetViewerPrefs = () => { savePrefs({}); location.reload(); };
  // turn off what would change anything, as panes are drawn
  let queued = false;
  const lock = () => { queued = false; lockControls(app); };
  new MutationObserver(() => { if (!queued) { queued = true; queueMicrotask(lock); } })
    .observe(document.body, { childList: true, subtree: true });
  lock();
}

function lockControls(app) {
  const off = (e) => { if (!e.disabled && !e.matches(KEEP)) { e.disabled = true; e.classList.add('view-locked'); } };
  for (const t of LOCKED_PANES) $$(`#pane-${t} :is(input, select, textarea, button)`).forEach(off);
  for (const [t, sel] of Object.entries(PARTLY)) {
    $$(`#pane-${t} ${sel}`).forEach((x) => (x.matches('input, select, textarea, button') ? off(x) : x.querySelectorAll('input, select, textarea, button').forEach(off)));
  }
  // the data tables: Add row, Insert, Delete, Undo, Redo and Add resight (Columns… is a view choice)
  $$('.toolbar > button:not(.columns-btn):not(.showcols-btn)').forEach(off);
  const note = $('#pane-settings #viewer-prefs-note');
  if ($('#pane-settings .settings-sec') && !note) {
    $('#pane-settings').prepend(el('p', { class: 'warnbox', id: 'viewer-prefs-note' },
      el('b', {}, 'View only. '), 'Changes here only change how Spyhop looks in this browser (text size, the map, formats); the laptop’s settings and the data collection settings stay as they are. ',
      el('button', { onclick: () => app.resetViewerPrefs() }, 'Use the laptop’s settings again')));
  }
}

// the shortcuts a viewer can use (they only move around)
export const VIEWER_ACTIONS = new Set(['tab', 'next-tab', 'prev-tab', 'toggle-log', 'max-log', 'center-vessel', 'measure']);

export function viewerRefuses(app, action) {
  if (!app.viewer) return false;
  if (VIEWER_ACTIONS.has(String(action).split(':')[0])) return false;
  viewOnlyToast();
  return true;
}

// a banner while the websocket is down (any window; "the laptop" for a viewer)
export function connectionBanner(app, down, why = '') {
  let b = $('#conn-banner');
  if (!down) { b?.remove(); return; }
  const text = `${why || (app.viewer ? 'Lost connection to the laptop running Spyhop' : 'Lost connection to Spyhop')} — retrying…`;
  if (!b) {
    b = el('div', { id: 'conn-banner', role: 'alert' });
    document.body.prepend(b);
  }
  b.textContent = text;
}
