"""Map tiles: a caching proxy for online tile servers, and offline MBTiles files.

Tiles fetched online are saved under tile_cache/, so any area you have viewed
(or pre-fetched) while in port is still there at sea without internet.
"""
from __future__ import annotations

import asyncio
import math
import re
import sqlite3
from pathlib import Path

import aiohttp

USER_AGENT = "Spyhop/0.1 (field data logger; tile cache)"
HALF = 20037508.342789244


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


def sniff_type(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


class TileService:
    def __init__(self, cfg):
        self.cfg = cfg
        self.session: aiohttp.ClientSession | None = None
        self._mb: dict[str, sqlite3.Connection] = {}
        self.prefetch_state = {"running": False, "done": 0, "total": 0, "failed": 0, "source": ""}
        self._prefetch_task = None

    async def close(self):
        if self.session:
            await self.session.close()
        for c in self._mb.values():
            c.close()

    def _session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=15))
        return self.session

    # -- online + cache ------------------------------------------------------
    def _cache_path(self, src: dict, z, x, y) -> Path:
        return self.cfg.tile_cache_dir / _safe(src["name"]) / str(z) / str(x) / f"{y}.tile"

    def _url(self, src: dict, z, x, y) -> str:
        return (src["url"].replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
                .replace("{bbox}", tile_bbox_3857(z, x, y)))

    async def get_online(self, idx: int, z: int, x: int, y: int):
        try:
            src = self.cfg.tile_sources[idx]
        except IndexError:
            return None
        cache = self._cache_path(src, z, x, y)
        if cache.exists():
            data = cache.read_bytes()
            return data, sniff_type(data)
        data = await self._fetch(src, z, x, y)
        if data is None:
            return None
        return data, sniff_type(data)

    async def _fetch(self, src, z, x, y) -> bytes | None:
        try:
            async with self._session().get(self._url(src, z, x, y)) as r:
                if r.status != 200:
                    return None
                data = await r.read()
        except Exception:
            return None
        if sniff_type(data) == "application/octet-stream":
            return None
        if self.cfg.settings.get("tile_cache_enabled", True):
            cache = self._cache_path(src, z, x, y)
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(data)
            except OSError:
                pass
        return data

    # -- pre-fetch an area for offline use --------------------------------------
    def start_prefetch(self, idx: int, bounds: list[float], zmin: int, zmax: int, limit=20000):
        src = self.cfg.tile_sources[idx]
        if "openstreetmap.org" in src["url"]:
            raise ValueError("OpenStreetMap's tile policy doesn't allow bulk downloading. "
                             "Pre-fetch another layer, or use an MBTiles file for offline maps.")
        s, w, n, e = bounds
        jobs = []
        for z in range(int(zmin), int(zmax) + 1):
            x0, y0 = lonlat_to_tile(w, n, z)
            x1, y1 = lonlat_to_tile(e, s, z)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    jobs.append((z, x, y))
        if len(jobs) > limit:
            raise ValueError(f"That is {len(jobs):,} tiles — more than the {limit:,} limit. "
                             "Zoom in or lower the maximum zoom.")
        if self.prefetch_state["running"]:
            raise ValueError("A pre-fetch is already running.")
        self.prefetch_state = {"running": True, "done": 0, "total": len(jobs), "failed": 0,
                               "source": src["name"]}
        self._prefetch_task = asyncio.create_task(self._prefetch(src, jobs))
        return len(jobs)

    async def _prefetch(self, src, jobs):
        sem = asyncio.Semaphore(4)
        st = self.prefetch_state

        async def one(j):
            async with sem:
                z, x, y = j
                if not self._cache_path(src, z, x, y).exists():
                    ok = await self._fetch(src, z, x, y)
                    if ok is None:
                        st["failed"] += 1
                st["done"] += 1
        try:
            await asyncio.gather(*(one(j) for j in jobs))
        finally:
            st["running"] = False

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

    def mbtiles_info(self) -> list[dict]:
        out = []
        for name in self.cfg.mbtiles:
            info = {"file": name, "name": name.rsplit(".", 1)[0], "minzoom": 0, "maxzoom": 18,
                    "bounds": None, "format": "png", "overlay": False}
            try:
                c = self._mbconn(name)
                for k, v in c.execute("SELECT name, value FROM metadata"):
                    if k in ("minzoom", "maxzoom"):
                        info[k] = int(float(v))
                    elif k == "bounds":
                        info["bounds"] = [float(a) for a in v.split(",")]
                    elif k == "format":
                        info["format"] = v
                    elif k == "name" and v:
                        info["name"] = v
                    elif k == "type":
                        info["overlay"] = v == "overlay"
            except Exception as e:  # noqa: BLE001
                info["error"] = str(e)
            out.append(info)
        return out

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
