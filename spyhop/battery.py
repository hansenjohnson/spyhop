"""This computer's battery (0.63): its charge and whether it is plugged in, for the low-battery warning.

No extra packages: macOS asks ``pmset -g batt``, Windows asks GetSystemPowerStatus (ctypes) and Linux
reads /sys/class/power_supply. psutil is used instead when it happens to be installed.
``read()`` returns ``{"percent": 0–100, "plugged": bool}``, or None for a computer without a battery
(a desktop) or when it can't be read.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def read() -> dict | None:
    fake = os.environ.get("SPYHOP_FAKE_BATTERY")      # tests: a JSON file {"percent": …, "plugged": …} (or null)
    if fake:
        try:
            d = json.loads(Path(fake).read_text(encoding="utf-8"))
            return {"percent": int(d["percent"]), "plugged": bool(d["plugged"])} if d else None
        except (OSError, ValueError, KeyError, TypeError):
            return None
    try:
        import psutil  # type: ignore
        b = psutil.sensors_battery()
        if b is not None and b.percent is not None:
            return {"percent": round(float(b.percent)), "plugged": bool(b.power_plugged)}
    except Exception:
        pass
    try:
        if sys.platform == "darwin":
            return _mac()
        if sys.platform.startswith("win"):
            return _windows()
        if sys.platform.startswith("linux"):
            return _linux()
    except Exception:
        return None
    return None


def parse_pmset(text: str) -> dict | None:
    """``pmset -g batt``: "Now drawing from 'Battery Power'" … "-InternalBattery-0 (id=…)	84%; discharging; …"."""
    m = re.search(r"(\d{1,3})%", text)
    if not m or "InternalBattery" not in text:
        return None
    plugged = "AC Power" in text or "charged" in text.split(m.group(0), 1)[1][:30]
    return {"percent": int(m.group(1)), "plugged": plugged}


def _mac():
    out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5, encoding="utf-8")
    return parse_pmset(out.stdout)


def _windows():
    import ctypes

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    s = SYSTEM_POWER_STATUS()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):  # type: ignore[attr-defined]
        return None
    if s.BatteryFlag & 128 or s.BatteryLifePercent == 255:      # no battery / unknown
        return None
    return {"percent": int(s.BatteryLifePercent), "plugged": s.ACLineStatus == 1}


def read_sysfs(root: Path) -> dict | None:
    """Linux: the batteries under /sys/class/power_supply (several are averaged by their capacity)."""
    cap, plugged, found = [], False, False
    for d in sorted(root.glob("*")):
        try:
            kind = (d / "type").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if kind == "Mains":
            try:
                plugged = plugged or (d / "online").read_text(encoding="utf-8").strip() == "1"
            except OSError:
                pass
        elif kind == "Battery":
            try:
                if (d / "scope").exists() and (d / "scope").read_text(encoding="utf-8").strip() == "Device":
                    continue                                    # a mouse's or a keyboard's
                cap.append(int((d / "capacity").read_text(encoding="utf-8").strip()))
                found = True
                status = (d / "status").read_text(encoding="utf-8").strip() if (d / "status").exists() else ""
                plugged = plugged or status in ("Charging", "Full", "Not charging")
            except (OSError, ValueError):
                continue
    if not found:
        return None
    return {"percent": round(sum(cap) / len(cap)), "plugged": plugged}


def _linux():
    return read_sysfs(Path("/sys/class/power_supply"))
