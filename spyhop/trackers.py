"""Satellite trackers as "other" inputs (0.55): Globalstar SPOT (SPOT Gen4, SPOT Trace…) XML feeds and
Garmin inReach MapShare KML feeds, polled over the internet in the background (never on the NMEA path).

Input kinds (Settings → Inputs; always role "other"):
    {"type": "spot", "feed_id": "0onl…", "password": "", "interval": 300}
    {"type": "inreach", "mapshare": "MyName", "password": "", "interval": 300}
A feed may hold several devices: each one is its own "other" source on the map and in the survey folder,
named after the device. Fixes keep the device's own time (not when Spyhop heard of them); duplicates are
skipped by message ID and time, and a gap is caught up on the next poll (SPOT: startDate; inReach: d1).
Passwords are this computer's (templates leave them out, see config.input_definition) and never logged.

SPOT asks for no more than one request per feed every 2.5 minutes and 2 seconds between requests for
different feeds (MIN_SPOT_INTERVAL, SPOT_GAP_S). No internet only means "no internet connection" in the
status line: requests have a timeout and run on their own tasks.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote

import aiohttp

log = logging.getLogger("spyhop.trackers")

TYPES = ("spot", "inreach")
MIN_SPOT_INTERVAL = 150            # s, per feed (SPOT's rule)
MIN_INREACH_INTERVAL = 60
DEFAULT_INTERVAL = 300
SPOT_GAP_S = 2.0                   # between any two SPOT requests
TIMEOUT_S = 20
FIRST_LOOKBACK_S = 24 * 3600       # with no fix known yet, ask for the last day
SPOT_BASE = os.environ.get("SPYHOP_SPOT_BASE") or "https://api.findmespot.com/spot-main-web/consumer/rest-api/2.0/public/feed"
INREACH_BASE = os.environ.get("SPYHOP_INREACH_BASE") or "https://share.garmin.com/Feed/Share"     # (the variables: tests only)
KML_NS = "{http://www.opengis.net/kml/2.2}"


def is_tracker(src: dict) -> bool:
    return (src or {}).get("type") in TYPES


def clean_tracker(x: dict):
    """In place: role other, the feed's ID or MapShare name trimmed, the interval within the limits."""
    x["role"] = "other"
    if x.get("type") == "spot":
        x["feed_id"] = re.sub(r"\s+", "", str(x.get("feed_id") or ""))
        m = re.search(r"/feed/([^/?#]+)", x["feed_id"])          # a pasted feed address: keep its ID
        if m:
            x["feed_id"] = m.group(1)
        low = MIN_SPOT_INTERVAL
    else:
        name = str(x.get("mapshare") or "").strip()
        m = re.search(r"share\.garmin\.com/(?:Feed/Share/|feed/share/)?([^/?#\s]+)", name, re.I)
        x["mapshare"] = m.group(1) if m else name.strip("/")
        low = MIN_INREACH_INTERVAL
    try:
        iv = int(float(x.get("interval") or DEFAULT_INTERVAL))
    except (TypeError, ValueError):
        iv = DEFAULT_INTERVAL
    x["interval"] = max(low, min(24 * 3600, iv))
    x["password"] = str(x.get("password") or "")


def describe(src: dict) -> str:
    if src.get("type") == "spot":
        return f"SPOT feed {str(src.get('feed_id') or '')[:8]}…" if src.get("feed_id") else "SPOT feed"
    return f"inReach {src.get('mapshare') or ''}".strip()


# ------------------------------------------------------------------ SPOT
def spot_url(src: dict, start: float | None = None, page_start: int = 0) -> str:
    """message.json (the last 50 messages, or those since `start`), with the password if there is one."""
    q = []
    if src.get("password"):
        q.append("feedPassword=" + quote(src["password"]))
    if start:
        fmt = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S-0000")  # noqa: E731
        q += ["startDate=" + fmt(start), "endDate=" + fmt(time.time() + 60)]
    if page_start:
        q.append(f"start={page_start}")
    return f"{SPOT_BASE}/{quote(src.get('feed_id') or '')}/message.json" + ("?" + "&".join(q) if q else "")


class FeedError(Exception):
    """A message for the status line."""


