// Water depth under the cursor, read from a MapLibre style's raster-dem source (Seascape).
// Seascape's DEM is Terrarium-encoded: elevation = R*256 + G + B/256 − 32768 meters.
// Negative values are depths below chart datum; 0, 1 and 2 are codes for water of unknown
// depth, drying foreshore and land. The tiles come through Spyhop's tile cache, so this
// works offline wherever the map has been viewed or downloaded.

const MAX_TILES = 24;

export class DepthProbe {
  // styleUrl: the layer's style.json (/tiles/gl/<i>/style.json, or /tiles/off/<file>/style.json for a saved area)
  constructor(styleUrl, unit) {
    this.styleUrl = styleUrl;
    this.unit = ['m', 'ft', 'fm'].includes(unit) ? unit : 'm';
    this.tiles = new Map();          // url -> Promise<ImageData|null>
    this.info = null;
  }

  async init() {
    if (this.info) return this.info;
    try {
      const style = await (await fetch(this.styleUrl)).json();
      const src = Object.values(style.sources || {}).find((s) => s.type === 'raster-dem');
      if (!src) return (this.info = { none: true });
      let { tiles, minzoom = 0, maxzoom = 14 } = src;
      if (!tiles && src.url) {
        const tj = await (await fetch(src.url)).json();
        tiles = tj.tiles; minzoom = tj.minzoom ?? minzoom; maxzoom = tj.maxzoom ?? maxzoom;
      }
      this.info = tiles?.length ? { template: tiles[0], minzoom, maxzoom } : { none: true };
    } catch { this.info = null; return { none: true }; }   // try again on the next move
    return this.info;
  }

  tile(z, x, y) {
    const url = this.info.template.replace('{z}', z).replace('{x}', x).replace('{y}', y);
    if (this.tiles.has(url)) return this.tiles.get(url);
    const p = (async () => {
      const r = await fetch(url);
      if (r.status !== 200) return null;
      const bmp = await createImageBitmap(await r.blob());
      const c = document.createElement('canvas');
      c.width = bmp.width; c.height = bmp.height;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(bmp, 0, 0);
      return ctx.getImageData(0, 0, c.width, c.height);
    })().catch(() => null);
    this.tiles.set(url, p);
    p.then((d) => { if (d === null) this.tiles.delete(url); });   // retry missing tiles later
    if (this.tiles.size > MAX_TILES) this.tiles.delete(this.tiles.keys().next().value);
    return p;
  }

  // {depthM} for water with a depth, else {code: 'unknown'|'drying'|'land'}, or null (no data).
  async at(lat, lon, leafletZoom) {
    const info = await this.init();
    if (!info || info.none) return null;
    // MapLibre runs one zoom below Leaflet with 512 px tiles, so this is the tile it already drew.
    const z = Math.max(info.minzoom, Math.min(info.maxzoom, Math.round(leafletZoom - 1)));
    const n = 2 ** z;
    const la = Math.max(-85.05, Math.min(85.05, lat)) * Math.PI / 180;
    const xf = ((((lon + 180) / 360) % 1) + 1) % 1 * n;
    const yf = (1 - Math.log(Math.tan(la) + 1 / Math.cos(la)) / Math.PI) / 2 * n;
    const tx = Math.floor(xf), ty = Math.floor(yf);
    const img = await this.tile(z, tx, ty);
    if (!img) return null;
    const px = Math.min(img.width - 1, Math.floor((xf - tx) * img.width));
    const py = Math.min(img.height - 1, Math.floor((yf - ty) * img.height));
    const i = (py * img.width + px) * 4, d = img.data;
    const e = d[i] * 256 + d[i + 1] + d[i + 2] / 256 - 32768;
    if (e < -1 / 512) return { depthM: -e };
    return { code: ['unknown', 'drying', 'land'][Math.min(2, Math.max(0, Math.round(e)))] };
  }

  text(r) {
    if (!r) return '';
    if (r.code === 'land') return '';
    if (r.code === 'drying') return 'Depth: dries at low water';
    if (r.code === 'unknown') return 'Depth: unknown';
    const m = r.depthM;
    if (this.unit === 'ft') { const f = m * 3.28084; return `Depth ${f < 10 ? f.toFixed(1) : Math.round(f)} ft`; }
    if (this.unit === 'fm') return `Depth ${(m / 1.8288).toFixed(1)} fm`;
    return `Depth ${m < 10 ? m.toFixed(1) : Math.round(m)} m`;
  }
}
