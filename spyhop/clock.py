"""The computer's clock against the GPS (0.48).

Every record Spyhop makes is stamped with the computer's clock. At sea a laptop can't set its clock from
the internet, so it can drift, or be wrong after a battery swap. The primary GPS sends the time in its
RMC sentences, so Spyhop compares the two all the time (`ClockWatch`), warns when they differ by more
than `LIMIT_S`, checks when a survey starts, and can set the computer's clock to the GPS (`sync`). That
needs administrator rights, so the operating system asks (Mac: the password box; Windows: the "allow
this app to make changes" prompt; Linux: the system's password prompt). It's only allowed between surveys,
so a survey's records never jump in time.

A sentence reaches Spyhop a little after the second it gives, so the comparison is good to about a second;
the median of the last samples smooths that out.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from statistics import median

log = logging.getLogger("spyhop.clock")

LIMIT_S = 2.0          # more than this between the computer's clock and the GPS: warn, offer to sync
SAMPLES = 15           # median of the last this many comparisons
FRESH_S = 10           # a GPS time older than this doesn't count (GPS lost)
SYNC_TIMEOUT_S = 180   # time to answer the password prompt


class ClockWatch:
    """Fed the decoder's vessel state every second; keeps (GPS time − computer time) samples."""

    def __init__(self):
        self.samples: list[float] = []
        self._last_rx = None
        self.source = None

    def feed(self, state):
        rx, gt = getattr(state, "gps_time_rx", None), getattr(state, "gps_time", None)
        if rx is None or gt is None or rx == self._last_rx:
            return
        self._last_rx = rx
        try:
            g = datetime.fromisoformat(gt).timestamp()
        except (TypeError, ValueError):
            return
        self.samples = (self.samples + [g - rx])[-SAMPLES:]
        self.source = getattr(state, "source", None)

    def reset(self):
        self.samples, self._last_rx = [], None

    def status(self) -> dict:
        """{known, offset_s (GPS − computer: + means the computer is behind), ok, limit_s, source}."""
        fresh = self._last_rx is not None and time.time() - self._last_rx < FRESH_S
        if not fresh or len(self.samples) < 3:
            return {"known": False, "offset_s": None, "ok": None, "limit_s": LIMIT_S, "source": self.source}
        off = median(self.samples)
        return {"known": True, "offset_s": round(off, 1), "ok": abs(off) <= LIMIT_S, "limit_s": LIMIT_S, "source": self.source}


def sync_command(offset_s: float, platform: str | None = None) -> list[str]:
    """The command that moves the computer's clock by offset_s seconds, asking for administrator rights.
    The new time is worked out when the command runs (after the password), not before."""
    platform = platform or sys.platform
    sec = int(round(offset_s))
    if platform == "darwin":
        sh = f'date -u "$(date -u -r $(( $(date -u +%s) + ({sec}) )) +%m%d%H%M%Y.%S)"'
        return ["osascript", "-e", f'do shell script "{sh.replace(chr(34), chr(92) + chr(34))}" with administrator privileges']
    if platform == "win32":
        inner = f"Set-Date -Adjust ([TimeSpan]::FromSeconds({sec})) | Out-Null"
        return ["powershell", "-NoProfile", "-Command",
                f"Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList '-NoProfile','-Command','{inner}'"]
    sh = f'date -s "@$(( $(date +%s) + ({sec}) ))"'
    if shutil.which("pkexec"):
        return ["pkexec", "sh", "-c", sh]
    return ["sudo", "-A", "sh", "-c", sh]


def sync(offset_s: float) -> tuple[bool, str]:
    """Move the computer's clock to the GPS. (ok, message)."""
    if os.environ.get("SPYHOP_FAKE_CLOCK_SYNC"):          # tests: pretend it worked (the simulator's offset goes)
        os.environ["SPYHOP_TEST_CLOCK_OFFSET"] = "0"
        log.info("clock sync (fake): %+.1f s", offset_s)
        return True, f"The computer's clock was moved {offset_s:+.0f} s to the GPS time."
    cmd = sync_command(offset_s)
    log.info("clock sync: %+.1f s with %s", offset_s, cmd[0])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=SYNC_TIMEOUT_S)
    except FileNotFoundError:
        return False, f"This computer has no {cmd[0]}, so Spyhop can't change its clock. Set the time by hand in the computer's date and time settings."
    except subprocess.TimeoutExpired:
        return False, "No answer to the password prompt, so the clock wasn't changed."
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
        log.info("clock sync failed (%s): %s", r.returncode, err[0])
        if "-128" in err[0] or "cancel" in err[0].lower() or r.returncode == 126:
            return False, "The password prompt was cancelled, so the clock wasn't changed."
        return False, ("The clock couldn't be changed (administrator rights are needed; on a computer your IT department "
                       f"manages, ask them). {err[0]}").strip()
    return True, f"The computer's clock was moved {offset_s:+.0f} s to the GPS time."


# 0.61.1: Windows names its time zones in full ("Eastern Standard Time", "Coordinated Universal Time") where macOS and
# Linux give abbreviations (EST, UTC). Spyhop shows the short form everywhere.
_WINDOWS_ZONES = {
    "coordinated universal time": "UTC", "utc": "UTC", "greenwich mean time": "GMT", "gmt standard time": "GMT",
    "gmt daylight time": "BST", "gmt summer time": "BST",
    "eastern standard time": "EST", "eastern daylight time": "EDT", "eastern summer time": "EDT",
    "central standard time": "CST", "central daylight time": "CDT", "central summer time": "CDT",
    "mountain standard time": "MST", "mountain daylight time": "MDT", "mountain summer time": "MDT",
    "pacific standard time": "PST", "pacific daylight time": "PDT", "pacific summer time": "PDT",
    "alaskan standard time": "AKST", "alaskan daylight time": "AKDT", "alaskan summer time": "AKDT",
    "hawaiian standard time": "HST", "atlantic standard time": "AST", "atlantic daylight time": "ADT",
    "atlantic summer time": "ADT", "newfoundland standard time": "NST", "newfoundland daylight time": "NDT",
    "newfoundland summer time": "NDT",
}


def zone_abbr(dt) -> str:
    """A short name for dt's time zone: the system's abbreviation (EST, UTC, CEST…); for a long Windows name, the
    usual abbreviation for North America, UTC and the UK, else the offset (UTC+01:00)."""
    name = (dt.tzname() or "").strip()
    if name and " " not in name and len(name) <= 6:
        return name
    known = _WINDOWS_ZONES.get(name.lower())
    if known:
        return known
    off = dt.utcoffset()
    if off is None:
        return name
    m = int(off.total_seconds() // 60)
    return "UTC" if m == 0 else f"UTC{'+' if m > 0 else '-'}{abs(m) // 60:02d}:{abs(m) % 60:02d}"
