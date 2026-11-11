"""NMEA 0183 parsing and the live vessel state built from it."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, date
from pathlib import Path


def checksum(body: str) -> str:
    c = 0
    for ch in body:
        c ^= ord(ch)
    return f"{c:02X}"


def with_checksum(body: str) -> str:
    """'GPRMC,...' -> '$GPRMC,...*hh'"""
    return f"${body}*{checksum(body)}"


def split_sentence(line: str):
    """Return (talker, type, fields) or raise ValueError.

    Validates the checksum when one is present.
    """
    s = line.strip()
    if not s or s[0] not in "$!":
        raise ValueError("not an NMEA sentence")
    s = s[1:]
    if "*" in s:
        s, cs = s.rsplit("*", 1)
        cs = cs.strip()[:2]
        if cs and checksum(s) != cs.upper():
            raise ValueError("bad checksum")
    parts = s.split(",")
    head = parts[0]
    if len(head) < 5:
        raise ValueError("bad address field")
    if head.startswith("P"):  # proprietary
        return "P", head[1:], parts[1:]
    return head[:2], head[2:], parts[1:]


def _f(x):
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def _latlon(val, hemi, is_lat):
    if not val or not hemi:
        return None
    try:
        v = float(val)
    except ValueError:
        return None
    deg = int(v // 100)
    out = deg + (v - deg * 100) / 60.0
    if hemi in ("S", "W"):
        out = -out
    lim = 90 if is_lat else 180
    return out if abs(out) <= lim else None


def _hms(t):
    if not t or len(t) < 6:
        return None
    try:
        h, m = int(t[0:2]), int(t[2:4])
        sec = float(t[4:])
        return h, m, sec
    except ValueError:
        return None


@dataclass
class VesselState:
    lat: float | None = None
    lon: float | None = None
    sog: float | None = None         # knots
    cog: float | None = None         # degrees true
    heading: float | None = None     # degrees true
    variation: float | None = None   # degrees, east positive (from RMC/HDG)
    quality: int | None = None
    sats: int | None = None
    gps_time: str | None = None      # ISO UTC from the sentence, if any
    source: str | None = None
    updated: float | None = None     # wall clock (time.time) of last position
    heading_updated: float | None = None
    last_moved: float | None = None  # wall clock when position last changed

    def snapshot(self, lost_after: float = 10.0, frozen_after: float = 60.0) -> dict:
        now = time.time()
        d = asdict(self)
        d["age"] = None if self.updated is None else round(now - self.updated, 1)
        d["lost"] = self.updated is None or (now - self.updated) > lost_after
        d["frozen"] = (not d["lost"] and self.last_moved is not None
                       and (now - self.last_moved) > frozen_after
                       and (self.sog is None or self.sog > 0.3))
        hdg_fresh = self.heading is not None and self.heading_updated and now - self.heading_updated < 10
        d["best_heading"] = self.heading if hdg_fresh else self.cog
        d["has_fix"] = not d["lost"] and self.lat is not None
        return d


# Instrument readings shown in Tools → Instruments: key -> (group, label, unit).
# Readings not listed here (other transducers, extra engines) are added as they arrive.
INSTRUMENTS = {
    "lat": ("Navigation", "Latitude", "°"),
    "lon": ("Navigation", "Longitude", "°"),
    "sog": ("Navigation", "Speed over ground", "kn"),
    "stw": ("Navigation", "Speed through water", "kn"),
    "cog": ("Navigation", "Course over ground", "°T"),
    "heading_true": ("Navigation", "Heading", "°T"),
    "heading_mag": ("Navigation", "Heading (magnetic)", "°M"),
    "rot": ("Navigation", "Rate of turn", "°/min"),
    "rudder": ("Navigation", "Rudder angle", "°"),
    "gps_quality": ("Navigation", "GPS fix", ""),
    "sats": ("Navigation", "Satellites", ""),
    "hdop": ("Navigation", "HDOP", ""),
    "depth": ("Depth", "Depth", "m"),
    "depth_transducer": ("Depth", "Depth below transducer", "m"),
    "depth_keel": ("Depth", "Depth below keel", "m"),
    "wind_app_angle": ("Wind", "Apparent wind angle", "° rel"),
    "wind_app_speed": ("Wind", "Apparent wind speed", "kn"),
    "wind_true_angle": ("Wind", "True wind angle", "° rel"),
    "wind_true_speed": ("Wind", "True wind speed", "kn"),
    "wind_true_dir": ("Wind", "True wind direction", "°T"),
    "air_temp": ("Weather", "Air temperature", "°C"),
    "water_temp": ("Weather", "Water temperature", "°C"),
    "humidity": ("Weather", "Relative humidity", "%"),
    "dew_point": ("Weather", "Dew point", "°C"),
    "pressure": ("Weather", "Barometric pressure", "hPa"),
}
GPS_QUALITY = {0: "no fix", 1: "GPS", 2: "DGPS", 3: "PPS", 4: "RTK", 5: "float RTK", 6: "estimated",
               7: "manual", 8: "simulated"}
_SPEED_TO_KN = {"N": 1.0, "M": 1.943844, "K": 0.539957, "S": 0.868976}


class NmeaDecoder:
    """Feeds sentences into a VesselState and keeps a short raw log."""

    def __init__(self, state: VesselState | None = None):
        self.state = state or VesselState()
        self.raw = deque(maxlen=200)
        # latest readings of each input: source -> key -> {group, label, unit, value, t, sentence, source}
        self.inst_src: dict[str, dict[str, dict]] = {}
        self._order: dict[str, int] = {}
        self.raw_logger = None           # callable(line, source), set while raw logging is on
        self.counts: dict[str, int] = {}
        self.errors = 0
        # source name -> priority (lower wins): with no primary, or for failover, a lower-priority
        # source only supplies position when the preferred one has been quiet for 5 s.
        self.priority: dict[str, int] = {}
        # 0.41: the primary input supplies the vessel's position, course, speed and heading; secondaries
        # keep their own (others, drawn on the map if chosen). None = every input, by priority (as before).
        self.primary: str | None = None
        self.failover = False            # a secondary stands in while the primary has been quiet for 5 s
        self.others: dict[str, VesselState] = {}
        self.externals: set[str] = set()     # 0.42: inputs that aren't the platform (drone, buoy, other vessel)
        self.heard: dict[str, float] = {}    # source -> wall clock of its last position

    def feed(self, line: str, source: str = "") -> bool:
        line = line.strip()
        if not line:
            return False
        self.raw.append(f"{source}> {line}" if source else line)
        if self.raw_logger is not None:
            try:
                self.raw_logger(line, source)
            except Exception:  # noqa: BLE001 — logging must never stop the feed
                pass
        try:
            talker, typ, f = split_sentence(line)
        except ValueError:
            self.errors += 1
            return False
        self.counts[typ] = self.counts.get(typ, 0) + 1
        handler = getattr(self, "_" + typ, None)
        if handler is None:
            return False
        self._cur = (typ, source)
        main = source not in self.externals and (self.primary is None or not source or source == self.primary)
        st = self.state if main else self.others.setdefault(source, VesselState())
        saved, self.state = self.state, st
        try:
            ok = bool(handler(f, source))
        except (IndexError, ValueError):
            self.errors += 1
            ok = False
        finally:
            self.state = saved
        if ok and not main and self.failover and source not in self.externals:
            self._stand_in(source, st)
        return ok

    def failover_state(self) -> dict | None:
        """While a secondary stands in for the primary: {from, primary, quiet_s}; else None."""
        st = self.state
        if not self.primary or not st.source or st.source == self.primary or st.updated is None or time.time() - st.updated > 10:
            return None
        t = self.heard.get(self.primary)
        return {"from": st.source, "primary": self.primary, "quiet_s": None if t is None else round(time.time() - t)}

    def primary_quiet(self, after: float = 5.0) -> bool:
        t = self.heard.get(self.primary) if self.primary else None
        return t is None or time.time() - t > after

    def _stand_in(self, source: str, st: "VesselState"):
        """Failover: copy a secondary's position into the vessel's while the primary is quiet (the
        first secondary in the list that has a recent fix)."""
        if not self.primary_quiet():
            return
        now = time.time()
        live = [s for s, t in self.heard.items() if s != self.primary and s not in self.externals and now - t < 5]
        if not live or min(live, key=lambda s: self.priority.get(s, 99)) != source:
            return
        main = self.state
        for k in ("lat", "lon", "sog", "cog", "heading", "heading_updated", "variation", "quality", "sats", "gps_time", "updated"):
            setattr(main, k, getattr(st, k))
        if main.lat is not None and (main.last_moved is None or st.last_moved and st.last_moved > main.last_moved):
            main.last_moved = st.last_moved
        main.source = source

    # -- instruments ------------------------------------------------------
    def put(self, key: str, value, unit: str | None = None, label: str | None = None, group: str | None = None):
        """Store one instrument reading from the sentence being decoded."""
        if value is None:
            return
        g, lab, u = INSTRUMENTS.get(key, (group or "Other transducers", label or key, unit or ""))
        typ, source = getattr(self, "_cur", ("", ""))
        if isinstance(value, float):
            value = round(value, 6 if key in ("lat", "lon") else 2)
        if key not in self._order:
            self._order[key] = list(INSTRUMENTS).index(key) if key in INSTRUMENTS else 100 + len(self._order)
        self.inst_src.setdefault(source, {})[key] = {
            "group": group or g, "label": label or lab, "unit": u if unit is None else unit, "order": self._order[key],
            "value": value, "t": time.time(), "sentence": typ, "source": source}

    @property
    def inst(self) -> dict[str, dict]:
        """One reading per key: the primary's while it's under 15 s old, else the newest from any platform
        input (externals' readings are theirs, not the platform's: logged, not shown here)."""
        now, out = time.time(), {}
        for src, readings in self.inst_src.items():
            if src in self.externals:
                continue
            for k, r in readings.items():
                cur = out.get(k)
                prim = self.primary is not None and src == self.primary and now - r["t"] < 15
                cur_prim = cur is not None and self.primary is not None and cur["source"] == self.primary and now - cur["t"] < 15
                if cur is None or prim or (not cur_prim and r["t"] > cur["t"]):
                    out[k] = r
        return out

    def instruments(self) -> dict:
        now = time.time()
        return {k: {**v, "age": round(now - v["t"], 1)} for k, v in self.inst.items()}

    def secondaries(self, names=None, lost_after: float = 10.0) -> list[dict]:
        """The secondary inputs' latest fixes (for the map): [{name, lat, lon, sog, cog, heading, age}]."""
        now, out = time.time(), []
        for name, st in self.others.items():
            if names is not None and name not in names or st.lat is None or st.updated is None:
                continue
            age = now - st.updated
            if age > lost_after:
                continue
            out.append({"name": name, "external": name in self.externals, "lat": st.lat, "lon": st.lon, "sog": st.sog, "cog": st.cog,
                        "heading": st.heading if st.heading_updated and now - st.heading_updated < 10 else st.cog,
                        "age": round(age, 1)})
        return out

    # -- position ---------------------------------------------------------
    def _set_pos(self, lat, lon, source):
        st = self.state
        now = time.time()
        if lat is None or lon is None:
            return False
        if (st.source and source != st.source and st.updated and now - st.updated < 5
                and self.priority.get(source, 99) > self.priority.get(st.source, 99)):
            return False
        if st.lat is None or abs(st.lat - lat) > 1e-7 or abs(st.lon - lon) > 1e-7:
            st.last_moved = now
        st.lat, st.lon = lat, lon
        st.updated = now
        st.source = source
        self.heard[source] = now
        self.put("lat", lat)
        self.put("lon", lon)
        return True

    def _RMC(self, f, source):
        # hhmmss,A,llll.ll,a,yyyyy.yy,a,sog,cog,ddmmyy,var,E/W[,mode]
        if len(f) < 9 or f[1] != "A":
            return False
        lat = _latlon(f[2], f[3], True)
        lon = _latlon(f[4], f[5], False)
        if not self._set_pos(lat, lon, source):
            return False
        st = self.state
        st.sog = _f(f[6])
        cog = _f(f[7])
        st.cog = cog if cog is not None else st.cog
        self.put("sog", st.sog)
        self.put("cog", cog)
        if len(f) > 10 and f[9]:
            v = _f(f[9])
            if v is not None:
                st.variation = -v if f[10].startswith("W") else v
        hms, dmy = _hms(f[0]), f[8]
        if hms and len(dmy) == 6:
            try:
                d = date(2000 + int(dmy[4:6]), int(dmy[2:4]), int(dmy[0:2]))
                h, m, s = hms
                st.gps_time = datetime(d.year, d.month, d.day, h, m, int(s),
                                       tzinfo=timezone.utc).isoformat()
            except ValueError:
                pass
        return True

    def _GGA(self, f, source):
        if len(f) < 7:
            return False
        q = int(f[5]) if f[5].isdigit() else 0
        self.state.quality = q
        self.state.sats = int(f[6]) if f[6].isdigit() else None
        self.put("gps_quality", GPS_QUALITY.get(q, str(q)))
        self.put("sats", self.state.sats)
        if len(f) > 7:
            self.put("hdop", _f(f[7]))
        if q == 0:
            return False
        return self._set_pos(_latlon(f[1], f[2], True), _latlon(f[3], f[4], False), source)

    def _GLL(self, f, source):
        if len(f) >= 6 and f[5] != "A":
            return False
        return self._set_pos(_latlon(f[0], f[1], True), _latlon(f[2], f[3], False), source)

    def _VTG(self, f, source):
        cog = _f(f[0])
        sog = _f(f[4]) if len(f) > 4 else None
        if cog is not None:
            self.state.cog = cog
        if sog is not None:
            self.state.sog = sog
        self.put("cog", cog)
        self.put("sog", sog)
        return cog is not None or sog is not None

    # -- heading ----------------------------------------------------------
    def _set_heading(self, h):
        if h is None:
            return False
        self.put("heading_true", h % 360.0)
        self.state.heading = h % 360.0
        self.state.heading_updated = time.time()
        return True

    def _HDT(self, f, source):
        return self._set_heading(_f(f[0]))

    def _THS(self, f, source):
        if len(f) > 1 and f[1] == "V":
            return False
        return self._set_heading(_f(f[0]))

    def _HDG(self, f, source):
        # magnetic sensor heading, deviation, variation
        h = _f(f[0])
        if h is None:
            return False
        self.put("heading_mag", h)
        dev = _f(f[1]) if len(f) > 2 else None
        if dev is not None and f[2] == "W":
            dev = -dev
        var = _f(f[3]) if len(f) > 4 else None
        if var is not None:
            var = -var if f[4] == "W" else var
            self.state.variation = var
        if var is None:
            var = self.state.variation
        if var is None:
            return False
        return self._set_heading(h + (dev or 0.0) + var)

    def _HDM(self, f, source):
        h = _f(f[0])
        self.put("heading_mag", h)
        if h is None or self.state.variation is None:
            return False
        return self._set_heading(h + self.state.variation)


    # -- other instruments (shown in Tools → Instruments) ---------------------------
    def _VHW(self, f, source):
        # true hdg,T,mag hdg,M,speed kn,N,speed km/h,K
        stw = _f(f[4]) if len(f) > 4 else None
        if stw is None and len(f) > 6 and _f(f[6]) is not None:
            stw = _f(f[6]) * 0.539957
        self.put("stw", stw)
        return stw is not None

    def _VBW(self, f, source):
        # longitudinal water speed,transverse,status,ground long,ground trans,status
        if len(f) > 2 and f[2] == "A":
            self.put("stw", _f(f[0]))
            return True
        return False

    def _ROT(self, f, source):
        if len(f) > 1 and f[1] == "V":
            return False
        self.put("rot", _f(f[0]))
        return True

    def _RSA(self, f, source):
        if len(f) > 1 and f[1] == "A":
            self.put("rudder", _f(f[0]))
        if len(f) > 3 and f[3] == "A":
            self.put("rudder_port", _f(f[2]), "°", "Rudder angle (port)", "Navigation")
        return True

    def _DPT(self, f, source):
        # depth below transducer (m), offset (+ to waterline, - to keel)[, max range]
        d = _f(f[0])
        if d is None:
            return False
        off = _f(f[1]) if len(f) > 1 else None
        self.put("depth_transducer", d)
        if off is not None and off > 0:
            self.put("depth", d + off)
        elif off is not None and off < 0:
            self.put("depth_keel", d + off)
        return True

    def _depth_fields(self, f):
        # feet,f,meters,M,fathoms,F
        if len(f) > 2 and _f(f[2]) is not None:
            return _f(f[2])
        if _f(f[0]) is not None:
            return _f(f[0]) * 0.3048
        if len(f) > 4 and _f(f[4]) is not None:
            return _f(f[4]) * 1.8288
        return None

    def _DBT(self, f, source):
        self.put("depth_transducer", self._depth_fields(f))
        return True

    def _DBS(self, f, source):
        self.put("depth", self._depth_fields(f))
        return True

    def _DBK(self, f, source):
        self.put("depth_keel", self._depth_fields(f))
        return True

    def _MWV(self, f, source):
        # angle,R/T,speed,unit,status
        if len(f) < 5 or f[4] != "A":
            return False
        ang, spd = _f(f[0]), _f(f[2])
        if spd is not None:
            spd *= _SPEED_TO_KN.get(f[3], 1.0)
        kind = "true" if f[1] == "T" else "app"
        self.put(f"wind_{kind}_angle", ang)
        self.put(f"wind_{kind}_speed", spd)
        return True

    def _VWR(self, f, source):
        # angle,L/R,knots,N,m/s,M,km/h,K   (apparent, relative to the bow)
        ang = _f(f[0])
        if ang is not None and len(f) > 1 and f[1] == "L":
            ang = 360 - ang
        self.put("wind_app_angle", ang)
        spd = _f(f[2]) if len(f) > 2 else None
        if spd is None and len(f) > 4 and _f(f[4]) is not None:
            spd = _f(f[4]) * 1.943844
        self.put("wind_app_speed", spd)
        return True

    def _VWT(self, f, source):
        ang = _f(f[0])
        if ang is not None and len(f) > 1 and f[1] == "L":
            ang = 360 - ang
        self.put("wind_true_angle", ang)
        self.put("wind_true_speed", _f(f[2]) if len(f) > 2 else None)
        return True

    def _MWD(self, f, source):
        # dir T,T,dir M,M,speed kn,N,speed m/s,M
        self.put("wind_true_dir", _f(f[0]))
        spd = _f(f[4]) if len(f) > 4 else None
        if spd is None and len(f) > 6 and _f(f[6]) is not None:
            spd = _f(f[6]) * 1.943844
        self.put("wind_true_speed", spd)
        return True

    def _MTW(self, f, source):
        self.put("water_temp", _f(f[0]))
        return True

    def _MTA(self, f, source):
        self.put("air_temp", _f(f[0]))
        return True

    def _MHU(self, f, source):
        self.put("humidity", _f(f[0]))
        return True

    def _MMB(self, f, source):
        # inches,I,bars,B
        if len(f) > 2 and _f(f[2]) is not None:
            self.put("pressure", _f(f[2]) * 1000)
        elif _f(f[0]) is not None:
            self.put("pressure", _f(f[0]) * 33.8639)
        return True

    def _MDA(self, f, source):
        # 0 baro inHg,I,2 baro bar,B,4 air C,C,6 water C,C,8 rel hum,9 abs hum,10 dew C,C,
        # 12 wind dir T,T,14 wind dir M,M,16 wind kn,N,18 wind m/s,M
        g = lambda i: _f(f[i]) if len(f) > i else None  # noqa: E731
        if g(2) is not None:
            self.put("pressure", g(2) * 1000)
        elif g(0) is not None:
            self.put("pressure", g(0) * 33.8639)
        self.put("air_temp", g(4))
        self.put("water_temp", g(6))
        self.put("humidity", g(8))
        self.put("dew_point", g(10))
        self.put("wind_true_dir", g(12))
        spd = g(16) if g(16) is not None else (g(18) * 1.943844 if g(18) is not None else None)
        self.put("wind_true_speed", spd)
        return True

    def _RPM(self, f, source):
        # S/E (shaft/engine),number,rpm,pitch %,status
        if len(f) < 3 or (len(f) > 4 and f[4] == "V"):
            return False
        what = "Shaft" if f[0] == "S" else "Engine"
        n = f[1] or "1"
        self.put(f"rpm_{what.lower()}_{n}", _f(f[2]), "rpm", f"{what} {n}", "Engine")
        if len(f) > 3 and _f(f[3]) is not None:
            self.put(f"pitch_{what.lower()}_{n}", _f(f[3]), "%", f"{what} {n} pitch", "Engine")
        return True

    def _XDR(self, f, source):
        # repeated: type,value,unit,name
        got = False
        for i in range(0, len(f) - 3, 4):
            typ, val, unit, name = f[i], _f(f[i + 1]), f[i + 2], f[i + 3]
            if val is None:
                continue
            got = True
            up = name.upper()
            if typ == "C":
                if "WATER" in up or "SEA" in up:
                    self.put("water_temp", val)
                elif "AIR" in up or "ENV" in up or "OUTSIDE" in up or not name:
                    self.put("air_temp", val)
                else:
                    self.put(f"xdr_{name}", val, "°C", f"{name} temperature")
            elif typ == "P":
                hpa = val * 1000 if unit == "B" else val / 100 if unit == "P" else val
                if "BARO" in up or not name or "AIR" in up:
                    self.put("pressure", hpa)
                else:
                    self.put(f"xdr_{name}", hpa, "hPa", f"{name} pressure")
            elif typ == "H":
                self.put("humidity" if not name or "AIR" in up or "ENV" in up or "HUM" in up else f"xdr_{name}",
                         val, "%", None if not name else f"{name} humidity")
            elif typ == "T" and unit == "R":
                self.put(f"rpm_xdr_{name or 1}", val, "rpm", name or "Tachometer", "Engine")
            elif typ == "U" and unit == "V":
                self.put(f"xdr_{name}", val, "V", f"{name or 'Battery'} voltage")
            elif typ == "V" and unit == "P":
                self.put(f"xdr_{name}", val, "%", f"{name or 'Tank'} level")
            elif typ == "A":
                self.put(f"xdr_{name}", val, "°", f"{name or 'Angle'}")
            else:
                self.put(f"xdr_{typ}_{name}", val, unit, name or f"Transducer {typ}")
        return got


