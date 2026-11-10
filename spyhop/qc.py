"""Quality-control report for the open survey.

run_qc(recorder) checks the survey details, that required fields are filled in,
that values are valid, and that they are plausible. It returns a list of issues,
each with a level:

  error    must be fixed: a required field is blank, or a value is impossible or not allowed
  warning  probably wrong: worth checking (a typo in a position, an unusually large group…)
  info     not wrong, but worth a look (sightings off effort, long watches…)

The thresholds are in LIMITS. Nothing here changes any data.
"""
from __future__ import annotations

import json
import re
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import geo, resights, schema

LIMITS = {
    "max_sighting_nm": 10.0,        # animals further than this from the vessel
    "max_group": 500,               # a larger Num is flagged
    "pos_vs_track_nm": 0.5,         # a row's vessel position this far from the trackline
    "max_speed_kn": 30.0,           # faster than this between track points is a GPS jump
    "max_resight_kn": 30.0,         # animals swimming faster than this between a sighting and its next resight
    "track_gap_min": 10.0,          # no track points for this long while recording
    "conditions_gap_factor": 1.5,   # on effort with no Effort row for this × the reminder interval
    "max_watch_h": 2.0,             # an observer on watch this long without a break
    "max_seastate_on": 5,           # on effort in a higher sea state
    "visibility_margin": 1.0,       # a sighting further than visibility × this is flagged
    "land_buffer_km": 0.5,          # only flag points this far inside the coastline
    "future_min": 5,                # times this far past the computer's clock
}

# columns that may be left blank (everything else visible in the table is required)
OPTIONAL = {
    "sightings": {"Behaviors", "Bearing", "BrgRef", "Distance", "DistUnit", "Altitude", "ResightOf", "FieldID", "Notes"},
    "effort": {"Notes", "GlareStart", "GlareEnd", "GlareRef"},
    "events": {"ID", "Notes"},
}
# survey details that may be blank (platform altitude matters only for reticle distances: checked there)
META_OPTIONAL = {"platform_altitude_ft", "survey_notes"}
# Start and End rows need only their time and position
EFFORT_START_END_REQUIRED = {"DateTime", "Lat", "Lon", "Effort"}
NOT_DATA = {"RowID", "Map", "VesHdg"}          # internal / display columns

M_PER_NM = 1852.0


class Report:
    def __init__(self):
        self.issues: list[dict] = []

    def add(self, level, check, message, tab="", row=None, column="", label="", fix=None):
        self.issues.append({"level": level, "check": check, "message": message, "tab": tab,
                            "row_id": (row or {}).get("RowID", ""), "column": column,
                            "label": label, "time": (row or {}).get("DateTime", ""), "fix": fix})


def _t(s):
    try:
        t = datetime.fromisoformat(s)
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _pos(r, la, lo):
    a, b = _num(r.get(la)), _num(r.get(lo))
    return (a, b) if a is not None and b is not None else None


def _fmt_dur(sec: float) -> str:
    m = int(round(sec / 60))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


# ----------------------------------------------------------------- coastline
_LAND = None


def _land():
    """Natural Earth 1:10m land polygons as [(bbox, [rings])], decoded once."""
    global _LAND
    if _LAND is not None:
        return _LAND
    p = Path(__file__).parent / "web" / "vendor" / "land-10m.json"
    try:
        topo = json.loads(p.read_text())
    except (OSError, ValueError):
        _LAND = []
        return _LAND
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def ring(idx):
        out = []
        for i in idx:
            a = arcs[i] if i >= 0 else arcs[~i][::-1]
            out.extend(a if not out else a[1:])
        return out

    polys = []
    for g in topo["objects"]["land"]["geometries"]:
        shapes = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        for poly in shapes:
            rings = [ring(r) for r in poly]
            xs = [p[0] for p in rings[0]]
            ys = [p[1] for p in rings[0]]
            polys.append(((min(xs), min(ys), max(xs), max(ys)), rings))
    _LAND = polys
    return _LAND


def _in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def _dist_to_ring_km(lat, lon, ring):
    """Approximate distance from a point to a ring's edges (equirectangular, fine for < 50 km)."""
    k = math.cos(math.radians(lat))
    best = float("inf")
    px, py = lon * k, lat
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if abs(y1 - lat) > 1 and abs(y2 - lat) > 1:
            continue
        ax, ay, bx, by = x1 * k, y1, x2 * k, y2
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        u = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
        d = math.hypot(px - (ax + u * dx), py - (ay + u * dy))
        best = min(best, d)
    return best * 111.32


