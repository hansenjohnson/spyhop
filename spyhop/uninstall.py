"""Uninstalling and reinstalling Spyhop (Settings → About → Uninstall or reinstall).

Where Spyhop keeps things:
  program folder   the code, the start files and its Python set-up (.venv)   updater.PROGRAM_DIR
  Spyhop's folder  the current and saved templates (templates/), this computer's settings (spyhop-local.json),
                   maps, overlays, routes, feeds, logs                                cfg.root
  data folder      surveys, waypoints, templates, NMEA logs, exports     cfg.data_dir (default cfg.root/data)
  shortcuts        Spyhop.app and the Desktop link (macOS), Desktop and Start-menu shortcuts
                   (Windows), the applications-menu entry (Linux)                 shortcut.py

Uninstall deletes the program folder and the shortcuts; Spyhop's folder and the survey data are
deleted only when asked (each is a separate tick), and a data folder chosen elsewhere is never
deleted (it may hold other files): its path is given so it can be deleted by hand.

Reinstall downloads a clean copy of the latest version from GitHub first (nothing changes if that
fails), then replaces everything in the program folder, including the Python set-up, which the
start file makes again.
Settings are kept unless "reset" is ticked. Survey data is never touched.

The program can't delete itself while it runs (Windows locks its files), so both write a small
helper script to a temporary folder and start it with a Python that isn't in the program folder.
The helper waits for Spyhop to close, does the deleting (and, for reinstall, moves the new copy in
and starts Spyhop again), and writes what it did to spyhop-uninstall.log in that temporary folder.

A program folder that is a git checkout is deleted or reinstalled only when nothing would be lost:
no uncommitted changes and no commits that aren't on GitHub. Reinstalling it resets it to the branch
on GitHub (git fetch, git reset --hard, git clean -fdx), which also removes the Python set-up.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import shortcut, updater

log = logging.getLogger("spyhop.uninstall")

CONFIRM_DATA = "DELETE"         # typed to delete survey data


class UninstallError(Exception):
    pass


def _inside(p: Path, folder: Path) -> bool:
    try:
        p.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _risky(p: Path) -> bool:
    """A folder that must never be deleted wholesale: a drive root, the home folder or one of its
    standard folders, or anything above the home folder."""
    p = p.resolve()
    home = Path.home().resolve()
    if p == Path(p.anchor) or p == home or _inside(home, p):
        return True
    return p.parent == home and p.name.lower() in {"desktop", "documents", "downloads", "library", "applications",
                                                   "appdata", "pictures", "music", "movies", "videos", "onedrive"}


def shortcut_paths() -> list[Path]:
    """The shortcuts shortcut.py made for this program folder (only ours)."""
    out: list[Path] = []
    root = str(shortcut.ROOT)
    if sys.platform == "darwin":
        for d in shortcut._mac_app_dirs():
            app = d / "Spyhop.app"
            if app.exists() and shortcut._is_ours(app):
                try:
                    mine = (app / "Contents" / "Resources" / "folder.txt").read_text().strip() == root
                except OSError:
                    mine = False
                if mine:
                    out.append(app)
        link = Path.home() / "Desktop" / "Spyhop"
        if link.is_symlink():
            try:
                if Path(os.readlink(link)).name == "Spyhop.app":
                    out.append(link)
            except OSError:
                pass
    elif sys.platform.startswith("win"):
        prof = Path(os.environ.get("USERPROFILE", Path.home()))
        appdata = Path(os.environ.get("APPDATA", prof / "AppData" / "Roaming"))
        for p in (prof / "Desktop" / "Spyhop.lnk", prof / "OneDrive" / "Desktop" / "Spyhop.lnk",
                  appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Spyhop.lnk"):
            if p.exists():
                out.append(p)
    else:
        for p in (Path.home() / ".local" / "share" / "applications" / "spyhop.desktop",
                  Path.home() / "Desktop" / "spyhop.desktop"):
            try:
                if p.exists() and root in p.read_text(errors="ignore"):
                    out.append(p)
            except OSError:
                pass
    return out


def _du(p: Path) -> int:
    """Size of a file or folder; folders it can't read are skipped (never an error)."""
    try:
        if p.is_file():
            return p.stat().st_size
    except OSError:
        return 0
    n = 0
    for dirpath, _dirs, files in os.walk(p, onerror=lambda e: None):
        for f in files:
            try:
                fp = os.path.join(dirpath, f)
                if not os.path.islink(fp):
                    n += os.path.getsize(fp)
            except OSError:
                pass
    return n


