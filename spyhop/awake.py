"""Keep the computer (and optionally the screen) from going to sleep while Spyhop records.

One `KeepAwake` object per server. `set(mode)` is idempotent: mode is None (allow sleep),
"system" (no idle sleep; the screen may still turn off) or "display" (no idle sleep and
the screen stays on).

- macOS: runs `caffeinate -i [-d] -w <our pid>`, so it ends with Spyhop even after a crash.
- Windows: SetThreadExecutionState from a dedicated thread (the request belongs to the
  thread that made it, and ends when that thread or the process ends).
- Linux: `systemd-inhibit` around a tiny shell loop that exits when Spyhop does.

Closing a laptop's lid still puts most computers to sleep: none of these stop that.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time

log = logging.getLogger("spyhop.awake")

MODES = (None, "system", "display")
RETRY_S = 60      # after a failure, try the same request again at most this often


class KeepAwake:
    def __init__(self):
        self.mode: str | None = None
        self.error = ""
        self._proc: subprocess.Popen | None = None
        self._win: _WindowsAwake | None = None
        self._failed: tuple[str, float] | None = None   # (mode, when) of the last failure

    # -- public -------------------------------------------------------------------
    def set(self, mode: str | None):
        if mode not in MODES:
            mode = None
        if mode == self.mode and not self.error:
            return
        if mode and self._failed and self._failed[0] == mode and time.monotonic() - self._failed[1] < RETRY_S:
            return                                    # it just failed: don't retry every tick
        self._stop()
        prev_error, self.error = self.error, ""
        if mode:
            try:
                self._start(mode)
            except Exception as e:  # noqa: BLE001  (never let this stop recording)
                self.error = str(e) or e.__class__.__name__
                if self.error != prev_error:          # say it once, not at every retry
                    log.warning("couldn't keep the computer awake: %s", self.error)
                self._stop()
                self.mode = None
                self._failed = (mode, time.monotonic())
                return
            self._failed = None
            log.info("keeping the computer awake%s (%s)", " with the screen on" if mode == "display" else "",
                     self.method())
        else:
            self._failed = None
            if self.mode:
                log.info("the computer may sleep again")
        self.mode = mode

    def release(self):
        self.set(None)

    def method(self) -> str:
        if sys.platform == "darwin":
            return "caffeinate"
        if sys.platform == "win32":
            return "Windows power request"
        return "systemd-inhibit" if shutil.which("systemd-inhibit") else ""

    def status(self) -> dict:
        return {"mode": self.mode, "error": self.error, "method": self.method(),
                "supported": bool(self.method())}

    # -- platforms --------------------------------------------------------------------
    def _start(self, mode: str):
        pid = str(os.getpid())
        if sys.platform == "darwin":
            args = ["caffeinate", "-i"] + (["-d"] if mode == "display" else []) + ["-w", pid]
            self._proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
        elif sys.platform == "win32":
            self._win = _WindowsAwake(display=(mode == "display"))
        else:
            if not shutil.which("systemd-inhibit"):
                raise RuntimeError("this system has no systemd-inhibit, so Spyhop can't stop it sleeping")
            what = "idle:sleep" if mode == "display" else "sleep"
            loop = f"while kill -0 {pid} 2>/dev/null; do sleep 5; done"
            self._proc = subprocess.Popen(
                ["systemd-inhibit", f"--what={what}", "--who=Spyhop", "--why=Recording a survey",
                 "--mode=block", "sh", "-c", loop],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if self._proc is not None:
            try:                                  # a command that fails says so straight away
                self._proc.wait(timeout=0.3)
            except subprocess.TimeoutExpired:
                return
            err = (self._proc.stderr.read().decode(errors="replace").strip() if self._proc.stderr else "")
            self._proc = None
            raise RuntimeError(err or "the keep-awake helper stopped at once")

    def _stop(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                try:
                    self._proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            self._proc = None
        if self._win is not None:
            self._win.stop()
            self._win = None


class _WindowsAwake:
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_DISPLAY_REQUIRED = 0x00000002

    def __init__(self, display: bool):
        import ctypes
        self._k32 = ctypes.windll.kernel32
        self._flags = self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | (self.ES_DISPLAY_REQUIRED if display else 0)
        self._stop = threading.Event()
        self._ok = threading.Event()
        self._err = ""
        self._t = threading.Thread(target=self._run, name="spyhop-keep-awake", daemon=True)
        self._t.start()
        self._ok.wait(2)
        if self._err:
            raise RuntimeError(self._err)

    def _run(self):
        if not self._k32.SetThreadExecutionState(self._flags):
            self._err = "Windows refused the request to stay awake"
            self._ok.set()
            return
        self._ok.set()
        self._stop.wait()
        self._k32.SetThreadExecutionState(self.ES_CONTINUOUS)

    def stop(self):
        self._stop.set()
        self._t.join(2)