class RawLog:
    """Writes every received sentence to a text file, as it arrives.

    With timestamps each line is  <UTC time><TAB><input><TAB><sentence>;  without,
    just the sentence (plain NMEA, readable by any NMEA tool). Spyhop's own file
    replay reads both.
    """

    def __init__(self, folder: Path, stem: str, timestamps: bool = True):
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = folder / f"{stem}_nmea_{stamp}.nmea"
        n = 2
        while self.path.exists():        # restarted within the same second
            self.path = folder / f"{stem}_nmea_{stamp}-{n}.nmea"
            n += 1
        self.timestamps = timestamps
        self.lines = 0
        self.started = time.time()
        self.active = True
        self._fh = None                  # opened at the first sentence, so no empty files

    def write(self, line: str, source: str = ""):
        if not self.active:
            return
        if self._fh is None:
            self._fh = open(self.path, "a", encoding="ascii", errors="replace", buffering=1, newline="\n")
        if self.timestamps:
            now = datetime.now(timezone.utc)
            t = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
            self._fh.write(f"{t}\t{source}\t{line}\n")
        else:
            self._fh.write(line + "\n")
        self.lines += 1

    def close(self):
        self.active = False
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def status(self) -> dict:
        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0
        return {"on": self.active, "path": str(self.path), "name": self.path.name,
                "lines": self.lines, "bytes": size, "started": self.started, "timestamps": self.timestamps}
