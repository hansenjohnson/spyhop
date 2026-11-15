"""Navigation to a waypoint or along a route (0.57).

Not for steering (no cross-track error): it answers "how long until we get there?". The target (a waypoint, a map
point or a route's waypoints) is kept in this computer's setting `nav_active`, so navigation carries on after a
restart, and every window and view-only device sees the same numbers: the server works them out once a second
(App.ticker → Navigator.tick) and sends them in the vessel message as `nav`.

- VMG is the rate the distance to the waypoint has been shrinking over the last `nav_average_s` seconds (worked out
  from the vessel's positions, so it doesn't jump with every GPS fix); until there's enough history it is SOG ×
  cos(COG − bearing).
- ETA at the waypoint = distance / VMG. ETA at the end of a route adds the remaining legs at the average speed over
  ground (the same window), or at a fixed speed (`nav_eta_mode` "fixed", `nav_eta_speed_kn`) for every leg.
- A waypoint is reached within `nav_arrival_nm` (0.58: no "passed abeam" any more: it misfired). Then the next
  waypoint becomes the target (`nav_auto_advance`), or it waits for Next.
"""
from __future__ import annotations

import math
import time
from collections import deque

from . import geo

NM = 1852.0
MIN_HISTORY_S = 5           # VMG from the position history once it covers this much time (or 80 % of the window)
MIN_VMG_KN = 0.2            # slower than this: no ETA
MAX_POINTS = 500
NAV_SETTINGS = ("nav_arrival_nm", "nav_auto_advance", "nav_average_s", "nav_eta_mode",
                "nav_eta_speed_kn", "nav_show_box")


def clean_target(b: dict) -> dict:
    """{kind, name, points: [{name, lat, lon}], index} from the browser → a checked target, or ValueError."""
    kind = b.get("kind")
    if kind not in ("waypoint", "route"):
        raise ValueError("Navigate to a waypoint or along a route.")
    pts = []
    for i, p in enumerate((b.get("points") or [])[:MAX_POINTS]):
        try:
            lat, lon = float(p["lat"]), float(p["lon"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Waypoint {i + 1} has no position.") from None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError(f"Waypoint {i + 1}'s position is out of range.")
        pts.append({"name": str(p.get("name") or (str(i + 1) if kind == "route" else "Waypoint"))[:60], "lat": round(lat, 7), "lon": round(lon, 7)})
    if not pts or (kind == "waypoint" and len(pts) != 1) or (kind == "route" and len(pts) < 2):
        raise ValueError("A waypoint needs one position, a route at least two.")
    try:
        index = int(b.get("index", 0))
    except (TypeError, ValueError):
        index = 0
    index = min(max(index, 0), len(pts) - 1)
    return {"kind": kind, "name": str(b.get("name") or pts[-1]["name"])[:80], "points": pts, "index": index,
            "started": time.time(), "arrived": False}


def start_index(points: list[dict], lat: float | None, lon: float | None) -> int:
    """The waypoint ahead of the vessel: the end of the leg it's nearest to (the first waypoint if it's
    nearest to that, or there's no position)."""
    if lat is None or lon is None or len(points) < 2:
        return 0
    best, idx = geo.haversine_m(lat, lon, points[0]["lat"], points[0]["lon"]), 0
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        d = _dist_to_leg(lat, lon, a, b)
        if d < best - 1:
            best, idx = d, i
    return idx


def _xy(lat0, lat, lon, lon0):
    k = math.cos(math.radians(lat0))
    return (lon - lon0) * k * 60 * NM, (lat - lat0) * 60 * NM


def _dist_to_leg(lat, lon, a, b) -> float:
    """Metres from the vessel to the leg a→b (flat approximation, fine at survey scales)."""
    bx, by = _xy(a["lat"], b["lat"], b["lon"], a["lon"])
    px, py = _xy(a["lat"], lat, lon, a["lon"])
    L2 = bx * bx + by * by
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (px * bx + py * by) / L2))
    return math.hypot(px - t * bx, py - t * by)


