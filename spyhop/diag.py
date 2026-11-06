"""Diagnostic logs: what Spyhop did, how fast it was, and what went wrong.

Everything goes to <Spyhop folder>/logs/:
  spyhop.log      the main log, rotated at 5 MB (spyhop.log.1 … .5 are older)
  crash.log       Python tracebacks from hard crashes (faulthandler)

The log has a start-up header (version, Python, system, folders), survey actions,
errors with tracebacks (server and the Spyhop window), slow moments, and a
performance snapshot every 5 minutes. It never contains survey data values.

Save diagnostics… (Survey → File) zips the logs, settings and system details
for a bug report: see make_bundle().
"""
from __future__ import annotations

import faulthandler
import io
import json
import logging
import logging.handlers
import os
import platform
import sys
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from . import VERSION_DATE, __version__

log = logging.getLogger("spyhop.diag")
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_crash_fh = None


def log_dir(root: Path) -> Path:
    return root / "logs"


def setup(root: Path, verbose: bool = False) -> Path:
    """Log to the Terminal and to logs/spyhop.log; catch crashes. Returns the logs folder."""
    global _crash_fh
    d = log_dir(root)
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(d / "spyhop.log", maxBytes=5 * 1024 ** 2, backupCount=5,
                                                  encoding="utf-8")
        fh.setFormatter(logging.Formatter(FORMAT))
        handlers.append(fh)
    except OSError as e:
        print(f"Couldn't write diagnostic logs to {d}: {e}")
    logging.basicConfig(level=level, format=FORMAT, handlers=handlers, force=True)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

    # hard crashes (segfaults, fatal errors) write a traceback here
    try:
        _crash_fh = open(d / "crash.log", "a", encoding="utf-8")
        _crash_fh.write(f"\n--- Spyhop {__version__} started {datetime.now().isoformat(timespec='seconds')} ---\n")
        _crash_fh.flush()
        faulthandler.enable(file=_crash_fh, all_threads=True)
    except OSError:
        pass

    def excepthook(t, v, tb):
        if issubclass(t, KeyboardInterrupt):
            return sys.__excepthook__(t, v, tb)
        logging.getLogger("spyhop.crash").critical("Spyhop stopped because of an error", exc_info=(t, v, tb))

    sys.excepthook = excepthook
    threading.excepthook = lambda a: logging.getLogger("spyhop.crash").error(
        "error in background thread %s", a.thread.name if a.thread else "?", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))
    return d


def system_info(root: Path, data_dir: Path | None = None) -> dict:
    def ver(mod):
        try:
            return __import__(mod).__version__
        except Exception:  # noqa: BLE001
            return "not installed"
    return {
        "spyhop": __version__, "spyhop_date": VERSION_DATE,
        "python": sys.version.split()[0], "python_path": sys.executable,
        "system": f"{platform.system()} {platform.release()} ({platform.platform()})",
        "machine": platform.machine(), "processor_count": os.cpu_count(),
        "aiohttp": ver("aiohttp"), "pyserial": ver("serial"), "pygeomag": ver("pygeomag"),
        "spyhop_folder": str(root), "data_folder": str(data_dir or ""), "program_folder": str(Path(__file__).parent.parent),
    }


def log_startup(root: Path, data_dir: Path, settings: dict, argv: list[str]):
    info = system_info(root, data_dir)
    log.info("==== Spyhop %s (%s) starting ====", __version__, VERSION_DATE)
    for k, v in info.items():
        log.info("  %-16s %s", k, v)
    log.info("  %-16s %s", "command", " ".join(argv) or "(none)")
    srcs = [f"{s.get('type')}{'' if s.get('enabled', True) else ' (off)'}" for s in settings.get("nmea_sources") or []]
    log.info("  %-16s inputs: %s; tracking every %ss; clock %s; view %s", "settings", ", ".join(srcs) or "none",
             settings.get("tracking_interval"), settings.get("clock", "local"), settings.get("view"))


class PerfMonitor:
    """Measures the event loop and requests; logs a snapshot every PERIOD_S seconds."""
    PERIOD_S = 300

    def __init__(self):
        self.reset()
        self._cpu0 = time.process_time()
        self._t0 = time.time()

    def reset(self):
        self.lag_max = 0.0
        self.lag_sum = 0.0
        self.lag_n = 0
        self.requests = 0
        self.slowest = (0.0, "")
        self.lines = 0

    def loop_lag(self, ms: float):
        self.lag_max = max(self.lag_max, ms)
        self.lag_sum += ms
        self.lag_n += 1

    def request(self, path: str, ms: float):
        self.requests += 1
        if ms > self.slowest[0]:
            self.slowest = (ms, path)

    def snapshot(self, extra: dict) -> str:
        now, cpu = time.time(), time.process_time()
        wall = max(now - self._t0, 1e-6)
        cpu_pct = 100 * (cpu - self._cpu0) / wall
        self._cpu0, self._t0 = cpu, now
        mem = memory_mb()
        parts = [f"cpu {cpu_pct:.1f}%", f"memory {mem:.0f} MB" if mem else "memory ?",
                 f"loop lag avg {self.lag_sum / max(self.lag_n, 1):.1f} ms max {self.lag_max:.0f} ms",
                 f"{self.requests} requests" + (f" (slowest {self.slowest[0]:.0f} ms {self.slowest[1]})" if self.requests else ""),
                 f"nmea {self.lines / wall:.1f} lines/s"]
        parts += [f"{k} {v}" for k, v in extra.items()]
        self.reset()
        return ", ".join(parts)


def memory_mb() -> float | None:
    """Current memory use of this process, if the system lets us read it cheaply."""
    try:
        with open("/proc/self/statm") as f:                     # Linux
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
    except (OSError, ValueError, AttributeError):
        pass
    try:
        import resource                                          # macOS: peak, in bytes
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return r / 1e6 if sys.platform == "darwin" else r / 1e3
    except Exception:  # noqa: BLE001 — Windows has no resource module
        pass
    try:
        import ctypes                                            # Windows: working set
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        c = PMC()
        c.cb = ctypes.sizeof(c)
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(c), c.cb):
            return c.WorkingSetSize / 1e6
    except Exception:  # noqa: BLE001
        pass
    return None


SAFE_CONFIG = ["display.csv", "shortcuts.csv", "tile_sources.csv"]


def make_bundle(root: Path, data_dir: Path, settings_path: Path, extra: dict, dest: Path) -> Path:
    """Zip the logs, settings and system details (no survey data) for a bug report."""
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"spyhop_diagnostics_{__version__}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        info = system_info(root, data_dir) | extra
        z.writestr("system.txt", "\n".join(f"{k}: {v}" for k, v in info.items()) + "\n")
        for p in sorted(log_dir(root).glob("*.log*")):
            z.write(p, f"logs/{p.name}")
        try:
            s = json.loads(settings_path.read_text(encoding="utf-8"))
            s.pop("last_meta", None)                  # names and email of the survey team
            z.writestr("settings.json", json.dumps(s, indent=2))
        except (OSError, ValueError):
            pass
        for name in SAFE_CONFIG:
            p = root / name
            if p.exists():
                z.write(p, f"config/{name}")
        z.writestr("README.txt", io.StringIO(
            "Spyhop diagnostics bundle. It holds Spyhop's logs, its settings (without survey team names),\n"
            "display/shortcut/map settings and system details. It does not hold any survey data.\n").getvalue())
    return out
