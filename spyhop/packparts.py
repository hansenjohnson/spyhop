"""The parts of a config pack added in 0.22.0 (configpack.py has the rest):

    spyhop-pack.json      {format, min_spyhop, made_with, includes: [waypoints, routes, overlays]}
    spyhop-settings.json  {settings: {SHARED_SETTINGS}, nmea_sources: [network inputs only],
                           online_feeds: [...], online_display: {...}}
    feeds/<id>.geojson    the saved copy of each map feed, so it draws before the first download
    waypoints.csv         Name, DateTime, Lat, Lon, Shape, Color, Notes, Map        (optional)
    routes/*.gpx          saved routes                                             (optional)
    overlays/*            imported overlays (GeoJSON, GPX, KML; not "Survey - …")  (optional)

Settings are replaced (a pack's values become this computer's). Map feeds, waypoints, routes and
overlays are only ever added: one already on the computer (a feed with the same address, a
waypoint or file with the same name) is kept as it is, and nothing is removed. Serial GPS inputs,
file replays, the simulator and the data folder belong to one computer and are never in a pack.

Restoring a backup also removes what the pack used after that backup added (settings key
`group_config_added`, by backup file name), so a restore undoes a pull.
"""
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from . import __version__, feeds, schema

INFO = "spyhop-pack.json"
SETTINGS = "spyhop-settings.json"
WAYPOINTS = "waypoints.csv"
PACK_FORMAT = 2
FORMAT_MIN = "0.22.0"          # the first Spyhop that reads these parts
OPTIONAL = ("waypoints", "routes", "overlays")
NETWORK_INPUTS = ("udp", "tcp", "gpsd")
OVERLAY_EXT = (".geojson", ".json", ".gpx", ".kml")
WAYPOINT_COLS = [h for h in schema.headers("marks") if h != "RowID"]

# settings a team shares; everything else in settings.json belongs to the computer or the session
SHARED_SETTINGS = {
    "latlon_format": "Lat/lon format",
    "timezone": "Clock",
    "bearing_reference": "Bearing reference",
    "distance_unit": "Distance unit",
    "mag_variation": "Magnetic variation",
    "tracking_interval": "Track point every (s)",
    "track_break_kn": "Break the track above (kn)",
    "track_break_gap_s": "Break the track after a gap of (s)",
    "effort_reminder_min": "Effort reminder (min)",
    "keep_awake": "Keep the computer awake",
    "keep_screen_on": "Keep the screen on",
    "nmea_log_enabled": "Raw NMEA log",
    "nmea_log_timestamps": "Raw NMEA log time stamps",
}
DISPLAY_KEYS = ("ais", "radar_us", "radar_world", "feeds", "radar_opacity", "hide_stopped")


class PartError(ValueError):
    pass


# ------------------------------------------------------------------ versions
def version_tuple(v) -> tuple[int, ...] | None:
    m = re.fullmatch(r"\s*(\d+)\.(\d+)(?:\.(\d+))?\s*", str(v or ""))
    return tuple(int(x or 0) for x in m.groups()) if m else None


def clean_min_version(v) -> str:
    """The minimum Spyhop version for a pack being saved: x.y.z, from FORMAT_MIN to this version."""
    t = version_tuple(v or FORMAT_MIN)
    if not t:
        raise PartError("The minimum Spyhop version must look like 0.22.0.")
    if t < version_tuple(FORMAT_MIN):
        raise PartError(f"Packs need Spyhop {FORMAT_MIN} or newer, so the minimum can't be lower than that.")
    if t > version_tuple(__version__):
        raise PartError(f"The minimum can't be newer than this Spyhop ({__version__}).")
    return ".".join(map(str, t))


# ------------------------------------------------------------------ this computer's parts
def shared_settings(cfg) -> dict:
    st = cfg.settings
    return {k: st.get(k) for k in SHARED_SETTINGS if k in st}


def network_inputs(sources) -> list[dict]:
    return [dict(s) for s in (sources or []) if isinstance(s, dict) and s.get("type") in NETWORK_INPUTS]


