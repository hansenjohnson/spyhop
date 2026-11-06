// Measure on-screen marker offsets vs. their true coordinates.
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1400, height: 820 } });
  await p.goto('http://127.0.0.1:8765/');
  await p.waitForTimeout(2500);
  // drop three marks via the right-click menu at known screen points
  const box = await p.locator('#map').boundingBox();
  const pts = [[300, 250], [500, 400], [650, 300]];
  for (const [x, y] of pts) {
    await p.mouse.click(box.x + x, box.y + y, { button: 'right' });
    await p.click('.ctx-item:has-text("Add waypoint here")');
    await p.waitForTimeout(500);
    await p.keyboard.press('Escape');
  }
  await p.mouse.click(box.x + 200, box.y + 500, { button: 'right' });
  await p.click('.ctx-item:has-text("Add sighting here")');
  await p.waitForTimeout(600);
  await p.keyboard.press('Escape');
  const row = await p.evaluate(() => window.wsr.S.tables.sightings.rows.at(-1));
  console.log('sighting row: Bearing', row.Bearing, row.BrgRef, 'Distance', row.Distance, row.DistUnit);
  await p.click('#btn-follow');
  await p.waitForTimeout(800);
  const res = await p.evaluate(() => {
    const m = window.wsr.map.map, out = [];
    for (const [k, mk] of Object.entries(window.wsr.map.markerIndex)) {
      const want = m.latLngToContainerPoint(mk.getLatLng());
      const r = mk.getElement().getBoundingClientRect(), c = m.getContainer().getBoundingClientRect();
      const svg = mk.getElement().querySelector('svg').getBoundingClientRect();
      out.push({ k, wantX: Math.round(want.x), wantY: Math.round(want.y),
        gotX: Math.round(svg.left + svg.width / 2 - c.left), gotY: Math.round(svg.top + svg.height / 2 - c.top),
        pos: getComputedStyle(mk.getElement()).position });
    }
    const v = window.wsr.map.vessel;
    const vw = m.latLngToContainerPoint(v.getLatLng()), vr = v.getElement().querySelector('svg').getBoundingClientRect(), c = m.getContainer().getBoundingClientRect();
    out.push({ k: 'vessel', wantX: Math.round(vw.x), wantY: Math.round(vw.y), gotX: Math.round(vr.left + vr.width / 2 - c.left), gotY: Math.round(vr.top + vr.height / 2 - c.top), pos: getComputedStyle(v.getElement()).position });
    return out;
  });
  console.log('clicked at', pts.map(([x, y]) => `(${x},${y})`).join(' '));
  for (const r of res) console.log(r.k.padEnd(22), 'should be', `(${r.wantX},${r.wantY})`.padEnd(12), 'drawn at', `(${r.gotX},${r.gotY})`.padEnd(12), 'off by', r.gotX - r.wantX, r.gotY - r.wantY, 'px', r.pos);
  await b.close();
})();
