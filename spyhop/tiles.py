"""Map tiles: a caching proxy for online tile servers, and offline MBTiles files.

Tiles fetched online are saved under tile_cache/, so any area you have viewed
(or downloaded) while in port is still there at sea without internet. MapLibre styles
(Seascape) go through the same cache: see TileService.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, urljoin, urlsplit

import aiohttp

USER_AGENT = "Spyhop (marine survey recorder; tile cache)"
HALF = 20037508.342789244
OFFLINE_S = 20            # after OFFLINE_AFTER failed connections in a row, don't try the internet for this long
OFFLINE_AFTER = 3
STYLE_MAX_AGE_S = 86400   # refresh a cached map style (and TileJSON) after a day, when online
GLYPH_RANGES = ("0-255", "256-511", "8192-8447")   # Latin, Latin-1/Extended-A, punctuation


def tile_bbox_3857(z: int, x: int, y: int) -> str:
    size = 2 * HALF / (2 ** z)
    minx = -HALF + x * size
    maxy = HALF - y * size
    return f"{minx},{maxy - size},{minx + size},{maxy}"


def lonlat_to_tile(lon, lat, z):
    lat = max(-85.0511, min(85.0511, lat))
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _safe(s: str) -> str:
    return re.sub(r"[^\w\-]+", "_", s)[:50]


def _h(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def sniff_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _is_html(data: bytes) -> bool:
    head = data[:200].lstrip().lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html") or head.startswith(b"<?xml")


def _is_sounding_layer(layer) -> bool:
    """Spot depth soundings (Seascape's `soundings` vector layer): dropped from every style (user, 0.13.1)."""
    if not isinstance(layer, dict):
        return False
    sl = str(layer.get("source-layer") or "").lower()
    return sl == "soundings" or "sounding" in str(layer.get("id") or "").lower()


CONTOUR_LABEL_PADDING = 2      # Seascape uses 50, which hides many contour labels


def _more_contour_labels(layer) -> None:
    """Label more contour lines (user, 0.13.2): a smaller collision padding on contour labels."""
    if (isinstance(layer, dict) and layer.get("type") == "symbol"
            and str(layer.get("source-layer") or "").lower() == "contours"):
        layer.setdefault("layout", {})["text-padding"] = CONTOUR_LABEL_PADDING


def _no_bulk(url: str) -> bool:
    """Servers whose terms don't allow bulk downloading (pre-fetch)."""
    return "openstreetmap.org" in url


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _unb64(s: str) -> str:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()


CHART_BATCH = 200          # tiles written to a chart file between commits


def chart_file_name(name: str) -> str:
    """The charts-folder file name for a downloaded area: <name>.mbtiles."""
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "").strip()).strip(" .")
    if n.lower().endswith(".mbtiles"):
        n = n[:-8].strip(" .")
    return f"{n}.mbtiles" if n else ""


class ChartWriter:
    """Writes a downloaded area into an MBTiles file in the charts folder.

    A raster layer (Esri, NOAA) is a standard MBTiles file (`tiles`, `metadata`), so other map
    programs can open it too. A MapLibre style (Seascape) has several tile sets plus its style,
    TileJSON documents and fonts, so it also gets `spyhop_tiles` (one row per tile per tile set,
    keyed by a hash of the tile set's address) and `spyhop_files`. Rows use the MBTiles (TMS) row
    order. Writing to an existing file adds to it."""

    def __init__(self, path: Path, kind: str):
        self.path, self.kind, self.n = path, kind, 0
        path.parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(path)
        self.c.executescript("""
            CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB,
                                              PRIMARY KEY (zoom_level, tile_column, tile_row));""")
        if kind == "style":
            self.c.executescript("""
                CREATE TABLE IF NOT EXISTS spyhop_tiles (tileset TEXT, zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
                                                         tile_data BLOB, PRIMARY KEY (tileset, zoom_level, tile_column, tile_row));
                CREATE TABLE IF NOT EXISTS spyhop_files (key TEXT PRIMARY KEY, data BLOB);""")

    def meta(self) -> dict:
        return dict(self.c.execute("SELECT name, value FROM metadata"))

    def set_meta(self, values: dict):
        self.c.executemany("INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)",
                           [(k, str(v)) for k, v in values.items() if v is not None])

    def has(self, z, x, y, tileset=None) -> bool:
        row = (2 ** z - 1) - y
        if tileset is None:
            q = self.c.execute("SELECT 1 FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?", (z, x, row))
        else:
            q = self.c.execute("SELECT 1 FROM spyhop_tiles WHERE tileset=? AND zoom_level=? AND tile_column=? AND tile_row=?",
                               (tileset, z, x, row))
        return q.fetchone() is not None

    def put(self, z, x, y, data: bytes, tileset=None):
        row = (2 ** z - 1) - y
        if tileset is None:
            self.c.execute("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)", (z, x, row, data))
        else:
            self.c.execute("INSERT OR REPLACE INTO spyhop_tiles VALUES (?, ?, ?, ?, ?)", (tileset, z, x, row, data))
        self._tick()

    def put_file(self, key: str, data: bytes):
        self.c.execute("INSERT OR REPLACE INTO spyhop_files VALUES (?, ?)", (key, data))
        self._tick()

    def _tick(self):
        self.n += 1
        if self.n % CHART_BATCH == 0:
            self.c.commit()

    def close(self):
        self.c.commit()
        self.c.close()


