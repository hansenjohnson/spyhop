"""Geodesy helpers: distances, bearings, destination points, lat/lon parsing.

All positions are decimal degrees (WGS 84). Distances in meters unless stated.
"""
from __future__ import annotations

import math
import re
from datetime import datetime

EARTH_RADIUS_M = 6371008.8

UNIT_TO_M = {
    "m": 1.0,
    "km": 1000.0,
    "nm": 1852.0,
    "mi": 1609.344,
    "yd": 0.9144,
}


def to_meters(value: float, unit: str) -> float:
    return float(value) * UNIT_TO_M.get(unit, 1.0)


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination(lat, lon, bearing_deg, dist_m):
    """Great-circle destination point from start, true bearing and distance."""
    d = dist_m / EARTH_RADIUS_M
    b = math.radians(bearing_deg)
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    lon2 = (math.degrees(l2) + 540.0) % 360.0 - 180.0
    return math.degrees(p2), lon2


# ---------------------------------------------------------------- magnetic

_geomag = None


def magnetic_variation(lat: float, lon: float, when: datetime | None = None) -> float | None:
    """Magnetic declination in degrees (east positive) from the WMM, if pygeomag
    is installed; otherwise None."""
    global _geomag
    try:
        if _geomag is None:
            from pygeomag import GeoMag  # type: ignore
            _geomag = GeoMag()
        when = when or datetime.utcnow()
        year = when.year + (when.timetuple().tm_yday - 1) / 365.25
        return float(_geomag.calculate(glat=lat, glon=lon, alt=0, time=year).d)
    except Exception:
        return None


def to_true_bearing(bearing: float, reference: str, heading: float | None,
                    variation: float | None) -> float | None:
    """Convert an observed bearing to true.

    reference: 'T' true, 'M' magnetic, 'R' relative to the vessel's heading, 'C' a clock bearing
    relative to the heading (1–12, each hour 30°: 3 = 90° to starboard, 12 = dead ahead).
    """
    reference = (reference or "M").upper()[:1]
    if reference == "T":
        return bearing % 360.0
    if reference == "M":
        if variation is None:
            return None
        return (bearing + variation) % 360.0
    if reference == "R":
        if heading is None:
            return None
        return (bearing + heading) % 360.0
    if reference == "C":
        if heading is None or not 0 <= bearing <= 12:
            return None
        return (bearing * 30.0 + heading) % 360.0
    return None


# ---------------------------------------------------------------- lat/lon text

_HEMI = {"N": 1, "S": -1, "E": 1, "W": -1}


def parse_coord(text: str, is_lat: bool, default_negative: bool = False) -> float:
    """Parse a latitude or longitude written as DD, DDM or DMS.

    Accepts things like:
      41.5   -70.25   41.5N   70 15.0W   70°15.000'W   41 30 15.5 N
      N41 30.5   41-30.5N   W070 15.25   4130.5N (packed DDM, NMEA style)
    With no hemisphere letter and no sign, default_negative=True makes the value
    S/W (so "70 20.5" typed in the western hemisphere means 70°20.5'W).
    Raises ValueError if it can't make sense of it.
    """
    if text is None:
        raise ValueError("empty")
    s = str(text).strip().upper()
    if not s:
        raise ValueError("empty")
    sign = 1
    explicit = s.startswith(("-", "+"))
    hemi = re.findall(r"[NSEW]", s)
    if len(hemi) > 1:
        raise ValueError("more than one hemisphere letter")
    if hemi:
        h = hemi[0]
        if is_lat and h in "EW" or (not is_lat and h in "NS"):
            raise ValueError(f"hemisphere {h} is wrong for a {'latitude' if is_lat else 'longitude'}")
        sign = _HEMI[h]
        s = s.replace(h, " ")
    s = s.strip()
    if s.startswith("-"):
        if hemi:
            raise ValueError("use either a minus sign or a hemisphere letter, not both")
        sign = -1
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    # unify separators
    s = re.sub(r"[°º˚'′\"″:,;_]|(?<=\d)-(?=\d)", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    parts = s.split(" ") if s else []
    if not parts:
        raise ValueError("no numbers")
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        raise ValueError(f"can't read '{text}'")
    if len(nums) == 1:
        v = nums[0]
        # packed NMEA style ddmm.mmm / dddmm.mmm
        if hemi and v >= (100 if is_lat else 1000) and "." in parts[0] and len(parts[0].split(".")[0]) >= 4:
            deg = int(v // 100)
            v = deg + (v - deg * 100) / 60.0
        deg = v
    elif len(nums) == 2:
        d, m = nums
        if m < 0 or m >= 60:
            raise ValueError("minutes must be 0–60")
        deg = d + m / 60.0
    elif len(nums) == 3:
        d, m, sec = nums
        if m < 0 or m >= 60 or sec < 0 or sec >= 60:
            raise ValueError("minutes/seconds must be 0–60")
        deg = d + m / 60.0 + sec / 3600.0
    else:
        raise ValueError(f"can't read '{text}'")
    if not hemi and not explicit and default_negative:
        sign = -1
    val = sign * deg
    lim = 90 if is_lat else 180
    if abs(val) > lim:
        raise ValueError(f"out of range (±{lim})")
    return round(val, 7)


def format_coord(value: float, is_lat: bool, fmt: str = "DDM") -> str:
    """The same formats as the window's fmtCoord (util.js): DD, DDM or DMS. Used by the reports."""
    if value is None or value == "":
        return ""
    v = float(value)
    hemi = ("N" if v >= 0 else "S") if is_lat else ("E" if v >= 0 else "W")
    a = abs(v)
    if fmt == "DD":
        return f"{v:.5f}"
    d = int(a)
    m = (a - d) * 60
    if fmt == "DMS":
        mi = int(m)
        sec = (m - mi) * 60
        if round(sec, 1) >= 60:
            sec = 0; mi += 1
        if mi >= 60:
            mi = 0; d += 1
        return f"{d}°{mi:02d}'{sec:04.1f}\"{hemi}"
    if round(m, 3) >= 60:
        m = 0; d += 1
    width = 2 if is_lat else 3
    return f"{d:0{width}d}°{m:06.3f}'{hemi}"