def _git(prog: Path, *args, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(prog), *args], capture_output=True, text=True, timeout=timeout)


def git_state(prog: Path, fetch: bool = False) -> str:
    """"" if a git checkout can be deleted or reset without losing anything, else why not."""
    if not shutil.which("git"):
        return "git isn't installed on this computer"
    try:
        if fetch:
            _git(prog, "fetch", "--quiet", timeout=60)
        st = _git(prog, "status", "--porcelain")
        if st.returncode != 0:
            return "git can't read it (" + (st.stderr or st.stdout).strip()[:200] + ")"
        dirty = [ln for ln in st.stdout.splitlines() if ln.strip()]
        if dirty:
            return f"uncommitted changes ({len(dirty)} file{'s' if len(dirty) > 1 else ''})"
        up = _git(prog, "rev-parse", "--abbrev-ref", "@{u}")
        if up.returncode != 0:
            return "a branch that isn't on GitHub (it has no upstream)"
        ahead = _git(prog, "rev-list", "--count", "@{u}..HEAD")
        n = int((ahead.stdout or "0").strip() or 0)
        if n:
            return f"{n} commit{'s' if n > 1 else ''} not pushed to GitHub"
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        return f"git didn't answer ({e})"
    return ""


def plan(cfg, mode: str = "uninstall", delete_settings: bool = False, delete_data: bool = False) -> dict:
    """What `mode` ('uninstall' or 'reinstall') would delete and keep, and why it can't (if so).
    Shown in the confirmation; start() repeats the same checks."""
    prog, root, data = updater.PROGRAM_DIR, Path(cfg.root), Path(cfg.data_dir)
    default_data = data.resolve() == (root / "data").resolve()
    problems: list[str] = []
    if mode not in ("uninstall", "reinstall"):
        problems.append("Unknown action.")
    git = updater.git_checkout()
    if git:
        why = git_state(prog)
        if why:
            problems.append(f"This copy of Spyhop is a git checkout ({prog}) with {why}. Spyhop deletes or reinstalls it "
                            "only when nothing would be lost: commit and push first (or delete the folder yourself).")
    if not (prog / "spyhop" / "__init__.py").is_file() or not (prog / "pyproject.toml").is_file():
        problems.append(f"{prog} doesn't look like Spyhop's program folder, so nothing will be deleted.")
    if _risky(prog):
        problems.append(f"Spyhop's program folder is {prog}, which is too general a folder to delete.")
    if _inside(root, prog) or _inside(data, prog):
        problems.append("Spyhop's settings or data folder is inside the program folder, so deleting the program would "
                        "delete them too. Move the data folder (Settings → General) first.")
    if delete_settings and (_risky(root) or not (root / "templates").is_dir()):
        problems.append(f"{root} doesn't look like Spyhop's own folder, so it won't be deleted.")
    if mode == "reinstall" and not git and not os.access(prog.parent, os.W_OK):
        problems.append(f"Spyhop can't write next to its program folder ({prog.parent}), so it can't put a new copy there.")
    if mode == "reinstall":
        delete_data = False

    delete: list[dict] = []
    keep: list[dict] = []
    delete.append({"what": "Program and its Python set-up" if mode == "uninstall" else
                   "Program and its Python set-up (reset to the latest on GitHub with git)" if git else
                   "Program and its Python set-up (replaced by a clean copy)", "path": str(prog)})
    if mode == "uninstall":
        for p in shortcut_paths():
            delete.append({"what": "Shortcut", "path": str(p)})
    if delete_settings:
        what = "Settings, templates, offline maps, overlays, routes, feeds and logs"
        delete.append({"what": what + (" (survey data inside it is kept)" if default_data and not delete_data else ""),
                       "path": str(root)})
    else:
        keep.append({"what": "Settings, templates, offline maps, overlays, routes, feeds and logs", "path": str(root)})
    if delete_data and default_data:
        delete.append({"what": "Survey data, waypoints, templates, NMEA logs and exports", "path": str(data)})
    elif delete_data:
        keep.append({"what": "Survey data — in a folder you chose, which Spyhop won't delete (it may hold other files): "
                     "delete it yourself if you want", "path": str(data)})
    else:
        keep.append({"what": "Survey data, waypoints, templates, NMEA logs and exports", "path": str(data)})
    for d in delete:
        try:
            d["size"] = _du(Path(d["path"])) if d["what"] != "Shortcut" else 0
        except OSError:
            d["size"] = 0
    return {"mode": mode, "delete": delete, "keep": keep, "problems": problems, "git": git,
            "program": str(prog), "spyhop_folder": str(root), "data_folder": str(data), "default_data": default_data,
            "confirm_data": CONFIRM_DATA}


