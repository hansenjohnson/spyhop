"""AIS targets from the NMEA inputs (0.56).

AIS receivers and transponders send !AIVDM sentences (other vessels) and !AIVDO (this vessel) on the
same serial, UDP or TCP connections as the GPS. NmeaDecoder hands each VDM sentence to AisTargets.sentence;
VDO is this vessel's own transponder and is ignored. Multi-part messages are put back together; position
reports and static data are merged per MMSI. `features()` gives the targets in the same shape as
the online AIS overlay (/api/ais), so the map draws both the same way (online.js drawAis).

Decoded: 1/2/3 (Class A position), 4 (base station), 5 (Class A static and voyage), 9 (SAR aircraft),
18/19 (Class B position), 21 (aid to navigation), 24 (Class B static). Other types are counted and ignored.
"""
from __future__ import annotations

import time

SIXBIT_TEXT = "@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_ !\"#$%&'()*+,-./0123456789:;<=>?"
PART_TIMEOUT_S = 10          # a multi-part message whose parts don't all arrive in this time is dropped
MAX_AGE_S = {"vessel": 20 * 60, "sar": 10 * 60, "aton": 30 * 60, "base": 30 * 60}   # then a target is dropped
MAX_TARGETS = 5000


def payload_bits(payload: str, fill: int = 0) -> str:
    out = []
    for ch in payload:
        v = ord(ch) - 48
        if v > 40:
            v -= 8
        if not 0 <= v < 64:
            raise ValueError("bad AIS payload character")
        out.append(format(v, "06b"))
    bits = "".join(out)
    return bits[:len(bits) - fill] if fill else bits


def _u(bits: str, start: int, n: int) -> int | None:
    s = bits[start:start + n]
    return int(s, 2) if len(s) == n else None


def _s(bits: str, start: int, n: int) -> int | None:
    v = _u(bits, start, n)
    if v is None:
        return None
    return v - (1 << n) if v & (1 << (n - 1)) else v


def _text(bits: str, start: int, n: int) -> str:
    chars = []
    for i in range(start, start + n, 6):
        v = _u(bits, i, 6)
        if v is None:
            break
        chars.append(SIXBIT_TEXT[v])
    return "".join(chars).split("@")[0].strip()


def _pos(bits: str, lon_at: int, lat_at: int) -> tuple[float | None, float | None]:
    lon, lat = _s(bits, lon_at, 28), _s(bits, lat_at, 27)
    if lon is None or lat is None:
        return None, None
    lon, lat = lon / 600000.0, lat / 600000.0
    if not (-180 <= lon <= 180 and -90 <= lat <= 90) or (lon == 0 and lat == 0):
        return None, None          # 181 / 91 = not available
    return round(lat, 6), round(lon, 6)


def _sog(v: int | None, scale: float = 10.0) -> float | None:
    return None if v is None or v >= 1023 else round(v / scale, 1)


def _cog(v: int | None) -> float | None:
    return None if v is None or v >= 3600 else round(v / 10.0, 1)


def _hdg(v: int | None) -> int | None:
    return None if v is None or v >= 360 else v


def decode(bits: str) -> dict | None:
    """One assembled AIS message → a dict of what it says (mmsi, msg, and the fields it has), or None."""
    t = _u(bits, 0, 6)
    mmsi = _u(bits, 8, 30)
    if t is None or mmsi is None:
        return None
    d: dict = {"msg": t, "mmsi": mmsi}
    if t in (1, 2, 3):
        if len(bits) < 137:
            return None
        lat, lon = _pos(bits, 61, 89)
        d.update(kind="vessel", cls="A", nav_status=_u(bits, 38, 4), sog=_sog(_u(bits, 50, 10)), lat=lat, lon=lon,
                 cog=_cog(_u(bits, 116, 12)), heading=_hdg(_u(bits, 128, 9)))
        if d["nav_status"] == 15:
            d["nav_status"] = None
    elif t == 4:
        lat, lon = _pos(bits, 79, 107)
        d.update(kind="base", lat=lat, lon=lon)
    elif t == 5:
        if len(bits) < 420:
            return None
        d.update(kind="vessel", cls="A", callsign=_text(bits, 70, 42), name=_text(bits, 112, 120), type=_u(bits, 232, 8),
                 length=(_u(bits, 240, 9) or 0) + (_u(bits, 249, 9) or 0) or None,
                 beam=(_u(bits, 258, 6) or 0) + (_u(bits, 264, 6) or 0) or None,
                 draught=(_u(bits, 294, 8) or 0) / 10 or None, destination=_text(bits, 302, 120))
    elif t == 9:
        lat, lon = _pos(bits, 61, 89)
        d.update(kind="sar", sog=_sog(_u(bits, 50, 10), 1.0), lat=lat, lon=lon, cog=_cog(_u(bits, 116, 12)))
    elif t in (18, 19):
        if len(bits) < 133:
            return None
        lat, lon = _pos(bits, 57, 85)
        d.update(kind="vessel", cls="B", sog=_sog(_u(bits, 46, 10)), lat=lat, lon=lon,
                 cog=_cog(_u(bits, 112, 12)), heading=_hdg(_u(bits, 124, 9)))
        if t == 19 and len(bits) >= 271:
            d.update(name=_text(bits, 143, 120), type=_u(bits, 263, 8))
    elif t == 21:
        if len(bits) < 219:
            return None
        lat, lon = _pos(bits, 164, 192)
        d.update(kind="aton", aid_type=_u(bits, 38, 5), name=_text(bits, 43, 120), lat=lat, lon=lon)
    elif t == 24:
        part = _u(bits, 38, 2)
        if part == 0:
            d.update(name=_text(bits, 40, 120))
        elif part == 1:
            d.update(type=_u(bits, 40, 8), callsign=_text(bits, 90, 42),
                     length=(_u(bits, 132, 9) or 0) + (_u(bits, 141, 9) or 0) or None,
                     beam=(_u(bits, 150, 6) or 0) + (_u(bits, 156, 6) or 0) or None)
        else:
            return None
        d["cls"] = "B"
    else:
        return None
    return {k: v for k, v in d.items() if v not in (None, "")}


