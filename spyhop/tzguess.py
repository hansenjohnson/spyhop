"""Guess the local time zone from a position (Settings → General → Clock → "From the platform's position").

Uses the offline time-zone map in `tzfpy` when it's installed. At sea, more than about
12 nm from shore, the map only has the nautical zones (Etc/GMT+5 and so on, which have no
daylight saving), so the nearest coast's zone within NEAR_COAST_NM is used instead: a survey
off Cape Cod in July keeps EDT. Further out, the nautical zone is used. Without tzfpy the
nautical zone is worked out from the longitude.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta, timezone, tzinfo

from . import geo

log = logging.getLogger("spyhop.tz")

try:                                            # optional: offline zone boundaries
    import tzfpy  # type: ignore
except Exception:                               # pragma: no cover - depends on the install
    tzfpy = None

try:
    from zoneinfo import ZoneInfo
except ImportError:                             # pragma: no cover
    ZoneInfo = None

NEAR_COAST_NM = 150
_RINGS_NM = (5, 12, 25, 50, 75, 100, 150)
_DIRS = range(0, 360, 30)

def offset_name(h: float) -> str:
    sign = "-" if h < 0 else "+"
    m = round(abs(h) * 60)
    return f"UTC{sign}{m // 60:02d}:{m % 60:02d}"


def parse_offset(v: str) -> timezone | None:
    """'UTC+05:30' / 'UTC-4' → a fixed-offset tzinfo named like that."""
    m = re.fullmatch(r"UTC([+-])(\d{1,2})(?::?(\d{2}))?", str(v or "").strip().upper())
    if not m:
        return None
    mins = int(m.group(2)) * 60 + int(m.group(3) or 0)
    if mins > 14 * 60:
        return None
    if m.group(1) == "-":
        mins = -mins
    return timezone(timedelta(minutes=mins), offset_name(mins / 60) if mins else "UTC")


def nautical_zone(lon: float) -> str:
    """The nautical zone for a longitude, as an IANA Etc/ name (note the reversed sign)."""
    h = max(-12, min(12, round(lon / 15)))
    return "Etc/GMT" if h == 0 else f"Etc/GMT{'-' if h > 0 else '+'}{abs(h)}"


def _lookup(lat: float, lon: float) -> str | None:
    if tzfpy is None:
        return None
    try:
        return tzfpy.get_tz(lon, lat) or None
    except Exception:                           # pragma: no cover
        return None


def zone_at(lat: float, lon: float) -> tuple[str, str]:
    """(IANA zone name, how it was found): 'position', 'nearest coast', 'nautical zone' or 'longitude'."""
    z = _lookup(lat, lon)
    if z is None:
        return nautical_zone(lon), "longitude"
    if not z.startswith("Etc/"):
        return z, "position"
    # at sea: the nearest land zone, searching outwards in rings
    for r in _RINGS_NM:
        if r > NEAR_COAST_NM:
            break
        found = {}
        for b in _DIRS:
            la, lo = geo.destination(lat, lon, b, r * 1852)
            zz = _lookup(la, lo)
            if zz and not zz.startswith("Etc/"):
                found[zz] = found.get(zz, 0) + 1
        if found:
            return max(found, key=found.get), "nearest coast"
    return z, "nautical zone"


def tzinfo_for(name: str) -> tzinfo | None:
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(name)
    except Exception:
        log.warning("time zone %s isn't available (install the tzdata package)", name)
        return None


class ZoneGuess:
    """Caches the zone for the platform position; looks it up again after moving GUESS_MOVE_NM."""
    GUESS_MOVE_NM = 5

    def __init__(self):
        self.name: str | None = None
        self.how = ""
        self._at: tuple[float, float] | None = None

    def update(self, lat, lon) -> str | None:
        if lat is None or lon is None or (lat == 0 and lon == 0):
            return self.name
        if self._at and geo.haversine_m(self._at[0], self._at[1], lat, lon) < self.GUESS_MOVE_NM * 1852:
            return self.name
        name, how = zone_at(lat, lon)
        if name != self.name:
            log.info("clock zone from position %.3f, %.3f: %s (%s)", lat, lon, name, how)
        self.name, self.how, self._at = name, how, (lat, lon)
        return name
