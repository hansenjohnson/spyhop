"""One Spyhop per computer (0.46).

A second Spyhop, started from the same or another program folder, on any port, would record into the
same surveys as the first. So Spyhop takes an exclusive lock on `spyhop.lock` in the standard Spyhop
folder of this user (the same place whatever --data-dir or --port says) for as long as it runs. The
operating system releases the lock when the process ends, even after a crash, so a stale file never
blocks a start. The file also says where the running Spyhop is (pid, port), so a second start can open
a window onto it instead.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_held = None          # the open lock file, kept for the life of the process


def lock_path() -> Path:
    from .config import default_data_dir
    return Path(os.environ.get("SPYHOP_LOCK_DIR") or default_data_dir()) / "spyhop.lock"


def _try_lock(fh) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def running() -> dict | None:
    """What the lock file says about the Spyhop that holds it ({pid, port, ...}), if readable."""
    try:
        return json.loads(lock_path().read_text(encoding="utf-8").strip() or "{}") or None
    except (OSError, ValueError):
        return None


def acquire(port: int, wait_s: float = 0.0) -> bool:
    """Take the lock (retrying for wait_s seconds, e.g. while an updated Spyhop replaces itself).
    True if this process is now the one Spyhop; False if another one holds it."""
    global _held
    p = lock_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fh = open(p, "a+", encoding="utf-8")
    deadline = time.monotonic() + wait_s
    while not _try_lock(fh):
        if time.monotonic() >= deadline:
            fh.close()
            return False
        time.sleep(0.25)
    info = json.dumps({"pid": os.getpid(), "port": port, "program": str(Path(__file__).resolve().parent.parent),
                       "started": time.strftime("%Y-%m-%dT%H:%M:%S")})
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(info + "\n")
        fh.flush()
    except OSError:
        pass
    _held = fh
    return True
