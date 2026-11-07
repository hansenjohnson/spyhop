"""Saved routes (Tools → Routes): one GPX file per route in the `routes` folder in Spyhop's folder.

The window designs routes and writes the GPX (planning.js); a Spyhop GPX keeps the whole
design (mode, legs, speed, appearance) in <metadata><extensions><spyhop:route> as JSON, so a
route opens again exactly as designed. Any other GPX file copied into the folder is listed
too, and opens as a manual route of its route points (or waypoints, or track).
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class RouteError(ValueError):
    pass


def routes_dir(cfg) -> Path:
    d = cfg.routes_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_name(name: str) -> str:
    s = _BAD.sub("_", str(name or "").strip()).strip(" .")
    return (s[:80] or "Route") + ".gpx"


def _path(cfg, fn: str) -> Path:
    fn = str(fn or "")
    if not fn.lower().endswith(".gpx") or "/" in fn or "\\" in fn or fn.startswith("."):
        raise RouteError("That isn't the name of a saved route.")
    p = routes_dir(cfg) / fn
    if not p.is_file():
        raise RouteError(f"There's no saved route {fn}.")
    return p


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _dist_nm(pts) -> float:
    tot = 0.0
    for (a, b), (c, d) in zip(pts, pts[1:]):
        p1, p2 = math.radians(a), math.radians(c)
        dl = math.radians(d - b)
        h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        tot += 2 * 6371008.8 * math.asin(min(1, math.sqrt(h)))
    return tot / 1852


def summary(p: Path) -> dict:
    """What the list shows about one GPX file."""
    st = p.stat()
    out = {"file": p.name, "name": p.stem, "mode": "", "points": 0, "nm": None, "speed": None,
           "color": None, "spyhop": False, "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
           "size": st.st_size, "error": None}
    try:
        if st.st_size > MAX_BYTES:
            raise RouteError("too big for a route")
        root = ET.fromstring(p.read_bytes())
        if _local(root.tag) != "gpx":
            raise RouteError("not a GPX file")
        design = None
        for el in root.iter():
            if el.tag.endswith("}route") and "spyhop" in el.tag:       # {https://github.com/spyhop/route/1}route
                try:
                    design = json.loads(el.text or "")
                except ValueError:
                    pass
        def pts(tag):
            return [(float(e.get("lat")), float(e.get("lon"))) for e in root.iter() if _local(e.tag) == tag
                    and e.get("lat") is not None and e.get("lon") is not None]
        rte = pts("rtept") or pts("wpt") or pts("trkpt")
        meta_name = next((e.text for e in root.iter() if _local(e.tag) == "name" and e.text), None)
        out["name"] = (design or {}).get("name") or meta_name or p.stem
        out["points"] = len(rte)
        out["nm"] = round(_dist_nm(rte), 2) if len(rte) > 1 else 0
        if design:
            out.update(spyhop=True, mode=design.get("mode", ""), speed=design.get("speed"),
                       color=(design.get("style") or {}).get("color"))
        else:
            out["mode"] = "imported"
    except (ET.ParseError, RouteError, ValueError, OSError) as e:
        out["error"] = f"Can't be read ({e})"
    return out


def list_routes(cfg) -> list[dict]:
    return sorted((summary(p) for p in routes_dir(cfg).glob("*.gpx") if p.is_file()),
                  key=lambda r: r["name"].lower())


def read(cfg, fn: str) -> str:
    p = _path(cfg, fn)
    if p.stat().st_size > MAX_BYTES:
        raise RouteError("That file is too big for a route.")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def save(cfg, name: str, gpx: str, replace: str | None = None, overwrite: bool = False) -> dict:
    """Save a route as <name>.gpx. replace: the file it was opened from (renamed if the name
    changed). An existing file of that name is only replaced when overwrite is true."""
    if not isinstance(gpx, str) or not gpx.lstrip().startswith("<?xml") or "<gpx" not in gpx[:800]:
        raise RouteError("That isn't a GPX file.")
    if len(gpx.encode("utf-8")) > MAX_BYTES:
        raise RouteError("That route is too big.")
    d = routes_dir(cfg)
    fn = file_name(name)
    dest = d / fn
    if dest.exists() and fn != replace and not overwrite:
        raise RouteError(f"exists:{fn}")
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + fn + ".")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(gpx)
    os.replace(tmp, dest)
    if replace and replace != fn:
        try:
            _path(cfg, replace).unlink()
        except RouteError:
            pass
    return summary(dest)


def delete(cfg, fn: str):
    _path(cfg, fn).unlink()
