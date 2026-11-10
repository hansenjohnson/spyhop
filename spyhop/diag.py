"""Diagnostic logs: what Spyhop did, how fast it was, and what went wrong.

Everything goes to <Spyhop folder>/logs/:
  spyhop.log      the main log, rotated at 5 MB (spyhop.log.1 … .5 are older)
  crash.log       Python tracebacks from hard crashes (faulthandler)

The log has a start-up header (version, Python, system, folders), survey actions,
errors with tracebacks (server and the Spyhop window), slow moments, and a
performance snapshot every 5 minutes. It never contains survey data values.

Save diagnostics… (Settings → About) zips the logs, settings, a listing of the
folders and system details for a bug report: see make_bundle().
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
    log.info("  %-16s inputs: %s; tracking every %ss; clock %s; panes %s", "settings", ", ".join(srcs) or "none",
             settings.get("tracking_interval"), settings.get("clock", "local"), settings.get("pane_layout") or "default")


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


# What a diagnostics bundle holds (no survey data, no people's names):
#   system.txt     versions, system, folders and what the window/inputs were doing
#   folders.txt    what is in Spyhop's folder and the data folder: names and sizes of the templates,
#                  maps, overlays, routes, feeds and logs; survey files only counted (their names are
#                  survey names, not data)
#   logs/          spyhop.log (and older rotations), crash.log
#   current/       the current template (templates/current): spyhop-config.json (web addresses' ?query
#                  removed, in case one holds a key), shortcuts.csv and the species, event and behavior
#                  lists (not observers.csv: names)
#   spyhop-local.json   this computer's settings, without the survey team's details
SAFE_CURRENT = ["spyhop-config.json", "shortcuts.csv", "species.csv", "event_types.csv", "behaviors.csv"]
# Spyhop's folder (config.Config, feeds.feeds_dir)
SPYHOP_FOLDERS = [("templates", "the current template (current/), saved templates (saved/) and backups (backups/)"),
                  ("charts", "offline maps (.mbtiles), downloaded in Settings → Basemap or added"),
                  ("overlays", "map overlays (GeoJSON, GPX, KML) from Tools → Overlays"),
                  ("routes", "saved routes (GPX), Tools → Routes"),
                  ("feeds", "online overlay feeds (GeoJSON kept for offline use)"),
                  ("tile_cache", "online map tiles kept for offline use"),
                  ("logs", "these logs")]
DATA_FOLDERS = [("nmea_logs", "raw NMEA logs"), ("exports", "exports and reports")]


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def _tree(d: Path, names: bool = True, depth: int = 2, limit: int = 60) -> list[str]:
    """Lines describing a folder: its files (names and sizes, or just a count) and sub-folders."""
    if not d.is_dir():
        return ["    (missing)"]
    out, files, total = [], [], 0
    try:
        entries = sorted(d.iterdir(), key=lambda p: (p.is_dir(), p.name.lower()))
    except OSError as e:
        return [f"    (can't read: {e})"]
    for p in entries:
        try:
            if p.is_dir():
                if depth > 1:
                    sub = _tree(p, names, depth - 1, limit)
                    out.append(f"    {p.name}/")
                    out += ["  " + x for x in sub]
                else:
                    n = sum(1 for _ in p.rglob("*"))
                    out.append(f"    {p.name}/  ({n} items)")
            else:
                sz = p.stat().st_size
                total += sz
                files.append((p.name, sz))
        except OSError:
            continue
    if names:
        out = [f"    {n}  {_size(z)}" for n, z in files[:limit]] + \
              ([f"    … and {len(files) - limit} more files"] if len(files) > limit else []) + out
    else:
        out = [f"    {len(files)} files, {_size(total)}"] + out
    return out


def folder_report(root: Path, data_dir: Path) -> str:
    lines = [f"Spyhop folder: {root}"]
    top = [p for p in sorted(root.glob("*")) if p.is_file()] if root.is_dir() else []
    lines += [f"    {p.name}  {_size(p.stat().st_size)}" for p in top]
    for name, what in SPYHOP_FOLDERS:
        lines.append(f"  {name}/  — {what}")
        lines += _tree(root / name, names=name != "tile_cache", depth=1 if name == "tile_cache" else 3)
    lines.append("")
    lines.append(f"Data folder: {data_dir}" + ("  (the default, inside the Spyhop folder)" if data_dir == root / "data" else ""))
    for name, what in DATA_FOLDERS:
        lines.append(f"  {name}/  — {what}")
        lines += _tree(data_dir / name, names=False)
    other = [p for p in sorted(data_dir.glob("*")) if p.name not in {n for n, _ in DATA_FOLDERS}] if data_dir.is_dir() else []
    nfiles = sum(1 for p in other if p.is_file())
    size = sum(p.stat().st_size for p in other if p.is_file())
    lines.append(f"  survey files and waypoints: {nfiles} files, {_size(size)} (names not listed)")
    dirs = [p for p in other if p.is_dir()]
    if dirs:
        lines.append(f"  other folders: {len(dirs)}")
    return "\n".join(lines) + "\n"


def _redact(v):
    """Drop the ?query part of web addresses (it may hold an access key)."""
    if isinstance(v, str):
        return v.split("?", 1)[0] + "?…" if "://" in v and "?" in v else v
    if isinstance(v, list):
        return [_redact(x) for x in v]
    if isinstance(v, dict):
        return {k: _redact(x) for k, x in v.items()}
    return v


def make_bundle(cfg, extra: dict, dest: Path) -> Path:
    """Zip the logs, the current template, this computer's settings, the folder layout and system details
    (no survey data) for a bug report."""
    root, data_dir = Path(cfg.root), Path(cfg.data_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"spyhop_diagnostics_{__version__}_{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        info = system_info(root, data_dir) | extra
        z.writestr("system.txt", "\n".join(f"{k}: {v}" for k, v in info.items()) + "\n")
        try:
            z.writestr("folders.txt", folder_report(root, data_dir))
        except Exception as e:  # noqa: BLE001 — the report must still be made
            z.writestr("folders.txt", f"(couldn't list the folders: {e})\n")
        for p in sorted(log_dir(root).glob("*.log*")):
            if p.resolve() != out.resolve():
                z.write(p, f"logs/{p.name}")
        for name in SAFE_CURRENT:
            p = cfg.current_dir / name
            if not p.is_file():
                continue
            if name.endswith(".json"):
                try:
                    z.writestr(f"current/{name}", json.dumps(_redact(json.loads(p.read_text(encoding="utf-8"))),
                                                             indent=2, ensure_ascii=False))
                except (OSError, ValueError):
                    pass
            else:
                z.write(p, f"current/{name}")
        try:
            loc = json.loads(cfg.local_path.read_text(encoding="utf-8"))
            if isinstance(loc.get("settings"), dict):
                loc["settings"].pop("last_meta", None)          # names and email of the survey team
            z.writestr("spyhop-local.json", json.dumps(_redact(loc), indent=2, ensure_ascii=False))
        except (OSError, ValueError, AttributeError):
            pass
        z.writestr("README.txt",
                   "Spyhop diagnostics bundle. It holds Spyhop's logs, the current template (templates/current, without the\n"
                   "observers list, and with any ?query removed from web addresses), this computer's settings (without\n"
                   "the survey team's details), a listing of Spyhop's folders (folders.txt) and system details.\n"
                   "It does not hold any survey data.\n")
    return out