class TileService:
    """Online tiles through a disk cache, MapLibre styles (Seascape) through the same cache, and MBTiles.

    A raster source is a URL template ({z}/{x}/{y}, or {bbox} for an ArcGIS export).
    A "style" source is a MapLibre style.json: the style, its TileJSON documents, vector and raster
    tiles and fonts are all fetched through /tiles/gl/<i>/…, cached under tile_cache/<name>/, and
    served from the cache when there's no internet. Only hosts named by the style are proxied."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.session: aiohttp.ClientSession | None = None
        self._mb: dict[str, sqlite3.Connection] = {}
        self.prefetch_state = {"running": False, "done": 0, "total": 0, "failed": 0, "source": "",
                               "error": "", "skipped": ""}
        self._prefetch_task = None
        self._offline_until = 0.0           # everything (a test, or set when clearly offline)
        self._host_until: dict[str, float] = {}     # per server: one that can't be reached doesn't block the others
        self._host_failures: dict[str, int] = {}
        self._gl_hosts: dict[int, set[str]] = {}
        self._chart_meta: dict[str, dict] = {}
        self.on_charts_changed = None       # set by the server: called after a download adds a chart file

    async def close(self):
        if self.session:
            await self.session.close()
        for c in self._mb.values():
            c.close()

    def _session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=20, connect=5, sock_read=15))
        return self.session

    def source(self, idx: int) -> dict | None:
        try:
            return self.cfg.tile_sources[idx] if idx >= 0 else None
        except IndexError:
            return None

    # -- the network, with an offline back-off ------------------------------------------
    async def _download(self, url: str) -> tuple[int, bytes, str]:
        """(status, body, content type); status 0 = no connection. Never raises."""
        host = urlsplit(url).netloc.lower()
        if time.monotonic() < max(self._offline_until, self._host_until.get(host, 0.0)):
            return 0, b"", "no internet connection"
        last = ""
        for attempt in range(2):            # a dropped keep-alive connection is worth one more try
            try:
                async with self._session().get(url) as r:
                    body = await r.read()
                    self._host_failures.pop(host, None)
                    return r.status, body, r.headers.get("Content-Type", "")
            except aiohttp.ServerDisconnectedError as e:
                last = f"the server closed the connection ({e.__class__.__name__})"
                continue
            except asyncio.TimeoutError:
                return 0, b"", "the server took too long to answer"
            except (aiohttp.ClientConnectionError, OSError) as e:
                last = f"no connection ({e.__class__.__name__})"
                break
            except Exception as e:  # noqa: BLE001
                return 0, b"", str(e)
        self._host_failures[host] = self._host_failures.get(host, 0) + 1
        if self._host_failures[host] >= OFFLINE_AFTER:   # can't reach it: answer from the cache at once for a while
            self._host_until[host] = time.monotonic() + OFFLINE_S
            self._host_failures[host] = 0
        return 0, b"", last

    @staticmethod
    def _save(path: Path, data: bytes):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".part")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        except OSError:
            pass

    # -- raster sources -------------------------------------------------------
    def _cache_path(self, src: dict, z, x, y) -> Path:
        return self.cfg.tile_cache_dir / _safe(src["name"]) / str(z) / str(x) / f"{y}.tile"

    def _url(self, src: dict, z, x, y) -> str:
        return (src["url"].replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
                .replace("{bbox}", tile_bbox_3857(z, x, y)))

    async def get_online(self, idx: int, z: int, x: int, y: int):
        src = self.source(idx)
        if not src or src.get("kind") == "style":
            return None
        cache = self._cache_path(src, z, x, y)
        if cache.exists():
            data = cache.read_bytes()
            return data, sniff_type(data)
        data = self._offline_tile(src, z, x, y)
        if data is not None:
            return data, sniff_type(data)
        data, _why = await self._fetch(src, z, x, y, save=self.cfg.settings.get("tile_cache_enabled", True))
        if data is None:
            return None
        return data, sniff_type(data)

    async def _fetch(self, src, z, x, y, save=True) -> tuple[bytes | None, str]:
        status, data, _ct = await self._download(self._url(src, z, x, y))
        if status != 200:
            return None, (f"HTTP {status}" if status else _ct)
        if sniff_type(data) == "application/octet-stream":
            return None, "not an image"
        if save:
            self._save(self._cache_path(src, z, x, y), data)
        return data, ""

    # -- MapLibre style sources (Seascape) ---------------------------------------------
    def _gl_dir(self, src: dict) -> Path:
        return self.cfg.tile_cache_dir / _safe(src["name"])

    def _allow(self, idx: int, url: str):
        self._gl_hosts.setdefault(idx, set()).add(urlsplit(url).netloc.lower())

    async def _ensure_hosts(self, idx: int):
        """After a restart, learn the style's hosts again before proxying for a page still open."""
        if idx not in self._gl_hosts:
            await self.gl_style(idx, "")

    def _allowed(self, idx: int, url: str) -> bool:
        src = self.source(idx)
        hosts = self._gl_hosts.get(idx, set()) | ({urlsplit(src["url"]).netloc.lower()} if src else set())
        return urlsplit(url).scheme in ("http", "https") and urlsplit(url).netloc.lower() in hosts

    async def _json_cached(self, path: Path, url: str) -> dict | None:
        """A JSON document from the internet, kept on disk; the saved copy when offline."""
        fresh = path.exists() and time.time() - path.stat().st_mtime < STYLE_MAX_AGE_S
        if not fresh:
            status, data, _ = await self._download(url)
            if status == 200 and not _is_html(data):
                try:
                    doc = json.loads(data)
                    self._save(path, data)
                    return doc
                except ValueError:
                    pass
        if path.exists():
            try:
                return json.loads(path.read_bytes())
            except ValueError:
                return None
        return None

    def _local(self, base: str, idx: int, what: str, upstream: str) -> str:
        """A local address for an upstream one; MapLibre fills in {z}/{x}/{y}, {fontstack}, {range}."""
        self._allow(idx, upstream)
        q = "?u=" + quote(upstream, safe="")
        return {"tiles": f"{base}/tiles/gl/{idx}/t/{{z}}/{{x}}/{{y}}{q}",
                "tilejson": f"{base}/tiles/gl/{idx}/tilejson{q}",
                "glyphs": f"{base}/tiles/gl/{idx}/glyphs/{{fontstack}}/{{range}}{q}",
                "sprite": f"{base}/tiles/gl/{idx}/sprite/{_b64(upstream)}"}[what]

    async def gl_style(self, idx: int, base: str) -> dict | None:
        src = self.source(idx)
        if not src or src.get("kind") != "style":
            return None
        style = await self._json_cached(self._gl_dir(src) / "_style.json", src["url"]) or self._offline_json(src, "style")
        if not style:
            return None
        style = json.loads(json.dumps(style))
        style["layers"] = [l for l in style.get("layers") or [] if not _is_sounding_layer(l)]
        for layer in style["layers"]:
            _more_contour_labels(layer)
        style_url = src["url"]
        for s in (style.get("sources") or {}).values():
            if isinstance(s.get("url"), str) and s["url"].startswith(("http://", "https://", "/")):
                s["url"] = self._local(base, idx, "tilejson", urljoin(style_url, s["url"]))
            if isinstance(s.get("tiles"), list):
                s["tiles"] = [self._local(base, idx, "tiles", urljoin(style_url, u)) for u in s["tiles"]]
        if isinstance(style.get("glyphs"), str):
            style["glyphs"] = self._local(base, idx, "glyphs", urljoin(style_url, style["glyphs"]))
        sp = style.get("sprite")
        if isinstance(sp, str):
            style["sprite"] = self._local(base, idx, "sprite", urljoin(style_url, sp))
        elif isinstance(sp, list):
            for item in sp:
                if isinstance(item, dict) and isinstance(item.get("url"), str):
                    item["url"] = self._local(base, idx, "sprite", urljoin(style_url, item["url"]))
        return style

    async def gl_tilejson(self, idx: int, upstream: str, base: str) -> dict | None:
        src = self.source(idx)
        await self._ensure_hosts(idx)
        if not src or not self._allowed(idx, upstream):
            return None
        doc = (await self._json_cached(self._gl_dir(src) / "_tilejson" / f"{_h(upstream)}.json", upstream)
               or self._offline_json(src, f"tilejson:{_h(upstream)}"))
        if not doc:
            return None
        doc = dict(doc)
        doc["tiles"] = [self._local(base, idx, "tiles", urljoin(upstream, u)) for u in doc.get("tiles", [])]
        return doc

    def _gl_tile_path(self, src, template: str, z, x, y) -> Path:
        return self._gl_dir(src) / _h(template) / str(z) / str(x) / f"{y}.tile"

    async def gl_tile(self, idx: int, template: str, z: int, x: int, y: int, save=None):
        """(bytes, content type, status). Vector tiles (.pbf/.mvt) pass through untouched."""
        src = self.source(idx)
        await self._ensure_hosts(idx)
        if not src or not self._allowed(idx, template):
            return None, "", 403
        p = self._gl_tile_path(src, template, z, x, y)
        if p.exists():
            data = p.read_bytes()
            return data, sniff_type(data), 200
        data = self._offline_tile(src, z, x, y, tileset=_h(template))
        if data is not None:
            return data, sniff_type(data), 200
        url = template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        status, data, ct = await self._download(url)
        if status != 200 or _is_html(data):
            return None, ct, status or 504
        if save if save is not None else self.cfg.settings.get("tile_cache_enabled", True):
            self._save(p, data)
        return data, sniff_type(data), 200

    async def gl_file(self, idx: int, upstream: str, folder: str, save=True):
        """A font range or sprite file, cached."""
        src = self.source(idx)
        await self._ensure_hosts(idx)
        if not src or not self._allowed(idx, upstream):
            return None
        p = self._gl_dir(src) / folder / _h(upstream)
        if p.exists():
            return p.read_bytes()
        data = self._offline_blob(src, f"file:{_h(upstream)}")
        if data is not None:
            return data
        status, data, _ = await self._download(upstream)
        if status != 200 or _is_html(data):
            return None
        if save:
            self._save(p, data)
        return data

    @staticmethod
    def fill_glyphs(template: str, fontstack: str, rng: str) -> str:
        return template.replace("{fontstack}", quote(fontstack, safe=",")).replace("{range}", rng)

    async def _gl_plan(self, idx: int) -> tuple[list[dict], list[str], list[str]]:
        """For pre-fetching a style: its tile sets [{template, minzoom, maxzoom, bounds}],
        the font files, and the tile sets left out (servers that don't allow bulk downloads)."""
        style = await self.gl_style(idx, "")
        if not style:
            raise ValueError("Couldn't load this map's style. Are you online?")
        sets, skipped = [], []
        for name, s in (style.get("sources") or {}).items():
            if s.get("type") not in ("vector", "raster", "raster-dem"):
                continue
            tj = s
            if s.get("url"):
                up = parse_qs(urlsplit(s["url"]).query).get("u", [""])[0]
                tj = await self.gl_tilejson(idx, up, "") or {}
            for tpl in tj.get("tiles", []):
                up = parse_qs(urlsplit(tpl).query).get("u", [""])[0]
                if _no_bulk(up):
                    skipped.append(f"{name} ({urlsplit(up).netloc})")
                    continue
                sets.append({"template": up, "minzoom": int(tj.get("minzoom", s.get("minzoom", 0)) or 0),
                             "maxzoom": int(tj.get("maxzoom", s.get("maxzoom", 22)) or 22),
                             "bounds": tj.get("bounds")})
                break                       # one template per source is enough
        fonts = set()
        for layer in style.get("layers", []):
            f = (layer.get("layout") or {}).get("text-font")
            if isinstance(f, list) and f and all(isinstance(v, str) for v in f):
                fonts.add(",".join(f))
        glyph_files = []
        g = style.get("glyphs")
        if g and fonts:
            up = parse_qs(urlsplit(g).query).get("u", [""])[0]
            glyph_files = [self.fill_glyphs(up, fs, r) for fs in sorted(fonts) for r in GLYPH_RANGES]
        return sets, glyph_files, skipped

    # -- pre-fetch an area for offline use --------------------------------------
    @staticmethod
    def _tiles_in(bounds, z, limit_bounds=None):
        s, w, n, e = bounds
        if limit_bounds:                        # TileJSON bounds: [west, south, east, north]
            lw, ls, le, ln = limit_bounds
            w, s, e, n = max(w, lw), max(s, ls), min(e, le), min(n, ln)
            if w >= e or s >= n:
                return []
        x0, y0 = lonlat_to_tile(w, n, z)
        x1, y1 = lonlat_to_tile(e, s, z)
        return [(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)]

    async def plan_prefetch(self, idx: int, bounds: list[float], zmin: int, zmax: int) -> dict:
        """What a pre-fetch would download: {jobs, total, zmax (clamped), skipped, note}."""
        src = self.source(idx)
        if not src:
            raise ValueError("Unknown map layer.")
        zmin, zmax = int(zmin), int(zmax)
        if zmin > zmax:
            raise ValueError("The lowest zoom must not be above the highest.")
        jobs, skipped, note = [], [], ""
        if src.get("kind") == "style":
            sets, glyphs, skipped = await self._gl_plan(idx)
            for ts in sets:
                for z in range(max(zmin, ts["minzoom"]), min(zmax, ts["maxzoom"]) + 1):
                    jobs += [("gl", ts["template"], *t) for t in self._tiles_in(bounds, z, ts["bounds"])]
            jobs += [("file", g) for g in glyphs]
        else:
            if _no_bulk(src["url"]):
                raise ValueError("OpenStreetMap's tile policy doesn't allow bulk downloading. "
                                 "Download another layer, or use an MBTiles file for offline maps.")
            top = int(src.get("max_zoom") or 18)
            if zmax > top:
                note = f"{src['name']} only goes up to zoom {top}; the map zooms in further on those tiles."
                zmax = top
            for z in range(zmin, zmax + 1):
                jobs += [("raster", *t) for t in self._tiles_in(bounds, z)]
        return {"jobs": jobs, "total": len(jobs), "zmax": zmax, "skipped": skipped, "note": note}

    async def start_prefetch(self, idx: int, bounds: list[float], zmin: int, zmax: int, limit=50000, name: str = "") -> dict:
        if self.prefetch_state["running"]:
            raise ValueError("A download is already running.")
        src = self.source(idx)
        fn = chart_file_name(name or (f"{src['name']} {time.strftime('%Y-%m-%d')}" if src else ""))
        if not fn:
            raise ValueError("Give the download a name.")
        path = self.cfg.charts_dir / fn
        kind = "style" if src and src.get("kind") == "style" else "raster"
        if path.exists():
            old = self.chart_meta(fn)
            if old.get("spyhop_source") != (src or {}).get("name"):
                made = f"made from {old['spyhop_source']}" if old.get("spyhop_source") else "not made by a Spyhop download"
                raise ValueError(f"There's already a chart called {fn} ({made}). Choose another name.")
        plan = await self.plan_prefetch(idx, bounds, zmin, zmax)
        if plan["total"] > limit:
            raise ValueError(f"That is {plan['total']:,} tiles — more than the {limit:,} limit. "
                             "Zoom the map in, or lower the highest zoom.")
        if not plan["total"]:
            raise ValueError("There are no tiles to download there at those zooms.")
        writer = ChartWriter(path, kind)
        try:
            self._start_chart(writer, idx, src, kind, bounds, zmin, plan["zmax"])
        except Exception:
            writer.close()
            raise
        self._mb.pop(fn, None)
        self.prefetch_state = {"running": True, "done": 0, "total": plan["total"], "failed": 0, "cached": 0, "empty": 0,
                               "saved": 0, "source": src["name"], "error": "", "skipped": ", ".join(plan["skipped"]),
                               "note": plan["note"], "file": fn}
        self._prefetch_task = asyncio.create_task(self._prefetch(idx, src, plan["jobs"], writer))
        return {**{k: v for k, v in plan.items() if k != "jobs"}, "file": fn}

    def _start_chart(self, w: ChartWriter, idx, src, kind, bounds, zmin, zmax):
        """The chart file's metadata (an existing file's area and zooms are widened), and for a style its
        style and TileJSON documents, so the area can be drawn from the file alone."""
        old = w.meta()
        s_, w_, n_, e_ = bounds
        if old.get("bounds"):
            try:
                ow, os_, oe, on = (float(v) for v in old["bounds"].split(","))
                w_, s_, e_, n_ = min(w_, ow), min(s_, os_), max(e_, oe), max(n_, on)
            except ValueError:
                pass
        zmin = min(int(zmin), int(old.get("minzoom", zmin)))
        zmax = max(int(zmax), int(old.get("maxzoom", zmax)))
        w.set_meta({"name": old.get("name") or w.path.stem, "type": "overlay" if src.get("overlay") == "1" else "baselayer",
                    "format": "spyhop-style" if kind == "style" else old.get("format", "png"),
                    "bounds": f"{max(-180, w_):.6f},{max(-85.0511, s_):.6f},{min(180, e_):.6f},{min(85.0511, n_):.6f}",
                    "minzoom": zmin, "maxzoom": zmax, "attribution": src.get("attribution", ""),
                    "description": f"Downloaded by Spyhop from {src['name']}",
                    "spyhop_kind": kind, "spyhop_source": src["name"], "spyhop_url": src["url"],
                    "spyhop_created": old.get("spyhop_created") or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "spyhop_updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        if kind == "style":
            d = self._gl_dir(src)
            for f in [d / "_style.json", *sorted((d / "_tilejson").glob("*.json"))]:
                if f.exists():
                    w.put_file("style" if f.name == "_style.json" else f"tilejson:{f.stem}", f.read_bytes())
        w.c.commit()

    async def _prefetch(self, idx, src, jobs, writer: ChartWriter):
        sem = asyncio.Semaphore(4)
        st = self.prefetch_state

        async def one(j):
            async with sem:
                for attempt in range(3):
                    why = await job(j)
                    if not why or not why.startswith(("no connection", "no internet", "the server")):
                        break
                    if attempt < 2:
                        st["failed"] -= 1                 # counted again below if it fails for good
                        await asyncio.sleep(2 + 3 * attempt)
                if why:
                    st["error"] = why
                st["done"] += 1

        async def job(j) -> str:
                # every tile goes into the chart file; one already saved (in the file, or in the
                # browsing cache) isn't downloaded again
                why = ""
                if j[0] == "raster":
                    _, z, x, y = j
                    if writer.has(z, x, y):
                        st["cached"] += 1
                        return ""
                    cache = self._cache_path(src, z, x, y)
                    if cache.exists():
                        data = cache.read_bytes()
                        st["cached"] += 1
                    else:
                        data, why = await self._fetch(src, z, x, y, save=False)
                        if data is None:
                            st["failed"] += 1
                            return why
                    if st["saved"] == 0 and not writer.n:
                        writer.set_meta({"format": "jpg" if sniff_type(data) == "image/jpeg" else "png"})
                    writer.put(z, x, y, data)
                    st["saved"] += 1
                elif j[0] == "gl":
                    _, tpl, z, x, y = j
                    ts_id = _h(tpl)
                    if writer.has(z, x, y, ts_id):
                        st["cached"] += 1
                        return ""
                    data, ct, status = await self.gl_tile(idx, tpl, z, x, y, save=False)
                    if data is None and status in (404, 204):   # no data there (open ocean, land)
                        st["empty"] += 1
                    elif data is None:
                        st["failed"] += 1
                        why = f"HTTP {status}" if status and status != 504 else (ct or "no connection")
                    else:
                        writer.put(z, x, y, data, ts_id)
                        st["saved"] += 1
                else:
                    data = await self.gl_file(idx, j[1], "_glyphs")
                    if data is None:
                        st["failed"] += 1
                        why = "a font file failed"
                    else:
                        writer.put_file(f"file:{_h(j[1])}", data)
                return why
        try:
            await asyncio.gather(*(one(j) for j in jobs))
        except asyncio.CancelledError:
            st["error"] = st["error"] or "stopped"
        finally:
            if src.get("kind") == "style":         # TileJSON fetched during the download, too
                for f in sorted((self._gl_dir(src) / "_tilejson").glob("*.json")):
                    writer.put_file(f"tilejson:{f.stem}", f.read_bytes())
            writer.close()
            self.rescan_charts()
            st["running"] = False
            if self.on_charts_changed:
                try:
                    self.on_charts_changed()
                except Exception:  # noqa: BLE001
                    pass

    def cancel_prefetch(self):
        if self._prefetch_task:
            self._prefetch_task.cancel()
        self.prefetch_state["running"] = False

    # -- MBTiles --------------------------------------------------------------
    def _mbconn(self, name: str):
        if name not in self._mb:
            p = self.cfg.charts_dir / name
            if not p.exists() or p.suffix != ".mbtiles":
                return None
            self._mb[name] = sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)
        return self._mb[name]

    def rescan_charts(self):
        """Look at the charts folder again (after a download, or files copied in)."""
        self.cfg.mbtiles = sorted(p.name for p in self.cfg.charts_dir.glob("*.mbtiles"))
        for name in list(self._mb):
            self._mb.pop(name).close()
        self._chart_meta.clear()

    def chart_meta(self, name: str) -> dict:
        """A chart file's metadata table, with its tile count and size ({} if unreadable)."""
        if name not in self._chart_meta:
            meta = {}
            try:
                c = self._mbconn(name)
                if c is not None:
                    meta = dict(c.execute("SELECT name, value FROM metadata"))
                    n = c.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
                    if meta.get("spyhop_kind") == "style":
                        n += c.execute("SELECT COUNT(*) FROM spyhop_tiles").fetchone()[0]
                    meta["_tiles"] = n
                    meta["_bytes"] = (self.cfg.charts_dir / name).stat().st_size
            except Exception as e:  # noqa: BLE001
                meta = {"_error": str(e)}
            self._chart_meta[name] = meta
        return self._chart_meta[name]

    def mbtiles_info(self) -> list[dict]:
        out = []
        for name in self.cfg.mbtiles:
            info = {"file": name, "name": name.rsplit(".", 1)[0], "minzoom": 0, "maxzoom": 18,
                    "bounds": None, "format": "png", "overlay": False, "kind": "chart", "source": "",
                    "tiles": None, "mb": None, "created": ""}
            m = self.chart_meta(name)
            if m.get("_error"):
                info["error"] = m["_error"]
            try:
                for k in ("minzoom", "maxzoom"):
                    if m.get(k) not in (None, ""):
                        info[k] = int(float(m[k]))
                if m.get("bounds"):
                    info["bounds"] = [float(a) for a in m["bounds"].split(",")]
            except ValueError:
                pass
            # a Spyhop download is called by its file name (a copied file keeps the original's metadata name)
            label = info["name"] if m.get("spyhop_kind") else (m.get("name") or info["name"])
            info.update(format=m.get("format", info["format"]), name=label, bytes=m.get("_bytes"),
                        overlay=m.get("type") == "overlay", kind=m.get("spyhop_kind") or "chart",
                        source=m.get("spyhop_source", ""), created=m.get("spyhop_updated") or m.get("spyhop_created", ""),
                        tiles=m.get("_tiles"), mb=round(m["_bytes"] / 1e6, 1) if m.get("_bytes") is not None else None)
            out.append(info)
        return out

    def _charts_for(self, src: dict, kind: str):
        for name in self.cfg.mbtiles:
            m = self.chart_meta(name)
            if m.get("spyhop_source") == src["name"] and m.get("spyhop_kind") == kind:
                c = self._mbconn(name)
                if c is not None:
                    yield c

    def _offline_tile(self, src: dict, z, x, y, tileset=None) -> bytes | None:
        """A tile of this layer from a downloaded area in the charts folder."""
        row = (2 ** z - 1) - y
        try:
            for c in self._charts_for(src, "style" if tileset else "raster"):
                if tileset:
                    r = c.execute("SELECT tile_data FROM spyhop_tiles WHERE tileset=? AND zoom_level=? AND tile_column=? AND tile_row=?",
                                  (tileset, z, x, row)).fetchone()
                else:
                    r = c.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                                  (z, x, row)).fetchone()
                if r:
                    return bytes(r[0])
        except sqlite3.Error:
            pass
        return None

    def _offline_blob(self, src: dict, key: str) -> bytes | None:
        try:
            for c in self._charts_for(src, "style"):
                r = c.execute("SELECT data FROM spyhop_files WHERE key=?", (key,)).fetchone()
                if r:
                    return bytes(r[0])
        except sqlite3.Error:
            pass
        return None

    def _offline_json(self, src: dict, key: str) -> dict | None:
        data = self._offline_blob(src, key)
        try:
            return json.loads(data) if data else None
        except ValueError:
            return None

    # -- a downloaded style area on its own: /tiles/off/<file>/… (preview, and an offline layer)
    def _chart_conn(self, name: str):
        m = self.chart_meta(name) if name in self.cfg.mbtiles else {}
        return (self._mbconn(name), m) if m.get("spyhop_kind") == "style" else (None, m)

    def offline_style(self, name: str, base: str) -> dict | None:
        """The style saved in a downloaded chart file, drawing only that file's tiles and fonts."""
        c, m = self._chart_conn(name)
        if c is None:
            return None
        files = {k: bytes(v) for k, v in c.execute("SELECT key, data FROM spyhop_files")}
        try:
            style = json.loads(files["style"])
        except (KeyError, ValueError):
            return None
        style_url = m.get("spyhop_url", "")
        style["layers"] = [l for l in style.get("layers") or [] if not _is_sounding_layer(l)]
        for layer in style["layers"]:
            _more_contour_labels(layer)
        top = int(float(m.get("maxzoom", 22) or 22))
        here = f"{base}/tiles/off/{quote(name, safe='')}"
        for s in (style.get("sources") or {}).values():
            tpls, tj = list(s.get("tiles") or []), {}
            if isinstance(s.get("url"), str):
                up = urljoin(style_url, s["url"])
                try:
                    tj = json.loads(files.get(f"tilejson:{_h(up)}", b"{}"))
                except ValueError:
                    tj = {}
                tpls = [urljoin(up, u) for u in tj.get("tiles", [])]
                s.pop("url")
                for k in ("minzoom", "maxzoom", "bounds", "encoding", "tileSize", "scheme", "attribution"):
                    if k in tj and k not in s:
                        s[k] = tj[k]
            else:
                tpls = [urljoin(style_url, u) for u in tpls]
            tile_id = _h(tpls[0]) if tpls else "none"
            s["tiles"] = [f"{here}/t/{tile_id}/{{z}}/{{x}}/{{y}}"]
            s["maxzoom"] = min(int(s.get("maxzoom", top) or top), top)   # past what was saved, enlarge the saved tiles
        if isinstance(style.get("glyphs"), str):
            style["glyphs"] = f"{here}/glyphs/{{fontstack}}/{{range}}"
        style.pop("sprite", None)
        return style

    def offline_style_tile(self, name: str, tileset: str, z, x, y) -> bytes | None:
        c, _m = self._chart_conn(name)
        if c is None:
            return None
        r = c.execute("SELECT tile_data FROM spyhop_tiles WHERE tileset=? AND zoom_level=? AND tile_column=? AND tile_row=?",
                      (tileset, z, x, (2 ** z - 1) - y)).fetchone()
        return bytes(r[0]) if r else None

    def offline_glyphs(self, name: str, fontstack: str, rng: str) -> bytes | None:
        c, m = self._chart_conn(name)
        if c is None:
            return None
        r = c.execute("SELECT data FROM spyhop_files WHERE key='style'").fetchone()
        try:
            g = json.loads(bytes(r[0])).get("glyphs") if r else None
        except ValueError:
            g = None
        if not isinstance(g, str):
            return None
        up = self.fill_glyphs(urljoin(m.get("spyhop_url", ""), g), fontstack, rng)
        r = c.execute("SELECT data FROM spyhop_files WHERE key=?", (f"file:{_h(up)}",)).fetchone()
        return bytes(r[0]) if r else None

    def get_mbtile(self, name: str, z: int, x: int, y: int):
        c = self._mbconn(name)
        if c is None:
            return None
        row = c.execute("SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                        (z, x, (2 ** z - 1) - y)).fetchone()
        if not row:
            return None
        data = bytes(row[0])
        return data, sniff_type(data)

    def cache_stats(self) -> dict:
        total, files = 0, 0
        d = self.cfg.tile_cache_dir
        if d.exists():
            for p in d.rglob("*.tile"):
                files += 1
                total += p.stat().st_size
        return {"tiles": files, "mb": round(total / 1e6, 1)}