def clean_display(d) -> dict | None:
    if not isinstance(d, dict):
        return None
    out = {k: d[k] for k in DISPLAY_KEYS if k in d}
    for k in ("ais", "radar_us", "radar_world", "hide_stopped"):
        if k in out:
            out[k] = bool(out[k])
    if "feeds" in out:
        out["feeds"] = [str(u) for u in out["feeds"] if isinstance(u, str)][:200]
    if "radar_opacity" in out:
        try:
            out["radar_opacity"] = max(0.2, min(1.0, float(out["radar_opacity"])))
        except (TypeError, ValueError):
            out.pop("radar_opacity")
    return out


def settings_doc(cfg, online_display=None) -> dict:
    doc = {"settings": shared_settings(cfg),
           "nmea_sources": network_inputs(cfg.settings.get("nmea_sources")),
           "online_feeds": [dict(f) for f in cfg.settings.get("online_feeds") or []]}
    d = clean_display(online_display)
    if d:
        doc["online_display"] = d
    return doc


def local_waypoints(cfg) -> list[dict]:
    p = cfg.data_dir / "waypoints.csv"
    if not p.is_file():
        return []
    try:
        with open(p, newline="", encoding="utf-8-sig") as fh:
            return [r for r in csv.DictReader(fh) if any((v or "").strip() for v in r.values())]
    except (OSError, csv.Error):
        return []


def waypoints_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(WAYPOINT_COLS)
    for r in rows:
        w.writerow([r.get(c, "") or "" for c in WAYPOINT_COLS])
    return "﻿" + out.getvalue()


def local_overlays(cfg) -> dict[str, Path]:
    d = cfg.overlays_dir
    if not d.is_dir():
        return {}
    return {p.name: p for p in sorted(d.iterdir())
            if p.is_file() and p.suffix.lower() in OVERLAY_EXT and not p.name.startswith(("Survey - ", "."))}


def local_routes(cfg) -> dict[str, Path]:
    d = cfg.routes_dir
    return {p.name: p for p in sorted(d.glob("*.gpx")) if p.is_file()} if d.is_dir() else {}


def entries(cfg, include=OPTIONAL, min_spyhop=None, online_display=None, info=True) -> dict[str, bytes]:
    """This computer's new-style pack files, as {path in the pack: bytes}."""
    include = [k for k in OPTIONAL if k in (include or ())]
    out: dict[str, bytes] = {}
    if info:
        out[INFO] = json.dumps({"format": PACK_FORMAT, "min_spyhop": min_spyhop or FORMAT_MIN,
                                "made_with": __version__, "includes": include}, indent=2).encode()
    doc = settings_doc(cfg, online_display)
    out[SETTINGS] = json.dumps(doc, indent=2).encode()
    for f in doc["online_feeds"]:
        p = feeds.cache_path(cfg, f.get("id", ""))
        if p.is_file():
            out[f"feeds/{p.name}"] = p.read_bytes()
    if "waypoints" in include:
        out[WAYPOINTS] = waypoints_csv(local_waypoints(cfg)).encode("utf-8")
    if "routes" in include:
        out.update({f"routes/{n}": p.read_bytes() for n, p in local_routes(cfg).items()})
    if "overlays" in include:
        out.update({f"overlays/{n}": p.read_bytes() for n, p in local_overlays(cfg).items()})
    return out


# ------------------------------------------------------------------ reading a pack
def is_part(name: str) -> bool:
    if name in (INFO, SETTINGS, WAYPOINTS):
        return True
    top, _, rest = name.partition("/")
    return top in ("feeds", "routes", "overlays") and bool(rest) and "/" not in rest


def empty(pack: dict):
    pack.update(info=None, settings=None, feed_data={}, waypoints=None, routes=None, overlays=None)


