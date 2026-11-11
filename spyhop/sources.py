"""NMEA input sources: serial, UDP, TCP, gpsd, log-file replay and a simulator.

Each source is described by a small dict (stored in spyhop-local.json; network ones also in templates/current/spyhop-config.json), e.g.
    {"type": "serial", "port": "COM3", "baud": 4800}
    {"type": "udp", "port": 10110}
    {"type": "tcp", "host": "192.168.1.10", "port": 10110}
    {"type": "gpsd", "host": "127.0.0.1", "port": 2947}
    {"type": "file", "path": "/path/to/log.nmea", "speed": 1}
    {"type": "sim", "lat": 41.9, "lon": -70.33, "speed_kn": 10, "heading": 0, "rate": 1}
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import threading
import os
import time
from datetime import datetime, timezone

from . import geo
from .nmea import NmeaDecoder, with_checksum

log = logging.getLogger(__name__)


def label(src: dict) -> str:
    """The input's name (0.41), or a description of it."""
    return str(src.get("name") or "").strip() or describe(src)


def describe(src: dict) -> str:
    t = src.get("type")
    if t == "serial":
        return f"Serial {src.get('port')} @ {src.get('baud', 4800)}"
    if t == "udp":
        return f"UDP port {src.get('port', 10110)}"
    if t in ("tcp", "gpsd"):
        return f"{t.upper()} {src.get('host', '127.0.0.1')}:{src.get('port')}"
    if t == "file":
        return f"Replay {src.get('path')}"
    if t == "sim":
        return "Simulator"
    return str(t)


def clean_path(p: str) -> str:
    """A pasted file path as the computer means it: no surrounding quotes or spaces
    (Windows' "Copy as path" adds quotes), with ~ expanded."""
    p = (p or "").strip()
    if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'":
        p = p[1:-1].strip()
    return os.path.expanduser(p) if p else ""


def _sentence_time(ln: str, last_t: float | None) -> float | None:
    """Seconds of the day from an RMC, GGA, ZDA or GLL sentence (None for others)."""
    kind = ln[3:6]
    if kind not in ("RMC", "GGA", "ZDA", "GLL"):
        return None
    f = ln.split("*")[0].split(",")
    v = f[5] if kind == "GLL" and len(f) > 5 else (f[1] if len(f) > 1 else "")
    if not re.fullmatch(r"\d{6}(?:\.\d+)?", v):
        return None
    t = int(v[0:2]) * 3600 + int(v[2:4]) * 60 + float(v[4:])
    if last_t is not None and t < (last_t % 86400) - 43200:     # past midnight
        t += 86400
    return t + (last_t // 86400) * 86400 if last_t is not None and last_t >= 86400 else t


# a Spyhop raw-log line: <UTC ISO time><TAB><input><TAB><sentence>
_LOG_STAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)Z?\t")


def list_serial_ports() -> list[dict]:
    try:
        from serial.tools import list_ports  # type: ignore
    except ImportError:
        return []
    return [{"device": p.device, "description": p.description or ""}
            for p in list_ports.comports()]


