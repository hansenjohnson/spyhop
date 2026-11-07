// Time-series plot of one NMEA reading since the start of the survey (Tools → Instruments → click a tile).
import { el, modal, timeParts, clockOffsetMin } from './util.js';

const GAP_MS = 60000;           // break the line where readings stopped for longer than this

function niceStep(range, target) {
  const raw = range / Math.max(target, 1);
  const p = 10 ** Math.floor(Math.log10(raw || 1));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p;
  return 10 * p;
}

const TIME_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1440].map((m) => m * 60000);

export function openInstrumentPlot(app, key) {
  const canvas = el('canvas', { class: 'plot-canvas' });
  const stats = el('div', { class: 'plot-stats' });
  const readout = el('div', { class: 'plot-readout hint' }, 'Move the mouse over the plot to read values.');
  let data = null, timer = null, hoverX = null;
  const clock = () => app.clock();
  const fmtT = (ms, withDate) => { const t = timeParts(new Date(ms), clock()); return `${withDate ? `${t.date} ` : ''}${t.time.slice(0, 5)}`; };
  const digits = () => (data?.angle || data?.unit === 'rpm' || data?.unit === '%' ? 0 : 1);

  const draw = () => {
    const ctx = canvas.getContext('2d');
    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue('--text').trim() || '#1b2733';
    const muted = css.getPropertyValue('--muted').trim() || '#6b7785';
    const line = css.getPropertyValue('--line').trim() || '#d5dce3';
    const accent = css.getPropertyValue('--accent').trim() || '#0b5f86';
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.font = '12px system-ui, sans-serif';
    const pts = data?.points || [];
    if (pts.length < 1) {
      ctx.fillStyle = muted;
      ctx.fillText(app.S.survey?.active ? 'No readings saved yet: Spyhop saves one every 5 seconds while the survey is active.'
        : 'No readings were saved for this survey.', 16, H / 2);
      return;
    }
    const L = 56, R = 14, T = 12, B = 34;
    const t0 = Math.min(data.start || pts[0][0], pts[0][0]), t1 = Math.max(pts[pts.length - 1][0], t0 + 60000);
    let y0, y1;
    if (data.angle) { y0 = 0; y1 = 360; } else {
      y0 = Math.min(...pts.map((p) => p[1])); y1 = Math.max(...pts.map((p) => p[1]));
      if (y1 - y0 < 1e-9) { y0 -= 1; y1 += 1; }
      const pad = (y1 - y0) * 0.08; y0 -= pad; y1 += pad;
    }
    const X = (t) => L + (t - t0) / (t1 - t0) * (W - L - R);
    const Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
    // grid + labels
    ctx.strokeStyle = line; ctx.fillStyle = muted; ctx.lineWidth = 1;
    const ys = data.angle ? 90 : niceStep(y1 - y0, 5);
    for (let v = Math.ceil(y0 / ys) * ys; v <= y1 + 1e-9; v += ys) {
      const y = Math.round(Y(v)) + 0.5;
      ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(W - R, y); ctx.stroke();
      const lab = (+v.toFixed(6)).toString();
      ctx.fillText(lab, L - 6 - ctx.measureText(lab).width, y + 4);
    }
    const ts = TIME_STEPS.find((s) => (t1 - t0) / s <= 7) || TIME_STEPS[TIME_STEPS.length - 1];
    const tzOff = clockOffsetMin(new Date(t0), clock()) * 60000;
    for (let t = Math.ceil((t0 + tzOff) / ts) * ts - tzOff; t <= t1; t += ts) {
      const x = Math.round(X(t)) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, H - B); ctx.stroke();
      const lab = fmtT(t);
      ctx.fillText(lab, x - ctx.measureText(lab).width / 2, H - B + 16);
    }
    ctx.fillText(timeParts(new Date(t0), clock()).abbr, W - R - 30, H - 4);
    if (data.start) {                                         // the survey's Start
      const x = X(data.start);
      ctx.strokeStyle = muted; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, H - B); ctx.stroke(); ctx.setLineDash([]);
    }
    // data
    ctx.strokeStyle = accent; ctx.fillStyle = accent; ctx.lineWidth = 1.6;
    if (data.angle) {                                         // dots: angles wrap at 0/360, so lines would mislead
      for (const [t, v] of pts) { ctx.beginPath(); ctx.arc(X(t), Y(((v % 360) + 360) % 360), 1.8, 0, 7); ctx.fill(); }
    } else {
      ctx.beginPath();
      let prev = null;
      for (const [t, v] of pts) {
        if (prev === null || t - prev > GAP_MS) ctx.moveTo(X(t), Y(v)); else ctx.lineTo(X(t), Y(v));
        prev = t;
      }
      ctx.stroke();
      if (pts.length === 1) { ctx.beginPath(); ctx.arc(X(pts[0][0]), Y(pts[0][1]), 3, 0, 7); ctx.fill(); }
    }
    // hover
    if (hoverX !== null && hoverX >= L && hoverX <= W - R) {
      const t = t0 + (hoverX - L) / (W - L - R) * (t1 - t0);
      let best = pts[0];
      for (const p of pts) if (Math.abs(p[0] - t) < Math.abs(best[0] - t)) best = p;
      const x = X(best[0]), y = Y(data.angle ? ((best[1] % 360) + 360) % 360 : best[1]);
      ctx.strokeStyle = ink; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x + 0.5, T); ctx.lineTo(x + 0.5, H - B); ctx.stroke();
      ctx.beginPath(); ctx.arc(x, y, 4, 0, 7); ctx.stroke();
      readout.textContent = `${fmtT(best[0], true)} ${timeParts(new Date(best[0]), clock()).abbr} — ${best[1].toFixed(digits())} ${data.unit}`;
    }
  };

  const updateStats = () => {
    const pts = data?.points || [];
    if (!pts.length) { stats.replaceChildren(); return; }
    const vals = pts.map((p) => p[1]);
    const d = digits();
    const items = [['Now', vals[vals.length - 1].toFixed(d)], ['Min', Math.min(...vals).toFixed(d)], ['Max', Math.max(...vals).toFixed(d)]];
    if (!data.angle) items.push(['Mean', (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(d)]);
    stats.replaceChildren(...items.map(([k, v]) => el('span', {}, el('span', { class: 'hint' }, `${k} `), el('b', {}, v), ` ${data.unit}`)),
      el('span', { class: 'hint' }, `${data.samples || pts.length} readings since ${data.start ? fmtT(data.start, true) : 'the start'}`));
  };

  const load = async () => {
    try {
      const r = await fetch(`/api/instruments/history?key=${encodeURIComponent(key)}`).then((x) => x.json());
      data = r;
      updateStats(); draw();
    } catch {}
  };

  canvas.addEventListener('mousemove', (e) => { hoverX = e.offsetX; draw(); });
  canvas.addEventListener('mouseleave', () => { hoverX = null; readout.textContent = 'Move the mouse over the plot to read values.'; draw(); });
  const label = app.S.inst?.[key]?.label || key;
  const done = modal({ title: `${label} since the start of the survey`, width: '52em', closeOnOutside: true,
    body: el('div', { class: 'plot-box' }, stats, canvas, readout,
      el('p', { class: 'hint' }, 'Updates every 5 seconds while open. The dashed line is the survey’s Start. Readings are saved in the survey’s _instruments.csv file and included in the separate-CSV export.')),
    onOpen: () => { load(); timer = setInterval(load, 5000); return false; },
    buttons: [{ label: 'Close', primary: true, value: true }] });
  done.finally(() => clearInterval(timer));
  const ro = new ResizeObserver(() => draw());
  ro.observe(canvas);
  done.finally(() => ro.disconnect());
  return done;
}