def read_entry(pack: dict, name: str, b: bytes, text_of) -> None:
    """Add one file of a pack (is_part(name) is true) to the pack dict, or note a problem."""
    probs = pack["problems"]
    top, _, rest = name.partition("/")
    try:
        if name == INFO:
            d = json.loads(text_of(b, name))
            if not isinstance(d, dict):
                raise ValueError("not an object")
            pack["info"] = d
            need = version_tuple(d.get("min_spyhop"))
            if d.get("min_spyhop") and not need:
                probs.append(f"{INFO}: the minimum Spyhop version “{d.get('min_spyhop')}” isn't a version number.")
            elif need and need > version_tuple(__version__):
                probs.append(f"This pack needs Spyhop {d['min_spyhop']} or newer, and this computer has {__version__}. "
                             f"Update Spyhop first (Settings → About), then use the pack.")
        elif name == SETTINGS:
            pack["settings"] = _read_settings(json.loads(text_of(b, name)), probs)
        elif name == WAYPOINTS:
            pack["waypoints"] = _read_waypoints(text_of(b, name), probs)
        elif top == "feeds":
            if rest.endswith(".geojson"):
                d = json.loads(text_of(b, name))
                if isinstance(d, dict) and isinstance(d.get("features"), list):
                    pack["feed_data"][rest[:-8]] = b
        elif top == "routes":
            if not rest.lower().endswith(".gpx") or rest.startswith("."):
                pack["ignored"].append(name)
                return
            t = text_of(b, name)
            if "<gpx" not in t[:2000]:
                probs.append(f"{name} isn't a GPX file.")
                return
            pack["routes"] = {**(pack["routes"] or {}), rest: b}
        elif top == "overlays":
            if Path(rest).suffix.lower() not in OVERLAY_EXT or rest.startswith("."):
                pack["ignored"].append(name)
                return
            pack["overlays"] = {**(pack["overlays"] or {}), rest: b}
    except ValueError as e:
        probs.append(f"{name} can't be read ({e}).")


def _read_settings(d, probs) -> dict:
    if not isinstance(d, dict):
        raise ValueError("not an object")
    out = {"settings": {}, "nmea_sources": None, "online_feeds": [], "online_display": None}
    for k, v in (d.get("settings") or {}).items():
        if k in SHARED_SETTINGS:
            out["settings"][k] = v
    if isinstance(d.get("nmea_sources"), list):
        out["nmea_sources"] = network_inputs(d["nmea_sources"])
    for f in d.get("online_feeds") or []:
        try:
            out["online_feeds"].append(feeds.clean(f))
        except (feeds.FeedError, AttributeError) as e:
            probs.append(f"{SETTINGS}: the map feed “{(f or {}).get('name', '?')}”: {e}")
    out["online_display"] = clean_display(d.get("online_display"))
    return out


def _read_waypoints(text: str, probs) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and not {"Lat", "Lon"} <= set(rows[0].keys()):
        probs.append(f"{WAYPOINTS} needs Lat and Lon columns.")
        return []
    out = []
    for r in rows:
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if not r.get("Lat") or not r.get("Lon"):
            continue
        out.append({c: r.get(c, "") for c in WAYPOINT_COLS})
    return out


# ------------------------------------------------------------------ comparing
def _fmt(v):
    return "on" if v is True else "off" if v is False else ("—" if v in (None, "") else str(v))


def _wp_key(r):
    n = (r.get("Name") or "").strip().lower()
    return ("name", n) if n else ("pos", (r.get("Lat") or "").strip(), (r.get("Lon") or "").strip())


def _feed_url(f):
    try:
        return feeds.clean_url(f.get("url", ""))
    except feeds.FeedError:
        return str(f.get("url", ""))