def on_land(lat, lon, buffer_km=LIMITS["land_buffer_km"]) -> bool:
    """True if the point is on land by the 1:10m coastline, and more than buffer_km from it."""
    for (x0, y0, x1, y1), rings in _land():
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        if _in_ring(lon, lat, rings[0]) and not any(_in_ring(lon, lat, h) for h in rings[1:]):
            near = min(_dist_to_ring_km(lat, lon, r) for r in rings)
            return near > buffer_km
    return False


PLACEHOLDER_OBSERVERS = {"NA", "N/A", "NONE", "-", "—"}


def is_placeholder_observer(name: str, full_name: str = "") -> bool:
    """'NA' (None) and the like stand for an empty watch position, not an observer."""
    return str(name).strip().upper() in PLACEHOLDER_OBSERVERS or str(full_name).strip().lower() == "none"


def _setting_num(cfg, key, default):
    try:
        return float(cfg.settings.get(key, default))
    except (TypeError, ValueError):
        return default


def visibility_nm(v) -> float | None:
    """Upper limit of a visibility value in nm: '1-2 nm' → 2, '<0.5 nm' → 0.5, '>10 nm' → None (no limit).
    Plain numbers and km / m / mi values (custom lists) are understood too."""
    if not v:
        return None
    t = str(v).strip().lower().replace(",", ".")
    if t.startswith(">"):
        return None
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if not nums:
        return None
    unit = "nm"
    for u in ("km", "nm", "mi", "m"):
        if re.search(rf"\d\s*{u}\b", t) or t.endswith(u):
            unit = u
            break
    try:
        return geo.to_meters(max(nums), unit) / M_PER_NM
    except (KeyError, ValueError):
        return None