def _helper_python() -> str | None:
    """A Python outside the program folder to run the helper (the .venv one is being deleted)."""
    prog = updater.PROGRAM_DIR
    cands = [getattr(sys, "_base_executable", ""),
             str(Path(sys.base_prefix) / ("python.exe" if os.name == "nt" else "bin/python3")),
             str(Path(sys.base_prefix) / "bin" / "python"),
             shutil.which("python3") or "", shutil.which("python") or "", shutil.which("py") or ""]
    for c in cands:
        if c and Path(c).is_file() and not _inside(Path(c), prog):
            return c
    if os.name != "nt":
        return sys.executable           # POSIX: a running program's files can be deleted under it
    return None


HELPER = r'''
import json, os, shutil, stat, subprocess, sys, time
from pathlib import Path
job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
logf = open(Path(sys.argv[1]).with_name("spyhop-uninstall.log"), "a", encoding="utf-8")
def say(*a):
    logf.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n"); logf.flush()

def alive(pid):
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)      # SYNCHRONIZE
        if not h:
            return False
        r = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
        ctypes.windll.kernel32.CloseHandle(h)
        return r == 0x102                                                    # WAIT_TIMEOUT: still running
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def onerr(func, path, exc):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass

def remove(p, keep=()):
    """Delete p (a file, link or folder), except the folders in keep; retries while Windows holds files."""
    p = Path(p)
    for attempt in range(30):
        try:
            if p.is_symlink() or p.is_file():
                p.unlink()
            elif p.is_dir():
                if keep:
                    for c in p.iterdir():
                        if any(str(c.resolve()) == str(Path(k).resolve()) for k in keep):
                            continue
                        if c.is_dir() and not c.is_symlink():
                            shutil.rmtree(c, onerror=onerr)
                        else:
                            c.unlink()
                else:
                    shutil.rmtree(p, onerror=onerr)
            if not p.exists() or keep:
                return True
        except OSError as e:
            say("retrying", p, e)
        time.sleep(1)
    say("couldn't delete all of", p)
    return False

say("waiting for Spyhop (process", job["pid"], ") to close")
t0 = time.time()
while alive(job["pid"]) and time.time() - t0 < 120:
    time.sleep(0.5)
time.sleep(1)
prog = Path(job["program"])
for item in job["delete"]:
    say("deleting", item["path"])
    if item["path"] == job["program"] and job["mode"] == "reinstall":
        remove(prog)                     # everything, .venv too; the folder is made again below
    else:
        remove(item["path"], keep=item.get("keep", ()))
if job["mode"] == "reinstall" and job.get("git"):
    for args in (["fetch", "--quiet"], ["reset", "--hard", "@{u}"], ["clean", "-fdx"]):
        r = subprocess.run([job["git"], "-C", str(prog), *args], capture_output=True, text=True)
        say("git", *args, "->", r.returncode, (r.stdout + r.stderr).strip()[-300:])
    start = job.get("start") or []
    if start:
        try:
            kw = {"cwd": str(prog)}
            if os.name == "nt":
                kw["creationflags"] = 0x00000010
            else:
                kw["start_new_session"] = True
            subprocess.Popen(start, **kw)
            say("started", start)
        except OSError as e:
            say("couldn't start Spyhop:", e)
elif job["mode"] == "reinstall":
    new = Path(job["staged"])
    prog.mkdir(parents=True, exist_ok=True)
    for c in new.iterdir():
        shutil.move(str(c), str(prog / c.name))
    shutil.rmtree(job.get("staged_parent") or new, ignore_errors=True)
    say("new copy moved into", prog)
    start = job.get("start") or []
    if start:
        try:
            kw = {"cwd": str(prog)}
            if os.name == "nt":
                kw["creationflags"] = 0x00000010                              # CREATE_NEW_CONSOLE
            else:
                kw["start_new_session"] = True
            subprocess.Popen(start, **kw)
            say("started", start)
        except OSError as e:
            say("couldn't start Spyhop:", e)
else:
    try:
        prog.rmdir()
    except OSError:
        pass
say("done")
'''