class Navigator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.hist: deque = deque()         # (t, lat, lon, sog)
        self.events: list[dict] = []       # arrivals since the last message (shown as toasts)

    # -- the target ---------------------------------------------------------------
    @property
    def target(self) -> dict | None:
        t = self.cfg.settings.get("nav_active")
        return t if isinstance(t, dict) and t.get("points") else None

    def _save(self, t):
        self.cfg.save_settings({"nav_active": t})

    def start(self, body: dict, lat=None, lon=None) -> dict:
        t = clean_target(body)
        if t["kind"] == "route" and body.get("index") in (None, "", "ahead"):
            t["index"] = start_index(t["points"], lat, lon)
        self._save(t)
        return t

    def stop(self):
        if self.target:
            self._save(None)

    def step(self, by: int) -> dict | None:
        t = self.target
        if not t:
            return None
        t = {**t, "index": min(max(t["index"] + int(by), 0), len(t["points"]) - 1), "arrived": False}
        self._save(t)
        return t

    # -- every second ---------------------------------------------------------------
    def settings(self) -> dict:
        s = self.cfg.settings

        def num(k, d, lo, hi):
            try:
                return min(max(float(s.get(k, d)), lo), hi)
            except (TypeError, ValueError):
                return d
        return {"arrival_nm": num("nav_arrival_nm", 0.1, 0.001, 10), "average_s": num("nav_average_s", 10, 5, 1800),
                "auto": bool(s.get("nav_auto_advance", True)),
                "fixed": s.get("nav_eta_mode") == "fixed", "speed_kn": num("nav_eta_speed_kn", 10, 0.1, 100)}

    def tick(self, v: dict, now: float | None = None, record: bool = True) -> dict | None:
        """The navigation numbers for this second (None when not navigating). record=False: only look (an API
        reply between the server's once-a-second ticks), without adding the position to the speed history."""
        now = time.time() if now is None else now
        lat, lon = v.get("lat"), v.get("lon")
        if record and lat is not None and lon is not None and v.get("has_fix", True):
            self.hist.append((now, lat, lon, v.get("sog")))
        cfg = self.settings()
        while self.hist and now - self.hist[0][0] > cfg["average_s"]:
            self.hist.popleft()
        t = self.target
        if not t:
            return None
        pts, i = t["points"], t["index"]
        wp = pts[i]
        out = {"kind": t["kind"], "name": t["name"], "index": i, "count": len(pts), "target": wp["name"],
               "wp": [wp["lat"], wp["lon"]], "arrived": bool(t.get("arrived")), "fixed_speed": cfg["fixed"]}
        if lat is None or lon is None:
            out["no_fix"] = True
            return out
        dist = geo.haversine_m(lat, lon, wp["lat"], wp["lon"])
        brg = geo.initial_bearing(lat, lon, wp["lat"], wp["lon"])
        var = v.get("mag_var")
        out.update(dist_m=round(dist, 1), brg_t=round(brg, 1), brg_m=round((brg - var) % 360, 1) if var is not None else None)

        # arrival
        reached = dist <= cfg["arrival_nm"] * NM
        if reached and not t.get("arrived"):
            last = i == len(pts) - 1
            self.events.append({"arrived": wp["name"], "last": last, "kind": t["kind"], "index": i, "count": len(pts)})
            if last:
                self._save(None)
                out.update(arrived=True, finished=True)
                return out
            if cfg["auto"]:
                return self.tick_after_advance(v, now, i + 1)
            self._save({**t, "arrived": True})
            out["arrived"] = True

        # speeds over the window
        h = self.hist
        span = h[-1][0] - h[0][0] if len(h) > 1 else 0
        sogs = [x[3] for x in h if x[3] is not None]
        sog_avg = sum(sogs) / len(sogs) if sogs else v.get("sog")
        if span >= min(MIN_HISTORY_S, 0.8 * cfg["average_s"]):
            d0 = geo.haversine_m(h[0][1], h[0][2], wp["lat"], wp["lon"])
            vmg = (d0 - dist) / NM / (span / 3600)
            moved = sum(geo.haversine_m(h[k - 1][1], h[k - 1][2], h[k][1], h[k][2]) for k in range(1, len(h)))
            sog_avg = moved / NM / (span / 3600)
        elif v.get("sog") is not None and v.get("cog") is not None:
            vmg = v["sog"] * math.cos(math.radians(v["cog"] - brg))
        else:
            vmg = None
        out.update(vmg_kn=round(vmg, 2) if vmg is not None else None,
                   sog_kn=round(sog_avg, 2) if sog_avg is not None else None, window_s=round(span))

        # times
        rest = sum(geo.haversine_m(pts[k - 1]["lat"], pts[k - 1]["lon"], pts[k]["lat"], pts[k]["lon"]) for k in range(i + 1, len(pts)))
        speed_next = cfg["speed_kn"] if cfg["fixed"] else vmg
        speed_rest = cfg["speed_kn"] if cfg["fixed"] else sog_avg
        ttg = dist / NM / speed_next * 3600 if speed_next and speed_next >= MIN_VMG_KN else None
        out.update(ttg_s=round(ttg) if ttg is not None else None, eta=now + ttg if ttg is not None else None)
        if t["kind"] == "route":
            out["remaining_m"] = round(dist + rest, 1)
            if ttg is not None and (rest == 0 or (speed_rest and speed_rest >= MIN_VMG_KN)):
                total = ttg + (rest / NM / speed_rest * 3600 if rest else 0)
                out.update(ttg_end_s=round(total), eta_end=now + total)
        return out

    def tick_after_advance(self, v, now, i):
        t = self.target
        self._save({**t, "index": i, "arrived": False})
        return self.tick(v, now, record=False)

    def take_events(self) -> list[dict]:
        e, self.events = self.events, []
        return e