def compare(cfg, pack: dict) -> list[dict]:
    """Rows for configpack.compare(). Statuses: new, changed, same, kept (here already and
    different: this computer's is kept), removed (only when restoring a backup)."""
    out = []
    s = pack.get("settings")
    if s:
        here = cfg.settings
        diffs = [f"{SHARED_SETTINGS[k]}: {_fmt(here.get(k))} → {_fmt(v)}"
                 for k, v in s["settings"].items() if here.get(k) != v]
        out.append({"file": "Settings (clock, units, tracking, keep awake, NMEA log)", "status": "changed" if diffs else "same",
                    "detail": "; ".join(diffs), "unit": "settings"})
        if s["nmea_sources"] is not None:
            mine = network_inputs(here.get("nmea_sources"))
            desc = lambda L: ", ".join(f"{x['type'].upper()} {x.get('host', '') + ':' if x.get('host') else ''}{x.get('port', '')}"  # noqa: E731
                                       + ("" if x.get("enabled", True) else " (off)") for x in L) or "none"
            same = [_norm_src(x) for x in mine] == [_norm_src(x) for x in s["nmea_sources"]]
            out.append({"file": "GPS / NMEA network inputs (UDP, TCP, gpsd)", "status": "same" if same else "changed",
                        "detail": "" if same else f"{desc(mine)} → {desc(s['nmea_sources'])}; serial ports are left as they are",
                        "unit": "settings"})
        mine = {_feed_url(f): f for f in here.get("online_feeds") or []}
        for f in s["online_feeds"]:
            m = mine.get(_feed_url(f))
            st = "new" if not m else "same" if (m.get("name"), m.get("color"), m.get("refresh_min")) == (f["name"], f["color"], f["refresh_min"]) else "kept"
            out.append({"file": f"Map feed: {f['name']}", "status": st, "unit": "feed",
                        "detail": "" if st != "kept" else f"this computer calls it “{m.get('name')}” ({m.get('color')}); kept"})
    if pack.get("waypoints") is not None:
        mine = {_wp_key(r): r for r in local_waypoints(cfg)}
        new = [r for r in pack["waypoints"] if _wp_key(r) not in mine]
        kept = [r for r in pack["waypoints"] if _wp_key(r) in mine
                and (mine[_wp_key(r)].get("Lat"), mine[_wp_key(r)].get("Lon")) != (r.get("Lat"), r.get("Lon"))]
        detail = []
        if new:
            detail.append(', '.join(r['Name'] or '(no name)' for r in new[:6]) + (f" and {len(new) - 6} more" if len(new) > 6 else ""))
        if kept:
            detail.append(f"{len(kept)} with the same name here in another place, kept as they are here ({', '.join(r['Name'] for r in kept[:4])})")
        out.append({"file": WAYPOINTS, "status": "new" if new else "kept" if kept else "same", "unit": "waypoints",
                    "detail": "; ".join(detail), "here": len(mine), "pack": len(pack["waypoints"]), "add": len(new)})
    for key, local in (("routes", local_routes(cfg)), ("overlays", local_overlays(cfg))):
        for fn, b in sorted((pack.get(key) or {}).items()):
            p = local.get(fn)
            st = "new" if not p else "same" if p.read_bytes() == b else "kept"
            out.append({"file": f"{key}/{fn}", "status": st, "unit": key[:-1],
                        "detail": "different here; this computer’s copy is kept" if st == "kept" else ""})
    undo = pack.get("_undo")
    if undo:
        for line in undo_rows(cfg, undo):
            out.append(line)
    return out


def _norm_src(x):
    return {k: v for k, v in x.items() if k != "session"}


def undo_rows(cfg, undo: dict) -> list[dict]:
    rows = []
    ids = set(undo.get("waypoints") or [])
    if ids:
        n = sum(1 for r in local_waypoints(cfg) if r.get("RowID") in ids)
        if n:
            rows.append({"file": WAYPOINTS, "status": "removed", "unit": "waypoints",
                         "detail": f"{n} added by the pack used after this backup"})
    for key, local in (("routes", local_routes(cfg)), ("overlays", local_overlays(cfg))):
        for fn in undo.get(key) or []:
            if fn in local:
                rows.append({"file": f"{key}/{fn}", "status": "removed", "unit": key[:-1],
                             "detail": "added by the pack used after this backup"})
    mine = {f.get("id"): f for f in cfg.settings.get("online_feeds") or []}
    for fid in undo.get("feeds") or []:
        if fid in mine:
            rows.append({"file": f"Map feed: {mine[fid].get('name')}", "status": "removed", "unit": "feed",
                         "detail": "added by the pack used after this backup"})
    return rows