# ----------------------------------------------------------------- the checks
def run_qc(rec) -> dict:
    if rec.survey is None:
        raise ValueError("Open a survey to check it.")
    L = LIMITS
    rep = Report()
    add = rep.add
    cfg = rec.cfg
    now = datetime.now(timezone.utc)
    S = rec.tables["sightings"].rows
    E = rec.tables["effort"].rows
    V = rec.tables["events"].rows
    T = rec.track.points if rec.track else []

    def lab(tab, r, i):
        if tab == "sightings":
            return f"Sighting {r.get('SightNo') or '?'}"
        if tab == "events":
            return f"Event {r.get('EventNo') or '?'}"
        return f"Effort row {i + 1}" + (f" ({r.get('Effort')})" if r.get("Effort") else "")

    # ---- survey details
    meta = rec.read_meta()
    blank = [(k, label) for k, label, _ in schema.SURVEY_META
             if k not in META_OPTIONAL and not (meta.get(k) or "").strip()]
    if blank:
        add("error", "Survey details complete",
            f"{', '.join(l for _, l in blank)} {'is' if len(blank) == 1 else 'are'} blank. Fill {'it' if len(blank) == 1 else 'them'} in under Survey details.",
            "survey", column=blank[0][0], label="Survey details")

    # ---- survey start/end and times
    start_t = _t(E[0]["DateTime"]) if E and E[0].get("Effort") == "Start" else None
    end_t = _t(E[-1]["DateTime"]) if E and E[-1].get("Effort") == "End" else None
    if not E or E[0].get("Effort") != "Start":
        add("error", "Effort starts with Start", "The first Effort row should be Start.", "effort", E[0] if E else None,
            "Effort", "Effort row 1")
    if end_t is None:
        add("warning", "Survey ended", "The survey has no End row yet. Use End Survey… when the survey is finished.",
            "survey", label="Survey")

    for tab, rows in (("sightings", S), ("effort", E), ("events", V)):
        cols = [c for c in schema.TABS[tab]["columns"] if c["key"] not in NOT_DATA]
        last_t = None
        for i, r in enumerate(rows):
            name = lab(tab, r, i)
            # required fields
            if tab == "effort" and r.get("Effort") in ("Start", "End", "ERROR"):
                need = EFFORT_START_END_REQUIRED
            else:
                need = {c["key"] for c in cols} - OPTIONAL[tab]
            for c in cols:
                v = (r.get(c["key"]) or "").strip()
                if c["key"] in need and v == "":
                    add("error", "Required fields filled", f"{c['label']} is blank.", tab, r, c["key"], name)
                    continue
                if v == "":
                    continue
                # values allowed by the column
                if c["type"] in ("choice", "multi") and c["list"]:
                    allowed = rec.list_values(c["list"]) or []
                    vals = [x.strip() for x in v.split(";")] if c["type"] == "multi" else [v]
                    for x in vals:
                        if x and x not in allowed:
                            fixed = c["list"] in schema.FIXED_LISTS
                            add("error" if fixed else "warning", "Values from the lists",
                                f"{c['label']} “{x}” isn't in the {'allowed values' if fixed else c['list'] + '.csv list'}.",
                                tab, r, c["key"], name)
                elif c["type"] in ("lat", "lon"):
                    n = _num(v)
                    lim = 90 if c["type"] == "lat" else 180
                    if n is None or abs(n) > lim:
                        add("error", "Valid positions", f"{c['label']} “{v}” isn't a valid position.", tab, r, c["key"], name)
                elif c["type"] in ("int", "float", "seq"):
                    if _num(v) is None and not (c.get("na") and v == "NA"):
                        add("error", "Valid numbers", f"{c['label']} “{v}” isn't a number.", tab, r, c["key"], name)
                elif c["type"] == "datetime":
                    t = _t(v)
                    if t is None:
                        add("error", "Valid times", f"Time “{v}” can't be read.", tab, r, c["key"], name)
            # times
            t = _t(r.get("DateTime"))
            if t is None:
                continue
            if t > now + timedelta(minutes=L["future_min"]):
                add("error", "Times not in the future", "The time is later than now — check the date and time.", tab, r, "DateTime", name)
            if start_t and t < start_t and not (tab == "effort" and i == 0):
                add("warning", "Times within the survey", "Recorded before the survey's Start.", tab, r, "DateTime", name)
            if end_t and t > end_t and not (tab == "effort" and i == len(rows) - 1):
                add("warning", "Times within the survey", "Recorded after the survey's End.", tab, r, "DateTime", name)
            if last_t and t < last_t - timedelta(seconds=1):
                add("warning", "Rows in time order", "Earlier than the row above it — check the time (or the order the rows were entered).",
                    tab, r, "DateTime", name)
            last_t = t

    # ---- numbering
    for tab, rows, key, word in (("sightings", S, "SightNo", "Sighting"), ("events", V, "EventNo", "Event")):
        seen = {}
        for i, r in enumerate(rows):
            n = (r.get(key) or "").strip()
            if n and n in seen:
                add("error", "Unique numbers", f"{schema.column(tab, key)['label']} {n} is used twice (also on row {seen[n] + 1}).", tab, r, key, lab(tab, r, i))
            seen.setdefault(n, i)
        nums = sorted(int(k) for k in seen if k.isdigit())
        missing = sorted(set(range(1, nums[-1] + 1)) - set(nums)) if nums else []
        if missing:
            add("info", "Unique numbers", f"{word} numbers skip {', '.join(map(str, missing[:10]))}{'…' if len(missing) > 10 else ''} "
                "(fine if rows were deleted on purpose).", tab, label=f"{word}s")

    # ---- glare: where it starts and ends, and their reference (0.37)
    for i, r in enumerate(E):
        gs, ge, gref = (str(r.get(k) or "").strip() for k in ("GlareStart", "GlareEnd", "GlareRef"))
        if not (gs or ge or gref):
            continue
        name = lab("effort", r, i)
        if bool(gs) != bool(ge):
            add("warning", "Glare bearings", "Give both Gstart and Gend (or neither).", "effort", r, "GlareEnd" if gs else "GlareStart", name)
        if (gs or ge) and not gref:
            add("warning", "Glare bearings", "Gstart / Gend have no Gref (M, T, R or C).", "effort", r, "GlareRef", name)
        lo, hi = (1, 12) if gref == "C" else (0, 360)
        for key, v in (("GlareStart", gs), ("GlareEnd", ge)):
            n = _num(v)
            if v and n is not None and not lo <= n <= hi:
                add("error", "Glare bearings", f"{schema.column('effort', key)['label']} {v} is outside {lo}–{hi}"
                    + (" (a clock bearing)." if gref == "C" else "°."), "effort", r, key, name)

    # ---- effort, conditions and observers
    eff = []                                    # (t0, t1, row) in time order
    rows_t = sorted(((_t(r.get("DateTime")), i, r) for i, r in enumerate(E)), key=lambda x: (x[0] is None, x[0] or now, x[1]))
    rows_t = [x for x in rows_t if x[0] is not None]
    for k, (t0, i, r) in enumerate(rows_t):
        t1 = rows_t[k + 1][0] if k + 1 < len(rows_t) else (end_t or now)
        eff.append((t0, t1, r, i))

    def state_at(t):
        cur = None
        for t0, t1, r, i in eff:
            if t0 <= t:
                cur = r
            else:
                break
        return cur

    remind_min = float(cfg.settings.get("effort_reminder_min", 30) or 30)
    # "NA" (None) is a placeholder for an empty position, not a person: it can fill several
    # positions at once and isn't counted as on watch
    full = {o.get("name", ""): o.get("full_name", "") for o in cfg.lists.get("observers", [])}
    def person(o):
        return bool(o) and not is_placeholder_observer(o, full.get(o, ""))
    watch: dict[str, datetime] = {}             # observer -> on watch since (while effort ON)
    watch_flagged = set()
    for t0, t1, r, i in eff:
        name = lab("effort", r, i)
        st = r.get("Effort")
        obs = [(pos, r.get(pos, "").strip()) for pos in ("Port", "Recorder", "Starboard")]
        names = [o for _, o in obs if person(o)]
        dups = {o for o in names if names.count(o) > 1}
        for o in dups:
            add("error", "Observers in one position at a time", f"{o} is in more than one position (Port / Recorder / Stbd).",
                "effort", r, "Port", name)
        if schema.is_on(st):
            gap = (t1 - t0).total_seconds() / 60
            if gap > remind_min * L["conditions_gap_factor"]:
                add("warning", "Conditions recorded regularly",
                    f"On effort for {_fmt_dur(gap * 60)} after this row with no new Effort row (the reminder is every {remind_min:g} min).",
                    "effort", r, "DateTime", name)
            ss = _num(r.get("SeaState"))
            if ss is not None and ss > L["max_seastate_on"]:
                add("info", "Survey conditions", f"On effort in sea state {r.get('SeaState')} — check this is within your protocol.",
                    "effort", r, "SeaState", name)
            vis = visibility_nm(r.get("Visibility"))
            if vis is not None and vis <= 0.5:
                add("info", "Survey conditions", "On effort with visibility under 0.5 nm — check this is within your protocol.",
                    "effort", r, "Visibility", name)
            on_names = set(names)
            for o in list(watch):
                if o not in on_names:
                    del watch[o]
            for o in on_names:
                watch.setdefault(o, t0)
                hours = (t1 - watch[o]).total_seconds() / 3600
                if hours > L["max_watch_h"] and o not in watch_flagged:
                    watch_flagged.add(o)
                    add("info", "Observer rest", f"{o} was on watch for {_fmt_dur(hours * 3600)} without a break "
                        f"(from {watch[o].astimezone().strftime('%H:%M')}).", "effort", r, "Port", name)
        else:
            watch.clear()

    # ---- positions against the trackline, and speeds along it
    tp = []
    for p in T:
        t, la, lo = _t(p.get("DateTime")), _num(p.get("Lat")), _num(p.get("Lon"))
        if t and la is not None and lo is not None:
            tp.append((t, la, lo))
    tp.sort()

    def track_pos(t):
        """Track position at time t, interpolated, if there are track points within 10 min either side."""
        if not tp:
            return None
        lo_i, hi_i = 0, len(tp) - 1
        if t < tp[0][0] or t > tp[-1][0]:
            return None
        while hi_i - lo_i > 1:
            mid = (lo_i + hi_i) // 2
            if tp[mid][0] <= t:
                lo_i = mid
            else:
                hi_i = mid
        a, b = tp[lo_i], tp[hi_i]
        span = (b[0] - a[0]).total_seconds()
        if span > 600:
            return None
        f = 0 if span == 0 else (t - a[0]).total_seconds() / span
        return a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f

    interval = float(cfg.settings.get("tracking_interval", 10) or 10)
    max_kn = _setting_num(cfg, "track_break_kn", L["max_speed_kn"]) or L["max_speed_kn"]
    gap_s = _setting_num(cfg, "track_break_gap_s", 0)
    gap_limit = max(gap_s if gap_s > 0 else L["track_gap_min"] * 60, interval * 5)
    tz = rec.tz()

    def broken(t0, t1):
        """An ERROR row already marks this stretch (in force at t0, or added within it)."""
        if (state_at(t0) or {}).get("Effort") == "ERROR":
            return True
        return any(a < t1 and a >= t0 and r.get("Effort") == "ERROR" for a, _, r, _ in eff)

    def speed_kn(i, j):
        dt = (tp[j][0] - tp[i][0]).total_seconds()
        d = geo.haversine_m(tp[i][1], tp[i][2], tp[j][1], tp[j][2]) / M_PER_NM
        return d, dt, (d / (dt / 3600) if dt > 0 else (math.inf if d > 0.05 else 0))

    jumps = [i for i in range(len(tp) - 1) if speed_kn(i, i + 1)[2] > max_kn and speed_kn(i, i + 1)[0] > 0.05]
    paired, skip = {}, set()
    for k, i in enumerate(jumps):
        if i in skip:
            continue
        # the GPS jumped away and came back: one break from before the first jump to after the second
        for j in jumps[k + 1:]:
            if (tp[j][0] - tp[i][0]).total_seconds() > 1800:
                break
            if speed_kn(i, j + 1)[2] <= max_kn:
                paired[i] = j
                skip.add(j)
                break
    for i in range(len(tp) - 1):
        (t0, a0, o0), (t1, a1, o1) = tp[i], tp[i + 1]
        dt = (t1 - t0).total_seconds()
        d_nm = geo.haversine_m(a0, o0, a1, o1) / M_PER_NM
        if i in skip:
            continue
        st = (state_at(t0) or {}).get("Effort")
        can_fix = schema.is_on(st) or st in ("OFF", "Start", "")
        if i in paired:
            j = paired[i]
            tb = tp[j + 1][0]
            if broken(t0, tb):
                continue
            away = (tb - t0).total_seconds()
            add("warning", "Trackline plausible", f"The track jumps {d_nm:.2f} nm away at {t0.astimezone(tz).strftime('%H:%M:%S')} "
                f"and back {f'{away:.0f} s' if away < 120 else _fmt_dur(away)} later — a GPS glitch? Fix adds an ERROR row to the Effort table for that stretch.",
                "track", label="Trackline", fix={"kind": "track_break", "t0": t0.isoformat(), "t1": tb.isoformat()} if can_fix else None)
            continue
        if broken(t0, t1):
            continue
        fix = {"kind": "track_break", "t0": t0.isoformat(), "t1": t1.isoformat()}
        if i in jumps:
            add("warning", "Trackline plausible", f"The track jumps {d_nm:.2f} nm in {dt:.0f} s ({d_nm / (dt / 3600) if dt > 0 else 0:.0f} kn) "
                f"at {t1.astimezone(tz).strftime('%H:%M:%S')} — a GPS glitch? Fix adds an ERROR row to the Effort table for the jump.",
                "track", label="Trackline", fix=fix if can_fix else None)
        elif dt > gap_limit:
            if schema.is_on(st) or st in ("OFF", "Start"):
                add("warning" if schema.is_on(st) else "info", "Trackline plausible",
                    f"No track points for {_fmt_dur(dt)} from {t0.astimezone(tz).strftime('%H:%M:%S')} "
                    f"({'on' if schema.is_on(st) else 'off'} effort) — was tracking paused or the GPS lost?"
                    + (" Fix adds an ERROR row to the Effort table for the gap." if schema.is_on(st) else ""),
                    "track", label="Trackline", fix=fix if schema.is_on(st) else None)

    def check_vessel_pos(tab, r, name, la, lo):
        p = _pos(r, la, lo)
        t = _t(r.get("DateTime"))
        if not p or not t:
            return
        q = track_pos(t)
        if q:
            d = geo.haversine_m(p[0], p[1], q[0], q[1]) / M_PER_NM
            if d > L["pos_vs_track_nm"]:
                add("warning", "Positions match the trackline",
                    f"{la}/{lo} is {d:.1f} nm from the trackline at this time — a typing mistake?", tab, r, la, name)

    land_points = []                             # (tab, row, name, lat col, lon col)
    for i, r in enumerate(S):
        name = lab("sightings", r, i)
        check_vessel_pos("sightings", r, name, "Lat", "Lon")
        land_points.append(("sightings", r, name, "SigLat", "SigLon"))
    for i, r in enumerate(E):
        if r.get("Effort") not in ("Start", "End", "ERROR"):   # the boat may be at the dock; ERROR marks bad GPS
            name = lab("effort", r, i)
            check_vessel_pos("effort", r, name, "Lat", "Lon")
            land_points.append(("effort", r, name, "Lat", "Lon"))
    for i, r in enumerate(V):
        name = lab("events", r, i)
        land_points.append(("events", r, name, "Lat", "Lon"))
    for tab, r, name, la, lo in land_points:
        p = _pos(r, la, lo)
        if p and on_land(*p):
            add("warning", "Positions at sea", f"{la}/{lo} is on land — check the position.", tab, r, la, name)

    # ---- sightings
    species = {x["name"]: x for x in cfg.lists.get("species", [])}
    prev = []
    rs_index = resights.by_sightno(S)
    for i, r in enumerate(S):
        name = lab("sightings", r, i)
        # resights: linked to a sighting that exists, after it, of the same species
        orig = resights.original_of(r, S, rs_index)
        resight = orig is not r
        if r.get("ResightOf") and not resight:
            add("warning", "Resights linked", f"ResNo {r['ResightOf']}: there is no such sighting (deleted or renumbered?), "
                "so this row is counted as a sighting of its own.", "sightings", r, "ResightOf", name)
        if resight:
            t_r, t_o = _t(r.get("DateTime")), _t(orig.get("DateTime"))
            if t_r and t_o and t_r < t_o:
                add("warning", "Resights linked", f"Timed before sighting {orig.get('SightNo')}, the first sighting it is a resight of.",
                    "sightings", r, "DateTime", name)
            if r.get("Species") and orig.get("Species") and r["Species"] != orig["Species"]:
                add("warning", "Resights linked", f"Species {r['Species']}, but sighting {orig.get('SightNo')} (its first sighting) is {orig['Species']}.",
                    "sightings", r, "Species", name)
        n, calves = _num(r.get("Count")), _num(r.get("Calves"))
        if n is not None:
            if n < 1 or n != int(n):
                add("error", "Plausible numbers", "Num should be a whole number of at least 1.", "sightings", r, "Count", name)
            elif n > L["max_group"]:
                add("warning", "Plausible numbers", f"Num {n:g} is unusually large — check it.", "sightings", r, "Count", name)
        if calves is not None:
            if calves < 0 or calves != int(calves):
                add("error", "Plausible numbers", "Calves should be a whole number, 0 or more.", "sightings", r, "Calves", name)
            elif n is not None and calves > n:
                add("error", "Plausible numbers", f"More calves ({calves:g}) than animals (Num {n:g}).", "sightings", r, "Calves", name)
            elif n is not None and calves == n and n > 0:
                add("warning", "Plausible numbers", "Every animal is a calf — is Num missing the adults?", "sightings", r, "Calves", name)
        b, d = _num(r.get("Bearing")), _num(r.get("Distance"))
        if b is not None and r.get("BrgRef") == "C" and not 0 <= b <= 12:
            add("error", "Plausible bearings and distances", "A clock bearing (Ref C) must be between 1 and 12.", "sightings", r, "Bearing", name)
        elif b is not None and not 0 <= b <= 360:
            add("error", "Plausible bearings and distances", "Bearing must be between 0 and 360°.", "sightings", r, "Bearing", name)
        if d is not None and d < 0:
            add("error", "Plausible bearings and distances", "Distance can't be negative.", "sightings", r, "Distance", name)
        if (b is None) != (d is None):
            add("warning", "Plausible bearings and distances",
                f"{'Bearing' if b is not None else 'Dist'} is given without {'Dist' if b is not None else 'Bearing'}, so the animals' position is the vessel's.",
                "sightings", r, "Distance" if b is not None else "Bearing", name)
        if b is not None and not r.get("BrgRef"):
            add("warning", "Plausible bearings and distances", "Bearing has no Ref (M, T, R or C).", "sightings", r, "BrgRef", name)
        if d is not None and not r.get("DistUnit"):
            add("warning", "Plausible bearings and distances", "Dist has no Unit.", "sightings", r, "DistUnit", name)
        if r.get("BrgRef") in ("R", "C") and b is not None and _num(r.get("VesHdg")) is None:
            add("error", "Plausible bearings and distances",
                f"A {'relative (R)' if r.get('BrgRef') == 'R' else 'clock (C)'} bearing needs the vessel heading, which wasn't recorded, so the position can't be worked out.",
                "sightings", r, "BrgRef", name)
        vp, sp = _pos(r, "Lat", "Lon"), _pos(r, "SigLat", "SigLon")
        if vp and sp:
            dist_nm = geo.haversine_m(vp[0], vp[1], sp[0], sp[1]) / M_PER_NM
            if dist_nm > L["max_sighting_nm"]:
                add("warning", "Plausible bearings and distances",
                    f"The animals are {dist_nm:.1f} nm from the vessel — check Dist and its Unit.", "sightings", r, "Distance", name)
        t = _t(r.get("DateTime"))
        if t:
            stt = state_at(t)
            effort = (stt or {}).get("Effort")
            if not schema.is_on(effort) and not resight:                 # resights off effort (an approach) are normal
                add("info", "Sightings on effort", f"Recorded {'off effort' if effort else 'before any Effort row'} — fine if intended.",
                    "sightings", r, "DateTime", name)
            elif r.get("Observer") and not resight:
                on = {stt.get(k) for k in ("Port", "Recorder", "Starboard")}
                if r["Observer"] not in on:
                    add("warning", "Sighting observer on watch",
                        f"Obs {r['Observer']} isn't on watch (Port / Recorder / Stbd) at this time.", "sightings", r, "Observer", name)
            # sighted further away than the visibility recorded at the time
            vis_nm = visibility_nm((stt or {}).get("Visibility"))
            far_nm = None
            if schema.reticle_name(r.get("DistUnit")) is not None:
                if not (r.get("Altitude") or meta.get("platform_altitude_ft")):
                    add("warning", "Plausible bearings and distances",
                        "Dist is a reticle reading, but there's no altitude (this row's Alt or the survey's Platform altitude), "
                        "so the animal's position couldn't be worked out.", "sightings", r, "Altitude", name)
                if vp and sp:
                    far_nm = geo.haversine_m(vp[0], vp[1], sp[0], sp[1]) / M_PER_NM
            elif d is not None and r.get("DistUnit"):
                try:
                    far_nm = geo.to_meters(d, r["DistUnit"]) / M_PER_NM
                except (KeyError, ValueError):
                    far_nm = None
            elif vp and sp:
                far_nm = geo.haversine_m(vp[0], vp[1], sp[0], sp[1]) / M_PER_NM
            if vis_nm is not None and far_nm is not None and far_nm > vis_nm * L["visibility_margin"] + 1e-9:
                add("warning", "Distance within visibility",
                    f"Sighted {far_nm:.2f} nm away, beyond the visibility recorded at the time ({stt.get('Visibility')}) — check Dist, its Unit or the Effort row's Vis.",
                    "sightings", r, "Distance", name)
            # entered twice: the same time, species, number and position as an earlier sighting
            key = (r.get("DateTime"), r.get("Species"), r.get("Count"), r.get("SigLat"), r.get("SigLon"))
            for (pt, pr, pname) in prev:
                if (pr.get("DateTime"), pr.get("Species"), pr.get("Count"), pr.get("SigLat"), pr.get("SigLon")) == key:
                    add("warning", "No duplicate records", f"Looks like {pname} entered twice (same time, species, number and position).",
                        "sightings", r, "Species", name)
                    break
            prev.append((t, r, name))
        sp_row = species.get(r.get("Species"))
        if sp_row is not None and r.get("Species", "").lower().startswith("unid") and r.get("IDrel") == "Definite":
            add("info", "Species identification", "An unidentified species with IDrel Definite — is that what you meant?",
                "sightings", r, "IDrel", name)

    # ---- resights: the animals' swim speed from one sighting of them to the next (as Tools → Resights)
    def animal_pos(r):
        return _pos(r, "SigLat", "SigLon") or _pos(r, "Lat", "Lon")
    for g in resights.groups(S):
        if len(g) < 2:
            continue
        timed = sorted(((t, r) for r in g if (t := _t(r.get("DateTime")))), key=lambda x: x[0])
        for (ta, a), (tb, b) in zip(timed, timed[1:]):
            pa, pb, dt = animal_pos(a), animal_pos(b), (tb - ta).total_seconds()
            if not (pa and pb) or dt <= 0:
                continue
            kn = geo.haversine_m(pa[0], pa[1], pb[0], pb[1]) / M_PER_NM / (dt / 3600)
            if kn > L["max_resight_kn"]:
                i = S.index(b)
                add("warning", "Resight swim speeds",
                    f"The animals would have swum {kn:.0f} kn from sighting {a.get('SightNo')} to this resight "
                    f"({_fmt_dur(dt) if dt >= 60 else f'{dt:.0f} s'} apart) — check the times, bearings and distances.",
                    "sightings", b, "SigLat" if _pos(b, "SigLat", "SigLon") else "Lat", lab("sightings", b, i))

    # ---- events
    prev = []
    for i, r in enumerate(V):
        name = lab("events", r, i)
        t = _t(r.get("DateTime"))
        if not t:
            continue
        for (pt, pr, pname) in prev:
            if pr.get("EventType") == r.get("EventType") and abs((t - pt).total_seconds()) <= 30 \
                    and (pr.get("ID") or "") == (r.get("ID") or ""):
                add("warning", "No duplicate records", f"Looks like a duplicate of {pname} (same event and ID within 30 s).",
                    "events", r, "EventType", name)
                break
        prev.append((t, r, name))

    order = {"error": 0, "warning": 1, "info": 2}
    tab_order = {"survey": 0, "sightings": 1, "effort": 2, "events": 3, "track": 4}
    row_index = {r["RowID"]: i for rows in (S, E, V) for i, r in enumerate(rows) if r.get("RowID")}
    issues = sorted(rep.issues, key=lambda x: (order[x["level"]], tab_order.get(x["tab"], 9),
                                               row_index.get(x["row_id"], -1)))
    counts = {k: sum(1 for x in issues if x["level"] == k) for k in order}
    return {"survey": rec.survey["prefix"], "generated": now.isoformat(), "counts": counts, "issues": issues,
            "checked": {"sightings": len(S), "effort": len(E), "events": len(V), "track": len(T)},
            "checks": CHECKS, "limits": LIMITS}