def parse_spot(doc) -> tuple[list[dict], int]:
    """SPOT's message.json / latest.json → ([fix], messages in this page). Raises FeedError for its errors
    ("no messages" isn't one)."""
    if isinstance(doc, (str, bytes)):
        try:
            doc = json.loads(doc)
        except ValueError:
            raise FeedError("SPOT sent something that isn't a feed (try again later)")
    resp = (doc or {}).get("response") or {}
    err = (resp.get("errors") or {}).get("error")
    if err:
        if isinstance(err, list):
            err = err[0]
        code, text = str(err.get("code") or ""), f"{err.get('text') or ''} {err.get('description') or ''}".strip()
        if code == "E-0195" or "no messages" in text.lower() or "no displayable" in text.lower():
            return [], 0
        if "password" in text.lower():
            raise FeedError("this feed is password protected: type its password (or the password is wrong)")
        if code == "E-0160" or "not found" in text.lower():
            raise FeedError("no such feed: check the XML Feed ID (and that the feed is still active)")
        raise FeedError(f"SPOT: {text or code}")
    fr = resp.get("feedMessageResponse") or {}
    msgs = (fr.get("messages") or {}).get("message") or []
    if isinstance(msgs, dict):
        msgs = [msgs]
    out = []
    for m in msgs:
        try:
            lat, lon = float(m["latitude"]), float(m["longitude"])
            t = float(m.get("unixTime") or 0) or _iso(m.get("dateTime"))
        except (KeyError, TypeError, ValueError):
            continue
        if not t or (lat == 0 and lon == 0) or str(m.get("hidden") or "0") not in ("0", "false", "False"):
            continue
        out.append({"device": str(m.get("messengerName") or m.get("messengerId") or "SPOT").strip(),
                    "device_id": str(m.get("messengerId") or ""), "id": str(m.get("id") or f"{t:.0f}"),
                    "time": t, "lat": lat, "lon": lon, "kind": str(m.get("messageType") or ""),
                    "battery": str(m.get("batteryState") or ""), "sog": None, "cog": None})
    return out, len(msgs)


def _iso(s) -> float:
    try:
        s = str(s).strip().replace("Z", "+00:00")
        s = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", s)
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return 0.0


# ------------------------------------------------------------------ inReach
def inreach_url(src: dict, since: float | None) -> str:
    q = ""
    if since:
        q = "?d1=" + datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%Mz")
    return f"{INREACH_BASE}/{quote(src.get('mapshare') or '')}{q}"


def _num(s) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", str(s or ""))
    return float(m.group(0)) if m else None