def _start_command(prog: Path) -> list[str]:
    """How to open the start file in a new console window after a reinstall."""
    if sys.platform == "darwin":
        return ["open", "-a", "Terminal", str(prog / "Start Spyhop (Mac).command")]
    if sys.platform.startswith("win"):
        return ["cmd", "/c", "start", "Spyhop", "/D", str(prog), str(prog / "Start Spyhop (Windows).bat")]
    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        if shutil.which(term):
            return [term, "-e", "bash", str(prog / "start-spyhop.sh")] if term != "gnome-terminal" else \
                   [term, "--", "bash", str(prog / "start-spyhop.sh")]
    return []


def start(cfg, mode: str, delete_settings: bool = False, delete_data: bool = False, confirm: str = "",
          info: dict | None = None, launch: bool = True) -> dict:
    """Prepare and start the helper. Spyhop must then close (the caller stops the server).
    Returns {plan, helper_log, message}. Raises UninstallError if it can't be done."""
    p = plan(cfg, mode, delete_settings, delete_data)
    if p["problems"]:
        raise UninstallError(" ".join(p["problems"]))
    if mode == "uninstall" and delete_data and p["default_data"] and confirm.strip() != CONFIRM_DATA:
        raise UninstallError(f"To delete the survey data too, type {CONFIRM_DATA}. Nothing was deleted.")
    py = _helper_python()
    if not py:
        raise UninstallError("Couldn't find a Python outside Spyhop's program folder to finish the job. "
                             f"Close Spyhop and delete {updater.PROGRAM_DIR} yourself.")
    prog, root, data = updater.PROGRAM_DIR, Path(cfg.root), Path(cfg.data_dir)
    work = Path(tempfile.mkdtemp(prefix="spyhop_uninstall_"))
    git = p["git"]
    if git:                      # check again, against GitHub as it is now
        why = git_state(prog, fetch=True)
        if why:
            raise UninstallError(f"This copy of Spyhop is a git checkout with {why}. Commit and push first. Nothing was changed.")
    job = {"pid": os.getpid(), "mode": mode, "program": str(prog), "delete": [], "start": []}
    if mode == "reinstall" and git:
        job["git"] = shutil.which("git")          # reset in place: the folder (and .git) stays
    else:
        job["delete"].append({"path": str(prog)})
    if mode == "uninstall":
        job["delete"] += [{"path": x["path"]} for x in p["delete"] if x["what"] == "Shortcut"]
    if delete_settings:
        keep = [str(data)] if p["default_data"] and not (delete_data and mode == "uninstall") else []
        job["delete"].append({"path": str(root), "keep": keep})
    elif mode == "uninstall" and delete_data and p["default_data"]:
        job["delete"].append({"path": str(data)})
    message = ""
    if mode == "reinstall" and git:
        if launch:
            job["start"] = _start_command(prog)
        message = (f"Spyhop's folder {prog} will be reset to the latest on GitHub, its Python set-up removed, and Spyhop "
                   + ("started again in a new window" if job["start"] else "left for you to start with the Start Spyhop file")
                   + " once this window closes.")
    elif mode == "reinstall":
        info = info or updater.check()
        data_zip = updater._get(info["zip"])                       # fails here, before anything changes
        staged_parent = Path(tempfile.mkdtemp(prefix=".spyhop-reinstall-", dir=str(prog.parent)))
        top = updater._extract(data_zip, staged_parent / "x")
        job["staged"] = str(top)
        job["staged_parent"] = str(staged_parent)      # removed once the new copy is moved in
        if launch:
            job["start"] = _start_command(prog)
        message += (f"Spyhop {info.get('latest', '')} will be installed fresh in {prog} and start again in a new window"
                    if job["start"] else f"Spyhop {info.get('latest', '')} will be installed fresh in {prog}: start it "
                    "with the Start Spyhop file there") + " once this window closes."
    else:
        message = "Spyhop is closing and will be removed from this computer."
        kept = [k["path"] for k in p["keep"]]
        if kept:
            message += " Kept: " + "; ".join(kept) + "."
    (work / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
    (work / "helper.py").write_text(HELPER, encoding="utf-8")
    kw: dict = {"cwd": str(work), "stdin": subprocess.DEVNULL,
                "stdout": open(work / "helper.out", "w"), "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000    # DETACHED, NEW_PROCESS_GROUP, NO_WINDOW
    else:
        kw["start_new_session"] = True
    subprocess.Popen([py, "-I", str(work / "helper.py"), str(work / "job.json")], **kw)
    log.warning("%s started: helper %s, job %s", mode, py, work / "job.json")
    return {"plan": p, "helper_log": str(work / "spyhop-uninstall.log"), "message": message}
