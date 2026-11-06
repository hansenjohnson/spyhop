"""NMEA input sources: serial, UDP, TCP, gpsd, log-file replay and a simulator.

Each source is described by a small dict (stored in settings.json), e.g.
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
import time
from datetime import datetime, timezone

from . import geo
from .nmea import NmeaDecoder, with_checksum

log = logging.getLogger(__name__)


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

    async def start(self, sources: list[dict]):
        await self.stop()
        self._stop_threads = threading.Event()
        self.status = {}
        self.decoder.priority = {describe(s): i for i, s in enumerate(sources)}
        for i, src in enumerate(sources):
            if not src.get("enabled", True):
                continue
            self.status[i] = {"name": describe(src), "state": "starting", "lines": 0, "error": ""}
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
        speed = float(src.get("speed", 1) or 1)
        loop = bool(src.get("loop", True))
        while True:
            with open(src["path"], "r", errors="ignore") as fh:
                lines = fh.readlines()
            self.status[i].update(state="replaying", error="")
            last_t = None
            for ln in lines:
                # Spyhop's raw logs may start each line with a time stamp and the input name
                k = min((x for x in (ln.find("$"), ln.find("!")) if x >= 0), default=-1)
                if k > 0:
                    ln = ln[k:]
                m = re.match(r"^\$..(RMC|GGA),(\d{6}(?:\.\d+)?)", ln.strip())
                if m:
                    t = float(m.group(2)[0:2]) * 3600 + float(m.group(2)[2:4]) * 60 + float(m.group(2)[4:])
                    if last_t is not None and 0 < t - last_t < 60:
                        await asyncio.sleep((t - last_t) / speed)
                    last_t = t
                self._line(i, ln)
            if not loop:
                return
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