class SourceManager:
    """Runs the configured sources, feeding every line to one decoder."""

    def __init__(self, decoder: NmeaDecoder):
        self.decoder = decoder
        self.tasks: list[asyncio.Task] = []
        self.status: dict[int, dict] = {}
        self._stop_threads = threading.Event()
        self._sims: dict[tuple, "Simulator"] = {}   # kept across restarts, keyed by start point
        self.on_map: set[str] = set()

    async def start(self, sources: list[dict], failover: bool = False):
        """Run the inputs in use. The one marked primary supplies the vessel's position (0.41); with none
        marked, every input does, by their order. Secondaries with show_on_map are listed in self.on_map."""
        await self.stop()
        self._stop_threads = threading.Event()
        self.status = {}
        on = [s for s in sources if s.get("enabled", True)]
        self.decoder.priority = {label(s): i for i, s in enumerate(on)}
        prim = next((s for s in on if s.get("primary")), None)
        self.decoder.primary = label(prim) if prim else None
        self.decoder.failover = bool(failover)
        self.decoder.others = {}
        self.decoder.inst_src = {}
        self.on_map = {label(s) for s in on if s is not prim and s.get("show_on_map")}
        for i, src in enumerate(sources):
            if not src.get("enabled", True):
                continue
            self.status[i] = {"name": label(src), "state": "starting", "lines": 0, "error": "",
                              "role": "primary" if src is prim or prim is None else "secondary", "type": src.get("type")}
            runner = getattr(self, "_run_" + str(src.get("type")), None)
            if runner is None:
                self.status[i].update(state="error", error="unknown source type")
                continue
            self.tasks.append(asyncio.create_task(self._guard(i, runner, src)))

    async def stop(self):
        self._stop_threads.set()
        for t in self.tasks:
            t.cancel()
        for t in self.tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self.tasks = []

    def _line(self, i: int, line: str):
        st = self.status.get(i)
        if st is not None:
            st["lines"] += 1
            st["state"] = "receiving"
            st["last"] = time.time()
        self.decoder.feed(line, source=st["name"] if st else "")

    async def _guard(self, i, runner, src):
        """Run a source forever, reconnecting after errors."""
        while True:
            try:
                await runner(i, src)
                if src.get("type") in ("file",):
                    self.status[i]["state"] = "finished"
                    return
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                self.status[i].update(state="error", error=str(e))
                log.warning("NMEA source %s: %s", describe(src), e)
            await asyncio.sleep(3)

    # -- serial ------------------------------------------------------------
    async def _run_serial(self, i, src):
        import serial  # type: ignore
        loop = asyncio.get_running_loop()
        stop = self._stop_threads
        port = serial.Serial(src["port"], int(src.get("baud", 4800)), timeout=1)
        self.status[i].update(state="connected", error="")

        def reader():
            buf = b""
            try:
                while not stop.is_set():
                    chunk = port.read(port.in_waiting or 1)
                    if not chunk:
                        continue
                    buf += chunk
                    while b"\n" in buf:
                        ln, buf = buf.split(b"\n", 1)
                        loop.call_soon_threadsafe(self._line, i, ln.decode("ascii", "ignore"))
            finally:
                port.close()

        await loop.run_in_executor(None, reader)

    # -- UDP ---------------------------------------------------------------
    async def _run_udp(self, i, src):
        loop = asyncio.get_running_loop()
        mgr = self

        class Proto(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                for ln in data.decode("ascii", "ignore").splitlines():
                    mgr._line(i, ln)

        transport, _ = await loop.create_datagram_endpoint(
            Proto, local_addr=(src.get("bind", "0.0.0.0"), int(src.get("port", 10110))),
            allow_broadcast=True)
        self.status[i].update(state="listening", error="")
        try:
            await asyncio.Future()
        finally:
            transport.close()

    # -- TCP / gpsd ----------------------------------------------------------
    async def _run_tcp(self, i, src, hello: bytes | None = None):
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(src.get("host", "127.0.0.1"), int(src.get("port", 10110))), 10)
        self.status[i].update(state="connected", error="")
        if hello:
            writer.write(hello)
            await writer.drain()
        try:
            while True:
                ln = await reader.readline()
                if not ln:
                    raise ConnectionError("connection closed")
                self._line(i, ln.decode("ascii", "ignore"))
        finally:
            writer.close()

    async def _run_gpsd(self, i, src):
        src = {"port": 2947, **src}
        await self._run_tcp(i, src, hello=b'?WATCH={"enable":true,"nmea":true};\n')

    # -- file replay ---------------------------------------------------------
    async def _run_file(self, i, src):
        """Replay an NMEA log at its own pace (× speed). Reads Spyhop's raw logs (time stamp, input
        name and sentence on each line; paced by those time stamps) and plain NMEA files (paced by the
        RMC/GGA/GLL/ZDA times). Gaps longer than a minute are skipped."""
        speed = float(src.get("speed", 1) or 1)
        if speed <= 0:
            speed = 1
        loop = bool(src.get("loop", True))
        path = clean_path(str(src.get("path") or ""))
        if not path:
            raise FileNotFoundError("no file chosen")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"no file at {path}")
        while True:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                lines = fh.readlines()
            n = len(lines)
            self.status[i].update(state="replaying", error="", total=n)
            last_t = None
            for k, ln in enumerate(lines):
                t = None
                m = _LOG_STAMP.match(ln)
                if m:
                    try:
                        t = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc).timestamp()
                    except ValueError:
                        t = None
                # the sentence starts at the first $ or ! (after any time stamp and input name)
                j = min((x for x in (ln.find("$"), ln.find("!")) if x >= 0), default=-1)
                if j < 0:
                    continue
                ln = ln[j:].strip()
                if t is None:
                    t = _sentence_time(ln, last_t)
                if t is not None:
                    if last_t is not None and 0 < t - last_t < 60:
                        await asyncio.sleep((t - last_t) / speed)
                    if last_t is None or t >= last_t or last_t - t > 60:
                        last_t = t
                self._line(i, ln)
                self.status[i]["at"] = k + 1
                if k % 500 == 499:
                    await asyncio.sleep(0)       # a log with no times at all mustn't hold up the server
            if not loop:
                return
            self.status[i]["loops"] = self.status[i].get("loops", 0) + 1
            await asyncio.sleep(1)

    # -- simulator -----------------------------------------------------------
    async def _run_sim(self, i, src):
        start = (float(src.get("lat", 41.90)), float(src.get("lon", -70.33)))
        heading = float(src.get("heading", 0) or 0)
        speed = float(src.get("speed_kn", 10))
        sim = self._sims.get(start)
        if sim is None:
            sim = Simulator(lat=start[0], lon=start[1], speed_kn=speed, heading=heading)
            self._sims[start] = sim
        else:
            # same start point as before: keep going from where the boat is now
            sim.speed, sim.heading = speed, heading % 360
        rate = float(src.get("rate", 1) or 1)  # time acceleration
        self.status[i].update(state="simulating", error="")
        while True:
            for s in sim.step(1.0 * rate):
                self._line(i, s)
            await asyncio.sleep(1.0)