# ------------------------------------------------------------------ applying
def apply(cfg, pack: dict, write) -> dict:
    """Use the pack's settings, feeds, routes and overlays (files and settings.json). Waypoints are
    returned for the caller to add (the recorder holds that table). Returns what was added:
    {settings: bool, inputs: bool, feeds: [ids], routes: [files], overlays: [files], waypoints: [rows],
     remove_waypoints: [RowIDs]}."""
    done = {"settings": False, "inputs": False, "feeds": [], "routes": [], "overlays": [], "waypoints": [],
            "remove_waypoints": [], "display": None}
    s = pack.get("settings")
    if s:
        upd = {k: v for k, v in s["settings"].items() if cfg.settings.get(k) != v}
        if s["nmea_sources"] is not None:
            mine = list(cfg.settings.get("nmea_sources") or [])
            at = next((i for i, x in enumerate(mine) if x.get("type") in NETWORK_INPUTS), None)
            rest = [x for x in mine if x.get("type") not in NETWORK_INPUTS]
            at = len(rest) if at is None else sum(1 for x in mine[:at] if x.get("type") not in NETWORK_INPUTS)
            new = rest[:at] + [dict(x) for x in s["nmea_sources"]] + rest[at:]
            if new != mine:
                upd["nmea_sources"] = new
                done["inputs"] = True
        feeds_now = [dict(f) for f in cfg.settings.get("online_feeds") or []]
        urls = {_feed_url(f) for f in feeds_now}
        for f in s["online_feeds"]:
            if _feed_url(f) in urls:
                continue
            f = dict(f)
            if any(x.get("id") == f["id"] for x in feeds_now):
                f["id"] = feeds.clean({**f, "id": ""})["id"]
            base, n = f["name"], 2
            while any(x.get("name", "").lower() == f["name"].lower() for x in feeds_now):
                f["name"] = f"{base} ({n})"
                n += 1
            data = pack["feed_data"].get(pack_id_of(pack, f))
            if data and not feeds.cache_path(cfg, f["id"]).exists():
                write(feeds.cache_path(cfg, f["id"]), data)
            feeds_now.append(f)
            urls.add(_feed_url(f))
            done["feeds"].append(f["id"])
        if done["feeds"]:
            upd["online_feeds"] = feeds_now
        if s.get("online_display"):
            import time
            done["display"] = upd["online_display"] = {**s["online_display"], "stamp": f"{time.time():.3f}"}
        done["settings"] = bool(set(upd) - {"nmea_sources", "online_feeds", "online_display"})
        if upd:
            cfg.save_settings(upd)
    if pack.get("waypoints"):
        mine = {_wp_key(r) for r in local_waypoints(cfg)}
        for r in pack["waypoints"]:
            if _wp_key(r) not in mine:
                done["waypoints"].append(dict(r))
                mine.add(_wp_key(r))
    for key, local in (("routes", local_routes(cfg)), ("overlays", local_overlays(cfg))):
        d = cfg.routes_dir if key == "routes" else cfg.overlays_dir
        for fn, b in (pack.get(key) or {}).items():
            if fn not in local and not (d / fn).exists():
                write(d / fn, b)
                done[key].append(fn)
    undo = pack.get("_undo")
    if undo:
        done["remove_waypoints"] = list(undo.get("waypoints") or [])
        for key in ("routes", "overlays"):
            d = cfg.routes_dir if key == "routes" else cfg.overlays_dir
            for fn in undo.get(key) or []:
                p = d / Path(fn).name
                if p.is_file():
                    p.unlink()
        gone = set(undo.get("feeds") or [])
        if gone:
            keep = [f for f in cfg.settings.get("online_feeds") or [] if f.get("id") not in gone]
            cfg.save_settings({"online_feeds": keep})
            for fid in gone:
                feeds.cache_path(cfg, fid).unlink(missing_ok=True)
    return done


def display_summary(pack) -> dict | None:
    """The pack's online_display, with the names of the feeds it switches on (for the check result)."""
    s = pack.get("settings") or {}
    d = s.get("online_display")
    if not d:
        return None
    names = {_feed_url(f): f["name"] for f in s.get("online_feeds") or []}
    return {**d, "feed_names": [names.get(u, u) for u in d.get("feeds") or []]}


def pack_id_of(pack, f):
    """The feed's id in the pack (its saved copy is feeds/<that id>.geojson), before any renumbering."""
    for x in (pack.get("settings") or {}).get("online_feeds", []):
        if _feed_url(x) == _feed_url(f):
            return x["id"]
    return f["id"]


def add_waypoints_to_file(cfg, rows: list[dict]) -> list[str]:
    """Without a recorder (tests, a pack used with Spyhop not running): append to waypoints.csv."""
    import uuid
    if not rows:
        return []
    p = cfg.data_dir / "waypoints.csv"
    header = schema.headers("marks")
    existing = local_waypoints(cfg)
    ids = []
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(header)
    for r in existing:
        w.writerow([r.get(c, "") or "" for c in header])
    for r in rows:
        rid = uuid.uuid4().hex[:12]
        ids.append(rid)
        w.writerow([rid if c == "RowID" else r.get(c, "") for c in header])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("﻿" + out.getvalue(), encoding="utf-8")
    return ids