class AisTargets:
    """The AIS targets heard on the NMEA inputs, by MMSI."""

    def __init__(self):
        self.targets: dict[int, dict] = {}
        self._parts: dict[tuple, dict] = {}
        self.messages = 0          # assembled messages decoded
        self.errors = 0
        self.heard: dict[str, float] = {}     # input name → wall clock of its last AIS sentence
        self.last = None

    def sentence(self, f: list[str], source: str = "", now: float | None = None) -> bool:
        """The fields of one VDM sentence after the address (total, number, sequence id, channel,
        payload, fill bits)."""
        now = time.time() if now is None else now
        try:
            total, num = int(f[0]), int(f[1])
            seq, chan, payload = f[2], f[3], f[4]
            fill = int((f[5] or "0")[:1] or 0)
        except (IndexError, ValueError):
            self.errors += 1
            return False
        self.heard[source] = now
        if total < 1 or not 1 <= num <= total or total > 9:
            self.errors += 1
            return False
        if total == 1:
            bits = payload, fill
        else:
            key = (source, seq, chan)
            for k in [k for k, v in self._parts.items() if now - v["t"] > PART_TIMEOUT_S]:
                self._parts.pop(k, None)
            p = self._parts.get(key)
            if num == 1 or p is None or p["total"] != total:
                p = self._parts[key] = {"t": now, "total": total, "parts": {}}
            p["parts"][num] = (payload, fill)
            if len(p["parts"]) < total:
                return True
            self._parts.pop(key, None)
            bits = "".join(p["parts"][i][0] for i in range(1, total + 1)), p["parts"][total][1]
        try:
            d = decode(payload_bits(*bits))
        except ValueError:
            self.errors += 1
            return False
        if not d:
            return False
        self.messages += 1
        self.last = now
        self._merge(d, source, now)
        return True

    def _merge(self, d: dict, source: str, now: float):
        mmsi = d["mmsi"]
        t = self.targets.get(mmsi)
        if t is None:
            if len(self.targets) >= MAX_TARGETS:
                self.prune(now, force=True)
            t = self.targets[mmsi] = {"mmsi": mmsi, "kind": "vessel"}
        msg = d.pop("msg")
        if "lat" in d:
            t["seen"] = now                    # last position report
            t["source"] = source
        t["heard"] = now
        if msg in (1, 2, 3, 18, 19) and "heading" not in d:
            t.pop("heading", None)
        t.update(d)

    def prune(self, now: float | None = None, force: bool = False):
        now = time.time() if now is None else now
        for m in [m for m, t in self.targets.items() if now - t.get("heard", 0) > MAX_AGE_S.get(t.get("kind"), 1200)]:
            self.targets.pop(m, None)
        if force and len(self.targets) >= MAX_TARGETS:
            for m in sorted(self.targets, key=lambda m: self.targets[m].get("heard", 0))[:len(self.targets) // 10]:
                self.targets.pop(m, None)

    def features(self, now: float | None = None) -> list[dict]:
        """GeoJSON point features shaped like the online AIS overlay's (online.js drawAis)."""
        now = time.time() if now is None else now
        self.prune(now)
        out = []
        for t in self.targets.values():
            if "lat" not in t or "lon" not in t:
                continue
            props = {k: v for k, v in t.items() if k not in ("lat", "lon")}
            props["seen"] = int(t.get("seen", t.get("heard", now)))
            props["local"] = True
            out.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [t["lon"], t["lat"]]}, "properties": props})
        return out

    def status(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        with_pos = sum(1 for t in self.targets.values() if "lat" in t)
        return {"targets": with_pos, "messages": self.messages, "errors": self.errors,
                "last": self.last, "inputs": sorted(s for s, ts in self.heard.items() if now - ts < 120 and s)}