class Simulator:
    """A simulated vessel steaming on a fixed heading at a fixed speed."""

    def __init__(self, lat=41.90, lon=-70.33, speed_kn=10.0, heading=0.0):
        self.lat, self.lon = lat, lon
        self.speed = float(speed_kn)
        self.heading = float(heading) % 360
        self.t = time.time()

    def step(self, dt: float) -> list[str]:
        dist = self.speed * 1852 / 3600 * dt
        self.lat, self.lon = geo.destination(self.lat, self.lon, self.heading, dist)
        self.t += dt
        return self.sentences()

    def sentences(self) -> list[str]:
        now = datetime.now(timezone.utc)
        hms = now.strftime("%H%M%S") + ".00"
        dmy = now.strftime("%d%m%y")

        def ll(v, is_lat):
            h = ("N" if v >= 0 else "S") if is_lat else ("E" if v >= 0 else "W")
            a = abs(v)
            d = int(a)
            m = (a - d) * 60
            return (f"{d:02d}{m:07.4f}" if is_lat else f"{d:03d}{m:07.4f}"), h

        la, lah = ll(self.lat, True)
        lo, loh = ll(self.lon, False)
        sog = self.speed
        cog = self.heading
        return [
            with_checksum(f"GPRMC,{hms},A,{la},{lah},{lo},{loh},{sog:.1f},{cog:.1f},{dmy},14.5,W,A"),
            with_checksum(f"GPGGA,{hms},{la},{lah},{lo},{loh},1,09,0.9,5.0,M,-33.0,M,,"),
            with_checksum(f"HEHDT,{self.heading:.1f},T"),
        ] + self.instrument_sentences()

    def instrument_sentences(self) -> list[str]:
        """Made-up but plausible depth, wind, weather and engine readings for practice."""
        t = self.t
        depth = 45 + 12 * math.sin(t / 400)
        tws = 12 + 3 * math.sin(t / 97)
        twd = (225 + 15 * math.sin(t / 300)) % 360
        twa = (twd - self.heading) % 360
        # apparent wind from true wind and the boat's own motion
        tx, ty = tws * math.sin(math.radians(twa)), tws * math.cos(math.radians(twa)) + self.speed
        aws, awa = math.hypot(tx, ty), math.degrees(math.atan2(tx, ty)) % 360
        air, water = 14.2 + 0.5 * math.sin(t / 900), 12.4 + 0.2 * math.sin(t / 1200)
        return [
            with_checksum(f"SDDPT,{depth:.1f},0.5,"),
            with_checksum(f"WIMWV,{awa:.1f},R,{aws:.1f},N,A"),
            with_checksum(f"WIMWV,{twa:.1f},T,{tws:.1f},N,A"),
            with_checksum(f"YXMTW,{water:.1f},C"),
            with_checksum(f"WIMDA,29.92,I,1.0132,B,{air:.1f},C,{water:.1f},C,78.0,,10.3,C,{twd:.0f},T,{(twd + 14.5) % 360:.0f},M,{tws:.1f},N,{tws / 1.9438:.1f},M"),
            with_checksum(f"VWVHW,{self.heading:.1f},T,{(self.heading + 14.5) % 360:.1f},M,{self.speed:.1f},N,{self.speed * 1.852:.1f},K"),
            with_checksum(f"ERRPM,E,1,{1400 + 10 * self.speed:.0f},,A"),
        ]