# What is checked, for the report's "What is checked" list.
CHECKS = [
    ("Survey details complete", "Every survey detail is filled in (platform, organization, chief scientist and email; the platform altitude only when reticle distances need it)."),
    ("Required fields filled", "Sightings: everything except Behaviors, Bearing, Ref, Dist, Unit, FieldID and Notes. "
     "Effort: everything except Notes (Start and End rows: time and position only). Events: everything except ID and Notes."),
    ("Values from the lists", "Choices are in their lists (species, observers, behaviors, event types, sea state…)."),
    ("Valid numbers, positions and times", "Numbers are numbers, positions are on the globe, times can be read."),
    ("Effort starts with Start / Survey ended", "The first Effort row is Start; the survey has an End row."),
    ("Times within the survey", "Nothing is timed before Start, after End, or in the future; rows are in time order."),
    ("Unique numbers", "No SigNo or EventNo is used twice; gaps in the numbering are noted."),
    ("Plausible numbers", f"Num is a whole number ≥ 1 (flagged above {LIMITS['max_group']}); Calves ≤ Num (or NA)."),
    ("Plausible bearings and distances", f"Bearing 0–360°, Dist not negative, both or neither given, Ref/Unit set, "
     f"relative bearings have a heading, animals within {LIMITS['max_sighting_nm']:g} nm of the vessel."),
    ("Positions match the trackline", f"Vessel positions within {LIMITS['pos_vs_track_nm']:g} nm of the trackline at that time."),
    ("Positions at sea", f"Positions more than {LIMITS['land_buffer_km']:g} km inside the 1:10m coastline are flagged."),
    ("Trackline plausible", "No jumps faster than the trackline-break speed in Settings (30 kn by default); no gaps longer than the GPS-loss time in Settings while recording. A stretch already marked by an ERROR Effort row is skipped; Fix adds one."),
    ("Conditions recorded regularly", f"On effort, a new Effort row at least every {LIMITS['conditions_gap_factor']:g} × the reminder interval."),
    ("Observers in one position at a time", "Nobody is in two of Port / Recorder / Stbd at once (NA / None, an empty position, can be in several)."),
    ("Sighting observer on watch", "On effort, the sighting's Obs is one of the observers on watch."),
    ("Sightings on effort", "Sightings made off effort are listed (information only; resights aren't)."),
    ("Survey conditions", f"On effort in sea state above {LIMITS['max_seastate_on']} or visibility under 0.5 nm (information only)."),
    ("Observer rest", f"Observers on watch over {LIMITS['max_watch_h']:g} h without a break (information only)."),
    ("Distance within visibility", "A sighting's distance (Dist and Unit, or the vessel-to-animal distance) isn't beyond the visibility on the Effort row in force at the time."),
    ("Resights linked", "Each ResNo names an existing sighting, timed before the resight and of the same species."),
    ("Glare bearings", "Gstart and Gend come together, with a Gref, and are 0–360° (1–12 for clock bearings)."),
    ("Resight swim speeds", f"The animals don’t swim faster than {LIMITS['max_resight_kn']:g} kn from one sighting of them to the next (warning; positions from SigLat/SigLon, else the platform’s)."),
    ("No duplicate records", "A sighting with the same time, species, number and position as another (entered twice), or the same event and ID within 30 s."),
]