def parse_inreach(text) -> list[dict]:
    """MapShare's Raw KML → [fix] (one per point Placemark; the track's LineString is left out)."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "replace")
    if "<kml" not in text[:2000].lower():
        raise FeedError("that isn't a MapShare feed: check the MapShare name, and that MapShare is on")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise FeedError("the MapShare feed couldn't be read (try again later)")
    out = []
    for pm in root.iter(f"{KML_NS}Placemark"):
        pt = pm.find(f".//{KML_NS}Point/{KML_NS}coordinates")
        if pt is None:
            continue
        data = {d.get("name"): (d.findtext(f"{KML_NS}value") or "").strip() for d in pm.iter(f"{KML_NS}Data")}
        if data.get("Valid GPS Fix", "True").lower() == "false":
            continue
        try:
            lon, lat = (float(v) for v in pt.text.strip().split(",")[:2])
            lat = float(data.get("Latitude") or lat)
            lon = float(data.get("Longitude") or lon)
        except (AttributeError, ValueError):
            continue
        t = _iso(pm.findtext(f".//{KML_NS}TimeStamp/{KML_NS}when"))
        if not t and data.get("Time UTC"):
            try:
                t = datetime.strptime(data["Time UTC"], "%m/%d/%Y %I:%M:%S %p").replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                t = 0
        if not t:
            continue
        v = _num(data.get("Velocity"))
        sog = None if v is None else (v / 1.852 if "km/h" in data.get("Velocity", "") else v * 0.868976 if "mph" in data.get("Velocity", "") else v)
        out.append({"device": data.get("Map Display Name") or data.get("Name") or data.get("IMEI") or "inReach",
                    "device_id": data.get("IMEI", ""), "id": data.get("Id") or f"{t:.0f}", "time": t, "lat": lat, "lon": lon,
                    "kind": data.get("Event", ""), "battery": "", "sog": sog, "cog": _num(data.get("Course"))})
    return out


# ------------------------------------------------------------------ the poller
class TrackerPoller:
    """Polls each tracker input in use; new fixes go to on_fixes(src, device_name, [fix]) (newest last).
    `last_time(device_name)` gives the newest fix already recorded (so a restart doesn't repeat any)."""

    def __init__(self, on_fixes, last_time=lambda name: None, on_devices=None):
        self.on_fixes, self.last_time, self.on_devices = on_fixes, last_time, on_devices
        self.tasks: list[asyncio.Task] = []
        self.status: dict[str, dict] = {}         # input name → status
        self.devices: dict[str, dict] = {}        # device (source) name → {feed, latest fix}
        self.session: aiohttp.ClientSession | None = None
        self._spot_lock = asyncio.Lock()
        self._spot_last = 0.0
        self._seen: dict[str, set] = {}
        self._newest: dict[str, float] = {}
        self._polled: dict[tuple, float] = {}     # (type, feed) → when it was last asked (kept across restarts)
        self.fetch = self._fetch                   # tests replace this: (url, password) → (status, text)

    async def start(self, sources: list[dict]):
        await self.stop()
        self.status, self.devices = {}, {k: v for k, v in self.devices.items() if any(s.get("name") == v["feed"] for s in sources)}
        for src in sources:
            if not is_tracker(src) or src.get("enabled", True) is False:
                continue
            self.status[src["name"]] = {"name": src["name"], "type": src["type"], "role": "other", "state": "starting",
                                        "error": "", "last_poll": None, "last_fix": None, "devices": [], "tracker": True,
                                        "interval": src.get("interval"), "lines": 0}
            self.tasks.append(asyncio.create_task(self._run(src)))

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        for t in self.tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self.tasks = []

    async def close(self):
        await self.stop()
        if self.session and not self.session.closed:
            await self.session.close()

    def device_name(self, src: dict, device: str) -> str:
        """The source name of a device in a feed: the device's own name (made unique among the inputs)."""
        name = (device or "").strip() or src["name"]
        for d, info in self.devices.items():
            if d.lower() == name.lower() and info["feed"] != src["name"]:
                return f"{name} ({src['name']})"
        return name

    async def _fetch(self, url: str, password: str = "") -> tuple[int, str]:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT_S),
                                                 headers={"User-Agent": "Spyhop (marine mammal survey recorder)"})
        auth = aiohttp.BasicAuth("", password) if password else None
        async with self.session.get(url, auth=auth) as r:
            return r.status, await r.text(errors="replace")

    async def _get(self, src, url) -> tuple[int, str]:
        if src["type"] == "spot":
            async with self._spot_lock:              # 2 s between SPOT requests, whichever feeds they're for
                wait = self._spot_last + SPOT_GAP_S - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    return await self.fetch(url, "")
                finally:
                    self._spot_last = time.monotonic()
        return await self.fetch(url, src.get("password") or "")

    @staticmethod
    def _key(src) -> tuple:
        return src["type"], src.get("feed_id") or src.get("mapshare") or ""

    async def _run(self, src):
        st = self.status[src["name"]]
        # inputs applied again soon after a check: keep to the feed's minimum interval (SPOT's rule)
        low = MIN_SPOT_INTERVAL if src["type"] == "spot" else MIN_INREACH_INTERVAL
        wait = self._polled.get(self._key(src), -1e9) + low - time.monotonic()
        if wait > 0:
            st.update(state="waiting", next_poll=time.time() + wait)
            await asyncio.sleep(wait)
        while True:
            try:
                await self.poll(src)
                st.update(state="ok", error="")
            except asyncio.CancelledError:
                raise
            except FeedError as e:
                st.update(state="error", error=str(e))
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError, OSError) as e:
                st.update(state="error", error="no internet connection (Spyhop keeps trying)" if not isinstance(e, asyncio.TimeoutError)
                          else "the feed didn't answer in time (Spyhop keeps trying)")
            except Exception as e:  # noqa: BLE001
                log.warning("tracker %s: %s", src["name"], e)
                st.update(state="error", error=str(e))
            # SPOT's rule counts every request; an inReach check that failed (wrong password, bad name) can be retried at once
            if src["type"] == "spot" or st.get("state") == "ok":
                self._polled[self._key(src)] = time.monotonic()
            else:
                self._polled.pop(self._key(src), None)
            st["last_poll"] = time.time()
            st["next_poll"] = time.time() + src["interval"]
            await asyncio.sleep(src["interval"])

    def _since(self, src) -> float | None:
        known = [self._newest.get(d) or self.last_time(d) or 0 for d, v in self.devices.items() if v["feed"] == src["name"]]
        t = max(known) if known else 0
        return t or None

    async def poll(self, src):
        """One poll of a feed: fetch, parse, keep the new fixes, hand them on."""
        since = self._since(src)
        fixes: list[dict] = []
        if src["type"] == "spot":
            start = (since + 1) if since else None
            page = 0
            for _ in range(4):                     # 50 messages a page; a long gap takes a few
                status, text = await self._get(src, spot_url(src, start, page))
                if status >= 400:
                    raise FeedError(f"SPOT answered {status}" + (": check the XML Feed ID" if status in (400, 404) else ""))
                got, n = parse_spot(text)
                fixes += got
                if n < 50 or not start:
                    break
                page += 50 if page else 51
        else:
            status, text = await self._get(src, inreach_url(src, since or time.time() - FIRST_LOOKBACK_S))
            if status == 401 or status == 403:
                raise FeedError("this MapShare page is password protected: type its password (or the password is wrong)")
            if status == 404:
                raise FeedError("no such MapShare page: check the MapShare name")
            if status >= 400:
                raise FeedError(f"Garmin answered {status}")
            fixes = parse_inreach(text)
        self.take(src, fixes)

    def take(self, src: dict, fixes: list[dict]) -> int:
        """Keep the fixes not seen before (by ID and time), per device, oldest first; returns how many."""
        st = self.status.setdefault(src["name"], {"name": src["name"], "type": src["type"], "role": "other", "devices": []})
        by: dict[str, list] = {}
        new_device = False
        for f in sorted(fixes, key=lambda f: f["time"]):
            name = self.device_name(src, f["device"])
            if name not in self.devices:
                self.devices[name] = {"feed": src["name"], "fix": None}
                new_device = True
            cur = self.devices[name]["fix"]
            if cur is None or f["time"] >= cur["time"]:
                self.devices[name]["fix"] = f          # the latest, for the map (recorded before or not)
            seen = self._seen.setdefault(name, set())
            newest = self._newest.get(name) or self.last_time(name) or 0
            if f["id"] in seen or f["time"] <= newest:
                continue
            seen.add(f["id"])
            if len(seen) > 2000:
                seen.clear()
            self._newest[name] = f["time"]
            by.setdefault(name, []).append(f)
        n = 0
        for name, fs in by.items():
            n += len(fs)
            self.on_fixes(src, name, fs)
        st["devices"] = sorted(d for d, v in self.devices.items() if v["feed"] == src["name"])
        last = [v["fix"]["time"] for v in self.devices.values() if v["feed"] == src["name"] and v["fix"]]
        st["last_fix"] = max(last) if last else st.get("last_fix")
        st["lines"] = st.get("lines", 0) + n
        if new_device and self.on_devices:
            self.on_devices()
        return n

    def latest(self) -> list[dict]:
        """Each device's latest fix, for the map: [{name, feed, lat, lon, sog, cog, heading, age, tracker}]."""
        now = time.time()
        out = []
        for name, v in self.devices.items():
            f = v["fix"]
            if not f:
                continue
            out.append({"name": name, "feed": v["feed"], "other": True, "tracker": True, "lat": f["lat"], "lon": f["lon"],
                        "sog": f.get("sog"), "cog": f.get("cog"), "heading": f.get("cog"), "age": round(now - f["time"], 1),
                        "battery": f.get("battery") or "", "kind": f.get("kind") or ""})
        return out
